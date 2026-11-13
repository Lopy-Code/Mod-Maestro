"""Export du rapport d'audit en Markdown."""

from __future__ import annotations

from datetime import datetime

from .i18n import _, get_lang


def _sev(k: str) -> str:
    return {"error": "🔴 " + _("Erreur"), "warning": "🟠 " + _("Avertissement"), "info": "🔵 " + _("Info")}[k]


def _cat(k: str) -> str:
    return {"files": _("Fichiers"), "duplicates": _("Doublons"), "dependencies": _("Dépendances manquantes"),
            "versions": _("Versions"), "compat": _("Compatibilité"), "updates": _("Mises à jour")}.get(k, k)


def _side(k: str) -> str:
    return {"client": _("Client"), "server": _("Serveur"), "both": _("Les deux"), "unsure": _("À vérifier")}.get(k, k)


def human_size(n: float) -> str:
    units = ("B", "KB", "MB", "GB") if get_lang() == "en" else ("o", "Ko", "Mo", "Go")
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.0f} {unit}" if unit == units[0] else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} {units[0]}"


def to_markdown(d: dict) -> str:
    c = d["counts"]
    lines = [
        _("# Rapport ModMaestro"),
        "",
        _("*Généré le {date} à {time}*", date=f"{datetime.now():%d/%m/%Y}", time=f"{datetime.now():%H:%M}"),
        "",
        _("- **Dossier** : `{path}`", path=d["mods_dir"]),
        _("- **Loader** : {loader}", loader=d["loader_label"])
        + (_(" · **Minecraft** {version}", version=d["mc_version"]) if d.get("mc_version") else ""),
        _("- **Contenu** : {jars} fichiers, {mods} mods, {bundled} intégrés (jar-in-jar), {size}",
          jars=c["jars"], mods=c["mods"], bundled=c["bundled"], size=human_size(c["size"])),
        _("- **Santé** : {score}/100 — {errors} erreur(s), {warnings} avertissement(s), {infos} info(s)",
          score=d["score"], errors=c["errors"], warnings=c["warnings"], infos=c["infos"]),
        "",
    ]
    o = d.get("online") or {}
    if o.get("enabled"):
        lines.insert(-1, _("- **Modrinth** : {a}/{b} mods reconnus par empreinte SHA-1", a=o.get("identified", 0), b=o.get("total", 0))
                     + (f" — ⚠ {o['error']}" if o.get("error") else ""))
    else:
        lines.insert(-1, _("- **Modrinth** : non interrogé (analyse hors ligne)"))
    if (d.get("kb") or {}).get("learned"):
        lines.insert(-1, _("- **Ma base** : {n} entrée(s) personnelle(s) appliquée(s)", n=d["kb"]["learned"]))
    if not d["issues"]:
        lines += [_("## ✅ Aucun problème détecté"), ""]
    else:
        cats: dict[str, list] = {}
        for i in d["issues"]:
            cats.setdefault(i["category"], []).append(i)
        for cat in ("duplicates", "dependencies", "versions", "compat", "updates", "files"):
            items = cats.get(cat)
            if not items:
                continue
            lines += [f"## {_cat(cat)} ({len(items)})", ""]
            for i in items:
                lines.append(f"### {_sev(i['severity'])} — {i['title']}")
                lines.append("")
                lines.append(i["message"])
                if i.get("fix"):
                    lines += ["", _("**À faire :** {fix}", fix=i["fix"])]
                if (i.get("data") or {}).get("updates"):
                    lines += ["", _("| Mod | Installée | Disponible |"), "|---|---|---|"]
                    lines += [f"| {u['name']} | {u['current']} | {u['latest']} |" for u in i["data"]["updates"]]
                if i.get("files"):
                    lines += ["", _("Fichiers : {files}", files=", ".join(f"`{f}`" for f in i["files"]))]
                lines.append("")

    p = d["plan"]
    lines += [
        _("## Dossier serveur (proposition)"),
        "",
        _("- {keep} mods conservés, {remove} retirés, {unsure} à vérifier",
          keep=c["server_keep"], remove=c["server_remove"], unsure=c["server_unsure"]),
        "",
    ]
    if p["remove"]:
        lines += [_("| Retiré | Raison |"), "|---|---|"]
        lines += [f"| `{r['file']}` | {r['reason']} |" for r in p["remove"]]
        lines.append("")
    if p["unsure"]:
        lines += [_("À vérifier (gardés par défaut) :"), ""]
        lines += [f"- `{u['file']}` — {u['reason']}" for u in p["unsure"]]
        lines.append("")

    lines += [_("## Liste des mods"), "", _("| Mod | Version | Loader | Côté | Fichier |"), "|---|---|---|---|---|"]
    for m in d["mods"]:
        lines.append(f"| {m['name']} | {m['version'] or '?'} | {m['loader'] or '—'} | "
                     f"{_side(m['side'])} | `{m['file']}` |")
    lines.append("")
    return "\n".join(lines)
