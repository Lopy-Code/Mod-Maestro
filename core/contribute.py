"""« Proposer à la communauté » : prépare une contribution à la base de connaissances du dépôt GitHub.

Rien n'est envoyé automatiquement. On fabrique (1) le texte d'une *issue* GitHub pré-remplie et (2) les fichiers au
format de `core/data/community/`, prêts à être ajoutés dans une pull request.
"""

from __future__ import annotations

import json
import os
import tempfile
from urllib.parse import quote

from . import __version__, learn
from .i18n import _

MAX_URL = 7000  # au-delà, GitHub (ou le navigateur) tronque l'adresse : on propose de copier le texte


def repo_url() -> str:
    """Adresse du dépôt (variable MODMAESTRO_REPO ou constante REPO_URL de core/__init__.py)."""
    from . import REPO_URL
    return (os.environ.get("MODMAESTRO_REPO") or REPO_URL or "").rstrip("/")


def build(cache, ids=None, context: dict | None = None) -> dict:
    """`ids` : entrées à proposer (par défaut toutes celles de ta base, hors « ignorées »)."""
    rows = [r for r in learn.list_learned(cache) if r["kind"] in ("conflict", "side") and (not ids or r["id"] in set(ids))]
    if not rows:
        raise ValueError(_("Rien à proposer : ta base personnelle est vide. Enregistre d'abord un conflit ou un mod client."))
    with tempfile.TemporaryDirectory() as tmp:
        paths = learn.export_files(cache, tmp, [r["id"] for r in rows])
        files = {}
        for p in paths:
            with open(p, encoding="utf-8") as fh:
                files[os.path.relpath(p, tmp).replace(os.sep, "/")] = fh.read()
    ctx = context or {}
    lines = [_("## Proposition d'entrées pour la base communautaire"), "",
             f"- ModMaestro {__version__}"]
    if ctx.get("loader") or ctx.get("mc_version"):
        lines.append(f"- {_('Pack')} : {ctx.get('loader', '?')} · Minecraft {ctx.get('mc_version', '?')}")
    lines += ["", _("### Ce que j'ai observé"), ""]
    for r in rows:
        what = f"`{r['a']}` ↔ `{r['b']}`" if r["kind"] == "conflict" else f"`{r['a']}` ({r['side']})"
        lines.append(f"- {what}" + (f" — {r['note']}" if r["note"] else ""))
    lines += ["", _("### Fichiers (format `core/data/community/`)"), ""]
    for name, text in files.items():
        lines += [f"`{name}`", "```json", text.strip(), "```"]
    lines += ["", _("### Source / preuve"), "", _("(colle ici un extrait de log, un lien Modrinth ou une issue)")]
    body = "\n".join(lines)
    title = _("Base communautaire : {n} entrée(s) proposée(s)", n=len(rows))
    repo = repo_url()
    url = f"{repo}/issues/new?title={quote(title)}&body={quote(body)}" if repo else None
    too_long = bool(url and len(url) > MAX_URL)
    if too_long:
        url = f"{repo}/issues/new?title={quote(title)}"
    return {"title": title, "body": body, "files": files, "url": url, "repo": repo or None,
            "body_in_url": bool(url) and not too_long, "count": len(rows)}


def dumps(bundle: dict) -> str:
    return json.dumps(bundle, ensure_ascii=False, indent=2)


# -- « Ce diagnostic était faux » -----------------------------------------------------------------------------------

# Alertes dont l'identifiant se termine par un nom de fichier : il n'est jamais repris dans le rapport.
_FILE_IDS = ("file", "loader", "nometa")


def build_false_report(a, issue_id: str, note: str = "") -> dict:
    """Rapport **anonyme** pour une alerte jugée fausse : ni nom de fichier, ni chemin, ni dossier.

    Il ne contient que : le type d'alerte, sa gravité, les identifiants (modid) des mods concernés, le loader, la
    version de Minecraft, et si le jeu a démarré d'après `latest.log`. Rien n'est envoyé : l'utilisateur le publie.
    """
    issue = next((i for i in a.issues if i["id"] == issue_id), None)
    if issue is None:
        raise ValueError(_("Cette alerte n'existe plus : relance l'analyse."))
    kind = issue_id.split(":", 1)[0]
    rule = kind if kind in _FILE_IDS or any(c in issue_id for c in "/\\") or ".jar" in issue_id.lower() else issue_id
    boot = (a.boot or {}).get("status") if a.boot and a.boot.get("fresh") else "unknown"
    mods = sorted({m for m in issue.get("modids", []) if m})
    note = (note or "").strip()[:1000]
    info = {"rule": rule, "severity": issue["severity"], "confidence": issue.get("confidence", "certain"),
            "mods": mods, "loader": a.loader, "minecraft": a.mc_version or "?", "game_booted": boot,
            "source": (issue.get("data") or {}).get("source") or "local", "modmaestro": __version__}
    lines = [_("## Faux diagnostic signalé"), "", f"- ModMaestro {__version__}",
             f"- {_('Alerte')} : `{rule}` ({issue['severity']}, {info['confidence']})",
             f"- {_('Mods concernés')} : {', '.join(f'`{m}`' for m in mods) or '—'}",
             f"- {_('Pack')} : {a.loader} · Minecraft {info['minecraft']}",
             f"- {_('Le jeu a démarré')} : {_('oui') if boot == 'ok' else _('non') if boot == 'crashed' else _('inconnu')}",
             f"- {_('Source de l’alerte')} : {info['source']}", "",
             _("### Pourquoi c'est faux"), "", note or _("(explique en une phrase ce qui se passe réellement)"), "",
             _("### Données (anonymes)"), "", "```json", json.dumps(info, ensure_ascii=False, indent=2), "```"]
    body = "\n".join(lines)
    title = _("Faux diagnostic : {rule}", rule=rule)[:120]
    repo = repo_url()
    url = f"{repo}/issues/new?title={quote(title)}&body={quote(body)}" if repo else None
    too_long = bool(url and len(url) > MAX_URL)
    if too_long:
        url = f"{repo}/issues/new?title={quote(title)}"
    return {"title": title, "body": body, "url": url, "repo": repo or None, "body_in_url": bool(url) and not too_long,
            "data": info}
