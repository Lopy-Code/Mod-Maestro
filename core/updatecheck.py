"""Vérifie s'il existe une Release plus récente que cette version — uniquement quand tu cliques sur le bouton.

Une seule requête vers l'API GitHub (dernière Release publiée) ; rien n'est téléchargé ni installé : on te donne le
lien de la page de téléchargement.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse

from . import __version__, versions
from .communitysync import API, _get, _parse_repo
from .i18n import _

_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-+]{0,60}$")


_OS_WORD = {"win32": "windows", "darwin": "macos"}


def _platform() -> str:
    return sys.platform


def _asset(rel: dict, repo: str) -> dict | None:
    """Le fichier de la Release qui correspond à ton système (nom contenant Windows, Linux ou macOS), s'il existe."""
    word = _OS_WORD.get(_platform(), "linux")
    prefix = f"{repo}/releases/download/"
    for a in rel.get("assets") or []:
        if not isinstance(a, dict):
            continue
        name, url = str(a.get("name") or ""), str(a.get("browser_download_url") or "")
        if word in name.lower() and url.startswith(prefix) and len(name) < 120 and "\n" not in name:
            size = a.get("size")
            return {"name": name, "url": url, "size": size if isinstance(size, int) and size >= 0 else 0}
    return None


def check(api: str | None = None) -> dict:
    from . import contribute
    repo = contribute.repo_url()
    parsed = _parse_repo(repo)
    if not parsed:
        raise ValueError(_("Le dépôt du projet n'est pas configuré dans cette version : impossible de chercher une mise à jour."))
    owner, name = parsed
    api = (api or os.environ.get("MODMAESTRO_GITHUB_API") or API).rstrip("/")
    q = urllib.parse.quote
    try:
        rel = json.loads(_get(f"{api}/repos/{q(owner)}/{q(name)}/releases/latest", 1_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:      # aucune Release publiée pour l'instant
            return {"current": __version__, "latest": None, "newer": False, "url": None, "notes": "", "asset": None}
        if exc.code in (403, 429):
            raise ValueError(_("GitHub limite les requêtes pour le moment : réessaie dans une heure.")) from exc
        raise ValueError(_("Dépôt ou branche introuvable sur GitHub (erreur {code}).", code=exc.code)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ValueError(_("Impossible de joindre GitHub : vérifie ta connexion.")) from exc
    tag = str(rel.get("tag_name") or "")
    if not _TAG.match(tag) or not versions.has_digits(tag):
        raise ValueError(_("Réponse de GitHub inattendue."))
    latest = tag.lstrip("vV")
    return {"current": __version__, "latest": latest, "newer": versions.compare(latest, __version__) > 0,
            "url": f"{repo}/releases/tag/{q(tag)}", "notes": str(rel.get("body") or "")[:1500],
            "asset": _asset(rel, repo)}
