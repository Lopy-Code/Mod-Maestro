"""Cache local SQLite de ModMaestro.

Il contient deux choses, toutes deux stockées uniquement sur ta machine :
  - les réponses de Modrinth (identification des .jar par empreinte SHA-1, fiches de projets,
    dernières versions) avec une durée de validité, pour ne pas redemander la même chose ;
  - ta base personnelle de conflits et de mods « client » apprise (table `learned`).

Emplacement par défaut :
  Windows  %APPDATA%\\ModMaestro
  macOS    ~/Library/Application Support/ModMaestro
  Linux    $XDG_DATA_HOME/modmaestro (ou ~/.local/share/modmaestro)
Il peut être changé avec la variable d'environnement MODMAESTRO_HOME.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time

FOUND_TTL = 7 * 86400      # un fichier reconnu reste valable 7 jours
MISS_TTL = 1 * 86400       # un fichier inconnu de Modrinth est redemandé après 1 jour
PROJECT_TTL = 7 * 86400
LATEST_TTL = 12 * 3600     # « dernière version » : 12 heures

SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    sha1 TEXT PRIMARY KEY, found INTEGER NOT NULL, data TEXT, checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY, data TEXT NOT NULL, checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS latest (
    sha1 TEXT NOT NULL, key TEXT NOT NULL, found INTEGER NOT NULL, data TEXT, checked_at REAL NOT NULL,
    PRIMARY KEY (sha1, key));
CREATE TABLE IF NOT EXISTS learned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- 'conflict' | 'side'
    a TEXT NOT NULL,
    b TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at REAL NOT NULL,
    UNIQUE (kind, a, b, side));
"""


def user_data_dir() -> str:
    env = os.environ.get("MODMAESTRO_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    home = os.path.expanduser("~")
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), "ModMaestro")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "ModMaestro")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "modmaestro")


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


