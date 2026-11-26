"""Surveillance d'un serveur en cours : lit `logs/latest.log` au fil de l'eau et prévient quand un mod pose problème.

Lecture seule : le fichier est ouvert à chaque relève (jamais verrouillé), on ne lit que les lignes nouvelles, par
paquets limités. Rien n'est envoyé nulle part. Un mod est mis en cause par :
* le nom de l'enregistreur (« logger ») de la ligne d'erreur, s'il correspond à un mod installé ;
* la pile d'erreur qui suit (voir core.stacktrace : jar cité, module, paquet de la classe, mixin).
"""

from __future__ import annotations

import os
import re
import time
from collections import OrderedDict

from . import knowledge, stacktrace
from .i18n import _

MAX_READ = 2 * 1024 * 1024       # par relève
BACKLOG = 300 * 1024             # au démarrage : on relit la fin du journal pour montrer l'état actuel
MAX_ALERTS = 60
MAX_PENDING = 250                # lignes de pile gardées pour une erreur
ESCALATE = (5, 25, 100)          # nombre d'erreurs d'un même mod qui déclenche (puis aggrave) l'alerte

_HEAD = re.compile(r"^\[(\d\d:\d\d:\d\d)(?:\.\d+)?\] \[([^\]/]*)/(INFO|WARN|ERROR|FATAL|DEBUG|TRACE)\](?: \[([^\]]*)\])?: ?(.*)$")
_LAG = re.compile(r"Can't keep up! .*?Running (\d+)\s*ms or (\d+) ticks? behind", re.I)
_DONE = re.compile(r'Done \(\d+(?:[.,]\d+)?s\)! For help, type "help"')
_NOISE = re.compile(r"\d+|0x[0-9a-f]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f-]{12,}", re.I)


def resolve_log(path: str = "", mods_dir: str = "") -> str:
    """Chemin du journal à suivre : un fichier .log, un dossier de serveur/instance, ou celui du pack analysé."""
    from . import configscan
    p = path.strip()
    if p:
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isfile(p):
            if not p.lower().endswith((".log", ".txt")):
                raise ValueError(_("Choisis un fichier .log (par exemple logs/latest.log)."))
            return p
        if os.path.isdir(p):
            if os.path.basename(p).lower() == "logs":
                return os.path.join(p, "latest.log")
            if os.path.basename(p).lower() == "mods":
                p = os.path.dirname(p)
            return os.path.join(p, "logs", "latest.log")
        raise ValueError(_("Dossier ou fichier introuvable."))
    if mods_dir:
        return os.path.join(configscan.instance_root(mods_dir), "logs", "latest.log")
    raise ValueError(_("Indique le dossier du serveur ou son fichier latest.log."))


