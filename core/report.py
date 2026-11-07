"""Export du rapport d'audit en Markdown."""

from __future__ import annotations

from datetime import datetime

_SEV = {"error": "🔴 Erreur", "warning": "🟠 Avertissement", "info": "🔵 Info"}
_CAT = {
    "files": "Fichiers", "duplicates": "Doublons", "dependencies": "Dépendances manquantes",
    "versions": "Versions", "compat": "Compatibilité",
}
_SIDE = {"client": "Client", "server": "Serveur", "both": "Les deux", "unsure": "À vérifier"}


def human_size(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} o"


def to_markdown(d: dict) -> str:
    c = d["counts"]
    lines = [
        "# Rapport ModMaestro",
        "",
        f"*Généré le {datetime.now():%d/%m/%Y à %H:%M}*",
        "",
        f"- **Dossier** : `{d['mods_dir']}`",
        f"- **Loader** : {d['loader_label']}" + (f" · **Minecraft** {d['mc_version']}" if d.get("mc_version") else ""),
        f"- **Contenu** : {c['jars']} fichiers, {c['mods']} mods, {c['bundled']} intégrés (jar-in-jar), {human_size(c['size'])}",
        f"- **Santé** : {d['score']}/100 — {c['errors']} erreur(s), {c['warnings']} avertissement(s), {c['infos']} info(s)",
        "",
    ]
    if not d["issues"]:
        lines += ["## ✅ Aucun problème détecté", ""]
    else:
        cats: dict[str, list] = {}
        for i in d["issues"]:
            cats.setdefault(i["category"], []).append(i)
        for cat in ("duplicates", "dependencies", "versions", "compat", "files"):
            items = cats.get(cat)
            if not items:
                continue
            lines += [f"## {_CAT.get(cat, cat)} ({len(items)})", ""]
            for i in items:
                lines.append(f"### {_SEV[i['severity']]} — {i['title']}")
                lines.append("")
                lines.append(i["message"])
                if i.get("fix"):
                    lines += ["", f"**À faire :** {i['fix']}"]
                if i.get("files"):
                    lines += ["", "Fichiers : " + ", ".join(f"`{f}`" for f in i["files"])]
                lines.append("")

    p = d["plan"]
    lines += [
        "## Dossier serveur (proposition)",
        "",
        f"- {c['server_keep']} mods conservés, {c['server_remove']} retirés, {c['server_unsure']} à vérifier",
        "",
    ]
    if p["remove"]:
        lines += ["| Retiré | Raison |", "|---|---|"]
        lines += [f"| `{r['file']}` | {r['reason']} |" for r in p["remove"]]
        lines.append("")
    if p["unsure"]:
        lines += ["À vérifier (gardés par défaut) :", ""]
        lines += [f"- `{u['file']}` — {u['reason']}" for u in p["unsure"]]
        lines.append("")

    lines += ["## Liste des mods", "", "| Mod | Version | Loader | Côté | Fichier |", "|---|---|---|---|---|"]
    for m in d["mods"]:
        lines.append(f"| {m['name']} | {m['version'] or '?'} | {m['loader'] or '—'} | "
                     f"{_SIDE.get(m['side'], m['side'])} | `{m['file']}` |")
    lines.append("")
    return "\n".join(lines)
