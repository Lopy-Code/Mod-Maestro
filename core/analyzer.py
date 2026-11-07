"""Analyse d'un modpack : doublons, dépendances, incompatibilités, côté client/serveur."""

from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter, defaultdict
from functools import cmp_to_key
from urllib.parse import quote

from . import versions as V
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

    # -- sérialisation -----------------------------------------------------
    def counts(self) -> dict:
        sev = Counter(i["severity"] for i in self.issues)
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
        }

    def score(self) -> int:
        c = Counter(i["severity"] for i in self.issues)
        return max(0, 100 - 7 * c["error"] - 2 * c["warning"])

    def verdict(self) -> str:
        sev = {i["severity"] for i in self.issues}
        return "bad" if "error" in sev else ("warn" if "warning" in sev else "ok")

    def to_dict(self) -> dict:
        mods = []
        for f, e in self.entries.items():
            side = e["side"]
            base = {
                "file": f, "size": e["size"], "status": e["status"], "side": side["value"],
                "side_confidence": side["confidence"], "side_reason": side["reason"],
                "compat": e["compat"], "bundled_count": e["bundled_count"],
            }
            if e["mods"]:
                for m in e["mods"]:
                    mods.append({**base, "name": m["name"], "modid": m["modid"], "version": m["version"],
                                 "loader": m["loader"], "requires": m["requires"]})
            else:
                mods.append({**base, "name": re.sub(r"\.jar$", "", f, flags=re.I), "modid": None,
                             "version": None, "loader": None, "requires": []})
        order = {"error": 0, "warning": 1, "info": 2}
        issues = sorted(self.issues, key=lambda i: (order[i["severity"]], i["category"], i["title"]))
        return {
            "id": self.id,
            "source": self.source,
            "mods_dir": self.mods_dir,
            "loader": self.loader,
            "loader_label": LOADER_LABELS.get(self.loader or "", "Inconnu"),
            "mc_version": self.mc_version,
            "mc_confidence": round(self.mc_confidence, 2),
            "counts": self.counts(),
            "score": self.score(),
            "verdict": self.verdict(),
            "issues": issues,
            "mods": mods,
            "plan": compute_plan(self),
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------

def _dominant_loader(jars: list[JarInfo]) -> str | None:
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


def _active_mods(jar: JarInfo, loader: str | None) -> tuple[list[ModInfo], str]:
    """Mods du jar pour le loader du pack + état de compatibilité (ok | fallback | mismatch)."""
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
    first = jar.mods[0].loader
    return [m for m in jar.mods if m.loader == first], "mismatch"


def _classify_side(mods: list[ModInfo], kb: dict) -> dict:
    none = {"value": "both", "confidence": None, "reason": None}
    if not mods:
        return none
    if all(m.env == "client" for m in mods):
        return {"value": "client", "confidence": "declared",
                "reason": mods[0].env_reason or "Déclaré côté client dans les métadonnées"}
    if all(m.env == "server" for m in mods):
        return {"value": "server", "confidence": "declared",
                "reason": mods[0].env_reason or "Déclaré côté serveur dans les métadonnées"}
    client_ids = {norm(i) for i in kb.get("client_only", {}).get("ids", [])}
    if all(norm(m.modid) in client_ids for m in mods):
        return {"value": "client", "confidence": "known",
                "reason": "Mod connu pour ne servir que côté client (rendu, interface, minimap…)"}
    viewers = {norm(i) for i in kb.get("recipe_viewers", {}).get("ids", [])}
    if any(norm(m.modid) in viewers for m in mods):
        return {"value": "unsure", "confidence": "probable",
                "reason": "Visionneuse de recettes : facultative sur un serveur"}
    for m in mods:
        text = f"{m.modid} {m.name}".lower()
        tokens = set(re.split(r"[^a-z0-9]+", text))
        for kw in kb.get("client_keywords", []):
            if (len(kw) >= 6 and kw in text) or kw in tokens:
                return {"value": "unsure", "confidence": "probable",
                        "reason": f"Le nom évoque un mod côté client (« {kw} ») — à vérifier"}
    return none


def analyze(jars: list[JarInfo], extras: dict | None = None, source: str = "", mods_dir: str = "",
            notes: list[str] | None = None, knowledge: dict | None = None) -> Analysis:
    kb = knowledge or load_knowledge()
    a = Analysis(source or mods_dir, mods_dir or source)
    a.notes = list(notes or [])
    a.jar_count = len(jars)
    a.total_size = sum(j.size for j in jars)
    a.loader = _dominant_loader(jars)
    loader_label = LOADER_LABELS.get(a.loader or "", "le loader")

    active: dict[str, list[ModInfo]] = {}
    compat: dict[str, str] = {}
    for j in jars:
        mods, state = _active_mods(j, a.loader)
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
        for _, _, r, _ in mc_items:
            cands |= V.candidate_versions(r)
        best_v, best_n = None, -1
        for c in sorted(cands, key=cmp_to_key(V.compare)):
            n = sum(V.satisfies(s, r, c) for _, _, r, s in mc_items)
            if n >= best_n:
                best_v, best_n = c, n
        if best_v:
            a.mc_version, a.mc_confidence = best_v, best_n / len(mc_items)

    def is_provided(modid: str) -> bool:
        n = norm(modid)
        return n in _PLATFORM_N or n in providers or n in bundled_ids

    def add(issue_id, severity, category, title, message, files=(), modids=(), fix="", links=None, data=None):
        a.issues.append({
            "id": issue_id, "severity": severity, "category": category, "title": title,
            "message": message, "files": list(files), "modids": list(modids), "fix": fix,
            "links": links or [], "data": data or {},
        })

    def display(modid: str) -> str:
        return kb.get("friendly_names", {}).get(norm(modid), modid)

    # --- fichiers problématiques -------------------------------------------
    for j in jars:
        if j.status in ("corrupt", "unreadable"):
            add(f"file:{j.file}", "error", "files", f"Fichier illisible : {j.file}", j.error or "",
                files=[j.file], fix="Retélécharge ce mod depuis sa source officielle, ou retire-le.")
        elif j.status == "no-metadata":
            add(f"nometa:{j.file}", "warning", "files", f"Sans métadonnées : {j.file}",
                "Aucun neoforge.mods.toml / mods.toml / fabric.mod.json n'a été trouvé. "
                "Si ce n'est pas une bibliothèque volontaire, le mod ne sera pas chargé.",
                files=[j.file], fix="Vérifie que c'est bien un mod pour ce loader ; sinon retire-le.")
        elif compat[j.file] == "mismatch":
            found = ", ".join(LOADER_LABELS.get(l, l) for l in j.loaders)
            add(f"loader:{j.file}", "error", "files", f"Mauvais loader : {j.file}",
                f"Ce mod est conçu pour {found}, mais le pack tourne sous {loader_label}. Il ne sera pas chargé.",
                files=[j.file], modids=[m.modid for m in active[j.file]],
                fix=f"Télécharge la version {loader_label} de ce mod, ou retire-le.")
        elif compat[j.file] == "fallback":
            add(f"loader:{j.file}", "warning", "files", f"Mod Forge dans un pack NeoForge : {j.file}",
                "Forge et NeoForge ont divergé depuis Minecraft 1.20.2 : ce mod risque de ne pas se charger "
                "(ou de planter) s'il n'existe pas en version NeoForge.",
                files=[j.file], modids=[m.modid for m in active[j.file]],
                fix="Cherche la version NeoForge de ce mod.")

    if extras:
        if extras.get("disabled"):
            add("disabled", "info", "files", f"{extras['disabled']} fichier(s) désactivé(s) ignoré(s)",
                "Les fichiers .jar.disabled / .jar.old ne sont pas chargés par le jeu et ne sont pas analysés.")
        if extras.get("subfolder_jars"):
            add("subfolders", "info", "files", f"{extras['subfolder_jars']} jar dans des sous-dossiers ignoré(s)",
                "Seuls les .jar situés directement dans le dossier mods sont lus par ModMaestro "
                "(comme par la plupart des loaders).")

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
        files = sorted({f for f, _ in items})
        if len(files) < 2:
            continue
        ordered = sorted(items, key=cmp_to_key(_cmp), reverse=True)
        keep = ordered[0][0]
        removed = [f for f in files if f != keep]
        dup_losers.update(removed)
        name = ordered[0][1].name
        lines = [f"{f} — v{next((m.version for ff, m in items if ff == f), '?') or '?'}" for f in files]
        same = len({(m.version or "") for _, m in items}) == 1
        add(f"dup:{gid}", "error", "duplicates", f"Doublon : {name}",
            ("Même version présente en plusieurs fichiers (copie ?) : " if same
             else "Plusieurs versions du même mod sont installées — le jeu refuse de démarrer : ")
            + " · ".join(lines),
            files=files, modids=[ordered[0][1].modid],
            fix=f"Garde {keep} (version la plus récente) et supprime : {', '.join(removed)}.",
            data={"keep": keep, "remove": removed})

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
                    missing[dep.modid].append((m.name, j.file, dep.range))
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
        ranges = sorted({str(r[2]) for r in reqs if r[2] and str(r[2]) not in ("*", "")})
        shown = ", ".join(names[:6]) + (f" et {len(names) - 6} autre(s)" if len(names) > 6 else "")
        hint = f" Version attendue : {' ; '.join(ranges[:3])}." if ranges else ""
        add(f"missing:{norm(modid)}", "error", "dependencies", f"Dépendance manquante : {display(modid)}",
            f"Requise par {len(names)} mod(s) : {shown}.{hint}",
            files=files, modids=[modid],
            fix=f"Télécharge « {display(modid)} » ({', '.join(x for x in [('Minecraft ' + a.mc_version) if a.mc_version else '', loader_label if a.loader else ''] if x)}) "
                f"et place-le dans le dossier mods.",
            links=_links(modid), data={"missing": modid, "required_by": names})

    for (modid, required), rows in sorted(bad_versions.items()):
        have = rows[0][2]
        names = sorted({r[0].name for r in rows})
        ranges = sorted({str(r[3]) for r in rows})
        add(f"version:{norm(modid)}:{'req' if required else 'opt'}",
            "error" if required else "info", "versions",
            f"Version incompatible : {display(modid)} {have}",
            f"{', '.join(names[:6])} demande{'nt' if len(names) > 1 else ''} {' ; '.join(ranges[:3])}, "
            f"mais la version installée est {have}."
            + ("" if required else " (dépendance facultative : l'intégration sera simplement désactivée)"),
            files=sorted({r[1] for r in rows}), modids=[modid],
            fix=f"Mets à jour « {display(modid)} » (ou le mod qui l'exige) pour que les versions concordent.",
            links=_links(modid))

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
                    why = f" Raison donnée par l'auteur : {dep.reason}" if dep.reason else ""
                    add(f"incompat:{pair[0]}:{pair[1]}", "error" if hard else "warning", "compat",
                        f"{m.name} ↔ {target.name}",
                        f"{m.name} déclare {'être incompatible avec' if hard else 'se marier mal avec'} "
                        f"{target.name}.{why}",
                        files=[j.file, f], modids=[m.modid, target.modid],
                        fix="Retire l'un des deux mods (ou cherche une version qui les rend compatibles).")

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
            add(f"known:{k}", rule.get("severity", "warning"), "compat", rule["title"],
                rule["message"] + " Présents : " + ", ".join(found) + ".",
                files=sorted({present[norm(g)] for g in found}), modids=found, fix=rule.get("fix", ""))

    # --- version de Minecraft (le calcul a eu lieu plus haut) --------------------------------
    best = a.mc_version
    if best and a.mc_confidence >= 0.5:
        chosen_minor = V.mc_minor(best)
        for f, m, r, s in mc_items:
            if V.satisfies(s, r, best):
                continue
            minors = {V.mc_minor(c) for c in V.candidate_versions(r)}
            far = chosen_minor not in minors
            wanted = r if isinstance(r, str) else " ou ".join(r)
            add(f"mc:{f}:{norm(m.modid)}", "error" if far else "warning", "versions",
                f"Minecraft {best} non visé : {m.name}",
                f"{m.name} {m.version or ''} indique viser Minecraft {wanted}, "
                f"alors que le reste du pack tourne sous {best}.".replace("  ", " "),
                files=[f], modids=[m.modid],
                fix=f"Prends la version de ce mod pour Minecraft {best}.", links=_links(m.modid))

    # --- fiches par fichier + plan serveur ------------------------------------------------------
    for j in jars:
        mods = active[j.file]
        side = _classify_side(mods, kb) if compat[j.file] != "mismatch" else {"value": "both", "confidence": None, "reason": None}
        if j.status == "no-metadata":
            side = {"value": "unsure", "confidence": "probable",
                    "reason": "Sans métadonnées : bibliothèque ou mod ancien — à vérifier"}
        required = sorted({
            d.modid for m in mods for d in m.deps
            if d.kind == "required" and norm(d.modid) not in _PLATFORM_N
        }, key=str.lower)
        provides = {norm(m.modid) for m in mods} | {norm(p) for m in mods for p in m.provides}
        provides |= {norm(b.modid) for b in j.bundled} | {norm(p) for b in j.bundled for p in b.provides}

        if j.status in ("corrupt", "unreadable"):
            server = {"action": "remove", "kind": "corrupt", "reason": "Fichier illisible", "unsure": False}
        elif compat[j.file] == "mismatch":
            server = {"action": "remove", "kind": "loader", "reason": f"Conçu pour un autre loader que {loader_label}", "unsure": False}
        elif j.file in dup_losers:
            server = {"action": "remove", "kind": "duplicate", "reason": "Doublon : version plus ancienne", "unsure": False}
        elif side["value"] == "client" and side["confidence"] in ("declared", "known"):
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
        state[f].update(keep=True, reason="Gardé manuellement", kind="manual", manual="include", unsure=False)
    for f in exclude & state.keys():
        state[f].update(keep=False, reason="Retiré manuellement", kind="manual", manual="exclude", unsure=False)

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
                                 reason=f"Gardé car requis par {a.entries[f]['mods'][0]['name'] if a.entries[f]['mods'] else f}")
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
