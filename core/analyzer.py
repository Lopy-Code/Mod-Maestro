"""Analyse d'un modpack : doublons, dépendances, incompatibilités, côté client/serveur."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
from collections import Counter, defaultdict
from functools import cmp_to_key
from urllib.parse import quote

from . import versions as V
from .i18n import _, ng, tr
from .parser import PLATFORM_IDS, JarInfo, ModInfo

_KNOWLEDGE_PATH = os.path.join(os.path.dirname(__file__), "data", "knowledge.json")

LOADER_LABELS = {"neoforge": "NeoForge", "forge": "Forge", "fabric": "Fabric", "quilt": "Quilt"}
# loader dominant -> (loaders acceptés, loaders « de secours » avec avertissement)
LOADER_COMPAT = {
    "neoforge": (["neoforge"], ["forge"]),
    "forge": (["forge"], []),
    "fabric": (["fabric"], []),
    "quilt": (["quilt", "fabric"], []),
}


# (gravité, confiance) -> points retirés au score (voir Analysis.score)
_PENALTY = {
    ("error", "certain"): 6.0, ("error", "likely"): 3.0, ("error", "heuristic"): 1.5,
    ("warning", "certain"): 2.0, ("warning", "likely"): 1.5, ("warning", "heuristic"): 0.7,
}


def norm(modid: str) -> str:
    return str(modid).lower().replace("-", "_")


_PLATFORM_N = {norm(i) for i in PLATFORM_IDS}


def load_knowledge(path: str = _KNOWLEDGE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"client_only": {"ids": []}, "recipe_viewers": {"ids": []}, "client_keywords": [],
                "friendly_names": {}, "conflict_rules": []}


def _links(modid: str) -> list[dict]:
    q = quote(modid)
    return [
        {"label": "Modrinth", "url": f"https://modrinth.com/mods?q={q}"},
        {"label": "CurseForge", "url": f"https://www.curseforge.com/minecraft/search?search={q}"},
    ]


class Analysis:
    def __init__(self, source: str, mods_dir: str):
        self.id = secrets.token_hex(6)
        self.source = source
        self.mods_dir = mods_dir
        self.loader: str | None = None
        self.mc_version: str | None = None
        self.mc_confidence = 0.0
        self.issues: list[dict] = []
        self.entries: dict[str, dict] = {}  # file -> entrée
        self.notes: list[str] = []
        self.jar_count = 0
        self.total_size = 0
        self.online: dict = {"enabled": False}  # rempli par core.enrich quand Modrinth est utilisé
        self.kb_stats: dict = {}
        self.boot: dict | None = None      # preuve de démarrage tirée de latest.log (core.pipeline)
        self.ignored_ids: set[str] = set()  # alertes que l'utilisateur a choisi d'ignorer

    def add_issue(self, issue_id, severity, category, title, message, files=(), modids=(), fix="",
                  links=None, data=None, confidence="certain") -> None:
        """confidence : certain (le jeu refusera de démarrer) · likely (très probable) · heuristic (estimation)."""
        self.issues.append({
            "id": issue_id, "severity": severity, "category": category, "title": title,
            "message": message, "files": list(files), "modids": list(modids), "fix": fix,
            "links": links or [], "data": data or {}, "confidence": confidence,
        })

    # -- alertes actives (non ignorées) -----------------------------------------------
    def active_issues(self) -> list[dict]:
        return [i for i in self.issues if i["id"] not in self.ignored_ids]

    def booted(self) -> bool:
        return bool(self.boot and self.boot.get("status") == "ok" and self.boot.get("fresh"))

    # -- sérialisation -----------------------------------------------------
    def counts(self) -> dict:
        sev = Counter(i["severity"] for i in self.active_issues())
        plan = compute_plan(self)
        return {
            "jars": self.jar_count,
            "mods": sum(len(e["mods"]) for e in self.entries.values()),
            "bundled": sum(e["bundled_count"] for e in self.entries.values()),
            "errors": sev["error"],
            "warnings": sev["warning"],
            "infos": sev["info"],
            "server_keep": len(plan["keep"]),
            "server_remove": len(plan["remove"]),
            "server_unsure": len(plan["unsure"]),
            "size": self.total_size,
            "ignored": len(self.issues) - len(self.active_issues()),
        }

    def score(self) -> int:
        """Score de santé 0-100, pondéré par la **confiance** de chaque alerte.

        Un problème certain (doublon, dépendance déclarée absente…) pèse lourd ; une estimation (version de
        Minecraft déduite, piège connu…) pèse peu. La courbe est exponentielle : 20 alertes mineures ne
        peuvent pas faire croire qu'un pack qui fonctionne est cassé. Si `latest.log` prouve que le pack a
        démarré, les alertes comptent pour un quart.
        """
        total = sum(_PENALTY.get((i["severity"], i.get("confidence", "certain")), 0.0) for i in self.active_issues())
        if self.booted():
            total *= 0.25
        return max(0, min(100, round(100 * math.exp(-total / 40))))

    def verdict(self) -> str:
        """bad : un problème certain · warn : à vérifier · ok : rien d'important."""
        act = self.active_issues()
        if self.booted():
            return "warn" if any(i["severity"] == "error" for i in act) else "ok"
        if any(i["severity"] == "error" and i.get("confidence", "certain") == "certain" for i in act):
            return "bad"
        if any(i["severity"] in ("error", "warning") for i in act):
            return "warn"
        return "ok"

    def to_dict(self) -> dict:
        mods = []
        for f, e in self.entries.items():
            side = e["side"]
            base = {
                "file": f, "size": e["size"], "status": e["status"], "side": side["value"],
                "side_confidence": side["confidence"], "side_reason": side["reason"],
                "compat": e["compat"], "bundled_count": e["bundled_count"], "online": e.get("online"),
            }
            if e["mods"]:
                for m in e["mods"]:
                    mods.append({**base, "name": m["name"], "modid": m["modid"], "version": m["version"],
                                 "loader": m["loader"], "requires": m["requires"]})
            else:
                mods.append({**base, "name": re.sub(r"\.jar$", "", f, flags=re.I), "modid": None,
                             "version": None, "loader": None, "requires": []})
        order = {"error": 0, "warning": 1, "info": 2}
        issues = sorted(({**i, "ignored": i["id"] in self.ignored_ids} for i in self.issues),
                        key=lambda i: (i["ignored"], order[i["severity"]], i["category"], i["title"]))
        return {
            "id": self.id,
            "source": self.source,
            "mods_dir": self.mods_dir,
            "loader": self.loader,
            "loader_label": LOADER_LABELS.get(self.loader or "", _("Inconnu")),
            "mc_version": self.mc_version,
            "mc_confidence": round(self.mc_confidence, 2),
            "counts": self.counts(),
            "score": self.score(),
            "verdict": self.verdict(),
            "issues": issues,
            "mods": mods,
            "plan": compute_plan(self),
            "notes": self.notes,
            "online": self.online,
            "kb": self.kb_stats,
            "boot": self.boot,
        }


# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------

def _dominant_loader(jars: list[JarInfo], bridges: list[dict] | None = None) -> str | None:
    # Une passerelle (Sinytra Connector) installée dans un mod NeoForge/Forge décide du loader du pack, même
    # si les mods Fabric qu'elle fait tourner sont plus nombreux : sinon tous les mods NeoForge seraient
    # signalés « mauvais loader ».
    for br in bridges or []:
        bid = norm(br.get("id", ""))
        for j in jars:
            if any(norm(m.modid) == bid and m.loader == br.get("loader") for m in j.mods):
                return br["loader"]
    votes: Counter = Counter()
    for j in jars:
        if j.status == "ok" and len(j.loaders) == 1:
            votes[j.loaders[0]] += 1
    if votes:
        return votes.most_common(1)[0][0]
    for j in jars:
        if j.loaders:
            return j.loaders[0]
    return None


def _active_mods(jar: JarInfo, loader: str | None, bridged: tuple = ()) -> tuple[list[ModInfo], str]:
    """Mods du jar pour le loader du pack + état (ok | fallback | bridged | mismatch).

    `bridged` : loaders acceptés en plus grâce à une passerelle présente dans le pack (Sinytra Connector…).
    """
    if not jar.mods:
        return [], "ok"
    if loader is None:
        first = jar.mods[0].loader
        return [m for m in jar.mods if m.loader == first], "ok"
    primary, fallback = LOADER_COMPAT.get(loader, ([loader], []))
    mods = [m for m in jar.mods if m.loader in primary]
    if mods:
        return mods, "ok"
    mods = [m for m in jar.mods if m.loader in fallback]
    if mods:
        return mods, "fallback"
    mods = [m for m in jar.mods if m.loader in bridged]
    if mods:
        return mods, "bridged"
    first = jar.mods[0].loader
    return [m for m in jar.mods if m.loader == first], "mismatch"


