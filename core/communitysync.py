"""Mise à jour de la base communautaire depuis le dépôt GitHub — uniquement quand tu cliques sur le bouton.

On lit la liste des fichiers de `core/data/community/` (une requête à l'API GitHub), puis on télécharge chaque fichier
`.json`. Chaque entrée est **validée** avec les mêmes règles que la base fournie ; ce qui est invalide est ignoré.
Les fichiers sont rangés dans `<dossier ModMaestro>/community_sync/` (jamais dans ton dossier de mods, jamais dans
`core/data`). On ne télécharge que du JSON de données : aucun code n'est récupéré ni exécuté.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, knowledge
from .i18n import _

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
SUBDIR = "core/data/community"
FOLDERS = ("sides", "conflicts")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,150}\.json$")
MAX_FILE = 64 * 1024      # un fichier d'entrée fait quelques centaines d'octets
MAX_FILES = 3000
TIMEOUT = 15
DEADLINE = 90             # secondes, pour l'ensemble de la mise à jour
_GITHUB = re.compile(r"^https://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+?)(?:\.git)?/?$")


def sync_dir() -> str:
    return knowledge.synced_community_dir()


def _meta_path() -> str:
    return os.path.join(sync_dir(), "sync.json")


def status() -> dict:
    """État affiché dans l'interface : dépôt visé, dernière mise à jour."""
    from . import contribute
    repo = contribute.repo_url()
    last = None
    try:
        with open(_meta_path(), encoding="utf-8") as fh:
            last = json.load(fh)
    except (OSError, ValueError):
        pass
    return {"repo": repo or None, "configured": bool(_parse_repo(repo)), "last": last}


def _parse_repo(repo: str):
    m = _GITHUB.match(repo or "")
    return (m.group(1), m.group(2)) if m else None


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"ModMaestro/{__version__}",
                                               "Accept": "application/vnd.github+json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(limit + 1)
    except urllib.error.HTTPError as exc:
        exc.close()          # libère la connexion avant de remonter l'erreur
        raise
    if len(data) > limit:
        raise ValueError(_("Fichier trop volumineux."))
    return data


def update(api: str | None = None, raw: str | None = None) -> dict:
    """Télécharge, valide et installe la base communautaire. `api`/`raw` : adresses de test."""
    from . import contribute
    parsed = _parse_repo(contribute.repo_url())
    if not parsed:
        raise ValueError(_("Le dépôt du projet n'est pas configuré dans cette version : impossible de chercher une mise à jour."))
    owner, name = parsed
    branch = os.environ.get("MODMAESTRO_BRANCH") or "main"
    api = (api or os.environ.get("MODMAESTRO_GITHUB_API") or API).rstrip("/")
    raw = (raw or os.environ.get("MODMAESTRO_RAW_URL") or RAW).rstrip("/")
    q = urllib.parse.quote
    try:
        tree = json.loads(_get(f"{api}/repos/{q(owner)}/{q(name)}/git/trees/{q(branch)}?recursive=1", 5_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise ValueError(_("GitHub limite les requêtes pour le moment : réessaie dans une heure.")) from exc
        raise ValueError(_("Dépôt ou branche introuvable sur GitHub (erreur {code}).", code=exc.code)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ValueError(_("Impossible de joindre GitHub : vérifie ta connexion.")) from exc

    wanted = []
    for item in tree.get("tree", []):
        parts = str(item.get("path", "")).split("/")
        if (item.get("type") == "blob" and "/".join(parts[:-2]) == SUBDIR and parts[-2] in FOLDERS
                and NAME_RE.match(parts[-1])):
            wanted.append((parts[-2], parts[-1]))
    if len(wanted) > MAX_FILES:
        raise ValueError(_("Le dépôt contient trop d'entrées : mise à jour annulée."))

    root = sync_dir()
    os.makedirs(os.path.dirname(root), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="community_", dir=os.path.dirname(root))
    skipped: list[str] = []
    t0 = time.monotonic()
    try:
        for folder, fname in wanted:
            if time.monotonic() - t0 > DEADLINE:
                raise ValueError(_("La mise à jour prend trop de temps : réessaie plus tard."))
            url = f"{raw}/{q(owner)}/{q(name)}/{q(branch)}/{SUBDIR}/{folder}/{q(fname)}"
            try:
                data = _get(url, MAX_FILE)
                entry = json.loads(data.decode("utf-8"))
            except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError):
                skipped.append(fname)
                continue
            check = knowledge.validate_side if folder == "sides" else knowledge.validate_conflict
            if any(check(e) for e in (entry if isinstance(entry, list) else [entry])):
                skipped.append(fname)
                continue
            os.makedirs(os.path.join(tmp, folder), exist_ok=True)
            with open(os.path.join(tmp, folder, fname), "w", encoding="utf-8") as fh:
                json.dump(entry, fh, ensure_ascii=False, indent=2)
        before = knowledge.load_dir(root) if os.path.isdir(root) else {"sides": [], "conflicts": []}
        after = knowledge.load_dir(tmp)
        info = {"date": time.strftime("%Y-%m-%d %H:%M"), "sides": len(after["sides"]),
                "conflicts": len(after["conflicts"]), "repo": f"{owner}/{name}", "branch": branch}
        with open(os.path.join(tmp, "sync.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        shutil.rmtree(root, ignore_errors=True)   # remplacement d'un bloc : jamais de base à moitié écrite
        os.replace(tmp, root)
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
    return {**info, "skipped": skipped,
            "added_sides": max(0, len(after["sides"]) - len(before["sides"])),
            "added_conflicts": max(0, len(after["conflicts"]) - len(before["conflicts"]))}


def reset() -> bool:
    """Retire les mises à jour téléchargées : il reste la base fournie avec ModMaestro et ta base personnelle."""
    existed = os.path.isdir(sync_dir())
    shutil.rmtree(sync_dir(), ignore_errors=True)
    return existed
