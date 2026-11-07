"""Lecture d'un journal de jeu / de serveur (latest.log, crash-report) pour en tirer les causes probables."""

from __future__ import annotations

import glob
import gzip
import os
import re
from collections import defaultdict

MAX_BYTES = 6 * 1024 * 1024  # on lit la fin du fichier, c'est là que se trouve le crash

_JAVA_BY_CLASS_VERSION = {52: 8, 53: 9, 54: 10, 55: 11, 60: 16, 61: 17, 62: 18, 63: 19, 64: 20, 65: 21, 66: 22, 67: 23, 68: 24}


def read_log(path: str) -> str:
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.isfile(path):
        raise ValueError(f"Fichier introuvable : {path}")
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
        out.append(_finding("error", "missing-dep", f"Dépendance manquante : {modid}",
                            f"Requise par : {', '.join(sorted(by))}.",
                            f"Ajoute le mod « {modid} » dans le dossier mods.", [modid, *sorted(by)]))
    for w in wrong.values():
        out.append(_finding("error", "wrong-version", f"Mauvaise version de {w['modid']}",
                            f"{w['by']} attend {w['range']} mais la version installée est {w['actual']}.",
                            f"Mets à jour (ou rétrograde) {w['modid']}.", [w["modid"], w["by"]]))

    # --- Fabric ------------------------------------------------------------------------
    fab_re = re.compile(
        r"Mod '([^']+)' \(([^)]+)\)[^\n]*?requires ([^\n]*?) of mod '([^']+)' \(([^)]+)\), which is missing")
    seen = set()
    for name, mid, ver, dep_name, dep_id in fab_re.findall(text):
        if (mid, dep_id) in seen:
            continue
        seen.add((mid, dep_id))
        out.append(_finding("error", "missing-dep", f"Dépendance manquante : {dep_name}",
                            f"{name} requiert {ver.strip()} de {dep_name} ({dep_id}).",
                            f"Ajoute « {dep_name} » dans le dossier mods.", [dep_id, mid]))

    # --- Doublons -------------------------------------------------------------------------
    dup_re = re.compile(r"Mod ID: '([^']+)' from mod files:\s*([^\n]+)")
    for modid, files in dup_re.findall(text):
        out.append(_finding("error", "duplicate", f"Doublon : {modid}",
                            f"Présent dans plusieurs fichiers : {files.strip()}.",
                            "Ne garde que la version la plus récente.", [modid]))

    # --- Mod client chargé sur un serveur ------------------------------------------------------
    dist = re.findall(r"Attempted to load class (\S+) for invalid dist DEDICATED_SERVER", text)
    if dist:
        classes = sorted(set(dist))[:3]
        out.append(_finding("error", "client-on-server", "Un mod côté client est chargé sur le serveur",
                            "Classe client demandée : " + ", ".join(classes) +
                            ". Le nom du package indique en général le mod fautif.",
                            "Retire ce mod du serveur (utilise l'onglet Serveur de ModMaestro pour générer un dossier propre)."))

    # --- Mixins ----------------------------------------------------------------------------------------
    mix = sorted(set(re.findall(r"Mixin apply for mod ([\w.\-]+) failed", text)))
    mix += sorted(set(re.findall(r"Mixin transformation of ([\w./$]+) failed", text)))[:3]
    if mix or "InvalidMixinException" in text or "MixinApplyError" in text:
        out.append(_finding("error", "mixin", "Un mixin n'a pas pu s'appliquer",
                            "Un mod modifie du code qu'un autre mod (ou une autre version de Minecraft) a déjà changé."
                            + (f" Mods cités : {', '.join(mix[:5])}." if mix else ""),
                            "Mets à jour ces mods, ou retire-en un. Cherche aussi un doublon de mod de rendu (Sodium/Embeddium…).",
                            mix[:5]))

    # --- Java --------------------------------------------------------------------------------------------
    for ver in sorted(set(re.findall(r"class file version (\d+)\.\d+", text))):
        java = _JAVA_BY_CLASS_VERSION.get(int(ver))
        if java:
            out.append(_finding("error", "java", f"Il faut Java {java} (ou plus)",
                                f"Un mod est compilé pour Java {java}, mais le jeu tourne avec une version plus ancienne.",
                                f"Installe Java {java} et choisis-le dans ton launcher / script de serveur."))
            break

    if "java.lang.OutOfMemoryError" in text:
        out.append(_finding("error", "memory", "Mémoire insuffisante",
                            "Java a manqué de RAM (OutOfMemoryError).",
                            "Augmente la RAM allouée (-Xmx) ; 6 à 8 Go sont courants pour un gros pack."))

    # --- Incompatibilités binaires ---------------------------------------------------------------------------
    cls = sorted(set(re.findall(r"(?:NoSuchMethodError|NoSuchFieldError|NoClassDefFoundError|ClassNotFoundException)[:\s]+([\w./$]+)", text)))
    if cls:
        out.append(_finding("warning", "binary", "Incompatibilité de versions entre mods",
                            "Un mod appelle du code qui n'existe pas dans la version installée d'un autre : "
                            + ", ".join(cls[:4]) + ("…" if len(cls) > 4 else "") + ".",
                            "Mets à jour le mod dont le package apparaît ici, ainsi que ses dépendances."))

    if re.search(r"You need to agree to the EULA", text):
        out.append(_finding("info", "eula", "EULA non acceptée",
                            "Le serveur s'arrête tant que l'EULA de Mojang n'est pas acceptée.",
                            "Ouvre eula.txt et mets eula=true."))
    if re.search(r"Failed to bind to port|Address already in use", text):
        out.append(_finding("error", "port", "Port déjà utilisé",
                            "Un autre serveur (ou une instance précédente) occupe déjà ce port.",
                            "Ferme l'autre processus ou change server-port dans server.properties."))

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda f: order[f["severity"]])
    return out
