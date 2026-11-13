"""Chercheur de cause de crash : dichotomie guidée.

Principe : on ne peut pas deviner quel mod fait planter le jeu sans essayer. On le trouve en peu d'essais en
coupant les suspects en deux à chaque tour : ModMaestro prépare un dossier `mods` de test (une COPIE, jamais ton
dossier d'origine) ; tu lances le jeu et tu réponds « ça plante » ou « ça marche ». 100 mods → 7 essais.

Une moitié n'est jamais testée seule : on y ajoute les mods dont elle dépend, sinon le jeu planterait pour une
autre raison (dépendance manquante) et fausserait tout.

L'état est un simple dictionnaire JSON : le serveur le garde, ou le client le renvoie.
"""

from __future__ import annotations

import math
import os
import secrets
import shutil

from .analyzer import Analysis, norm
from .i18n import _, ng

CRASH, FINE, SKIP = "crash", "fine", "skip"


def _closure(a: Analysis, files: set[str]) -> set[str]:
    """`files` + tous les fichiers qui fournissent ce dont ils ont besoin (récursivement)."""
    providers: dict[str, list[str]] = {}
    for f, e in a.entries.items():
        for pid in e["provides"]:
            providers.setdefault(pid, []).append(f)
    out, todo = set(files), list(files)
    while todo:
        f = todo.pop()
        for req in a.entries[f]["requires"]:
            for p in providers.get(norm(req), []):
                if p not in out:
                    out.add(p)
                    todo.append(p)
    return out


def _dependents(a: Analysis, f: str) -> set[str]:
    """`f` + tous les fichiers qui ne peuvent pas fonctionner sans lui."""
    return {g for g in a.entries if f in _closure(a, {g})}


def quick_suspects(a: Analysis, log_mods=(), limit: int = 8) -> list[dict]:
    """Suspects « évidents » à regarder avant la dichotomie : cités par le journal, puis derniers ajoutés."""
    cited = {norm(x) for x in log_mods}
    rows = []
    for f, e in a.entries.items():
        mids = {norm(m["modid"]) for m in e["mods"]}
        if cited & mids:
            rows.append({"file": f, "name": e["mods"][0]["name"], "why": _("Cité dans le journal"), "rank": 0, "mtime": 0})
    mt = {f: os.path.getmtime(e["path"]) for f, e in a.entries.items() if os.path.exists(e["path"])}
    if mt:
        newest = sorted(mt, key=mt.get, reverse=True)
        spread = mt[newest[0]] - mt[newest[-1]]
        if spread > 3600:  # si tout a été copié en même temps, l'ancienneté ne veut rien dire
            for f in newest[:5]:
                if all(r["file"] != f for r in rows):
                    name = a.entries[f]["mods"][0]["name"] if a.entries[f]["mods"] else f
                    rows.append({"file": f, "name": name, "why": _("Ajouté récemment"), "rank": 1, "mtime": mt[f]})
    return sorted(rows, key=lambda r: (r["rank"], -r["mtime"]))[:limit]


def start(a: Analysis, log_mods=()) -> dict:
    """Ouvre une session. Les fichiers sans métadonnées (bibliothèques) sont conservés en permanence."""
    always = {f for f, e in a.entries.items() if not e["mods"] or e["status"] != "ok"}
    suspects = sorted(set(a.entries) - always)
    state = {
        "id": secrets.token_hex(5), "analysis": a.id, "suspects": suspects, "cleared": [], "always": sorted(always),
        "history": [], "step": 0, "done": False, "result": None, "pending": None,
        "estimate": max(1, math.ceil(math.log2(max(2, len(suspects))))),
    }
    return _next_test(a, state)


