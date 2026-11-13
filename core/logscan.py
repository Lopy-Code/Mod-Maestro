"""Lecture d'un journal de jeu / de serveur (latest.log, crash-report) pour en tirer les causes probables."""

from __future__ import annotations

import glob
import gzip
import os
import re
from collections import defaultdict

from .i18n import _

MAX_BYTES = 6 * 1024 * 1024  # on lit la fin du fichier, c'est là que se trouve le crash

_JAVA_BY_CLASS_VERSION = {52: 8, 53: 9, 54: 10, 55: 11, 60: 16, 61: 17, 62: 18, 63: 19, 64: 20, 65: 21, 66: 22, 67: 23, 68: 24}


def read_log(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.isfile(path):
        raise ValueError(_("Fichier introuvable : {path}", path=path))
    opener = gzip.open if path.lower().endswith(".gz") else open
    with opener(path, "rb") as fh:
        data = fh.read() if path.lower().endswith(".gz") else _tail(fh)
    return data[-MAX_BYTES:].decode("utf-8", "replace")


def _tail(fh) -> bytes:
    fh.seek(0, os.SEEK_END)
    size = fh.tell()
    fh.seek(max(0, size - MAX_BYTES))
    return fh.read()


def find_logs(mods_dir: str) -> list[dict]:
    """Journaux probables à côté du dossier mods (instance Minecraft ou serveur)."""
    root = os.path.dirname(os.path.abspath(mods_dir))
    found = []
    for pattern in ("logs/latest.log", "logs/debug.log", "crash-reports/crash-*.txt"):
        for p in glob.glob(os.path.join(root, pattern)):
            try:
                found.append({"path": p, "name": os.path.relpath(p, root), "mtime": os.path.getmtime(p),
                              "size": os.path.getsize(p)})
            except OSError:
                pass
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found[:8]


def _finding(severity, code, title, message, fix="", mods=None):
    return {"severity": severity, "code": code, "title": title, "message": message, "fix": fix, "mods": mods or []}


def scan_text(text: str) -> list[dict]:
    out: list[dict] = []

    # --- NeoForge / Forge : dépendances manquantes ou mal versionnées --------------------
    dep_re = re.compile(
        r"Mod ID: '([^']+)', Requested by: '([^']+)', Expected range: '([^']*)', Actual version: '([^']*)'")
    missing: dict[str, set] = defaultdict(set)
    wrong: dict[str, dict] = {}
    for modid, by, rng, actual in dep_re.findall(text):
        if "MISSING" in actual.upper():
            missing[modid].add(by)
        else:
            wrong[f"{modid}|{by}"] = {"modid": modid, "by": by, "range": rng, "actual": actual}
    for modid, by in sorted(missing.items()):
        out.append(_finding("error", "missing-dep", _("Dépendance manquante : {name}", name=modid),
                            _("Requise par : {by}.", by=", ".join(sorted(by))),
                            _("Ajoute le mod « {name} » dans le dossier mods.", name=modid), [modid, *sorted(by)]))
    for w in wrong.values():
        out.append(_finding("error", "wrong-version", _("Mauvaise version de {name}", name=w["modid"]),
                            _("{by} attend {range} mais la version installée est {actual}.",
                              by=w["by"], range=w["range"], actual=w["actual"]),
                            _("Mets à jour (ou rétrograde) {name}.", name=w["modid"]), [w["modid"], w["by"]]))

    # --- Fabric ------------------------------------------------------------------------
    fab_re = re.compile(
        r"Mod '([^']+)' \(([^)]+)\)[^\n]*?requires ([^\n]*?) of mod '([^']+)' \(([^)]+)\), which is missing")
    seen = set()
    for name, mid, ver, dep_name, dep_id in fab_re.findall(text):
        if (mid, dep_id) in seen:
            continue
        seen.add((mid, dep_id))
        out.append(_finding("error", "missing-dep", _("Dépendance manquante : {name}", name=dep_name),
                            _("{name} requiert {ver} de {dep} ({dep_id}).", name=name, ver=ver.strip(), dep=dep_name, dep_id=dep_id),
                            _("Ajoute « {name} » dans le dossier mods.", name=dep_name), [dep_id, mid]))

    # --- Doublons -------------------------------------------------------------------------
    dup_re = re.compile(r"Mod ID: '([^']+)' from mod files:\s*([^\n]+)")
    for modid, files in dup_re.findall(text):
        out.append(_finding("error", "duplicate", _("Doublon : {name}", name=modid),
                            _("Présent dans plusieurs fichiers : {files}.", files=files.strip()),
                            _("Ne garde que la version la plus récente."), [modid]))

    # --- Mod client chargé sur un serveur ------------------------------------------------------
    dist = re.findall(r"Attempted to load class (\S+) for invalid dist DEDICATED_SERVER", text)
    if dist:
        classes = sorted(set(dist))[:3]
        out.append(_finding("error", "client-on-server", _("Un mod côté client est chargé sur le serveur"),
                            _("Classe client demandée : {classes}. Le nom du package indique en général le mod fautif.",
                              classes=", ".join(classes)),
                            _("Retire ce mod du serveur (utilise l'onglet Serveur de ModMaestro pour générer un dossier propre).")))

    # --- Mixins ----------------------------------------------------------------------------------------
    mix = sorted(set(re.findall(r"Mixin apply for mod ([\w.\-]+) failed", text)))
    mix += sorted(set(re.findall(r"Mixin transformation of ([\w./$]+) failed", text)))[:3]
    if mix or "InvalidMixinException" in text or "MixinApplyError" in text:
        out.append(_finding("error", "mixin", _("Un mixin n'a pas pu s'appliquer"),
                            _("Un mod modifie du code qu'un autre mod (ou une autre version de Minecraft) a déjà changé.")
                            + (_(" Mods cités : {mods}.", mods=", ".join(mix[:5])) if mix else ""),
                            _("Mets à jour ces mods, ou retire-en un. Cherche aussi un doublon de mod de rendu (Sodium/Embeddium…)."),
                            mix[:5]))

    # --- Java --------------------------------------------------------------------------------------------
    for ver in sorted(set(re.findall(r"class file version (\d+)\.\d+", text))):
        java = _JAVA_BY_CLASS_VERSION.get(int(ver))
        if java:
            out.append(_finding("error", "java", _("Il faut Java {java} (ou plus)", java=java),
                                _("Un mod est compilé pour Java {java}, mais le jeu tourne avec une version plus ancienne.", java=java),
                                _("Installe Java {java} et choisis-le dans ton launcher / script de serveur.", java=java)))
            break

    if "java.lang.OutOfMemoryError" in text:
        out.append(_finding("error", "memory", _("Mémoire insuffisante"),
                            _("Java a manqué de RAM (OutOfMemoryError)."),
                            _("Augmente la RAM allouée (-Xmx) ; 6 à 8 Go sont courants pour un gros pack.")))

    # --- Incompatibilités binaires ---------------------------------------------------------------------------
    cls = sorted(set(re.findall(r"(?:NoSuchMethodError|NoSuchFieldError|NoClassDefFoundError|ClassNotFoundException)[:\s]+([\w./$]+)", text)))
    if cls:
        out.append(_finding("warning", "binary", _("Incompatibilité de versions entre mods"),
                            _("Un mod appelle du code qui n'existe pas dans la version installée d'un autre : {classes}.",
                              classes=", ".join(cls[:4]) + ("…" if len(cls) > 4 else "")),
                            _("Mets à jour le mod dont le package apparaît ici, ainsi que ses dépendances.")))

    if re.search(r"You need to agree to the EULA", text):
        out.append(_finding("info", "eula", _("EULA non acceptée"),
                            _("Le serveur s'arrête tant que l'EULA de Mojang n'est pas acceptée."),
                            _("Ouvre eula.txt et mets eula=true.")))
    if re.search(r"Failed to bind to port|Address already in use", text):
        out.append(_finding("error", "port", _("Port déjà utilisé"),
                            _("Un autre serveur (ou une instance précédente) occupe déjà ce port."),
                            _("Ferme l'autre processus ou change server-port dans server.properties.")))

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda f: order[f["severity"]])
    return out