def _classify_side(mods: list[ModInfo], kb: dict, info: dict | None = None) -> dict:
    """Côté client/serveur d'un fichier. Ordre de confiance :

    déclaré par le mod > « à garder » forcé (base de connaissances) > Modrinth (« non pris en charge »)
    > mod client connu > visionneuse de recettes > Modrinth (« prend en charge le serveur ») > mots-clés.
    """
    none = {"value": "both", "confidence": None, "reason": None}
    if not mods and not info:
        return none
    if mods and all(m.env == "client" for m in mods):
        return {"value": "client", "confidence": "declared",
                "reason": mods[0].env_reason or _("Déclaré côté client dans les métadonnées")}
    if mods and all(m.env == "server" for m in mods):
        return {"value": "server", "confidence": "declared",
                "reason": mods[0].env_reason or _("Déclaré côté serveur dans les métadonnées")}
    force = {norm(i) for i in kb.get("force_both", [])}
    if mods and any(norm(m.modid) in force for m in mods):
        return {"value": "both", "confidence": "known", "reason": _("Marqué « à garder sur le serveur » dans la base de connaissances")}
    cs, ss = (info or {}).get("client_side"), (info or {}).get("server_side")
    if info and ss == "unsupported" and cs != "unsupported":
        return {"value": "client", "confidence": "modrinth", "reason": _("Modrinth : ce mod ne fonctionne pas côté serveur")}
    if info and cs == "unsupported" and ss != "unsupported":
        return {"value": "server", "confidence": "modrinth", "reason": _("Modrinth : ce mod ne fonctionne pas côté client")}
    client_ids = {norm(i) for i in kb.get("client_only", {}).get("ids", [])}
    if mods and all(norm(m.modid) in client_ids for m in mods):
        return {"value": "client", "confidence": "known",
                "reason": _("Mod connu pour ne servir que côté client (rendu, interface, minimap…)")}
    viewers = {norm(i) for i in kb.get("recipe_viewers", {}).get("ids", [])}
    if mods and any(norm(m.modid) in viewers for m in mods):
        return {"value": "unsure", "confidence": "probable",
                "reason": _("Visionneuse de recettes : facultative sur un serveur")}
    if info and ss in ("required", "optional"):
        return {"value": "both", "confidence": "modrinth", "reason": _("Modrinth : prend en charge le serveur")}
    for m in mods:
        text = f"{m.modid} {m.name}".lower()
        tokens = set(re.split(r"[^a-z0-9]+", text))
        for kw in kb.get("client_keywords", []):
            if (len(kw) >= 6 and kw in text) or kw in tokens:
                return {"value": "unsure", "confidence": "probable",
                        "reason": _("Le nom évoque un mod côté client (« {kw} ») — à vérifier", kw=kw)}
    return none


