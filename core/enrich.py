"""Transforme les données Modrinth en alertes : incompatibilités, dépendances manquantes, mises à jour.

Les règles sont volontairement prudentes : une alerte issue de Modrinth est marquée comme telle, et les
dépendances manquantes ne sont que des *avertissements* (Modrinth peut lister une dépendance que le mod
embarque déjà ou qu'un autre mod fournit sous un autre nom).
"""

from __future__ import annotations

from collections import defaultdict

from .analyzer import Analysis, norm
from .i18n import _, ng
from .modrinth import OnlineData, project_url


def _name(online: OnlineData, project_id: str, fallback: str = "") -> str:
    p = online.projects.get(project_id) or {}
    return p.get("title") or p.get("slug") or fallback or project_id


def apply_online(a: Analysis, online: OnlineData) -> None:
    a.online = {"enabled": True, **online.stats, "error": online.error, "updates": 0}

    by_project: dict[str, list[str]] = defaultdict(list)  # project_id -> fichiers installés
    for fname, info in online.files.items():
        by_project[info["project_id"]].append(fname)
        if fname in a.entries:
            dl = next((f for f in info.get("files", []) if f.get("sha1") == info["sha1"]), None)
            a.entries[fname]["online"] = {
                "title": info["title"], "slug": info["slug"], "url": info["url"],
                "version": info["version_number"], "client_side": info["client_side"],
                "server_side": info["server_side"],
                "download": {"url": dl["url"], "size": dl.get("size")} if dl and dl.get("url") else None,
            }

    # --- incompatibilités déclarées sur Modrinth ------------------------------------------------
    already = [set(i["files"]) for i in a.issues if i["category"] == "compat"]
    seen: set[tuple[str, str]] = set()
    for fname, info in sorted(online.files.items()):
        for dep in info["dependencies"]:
            target = dep.get("project_id")
            if dep.get("dependency_type") != "incompatible" or not target or target not in by_project:
                continue
            pair = tuple(sorted((info["project_id"], target)))
            if pair in seen or info["project_id"] == target:
                continue
            seen.add(pair)
            files = sorted({fname, *by_project[target]})
            if any({fname, by_project[target][0]} <= s for s in already):
                continue  # déjà signalé par les métadonnées du mod lui-même
            a.add_issue(
                f"mr-incompat:{pair[0]}:{pair[1]}", "error", "compat",
                f"{info['title'] or fname} ↔ {_name(online, target)}",
                _("D'après Modrinth, {a} est déclaré incompatible avec {b}.", a=info["title"] or fname, b=_name(online, target)),
                files=files, fix=_("Retire l'un des deux mods, ou cherche une version qui les rend compatibles."),
                data={"source": "modrinth"})

    # --- dépendances requises, absentes du pack -----------------------------------------------------
    provided: set[str] = set()
    for e in a.entries.values():
        provided |= set(e["provides"])
    local_missing = {i["id"].split(":", 1)[1] for i in a.issues if i["id"].startswith("missing:")}

    missing: dict[str, dict] = {}
    for fname, info in sorted(online.files.items()):
        for dep in info["dependencies"]:
            pid = dep.get("project_id")
            if dep.get("dependency_type") != "required" or not pid or pid in by_project:
                continue
            proj = online.projects.get(pid) or {}
            slug = proj.get("slug") or ""
            if slug and norm(slug) in provided | local_missing:
                continue  # déjà fourni par un autre fichier, ou déjà signalé par les métadonnées
            m = missing.setdefault(pid, {"title": _name(online, pid), "slug": slug or pid, "by": set(), "files": set()})
            m["by"].add(info["title"] or fname)
            m["files"].add(fname)
    for pid, m in sorted(missing.items(), key=lambda kv: kv[1]["title"].lower()):
        names = sorted(m["by"])
        a.add_issue(
            f"mr-missing:{pid}", "warning", "dependencies", _("Dépendance probablement manquante : {name}", name=m["title"]),
            ng("D'après Modrinth, {names}{more} a besoin de {name}, absent du pack. "
               "À vérifier : le mod peut déjà l'embarquer.",
               "D'après Modrinth, {names}{more} ont besoin de {name}, absent du pack. "
               "À vérifier : le mod peut déjà l'embarquer.",
               len(names), names=", ".join(names[:6]), more=_(" et d’autres") if len(names) > 6 else "", name=m["title"]),
            files=sorted(m["files"]), fix=_("Télécharge « {name} » sur Modrinth si le jeu refuse de démarrer.", name=m["title"]),
            links=[{"label": "Modrinth", "url": project_url(m["slug"])}],
            data={"source": "modrinth", "missing_project": pid})


def apply_updates(a: Analysis, updates: list[dict], error: str | None = None) -> None:
    if a.online.get("enabled"):
        a.online["updates"] = len(updates)
        if error and not a.online.get("error"):
            a.online["error"] = error
    if not updates:
        return
    shown = ", ".join(f"{u['name']} ({u['current']} → {u['latest']})" for u in updates[:5])
    a.add_issue(
        "updates", "info", "updates",
        ng("{n} mise à jour disponible", "{n} mises à jour disponibles", len(updates)),
        _("Versions plus récentes trouvées sur Modrinth pour votre loader et votre version de Minecraft : {shown}{dots}. "
          "Mettre à jour n'est jamais obligatoire : fais-le surtout si tu as un problème avec l'un de ces mods.",
          shown=shown, dots=" …" if len(updates) > 5 else ""),
        files=[u["file"] for u in updates], data={"source": "modrinth", "updates": updates})