def _next_test(a: Analysis, st: dict) -> dict:
    sus = st["suspects"]
    if len(sus) == 1 and not st.get("confirmed"):
        # Contre-épreuve : sans ce mod (ni ceux qui en dépendent), le jeu démarre-t-il vraiment ? Si non, le coupable
        # n'est pas ce mod seul (conflit entre plusieurs mods, Java, mémoire, configuration…).
        out = _dependents(a, sus[0])
        st["step"] += 1
        st["pending"] = {"files": sorted(set(a.entries) - out), "in_play": sorted(sus), "step": st["step"], "kind": "confirm"}
        return st
    if len(sus) <= 1:
        st["done"], st["pending"] = True, None
        st["result"] = {"kind": "single" if sus else "none", "files": list(sus)}
        return st
    # on teste la première moitié (avec ses dépendances) ; l'ordre est stable pour que ce soit reproductible
    half = set(sus[: len(sus) // 2])
    test = _closure(a, half) | set(st["cleared"]) | set(st["always"])
    # ce que ce test met réellement en jeu parmi les suspects
    in_play = sorted(set(sus) & test)
    if set(in_play) == set(sus):  # les dépendances ont tout remis : plus de dichotomie possible
        st["done"], st["pending"] = True, None
        st["result"] = {"kind": "group", "files": list(sus)}
        return st
    st["step"] += 1
    st["pending"] = {"files": sorted(test), "in_play": in_play, "step": st["step"]}
    return st


def answer(a: Analysis, st: dict, outcome: str) -> dict:
    """`outcome` : crash | fine | skip (je n'ai pas pu tester)."""
    if st["done"] or not st["pending"]:
        return st
    if outcome not in (CRASH, FINE, SKIP):
        raise ValueError(_("Réponse inconnue."))
    p = st["pending"]
    sus = set(st["suspects"])
    in_play = set(p["in_play"])
    st["history"].append({"step": p["step"], "in_play": len(in_play), "outcome": outcome, "kind": p.get("kind", "split")})
    if p.get("kind") == "confirm":
        st["confirmed"] = outcome != SKIP
        st["done"], st["pending"] = True, None
        st["result"] = {"kind": "unconfirmed" if outcome == CRASH else "single", "files": sorted(sus),
                        "confirmed": outcome == FINE}
        return st
    if outcome == CRASH:
        st["suspects"] = sorted(in_play)  # le fautif est parmi ce qui était en jeu
    elif outcome == FINE:
        st["cleared"] = sorted(set(st["cleared"]) | in_play)  # innocentés
        st["suspects"] = sorted(sus - in_play)
        if not st["suspects"]:
            st["done"], st["pending"] = True, None
            st["result"] = {"kind": "interaction", "files": sorted(in_play)}
            return st
    else:  # skip : on essaie l'autre moitié en mélangeant l'ordre
        st["suspects"] = st["suspects"][::-1]
    return _next_test(a, st)


def describe(a: Analysis, st: dict) -> dict:
    """Version affichable de l'état."""
    def name(f):
        e = a.entries.get(f)
        return e["mods"][0]["name"] if e and e["mods"] else f
    res = st["result"]
    if res:
        res = {**res, "names": [{"file": f, "name": name(f)} for f in res["files"]]}
    pend = st["pending"]
    return {
        "id": st["id"], "done": st["done"], "step": st["step"], "estimate": st["estimate"],
        "remaining": len(st["suspects"]), "cleared": len(st["cleared"]), "history": st["history"],
        "result": res,
        "pending": {"step": pend["step"], "count": len(pend["files"]), "in_play": len(pend["in_play"]),
                    "kind": pend.get("kind", "split"), "removed": sorted(set(a.entries) - set(pend["files"])) if pend.get("kind") == "confirm" else [],
                    "excluded": len(st["suspects"]) - len(pend["in_play"])} if pend else None,
    }


def build_test_folder(a: Analysis, st: dict, output: str) -> dict:
    """Écrit le dossier `mods` du test en cours dans `output` (nouveau dossier ; jamais la source)."""
    if not st.get("pending"):
        raise ValueError(_("Aucun test en cours."))
    out = os.path.abspath(os.path.expanduser(output.strip().strip('"')))
    src = os.path.realpath(a.mods_dir)
    if os.path.realpath(out) == src or os.path.realpath(out).startswith(src + os.sep) or src.startswith(os.path.realpath(out) + os.sep):
        raise ValueError(_("Le dossier de test ne doit pas être le dossier de mods (ni dedans, ni le contenir)."))
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        raise FileExistsError(_("« {path} » existe déjà et n'est pas vide. Choisis un autre nom.", path=out))
    os.makedirs(out, exist_ok=True)
    for f in st["pending"]["files"]:
        shutil.copy2(a.entries[f]["path"], os.path.join(out, f))
    return {"output": out, "copied": len(st["pending"]["files"])}


def summary(a: Analysis, st: dict) -> str:
    """Phrase de conclusion."""
    res = st["result"]
    if not res:
        return ""
    names = ", ".join(f"« {e['mods'][0]['name'] if e['mods'] else f} »" for f in res["files"] for e in [a.entries[f]])
    if res["kind"] == "single":
        if res.get("confirmed") is False:
            return _("Le mod fautif est probablement {names} (non confirmé).", names=names)
        return _("Le mod fautif est {names} : le jeu démarre sans lui.", names=names)
    if res["kind"] == "group":
        return ng("Le fautif est dans ce groupe de {n} mod, qui dépendent les uns des autres : {names}.",
                  "Le fautif est dans ce groupe de {n} mods, qui dépendent les uns des autres : {names}.",
                  len(res["files"]), names=names)
    if res["kind"] == "interaction":
        return _("Aucun mod ne plante seul : c'est une combinaison de mods qui pose problème (conflit). "
                 "Teste en retirant les mods suivants par paires : {names}.", names=names)
    if res["kind"] == "unconfirmed":
        return _("{names} semble impliqué, mais le jeu plante encore sans lui : plusieurs mods se gênent entre eux, "
                 "ou la cause n'est pas un mod (version de Java, mémoire, configuration). Regarde le journal de crash.",
                 names=names)
    return _("Aucun suspect n'a été trouvé.")