def analyze(jars: list[JarInfo], extras: dict | None = None, source: str = "", mods_dir: str = "",
            notes: list[str] | None = None, knowledge: dict | None = None,
            online: dict | None = None) -> Analysis:
    """`online` : nom de fichier → info Modrinth (voir core.modrinth.identify), facultatif."""
    kb = knowledge or load_knowledge()
    online = online or {}
    a = Analysis(source or mods_dir, mods_dir or source)
    a.notes = list(notes or [])
    a.kb_stats = kb.get("_stats", {})
    a.jar_count = len(jars)
    a.total_size = sum(j.size for j in jars)
    a.ignored_ids = {str(i) for i in kb.get("_ignored", [])}
    a.loader = _dominant_loader(jars, kb.get("loader_bridges", []))
    loader_label = LOADER_LABELS.get(a.loader or "", _("le loader"))

    # --- passerelles de loader (ex. Sinytra Connector : mods Fabric sur NeoForge) -----------------
    present_ids = {norm(m.modid) for j in jars for m in j.mods}
    bridged: dict[str, str] = {}  # loader accepté en plus -> nom de la passerelle
    for br in kb.get("loader_bridges", []):
        if br.get("loader") == a.loader and norm(br.get("id", "")) in present_ids:
            for accepted in br.get("accepts", []):
                bridged[accepted] = br.get("name", br["id"])

    active: dict[str, list[ModInfo]] = {}
    compat: dict[str, str] = {}
    for j in jars:
        mods, state = _active_mods(j, a.loader, tuple(bridged))
        active[j.file], compat[j.file] = mods, state

    # --- index des fournisseurs ------------------------------------------
    providers: dict[str, list[tuple[str, ModInfo, bool]]] = defaultdict(list)  # id -> (file, mod, direct)
    bundled_ids: dict[str, tuple[str, ModInfo]] = {}
    for j in jars:
        if compat[j.file] == "mismatch":
            continue
        for m in active[j.file]:
            providers[norm(m.modid)].append((j.file, m, True))
            for p in m.provides:
                providers[norm(p)].append((j.file, m, False))
        for b in j.bundled:
            if a.loader is None or b.loader in LOADER_COMPAT.get(a.loader, ([a.loader], []))[0] + ["forge"]:
                bundled_ids.setdefault(norm(b.modid), (j.file, b))
                for p in b.provides:
                    bundled_ids.setdefault(norm(p), (j.file, b))

    # --- version de Minecraft du pack : celle que la majorité des mods acceptent -----------------
    mc_items = []
    for j in jars:
        if compat[j.file] == "mismatch":
            continue
        for m in active[j.file]:
            for dep in m.deps:
                if norm(dep.modid) == "minecraft" and dep.kind == "required" and dep.range:
                    mc_items.append((j.file, m, dep.range, dep.syntax))
    if mc_items:
        cands: set[str] = set()
        for _f, _m, r, _s in mc_items:
            cands |= V.candidate_versions(r)
        # À égalité, on préfère la version qui satisfait les plages les plus *précises* (« [1.20.1] » en dit
        # plus que « [1.20,) »), puis la plus récente : sinon on risquait de viser 1.20.4 pour un pack 1.20.1.
        weight = {id(it): 1 + 1 / max(1, len(V.candidate_versions(it[2]))) for it in mc_items}
        best_v, best_key = None, (-1, -1.0)
        for c in sorted(cands, key=cmp_to_key(V.compare)):
            ok = [it for it in mc_items if V.satisfies(it[3], it[2], c)]
            key = (len(ok), sum(weight[id(it)] for it in ok))
            if key >= best_key:
                best_v, best_key = c, key
        if best_v:
            a.mc_version, a.mc_confidence = best_v, best_key[0] / len(mc_items)

    def is_provided(modid: str) -> bool:
        n = norm(modid)
        return n in _PLATFORM_N or n in providers or n in bundled_ids

    add = a.add_issue

    def display(modid: str) -> str:
        return kb.get("friendly_names", {}).get(norm(modid), modid)

    # --- fichiers problématiques -------------------------------------------
    for j in jars:
        if j.status in ("corrupt", "unreadable"):
            add(f"file:{j.file}", "error", "files", _("Fichier illisible : {file}", file=j.file), j.error or "",
                files=[j.file], fix=_("Retélécharge ce mod depuis sa source officielle, ou retire-le."))
        elif j.status == "no-metadata":
            if not getattr(j, "library", False):  # une bibliothèque déclarée (FMLModType) est normale : rien à dire
                add(f"nometa:{j.file}", "info", "files", _("Sans métadonnées : {file}", file=j.file),
                    _("Aucun neoforge.mods.toml / mods.toml / fabric.mod.json n'a été trouvé. C'est normal pour une "
                      "bibliothèque ; si c'est censé être un mod, il ne sera pas chargé."),
                    files=[j.file], fix=_("Vérifie que c'est bien un mod pour ce loader ; sinon ignore ce message."))
        elif compat[j.file] == "mismatch":
            found = ", ".join(LOADER_LABELS.get(l, l) for l in j.loaders)
            add(f"loader:{j.file}", "error", "files", _("Mauvais loader : {file}", file=j.file),
                _("Ce mod est conçu pour {found}, mais le pack tourne sous {loader}. Il ne sera pas chargé.",
                  found=found, loader=loader_label),
                files=[j.file], modids=[m.modid for m in active[j.file]],
                fix=_("Télécharge la version {loader} de ce mod, ou retire-le.", loader=loader_label), confidence="likely")
        elif compat[j.file] == "fallback":
            old_mc = bool(a.mc_version and (V.mc_minor(a.mc_version) or (9, 9)) <= (1, 20))
            add(f"loader:{j.file}", "info" if old_mc else "warning", "files", _("Mod Forge dans un pack NeoForge : {file}", file=j.file),
                (_("NeoForge reste compatible avec les mods Forge jusqu'à Minecraft 1.20.1 : ce mod devrait se charger.")
                 if old_mc else
                 _("Forge et NeoForge ont divergé depuis Minecraft 1.20.2 : ce mod risque de ne pas se charger "
                   "(ou de planter) s'il n'existe pas en version NeoForge.")),
                files=[j.file], modids=[m.modid for m in active[j.file]],
                fix="" if old_mc else _("Cherche la version NeoForge de ce mod."), confidence="heuristic")
        elif compat[j.file] == "bridged":
            via = bridged.get(active[j.file][0].loader, _("une passerelle"))
            add(f"loader:{j.file}", "info", "files", _("Mod {loader} chargé via {via} : {file}", loader=LOADER_LABELS.get(active[j.file][0].loader), via=via, file=j.file),
                _("Ce mod n'est pas conçu pour {loader}, mais {via} est présent dans le pack et sait en faire "
                  "tourner beaucoup. Ce n'est pas garanti pour tous : si le jeu plante, ce mod est un suspect de choix.",
                  loader=loader_label, via=via),
                files=[j.file], modids=[m.modid for m in active[j.file]])

    if extras:
        if extras.get("disabled"):
            add("disabled", "info", "files", _("{n} fichier(s) désactivé(s) ignoré(s)", n=extras["disabled"]),
                _("Les fichiers .jar.disabled / .jar.old ne sont pas chargés par le jeu et ne sont pas analysés."))
        if extras.get("subfolder_jars"):
            add("subfolders", "info", "files", _("{n} jar dans des sous-dossiers ignoré(s)", n=extras["subfolder_jars"]),
                _("Seuls les .jar situés directement dans le dossier mods sont lus par ModMaestro "
                  "(comme par la plupart des loaders)."))

    # --- doublons -----------------------------------------------------------
    dup_losers: set[str] = set()
    groups: dict[str, list[tuple[str, ModInfo]]] = defaultdict(list)
    for j in jars:
        if compat[j.file] == "mismatch":
            continue
        for m in active[j.file]:
            if norm(m.modid) not in _PLATFORM_N:
                groups[norm(m.modid)].append((j.file, m))
    mtimes = {j.file: j.mtime for j in jars}

    def _cmp(x, y):
        c = V.compare(x[1].version or "0", y[1].version or "0")
        return c or ((mtimes[x[0]] > mtimes[y[0]]) - (mtimes[x[0]] < mtimes[y[0]]))

    for gid, items in groups.items():
        files = sorted({f for f, _m in items})
        if len(files) < 2:
            continue
        ordered = sorted(items, key=cmp_to_key(_cmp), reverse=True)
        keep = ordered[0][0]
        removed = [f for f in files if f != keep]
        dup_losers.update(removed)
        name = ordered[0][1].name
        lines = [f"{f} — v{next((m.version for ff, m in items if ff == f), '?') or '?'}" for f in files]
        same = len({(m.version or "") for _f, m in items}) == 1
        add(f"dup:{gid}", "error", "duplicates", _("Doublon : {name}", name=name),
            (_("Même version présente en plusieurs fichiers (copie ?) : ") if same
             else _("Plusieurs versions du même mod sont installées — le jeu refuse de démarrer : "))
            + " · ".join(lines),
            files=files, modids=[ordered[0][1].modid],
            fix=_("Garde {keep} (version la plus récente) et supprime : {removed}.", keep=keep, removed=", ".join(removed)),
            data={"keep": keep, "remove": removed}, confidence="certain")

    # --- dépendances manquantes / versions ------------------------------------
    missing: dict[str, list[tuple[str, str, object]]] = defaultdict(list)
    bad_versions: dict[tuple[str, bool], list[tuple[ModInfo, str, str, object, str]]] = defaultdict(list)
    for j in jars:
        if compat[j.file] == "mismatch":
            continue
        for m in active[j.file]:
            for dep in m.deps:
                n = norm(dep.modid)
                if dep.kind == "required" and n not in _PLATFORM_N and not is_provided(dep.modid):
                    missing[dep.modid].append((m.name, j.file, dep.range, dep.side))
                if dep.kind in ("required", "optional") and n not in _PLATFORM_N and n in providers:
                    direct = [(f, pm) for f, pm, d in providers[n] if d]
                    if not direct:
                        continue
                    best = sorted(direct, key=cmp_to_key(lambda x, y: V.compare(x[1].version or "0", y[1].version or "0")),
                                  reverse=True)[0][1]
                    if not V.satisfies(dep.syntax, dep.range, best.version):
                        bad_versions[(dep.modid, dep.kind == "required")].append(
                            (m, j.file, best.version or "?", dep.range, best.name))

    for modid, reqs in sorted(missing.items()):
        names = sorted({r[0] for r in reqs})
        files = sorted({r[1] for r in reqs})
        # une dépendance réservée au client ou au serveur n'est pas forcément nécessaire dans ce dossier
        one_sided = all(r[3] in ("CLIENT", "SERVER") for r in reqs)
        ranges = sorted({str(r[2]) for r in reqs if r[2] and str(r[2]) not in ("*", "")})
        shown = ", ".join(names[:6]) + (_(" et {n} autre(s)", n=len(names) - 6) if len(names) > 6 else "")
        hint = _(" Version attendue : {ranges}.", ranges=" ; ".join(ranges[:3])) if ranges else ""
        target = ", ".join(x for x in [("Minecraft " + a.mc_version) if a.mc_version else "", loader_label if a.loader else ""] if x)
        add(f"missing:{norm(modid)}", "warning" if one_sided else "error", "dependencies",
            _("Dépendance manquante : {name}", name=display(modid)),
            _("Requise par {n} mod(s) : {shown}.{hint}", n=len(names), shown=shown, hint=hint),
            files=files, modids=[modid],
            fix=_("Télécharge « {name} » ({target}) et place-le dans le dossier mods.", name=display(modid), target=target),
            links=_links(modid), data={"missing": modid, "required_by": names},
            confidence="likely" if one_sided else "certain")

    for (modid, required), rows in sorted(bad_versions.items()):
        have = rows[0][2]
        names = sorted({r[0].name for r in rows})
        ranges = sorted({str(r[3]) for r in rows})
        add(f"version:{norm(modid)}:{'req' if required else 'opt'}",
            "error" if required else "info", "versions",
            _("Version incompatible : {name} {have}", name=display(modid), have=have),
            ng("{names} demande {ranges}, mais la version installée est {have}.",
               "{names} demandent {ranges}, mais la version installée est {have}.", len(names),
               names=", ".join(names[:6]), ranges=" ; ".join(ranges[:3]), have=have)
            + ("" if required else _(" (dépendance facultative : l'intégration sera simplement désactivée)")),
            files=sorted({r[1] for r in rows}), modids=[modid],
            fix=_("Mets à jour « {name} » (ou le mod qui l'exige) pour que les versions concordent.", name=display(modid)),
            links=_links(modid), confidence="likely")

    # --- incompatibilités déclarées -----------------------------------------------
    seen_pairs: set[tuple[str, str]] = set()
    for j in jars:
        if compat[j.file] == "mismatch":
            continue
        for m in active[j.file]:
            for dep in m.deps:
                if dep.kind not in ("incompatible", "discouraged"):
                    continue
                n = norm(dep.modid)
                direct = [(f, pm) for f, pm, d in providers.get(n, []) if d]
                for f, target in direct:
                    if f == j.file or not V.satisfies(dep.syntax, dep.range, target.version):
                        continue
                    pair = tuple(sorted((norm(m.modid), n)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    hard = dep.kind == "incompatible"
                    why = _(" Raison donnée par l'auteur : {reason}", reason=dep.reason) if dep.reason else ""
                    add(f"incompat:{pair[0]}:{pair[1]}", "error" if hard else "warning", "compat",
                        f"{m.name} ↔ {target.name}",
                        (_("{a} déclare être incompatible avec {b}.{why}", a=m.name, b=target.name, why=why) if hard
                         else _("{a} déclare se marier mal avec {b}.{why}", a=m.name, b=target.name, why=why)),
                        files=[j.file, f], modids=[m.modid, target.modid],
                        fix=_("Retire l'un des deux mods (ou cherche une version qui les rend compatibles)."),
                        confidence="certain" if hard else "likely")

    # --- conflits connus --------------------------------------------------------------
    present: dict[str, str] = {}
    for gid, items in groups.items():
        present[gid] = items[0][0]
    for k, rule in enumerate(kb.get("conflict_rules", [])):
        if "group" in rule:
            found = [g for g in rule["group"] if norm(g) in present]
            hit = len(found) >= 2
        else:
            fa = [g for g in rule.get("a", []) if norm(g) in present]
            fb = [g for g in rule.get("b", []) if norm(g) in present]
            found, hit = fa + fb, bool(fa and fb)
        if hit:
            src = rule.get("source")
            add(f"known:{k}", rule.get("severity", "warning"), "compat", tr(rule["title"]),
                tr(rule["message"]) + _(" Présents : {found}.", found=", ".join(found))
                + (_(" (source : {src})", src=tr(src)) if src else ""),
                files=sorted({present[norm(g)] for g in found}), modids=found, fix=tr(rule.get("fix", "")),
                data={"source": src} if src else None, confidence="likely" if rule.get("confirmed") else "heuristic")

    # --- version de Minecraft (le calcul a eu lieu plus haut) --------------------------------
    best = a.mc_version
    if best and a.mc_confidence >= 0.5:
        chosen_minor = V.mc_minor(best)
        off, far_n = [], 0
        for f, m, r, s in mc_items:
            if V.satisfies(s, r, best):
                continue
            minors = {V.mc_minor(c) for c in V.candidate_versions(r)}
            far = chosen_minor not in minors
            far_n += far
            off.append({"file": f, "modid": m.modid, "name": m.name, "version": m.version, "far": far,
                        "wanted": r if isinstance(r, str) else _(" ou ").join(r)})
        if off:
            # Une seule alerte pour tout le pack (et non une par mod) : une version de Minecraft mal devinée ne
            # doit pas faire s'effondrer le score. Sévérité et confiance dépendent de la netteté de la majorité.
            sure = a.mc_confidence >= 0.8
            shown = ", ".join(_("{name} (vise {wanted})", name=o["name"], wanted=o["wanted"]) for o in off[:6])
            add("mc-versions", "error" if (far_n and sure) else "warning", "versions",
                ng("{n} mod ne vise pas Minecraft {mc}", "{n} mods ne visent pas Minecraft {mc}", len(off), mc=best),
                _("La majorité du pack ({pct} %) vise Minecraft {mc}, mais {shown}{more}. "
                  "Si le pack démarre, c'est que la version déduite est fausse : ignore cette alerte.",
                  pct=round(a.mc_confidence * 100), mc=best, shown=shown,
                  more=_(" et {n} autre(s)", n=len(off) - 6) if len(off) > 6 else ""),
                files=sorted({o["file"] for o in off}), modids=[o["modid"] for o in off],
                fix=_("Prends la version de ces mods pour Minecraft {mc}.", mc=best),
                data={"mc": best, "items": off}, confidence="likely" if sure else "heuristic")

    # --- fiches par fichier + plan serveur ------------------------------------------------------
    for j in jars:
        mods = active[j.file]
        side = (_classify_side(mods, kb, online.get(j.file)) if compat[j.file] != "mismatch"
                else {"value": "both", "confidence": None, "reason": None})
        if j.status == "no-metadata" and side["confidence"] is None:
            side = {"value": "unsure", "confidence": "probable",
                    "reason": _("Sans métadonnées : bibliothèque ou mod ancien — à vérifier")}
        required = sorted({
            d.modid for m in mods for d in m.deps
            if d.kind == "required" and norm(d.modid) not in _PLATFORM_N
        }, key=str.lower)
        provides = {norm(m.modid) for m in mods} | {norm(p) for m in mods for p in m.provides}
        provides |= {norm(b.modid) for b in j.bundled} | {norm(p) for b in j.bundled for p in b.provides}

        if j.status in ("corrupt", "unreadable"):
            server = {"action": "remove", "kind": "corrupt", "reason": _("Fichier illisible"), "unsure": False}
        elif compat[j.file] == "mismatch":
            server = {"action": "remove", "kind": "loader", "reason": _("Conçu pour un autre loader que {loader}", loader=loader_label), "unsure": False}
        elif j.file in dup_losers:
            server = {"action": "remove", "kind": "duplicate", "reason": _("Doublon : version plus ancienne"), "unsure": False}
        elif side["value"] == "client" and side["confidence"] in ("declared", "known", "modrinth"):
            server = {"action": "remove", "kind": "client", "reason": side["reason"], "unsure": False}
        elif side["value"] == "unsure":
            server = {"action": "keep", "kind": "unsure", "reason": side["reason"], "unsure": True}
        else:
            server = {"action": "keep", "kind": "", "reason": "", "unsure": False}

        a.entries[j.file] = {
            "file": j.file, "path": j.path, "size": j.size, "status": j.status, "compat": compat[j.file],
            "bundled_count": len({norm(b.modid) for b in j.bundled}),
            "mods": [{"modid": m.modid, "name": m.name, "version": m.version, "loader": m.loader,
                      "requires": required} for m in mods],
            "side": side, "server": server, "requires": required, "provides": sorted(provides),
        }
    return a


# --------------------------------------------------------------------------
# Plan « dossier serveur »
# --------------------------------------------------------------------------

def compute_plan(a: Analysis, exclude=(), include=()) -> dict:
    """Décide quels fichiers vont sur le serveur.

    exclude : fichiers que l'utilisateur veut retirer en plus.
    include : fichiers que l'utilisateur veut garder malgré la proposition.
    Un mod côté client retiré est automatiquement remis s'il est requis par un mod conservé.
    """
    exclude, include = set(exclude), set(include)
    state: dict[str, dict] = {}
    for f, e in a.entries.items():
        s = e["server"]
        state[f] = {"keep": s["action"] == "keep", "reason": s["reason"], "kind": s["kind"],
                    "unsure": s["unsure"], "manual": None}
    for f in include & state.keys():
        state[f].update(keep=True, reason=_("Gardé manuellement"), kind="manual", manual="include", unsure=False)
    for f in exclude & state.keys():
        state[f].update(keep=False, reason=_("Retiré manuellement"), kind="manual", manual="exclude", unsure=False)

    def provider_files(modid_n: str) -> list[str]:
        return [f for f, e in a.entries.items() if modid_n in e["provides"]]

    changed = True
    while changed:
        changed = False
        kept_provides = set()
        for f, s in state.items():
            if s["keep"]:
                kept_provides |= set(a.entries[f]["provides"])
        for f, s in list(state.items()):
            if not s["keep"]:
                continue
            for req in a.entries[f]["requires"]:
                rn = norm(req)
                if rn in kept_provides:
                    continue
                for cand in provider_files(rn):
                    c = state[cand]
                    if not c["keep"] and c["kind"] == "client" and c["manual"] is None:
                        c.update(keep=True, kind="dependency", unsure=False,
                                 reason=_("Gardé car requis par {name}", name=a.entries[f]["mods"][0]["name"] if a.entries[f]["mods"] else f))
                        kept_provides |= set(a.entries[cand]["provides"])
                        changed = True

    kept_provides = set()
    for f, s in state.items():
        if s["keep"]:
            kept_provides |= set(a.entries[f]["provides"])
    warnings = []
    for f, s in state.items():
        if not s["keep"]:
            continue
        for req in a.entries[f]["requires"]:
            if norm(req) not in kept_provides and norm(req) not in _PLATFORM_N:
                prov = provider_files(norm(req))
                if prov:  # il existait mais on l'a retiré
                    name = a.entries[f]["mods"][0]["name"] if a.entries[f]["mods"] else f
                    warnings.append({"file": f, "name": name, "missing": req, "provider": prov[0]})

    keep = sorted([f for f, s in state.items() if s["keep"]], key=str.lower)
    remove = [{"file": f, "reason": s["reason"], "kind": s["kind"]}
              for f, s in sorted(state.items(), key=lambda kv: kv[0].lower()) if not s["keep"]]
    unsure = [{"file": f, "reason": s["reason"]}
              for f, s in sorted(state.items(), key=lambda kv: kv[0].lower()) if s["keep"] and s["unsure"]]
    restored = [{"file": f, "reason": s["reason"]} for f, s in state.items() if s["kind"] == "dependency" and s["keep"]]
    return {"keep": keep, "remove": remove, "unsure": unsure, "restored": restored, "warnings": warnings}