# --------------------------------------------------------------------------
# Le pack a-t-il démarré ? (preuve la plus fiable qu'un diagnostic statique se trompe)
# --------------------------------------------------------------------------

_BOOT_OK = re.compile(
    r"Done \(\d+[.,]\d+s\)! For help|Sound engine started|Created: \d+x\d+x\d+ minecraft:textures/atlas|"
    r"Reloading ResourceManager|Backend library: LWJGL")
_BOOT_FAIL = re.compile(
    r"Loading errors encountered|Missing or unsupported mandatory dependencies|Failed to start the minecraft server|"
    r"Crash report saved to|---- Minecraft Crash Report ----|Incompatible mod set|Mod loading has failed")


def boot_status(mods_dir: str, jar_mtimes) -> dict | None:
    """Lit `logs/latest.log` à côté du dossier mods.

    Retourne {status: ok|crashed|unknown, log, mtime, fresh} ou None s'il n'y a pas de journal.
    `fresh` : le journal est postérieur au dernier mod ajouté (sinon il décrit un ancien état du pack).
    """
    root = os.path.dirname(os.path.abspath(mods_dir))
    path = os.path.join(root, "logs", "latest.log")
    try:
        mtime = os.path.getmtime(path)
        text = read_log(path)
    except (OSError, ValueError):
        return None
    newest_jar = max(jar_mtimes, default=0.0)
    if _BOOT_FAIL.search(text) and not re.search(r"Done \(\d+[.,]\d+s\)! For help", text):
        status = "crashed"
        # un « Reloading ResourceManager » ou un écran de chargement précède parfois l'erreur : l'échec prime
        if re.search(r"Sound engine started|Created: \d+x\d+x\d+ minecraft:textures/atlas", text) \
                and not re.search(r"Loading errors encountered|Missing or unsupported mandatory dependencies", text):
            status = "ok"
    elif _BOOT_OK.search(text):
        status = "ok"
    else:
        status = "unknown"
    return {"status": status, "log": os.path.relpath(path, root), "path": path, "mtime": mtime,
            "fresh": mtime >= newest_jar - 1}
