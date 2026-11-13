"""Conseils de mods : ce qui ferait mieux tourner ce pack (performances, compagnons, passerelles, diagnostic).

Ce sont des **suggestions**, jamais des ajouts automatiques. Sans Modrinth, la disponibilité pour ta version de
Minecraft n'est pas vérifiée (et c'est dit). Avec Modrinth, chaque conseil est vérifié pour ton loader et ta version.
"""

from __future__ import annotations

import json
import os

from . import modrinth as mr
from .analyzer import Analysis, norm
from .i18n import _, get_lang

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "recommendations.json")
CATEGORIES = ("compat", "performance", "companion", "diagnostic")


def load_rules(path: str = DATA) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["suggestions"]


def _installed(a: Analysis) -> set[str]:
    out: set[str] = set()
    for e in a.entries.values():
        out |= set(e["provides"])
    return out


def suggest(a: Analysis, rules: list[dict] | None = None) -> list[dict]:
    rules = rules if rules is not None else load_rules()
    loader = a.loader or ""
    have = _installed(a)
    n_mods = sum(len(e["mods"]) for e in a.entries.values())
    foreign = {m.get("loader") for e in a.entries.values() if e["compat"] in ("mismatch", "bridged")
               for m in e["mods"]}
    en = get_lang() == "en"
    out = []
    for r in rules:
        if loader and loader not in r["loaders"]:
            continue
        if have & {norm(x) for x in r["ids"]} or have & {norm(x) for x in r.get("skip_if", [])}:
            continue
        if r.get("requires") and not (have & {norm(x) for x in r["requires"]}):
            continue
        if n_mods < r.get("min_mods", 0):
            continue
        if r.get("bridge_for") and not (foreign & set(r["bridge_for"])):
            continue  # inutile si aucun mod d'un autre loader n'est présent
        out.append({
            "id": r["id"], "name": r["name"], "slug": r["slug"], "url": mr.project_url(r["slug"]),
            "category": r["category"], "side": r["side"],
            "why": r.get("why_en") if en and r.get("why_en") else r["why"],
            "loaders": [x for x in r["loaders"]], "available": None, "version": None, "group": r.get("group"),
        })
    return out


def verify(items: list[dict], a: Analysis, client: mr.Modrinth, cache=None) -> str | None:
    """Vérifie sur Modrinth la disponibilité pour le loader et la version de Minecraft du pack."""
    if not a.mc_version or not a.loader:
        return None
    loaders = [a.loader] + (["fabric"] if a.loader == "quilt" else [])
    key = f"rec|{','.join(loaders)}|{a.mc_version}"
    for it in items:
        ck = f"rec:{it['slug']}"
        cached = cache.get_latest([ck], key) if cache else {}
        if ck in cached:
            v = cached[ck]
        else:
            try:
                versions = client.project_versions(it["slug"], loaders, [a.mc_version])
            except mr.ModrinthError as exc:
                return str(exc)
            v = versions[0] if versions else None
            if cache:
                cache.put_latest({ck: v}, key)
        it["available"] = bool(v)
        it["version"] = v["version_number"] if v else None
    return None


def _collapse_groups(items: list[dict]) -> list[dict]:
    """Un seul conseil par groupe d'alternatives (Sodium ou Embeddium…) : le premier disponible, sinon le premier."""
    out, seen = [], {}
    for it in items:
        g = it.get("group")
        if not g:
            out.append(it)
        elif g not in seen:
            seen[g] = it
            it["alternatives"] = []
            out.append(it)
        else:
            cur = seen[g]
            if cur["available"] is False and it["available"] is not False:
                it["alternatives"] = [cur["name"]] + cur["alternatives"]
                out[out.index(cur)] = it
                seen[g] = it
            else:
                cur["alternatives"].append(it["name"])
    return out


def run(a: Analysis, online: bool = False, client: mr.Modrinth | None = None, cache=None) -> dict:
    items = suggest(a)
    error = verify(items, a, client or mr.Modrinth(), cache) if online else None
    if online:
        items.sort(key=lambda i: (i["available"] is False, CATEGORIES.index(i["category"])))
    else:
        items.sort(key=lambda i: CATEGORIES.index(i["category"]))
    note = _("Disponibilité non vérifiée pour Minecraft {mc} : active Modrinth pour la contrôler.", mc=a.mc_version or "?") \
        if not online else None
    items = _collapse_groups(items)
    return {"items": items, "verified": online and error is None, "error": error, "note": note,
            "mc_version": a.mc_version, "loader": a.loader}
