"""Client Modrinth (API v2) : identification des .jar, côté client/serveur, incompatibilités, mises à jour.

Respect de la vie privée : seules les **empreintes SHA-1** des fichiers .jar (et des identifiants de projets
Modrinth) sont envoyées à api.modrinth.com. Ni les noms de fichiers, ni les chemins, ni le contenu des mods.
Cette fonction est facultative et désactivée par défaut.

Modrinth demande aux applications de s'identifier avec un User-Agent : renseigne ton lien GitHub dans la
variable d'environnement MODMAESTRO_CONTACT (ou dans CONTACT ci-dessous).

L'adresse de l'API peut être remplacée par MODMAESTRO_MODRINTH_URL (miroir, proxy, tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import __version__

API = "https://api.modrinth.com/v2"
WEB = "https://modrinth.com"
CONTACT = ""  # ex. "https://github.com/ton-pseudo/Mod-Maestro"
BATCH = 100


class ModrinthError(Exception):
    """Erreur lisible par l'utilisateur (réseau, limite de débit, réponse inattendue…)."""


def user_agent() -> str:
    contact = os.environ.get("MODMAESTRO_CONTACT") or CONTACT
    return f"ModMaestro/{__version__} (outil local d'audit de modpacks" + (f"; {contact})" if contact else ")")


def project_url(slug_or_id: str) -> str:
    return f"{WEB}/project/{urllib.parse.quote(str(slug_or_id))}"


# --------------------------------------------------------------------------
# Réduction des réponses : on ne garde que ce dont on a besoin (cache plus léger)
# --------------------------------------------------------------------------

def slim_version(v: dict) -> dict:
    return {
        "id": v.get("id"),
        "project_id": v.get("project_id"),
        "version_number": v.get("version_number"),
        "version_type": v.get("version_type") or "release",
        "date_published": v.get("date_published") or "",
        "game_versions": list(v.get("game_versions") or []),
        "loaders": list(v.get("loaders") or []),
        "dependencies": [
            {"project_id": d.get("project_id"), "version_id": d.get("version_id"),
             "dependency_type": d.get("dependency_type")}
            for d in (v.get("dependencies") or []) if isinstance(d, dict)
        ],
    }


def slim_project(p: dict) -> dict:
    return {
        "id": p.get("id"), "slug": p.get("slug"), "title": p.get("title") or p.get("slug"),
        "client_side": p.get("client_side") or "unknown", "server_side": p.get("server_side") or "unknown",
        "project_type": p.get("project_type") or "mod",
    }


# --------------------------------------------------------------------------
# Client HTTP
# --------------------------------------------------------------------------