class Cache:
    def __init__(self, path: str | None = None, clock=time.time):
        self.path = path or os.path.join(user_data_dir(), "cache.sqlite3")
        self.degraded: str | None = None  # raison, si on est retombé sur une base en mémoire
        self._clock = clock
        self._lock = threading.RLock()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.commit()

    # -- bas niveau ---------------------------------------------------------
    def _exec(self, sql: str, args=()):
        with self._lock:
            return self._db.execute(sql, args)

    def _many(self, sql: str, rows):
        with self._lock:
            self._db.executemany(sql, rows)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- fichiers (empreinte SHA-1 → version Modrinth) ------------------------------
    def get_files(self, hashes) -> dict:
        """sha1 → version (dict) ou None (inconnu de Modrinth). Les entrées périmées sont ignorées."""
        out, now = {}, self._clock()
        for chunk in _chunks(list(hashes), 400):
            q = ",".join("?" * len(chunk))
            for r in self._exec(f"SELECT sha1, found, data, checked_at FROM files WHERE sha1 IN ({q})", chunk):
                ttl = FOUND_TTL if r["found"] else MISS_TTL
                if now - r["checked_at"] <= ttl:
                    out[r["sha1"]] = json.loads(r["data"]) if r["found"] else None
        return out

    def put_files(self, items: dict) -> None:
        now = self._clock()
        self._many("INSERT OR REPLACE INTO files (sha1, found, data, checked_at) VALUES (?,?,?,?)",
                   [(h, 1 if v else 0, json.dumps(v) if v else None, now) for h, v in items.items()])

    # -- projets ----------------------------------------------------------------------------
    def get_projects(self, ids) -> dict:
        out, now = {}, self._clock()
        for chunk in _chunks(list(ids), 400):
            q = ",".join("?" * len(chunk))
            for r in self._exec(f"SELECT project_id, data, checked_at FROM projects WHERE project_id IN ({q})", chunk):
                if now - r["checked_at"] <= PROJECT_TTL:
                    out[r["project_id"]] = json.loads(r["data"])
        return out

    def put_projects(self, projects: list[dict]) -> None:
        now = self._clock()
        self._many("INSERT OR REPLACE INTO projects (project_id, data, checked_at) VALUES (?,?,?)",
                   [(p["id"], json.dumps(p), now) for p in projects])

    # -- dernières versions ----------------------------------------------------------------------
    def get_latest(self, hashes, key: str) -> dict:
        out, now = {}, self._clock()
        for chunk in _chunks(list(hashes), 400):
            q = ",".join("?" * len(chunk))
            for r in self._exec(
                    f"SELECT sha1, found, data, checked_at FROM latest WHERE key = ? AND sha1 IN ({q})", [key, *chunk]):
                if now - r["checked_at"] <= LATEST_TTL:
                    out[r["sha1"]] = json.loads(r["data"]) if r["found"] else None
        return out

    def put_latest(self, items: dict, key: str) -> None:
        now = self._clock()
        self._many("INSERT OR REPLACE INTO latest (sha1, key, found, data, checked_at) VALUES (?,?,?,?,?)",
                   [(h, key, 1 if v else 0, json.dumps(v) if v else None, now) for h, v in items.items()])

    # -- maintenance --------------------------------------------------------------------------------
    def stats(self) -> dict:
        def one(sql):
            return self._exec(sql).fetchone()[0]
        size = os.path.getsize(self.path) if self.path != ":memory:" and os.path.exists(self.path) else 0
        return {
            "path": self.path, "size": size, "degraded": self.degraded,
            "files": one("SELECT COUNT(*) FROM files WHERE found = 1"),
            "unknown_files": one("SELECT COUNT(*) FROM files WHERE found = 0"),
            "projects": one("SELECT COUNT(*) FROM projects"),
            "learned": one("SELECT COUNT(*) FROM learned"),
            "last_check": one("SELECT MAX(checked_at) FROM files"),
        }

    def clear_online(self) -> None:
        """Vide les données venues de Modrinth. Ta base personnelle (`learned`) est conservée."""
        with self._lock:
            for t in ("files", "projects", "latest"):
                self._db.execute(f"DELETE FROM {t}")
            self._db.commit()
            self._db.execute("VACUUM")

    # -- base personnelle -------------------------------------------------------------------------------
    def add_learned(self, kind: str, a: str, b: str = "", side: str = "", severity: str = "",
                    note: str = "", source: str = "manual") -> dict:
        self._exec(
            "INSERT INTO learned (kind, a, b, side, severity, note, source, created_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT (kind, a, b, side) DO UPDATE SET severity=excluded.severity, note=excluded.note, "
            "source=excluded.source",
            (kind, a, b, side, severity, note, source, self._clock()))
        with self._lock:
            self._db.commit()
        r = self._exec("SELECT * FROM learned WHERE kind=? AND a=? AND b=? AND side=?", (kind, a, b, side)).fetchone()
        return dict(r)

    def list_learned(self) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM learned ORDER BY created_at DESC, id DESC")]

    def remove_learned(self, learned_id: int) -> bool:
        cur = self._exec("DELETE FROM learned WHERE id = ?", (int(learned_id),))
        with self._lock:
            self._db.commit()
        return cur.rowcount > 0


_default: Cache | None = None
_default_lock = threading.Lock()


def get_cache() -> Cache:
    """Cache partagé du processus. Si le disque est inutilisable, on retombe sur une base en mémoire."""
    global _default
    with _default_lock:
        if _default is None:
            try:
                _default = Cache()
            except (sqlite3.Error, OSError) as exc:
                _default = Cache(":memory:")
                _default.degraded = f"Impossible d'utiliser le cache sur le disque ({exc}) : il ne durera que le temps de cette session."
        return _default


def reset_default() -> None:
    global _default
    with _default_lock:
        if _default is not None:
            try:
                _default.close()
            except sqlite3.Error:
                pass
        _default = None
