"""Chaîne complète d'analyse, partagée par l'interface web et le terminal.

    dossier → lecture des .jar → (Modrinth, facultatif) → base de connaissances → analyse → alertes en ligne
"""

from __future__ import annotations

from typing import Callable

from . import analyzer, enrich, knowledge, logscan, modrinth, parser
from .i18n import _
from .cache import get_cache

LOADERS_FOR = {"neoforge": ["neoforge"], "forge": ["forge"], "fabric": ["fabric"], "quilt": ["quilt", "fabric"]}

Progress = Callable[[str, int, int], None]


def run_analysis(path: str, online: bool = False, progress: Progress | None = None,
                 cache=None, client: modrinth.Modrinth | None = None) -> analyzer.Analysis:
    """`progress(étape, fait, total)` avec étape ∈ scan | hash | query | projects | updates."""
    prog = progress or (lambda stage, done, total: None)
    cache = cache if cache is not None else get_cache()
    mods_dir, notes = parser.resolve_source(path)
    jars, extras = parser.scan_folder(mods_dir, progress=lambda d, t: prog("scan", d, t))
    kb = knowledge.load_all(cache)

    data = None
    if online:
        client = client or modrinth.Modrinth()
        data = modrinth.identify(jars, client, cache, progress=prog)

    a = analyzer.analyze(jars, extras, source=path, mods_dir=mods_dir, notes=notes, knowledge=kb,
                         online=data.files if data else None)
    a.boot = logscan.boot_status(mods_dir, [j.mtime for j in jars])
    if a.boot and a.boot["status"] == "crashed" and a.boot["fresh"]:
        try:
            titles = [f["title"] for f in logscan.scan_text(logscan.read_log(a.boot["path"]))][:3]
        except (OSError, ValueError):
            titles = []
        a.add_issue("boot-crash", "error", "files", _("Le dernier lancement a échoué"),
                    _("{log} indique que le jeu n'a pas démarré.", log=a.boot["log"])
                    + (" " + _("Causes repérées : {titles}.", titles=" · ".join(titles)) if titles else ""),
                    fix=_("Ouvre « Journal de crash » pour le détail, ou « Trouver le mod fautif » pour isoler la cause."),
                    confidence="certain")
    if cache.degraded:
        a.notes.append(cache.degraded)
    for err in kb["_stats"]["errors"][:3]:
        a.notes.append(f"Base communautaire : {err}")

    if data:
        enrich.apply_online(a, data)
        updates, err = modrinth.check_updates(data, LOADERS_FOR.get(a.loader or "", []), client, cache, progress=prog)
        enrich.apply_updates(a, updates, err)
        if a.online.get("error"):
            a.notes.append(a.online["error"])
    return a