class Modrinth:
    def __init__(self, base_url: str | None = None, timeout: float = 20, max_retries: int = 2,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = (base_url or os.environ.get("MODMAESTRO_MODRINTH_URL") or API).rstrip("/")
        self.timeout, self.max_retries, self._sleep = timeout, max_retries, sleep
        self.requests = 0  # pratique pour les tests et les statistiques

    def _request(self, method: str, path: str, query: dict | None = None, body: dict | None = None):
        url = self.base_url + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"User-Agent": user_agent(), "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(self.max_retries + 1):
            self.requests += 1
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < self.max_retries:
                    wait = exc.headers.get("Retry-After") or exc.headers.get("X-Ratelimit-Reset") or "5"
                    try:
                        self._sleep(min(float(wait), 30))
                    except ValueError:
                        self._sleep(5)
                    continue
                if 500 <= exc.code < 600 and attempt < self.max_retries:
                    self._sleep(1 + attempt)
                    continue
                if exc.code == 429:
                    raise ModrinthError("Modrinth limite le nombre de requêtes : réessaie dans une minute.") from exc
                raise ModrinthError(f"Modrinth a répondu par une erreur {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    self._sleep(1 + attempt)
                    continue
                raise ModrinthError(
                    "Modrinth est injoignable (pas de connexion, pare-feu ou proxy ?). "
                    "L'analyse continue avec les données locales.") from exc
            except ValueError as exc:  # JSON invalide
                raise ModrinthError("Réponse inattendue de Modrinth.") from exc
        raise ModrinthError("Modrinth est injoignable.")  # pragma: no cover

    def versions_by_hashes(self, hashes: list[str]) -> dict:
        """sha1 → version (réduite). Les empreintes inconnues sont absentes de la réponse."""
        res = self._request("POST", "/version_files", body={"hashes": hashes, "algorithm": "sha1"})
        return {h: slim_version(v) for h, v in res.items()} if isinstance(res, dict) else {}

    def projects(self, ids: list[str]) -> list[dict]:
        res = self._request("GET", "/projects", query={"ids": json.dumps(ids)})
        return [slim_project(p) for p in res] if isinstance(res, list) else []

    def latest_by_hashes(self, hashes: list[str], loaders: list[str], game_versions: list[str]) -> dict:
        body: dict = {"hashes": hashes, "algorithm": "sha1"}
        if loaders:
            body["loaders"] = loaders
        if game_versions:
            body["game_versions"] = game_versions
        res = self._request("POST", "/version_files/update", body=body)
        return {h: slim_version(v) for h, v in res.items()} if isinstance(res, dict) else {}


# --------------------------------------------------------------------------
# Identification
# --------------------------------------------------------------------------

@dataclass
class OnlineData:
    files: dict = field(default_factory=dict)     # nom de fichier → info
    projects: dict = field(default_factory=dict)  # id de projet → fiche réduite
    stats: dict = field(default_factory=dict)
    error: str | None = None


def sha1_file(path: str) -> str:
    h = hashlib.sha1()  # noqa: S324 — empreinte demandée par l'API Modrinth, pas un usage de sécurité
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _chunks(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def identify(jars, client: Modrinth, cache, progress: Callable[[str, int, int], None] | None = None) -> OnlineData:
    """Reconnaît chaque .jar sur Modrinth (cache d'abord, réseau ensuite)."""
    prog = progress or (lambda stage, done, total: None)
    out = OnlineData()
    candidates = [j for j in jars if j.status in ("ok", "no-metadata")]
    file_hash: dict[str, str] = {}
    for i, j in enumerate(candidates, 1):
        try:
            file_hash[j.file] = sha1_file(j.path)
        except OSError:
            continue
        prog("hash", i, len(candidates))

    unique = sorted(set(file_hash.values()))
    cached = cache.get_files(unique) if cache else {}
    todo = [h for h in unique if h not in cached]
    versions: dict[str, dict | None] = dict(cached)
    out.stats = {"total": len(file_hash), "identified": 0, "unknown": 0,
                 "from_cache": len(unique) - len(todo), "queried": len(todo)}

    try:
        done = 0
        for chunk in _chunks(todo, BATCH):
            res = client.versions_by_hashes(chunk)
            found = {h: res.get(h) for h in chunk}
            versions.update(found)
            if cache:
                cache.put_files(found)
            done += len(chunk)
            prog("query", done, len(todo))

        wanted: set[str] = set()
        for h in set(file_hash.values()):
            v = versions.get(h)
            if v:
                wanted.add(v["project_id"])
                wanted.update(d["project_id"] for d in v["dependencies"]
                              if d.get("project_id") and d.get("dependency_type") in ("required", "incompatible"))
        projects = cache.get_projects(wanted) if cache else {}
        missing = sorted(wanted - set(projects))
        for chunk in _chunks(missing, BATCH):
            got = client.projects(chunk)
            if cache:
                cache.put_projects(got)
            projects.update({p["id"]: p for p in got})
            prog("projects", len(projects), len(wanted))
        out.projects = projects
    except ModrinthError as exc:
        out.error = str(exc)
        out.projects = cache.get_projects(
            {v["project_id"] for v in versions.values() if v}) if cache else {}

    for fname, sha in file_hash.items():
        v = versions.get(sha)
        if not v:
            if sha in versions:
                out.stats["unknown"] += 1
            continue
        p = out.projects.get(v["project_id"]) or {}
        out.files[fname] = {
            "sha1": sha, "found": True, "project_id": v["project_id"], "slug": p.get("slug"),
            "title": p.get("title"), "client_side": p.get("client_side", "unknown"),
            "server_side": p.get("server_side", "unknown"), "version_id": v["id"],
            "version_number": v["version_number"], "version_type": v["version_type"],
            "date_published": v["date_published"], "game_versions": v["game_versions"],
            "loaders": v["loaders"], "dependencies": v["dependencies"],
            "url": project_url(p.get("slug") or v["project_id"]),
        }
        out.stats["identified"] += 1
    return out


def check_updates(online: OnlineData, loaders: list[str], client: Modrinth, cache,
                  progress: Callable[[str, int, int], None] | None = None) -> tuple[list[dict], str | None]:
    """Cherche pour chaque mod reconnu une version plus récente (même loader, mêmes versions de Minecraft).

    On filtre avec les versions de Minecraft *du fichier installé* plutôt qu'avec une version devinée :
    c'est la seule façon d'être exact. Les fichiers sont regroupés pour limiter le nombre de requêtes.
    """
    prog = progress or (lambda stage, done, total: None)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for info in online.files.values():
        groups[tuple(sorted(info["game_versions"]))].append(info["sha1"])
    results: dict[str, dict | None] = {}
    error = None
    total = sum(len(set(v)) for v in groups.values())
    done = 0
    try:
        for gv, hashes in groups.items():
            hashes = sorted(set(hashes))
            key = f"{','.join(sorted(loaders))}|{','.join(gv)}"
            cached = cache.get_latest(hashes, key) if cache else {}
            results.update(cached)
            todo = [h for h in hashes if h not in cached]
            for chunk in _chunks(todo, BATCH):
                res = client.latest_by_hashes(chunk, loaders, list(gv))
                found = {h: res.get(h) for h in chunk}
                results.update(found)
                if cache:
                    cache.put_latest(found, key)
            done += len(hashes)
            prog("updates", done, total)
    except ModrinthError as exc:
        error = str(exc)

    updates = []
    for fname, info in online.files.items():
        latest = results.get(info["sha1"])
        if not latest or latest["id"] == info["version_id"]:
            continue
        if latest["date_published"] <= info["date_published"]:
            continue
        if latest["version_type"] != "release" and info["version_type"] == "release":
            continue  # on ne propose pas une alpha / bêta à quelqu'un qui est en version stable
        updates.append({"file": fname, "name": info["title"] or fname, "current": info["version_number"],
                        "latest": latest["version_number"], "url": info["url"]})
    updates.sort(key=lambda u: u["name"].lower())
    return updates, error