class Monitor:
    def __init__(self, log: str, jars: dict | None = None, index: dict | None = None):
        self.log, self.jars, self.index = log, jars or {}, index
        self.modids = {knowledge.normalize_id(m) for j in self.jars.values() for m in j.get("modids", [])}
        self.names = {}
        for j in self.jars.values():
            for m in j.get("modids", []):
                self.names[knowledge.normalize_id(m)] = j.get("name") or m
        self.offset: int | None = None
        self.ino: int | None = None
        self.alerts: "OrderedDict[str, dict]" = OrderedDict()
        self.errors_by_mod: dict[str, int] = {}
        self.stats = {"lines": 0, "warns": 0, "errors": 0, "lag": 0, "restarts": 0, "started": False}
        self.status = "waiting"
        self.last_activity = 0.0
        self._pending: list[str] = []
        self._pending_logger = ""
        self._pending_time = ""
        self._pending_polls = 0
        self._tail = b""

    # -- alertes --------------------------------------------------------------------------------------------------
    def _alert(self, key: str, severity: str, code: str, title: str, message: str, mods=(), when: str = "") -> None:
        a = self.alerts.get(key)
        when = when or time.strftime("%H:%M:%S")
        if a:
            a["count"] += 1
            a["last"] = when
            a["message"] = message
            if ["info", "warning", "error"].index(severity) > ["info", "warning", "error"].index(a["severity"]):
                a["severity"] = severity
            self.alerts.move_to_end(key)
            return
        self.alerts[key] = {"id": key, "severity": severity, "code": code, "title": title, "message": message,
                            "mods": [m for m in mods], "count": 1, "first": when, "last": when}
        while len(self.alerts) > MAX_ALERTS:
            self.alerts.popitem(last=False)

    def _logger_mod(self, logger: str) -> str | None:
        if not logger or not self.modids:
            return None
        low = logger.lower().strip()
        for mid in self.modids:
            nm = self.names.get(mid, "").lower()
            segs = {s.replace("-", "_") for s in re.split(r"[./ ]", low) if s}
            if low == mid or (nm and low == nm) or (len(mid) >= 4 and mid.replace("-", "_") in segs):
                return mid
        return None

    def _blame(self, mid: str, root: str, when: str, why: str) -> None:
        n = self.errors_by_mod[mid] = self.errors_by_mod.get(mid, 0) + 1
        name = self.names.get(mid, mid)
        level = sum(n >= t for t in ESCALATE)
        if level:
            sev = "error" if level >= 2 else "warning"
            self._alert(f"mod:{mid}", sev, "mod-errors", _("Le mod « {name} » produit des erreurs", name=name),
                        _("{n} erreurs liées à ce mod depuis le début de la surveillance. Dernière : {root} ({why})", n=n, root=root[:160], why=why),
                        [mid], when)

    # -- analyse d'une erreur complète (ligne d'en-tête + pile) -----------------------------------------------------
    def _flush(self) -> None:
        if not self._pending:
            return
        head, rest = self._pending[0], self._pending[1:]
        logger, when = self._pending_logger, self._pending_time
        self._pending, self._pending_polls = [], 0
        mod = self._logger_mod(logger)
        why = _("d'après le nom de l'enregistreur « {l} »", l=logger) if mod else ""
        root = head
        if rest:
            res = stacktrace.attribute(head + "\n" + "\n".join(rest), self.index, self.jars, self.modids)
            root = res["root"] or head
            strong = [s for s in res["suspects"] if s["confidence"] != "heuristic"]
            if strong and not mod:
                mod, why = strong[0]["modid"], "; ".join(strong[0]["evidence"][:1])
        if mod:
            self._blame(mod, root, when, why)
            return
        low = (head + " " + root + " " + " ".join(rest[:5])).lower()
        if "outofmemoryerror" in low:
            self._alert("memory", "error", "memory", _("Mémoire insuffisante"), _("Le serveur manque de RAM (OutOfMemoryError)."), (), when)
        else:
            key = "err:" + _NOISE.sub("#", head)[:90]
            self._alert(key, "warning", "error", _("Erreur dans le journal du serveur"), root[:220], (), when)

    def _line(self, line: str) -> None:
        self.stats["lines"] += 1
        m = _HEAD.match(line)
        if not m:                                    # suite d'un message : pile d'erreur, etc.
            if self._pending and len(self._pending) < MAX_PENDING:
                self._pending.append(line)
            return
        self._flush()
        when, _thread, level, logger, msg = m.groups()
        logger = logger or ""
        lag = _LAG.search(msg)
        if lag:
            self.stats["lag"] += 1
            self._alert("lag", "warning", "lag", _("Le serveur n'arrive pas à suivre"),
                        _("Dernier retard : {ms} ms ({ticks} ticks). Cherche un mod gourmand avec spark, ou baisse simulation-distance.",
                          ms=lag.group(1), ticks=lag.group(2)), (), when)
            return
        if _DONE.search(msg):
            self.stats["started"] = True
            return
        if level in ("ERROR", "FATAL"):
            self.stats["errors"] += 1
            self._pending, self._pending_logger, self._pending_time = [msg], logger, when
        elif level == "WARN":
            self.stats["warns"] += 1
            if re.search(r"A single server tick took|Server thread dump|ServerHangWatchdog", msg):
                self._alert("hang", "error", "hang", _("Un tick du serveur a été très long"), msg[:220], (), when)

    # -- relève -------------------------------------------------------------------------------------------------------
    def poll(self) -> dict:
        try:
            st = os.stat(self.log)
        except OSError:
            self.status = "waiting"
            return self.snapshot()
        ino = getattr(st, "st_ino", 0)
        if self.offset is None:                         # première relève : on montre la fin du journal
            self.offset = max(0, st.st_size - BACKLOG)
            self.ino = ino
            if self.offset:
                self._tail = b"skip"                    # on repart au milieu d'une ligne : la première est ignorée
        elif st.st_size < self.offset or ino != self.ino:   # nouveau démarrage du serveur : le journal a été recréé
            self.offset, self.ino, self._tail = 0, ino, b""
            self._flush()
            self.stats["restarts"] += 1
            self.stats["started"] = False
            self._alert(f"restart:{self.stats['restarts']}", "info", "restart", _("Le serveur a redémarré"), _("Le journal a été recréé."))
        if st.st_size > self.offset:
            with open(self.log, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read(MAX_READ)
            cut = data.rfind(b"\n")
            if cut >= 0:
                chunk, self.offset = data[:cut + 1], self.offset + cut + 1
                lines = chunk.decode("utf-8", errors="replace").splitlines()
                if self._tail == b"skip" and lines:
                    lines = lines[1:]
                self._tail = b""
                for ln in lines:
                    self._line(ln.rstrip("\r"))
                self.last_activity = time.time()
                self._pending_polls = 0
        if self._pending:
            self._pending_polls += 1
            if self._pending_polls >= 2:                # la pile est finie : on l'analyse
                self._flush()
        self.status = "active" if time.time() - max(self.last_activity, st.st_mtime) < 120 else "quiet"
        return self.snapshot()

    def snapshot(self) -> dict:
        return {"status": self.status, "log": os.path.basename(self.log), "stats": dict(self.stats),
                "alerts": list(reversed(list(self.alerts.values()))), "mods": {m: self.names.get(m, m) for m in self.errors_by_mod}}
