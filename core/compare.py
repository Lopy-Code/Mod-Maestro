"""Comparaison de deux modpacks (ou de deux versions d'un même pack)."""

from __future__ import annotations

from . import versions as V
from .i18n import _


def _index(d: dict) -> dict[str, dict]:
    """Les mods d'une analyse, indexés par identifiant (à défaut : nom de fichier)."""
    out: dict[str, dict] = {}
    for m in d["mods"]:
        key = (m["modid"] or m["file"]).lower().replace("-", "_")
        out.setdefault(key, m)
    return out


def compare(a: dict, b: dict) -> dict:
    """`a` = pack de départ (avant), `b` = pack d'arrivée (après). Les deux sont des `Analysis.to_dict()`."""
    ia, ib = _index(a), _index(b)
    added = [ib[k] for k in sorted(ib.keys() - ia.keys())]
    removed = [ia[k] for k in sorted(ia.keys() - ib.keys())]
    updated, downgraded, unchanged = [], [], 0
    for k in sorted(ia.keys() & ib.keys()):
        va, vb = ia[k]["version"], ib[k]["version"]
        row = {"modid": ib[k]["modid"], "name": ib[k]["name"], "from": va, "to": vb,
               "file_from": ia[k]["file"], "file_to": ib[k]["file"]}
        if (va or "") == (vb or ""):
            unchanged += 1
        elif V.compare(vb or "0", va or "0") > 0:
            updated.append(row)
        else:
            downgraded.append(row)

    issues_a = {i["id"]: i for i in a["issues"] if not i.get("ignored")}
    issues_b = {i["id"]: i for i in b["issues"] if not i.get("ignored")}
    new_issues = [issues_b[k] for k in issues_b.keys() - issues_a.keys() if issues_b[k]["severity"] != "info"]
    fixed_issues = [issues_a[k] for k in issues_a.keys() - issues_b.keys() if issues_a[k]["severity"] != "info"]
    order = {"error": 0, "warning": 1, "info": 2}
    new_issues.sort(key=lambda i: (order[i["severity"]], i["title"]))
    fixed_issues.sort(key=lambda i: (order[i["severity"]], i["title"]))

    def head(d):
        return {"source": d["source"], "loader": d["loader"], "loader_label": d["loader_label"],
                "mc_version": d["mc_version"], "score": d["score"], "mods": d["counts"]["mods"],
                "errors": d["counts"]["errors"], "warnings": d["counts"]["warnings"]}

    notes = []
    if a["loader"] != b["loader"]:
        notes.append(_("Les deux packs ne tournent pas sous le même loader ({a} / {b}) : la plupart des mods diffèrent.",
                       a=a["loader_label"], b=b["loader_label"]))
    if a["mc_version"] and b["mc_version"] and a["mc_version"] != b["mc_version"]:
        notes.append(_("Versions de Minecraft différentes ({a} / {b}).", a=a["mc_version"], b=b["mc_version"]))
    return {
        "a": head(a), "b": head(b), "added": added, "removed": removed, "updated": updated,
        "downgraded": downgraded, "unchanged": unchanged, "new_issues": new_issues,
        "fixed_issues": fixed_issues, "notes": notes,
        "score_delta": b["score"] - a["score"],
    }
