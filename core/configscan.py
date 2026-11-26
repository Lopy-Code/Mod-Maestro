"""Analyse des fichiers de configuration : réglages connus pour provoquer des lags ou des crashs.

Fichiers lus (en lecture seule, à la racine de l'instance, c.-à-d. le dossier qui contient `mods/`) :
`server.properties`, `options.txt`, `user_jvm_args.txt` / scripts de lancement, et les fichiers de `config/` visés par
les règles de `core/data/configrules.json` (+ tes règles dans `<dossier ModMaestro>/configrules/*.json`).

Chaque alerte est une **suggestion** (gravité « avertissement » ou « info ») : un réglage inhabituel n'est pas une erreur.
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re

from . import knowledge
from .cache import user_data_dir
from .i18n import _, get_lang

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

MAX_READ = 2 * 1024 * 1024
OPS = {"eq", "ne", "gt", "ge", "lt", "le", "true", "false", "contains"}
SEVERITIES = ("info", "warning")
RULE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")
SCRIPT_NAMES = ("user_jvm_args.txt", "start.sh", "start.bat", "run.sh", "run.bat", "launch.sh", "launch.bat", "startserver.sh", "startserver.bat")


def rules_files() -> list[str]:
    return [os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "configrules.json"),
            *sorted(glob.glob(os.path.join(user_data_dir(), "configrules", "*.json")))]


def validate_rule(r) -> list[str]:
    err: list[str] = []
    if not isinstance(r, dict):
        return [_("L'entrée doit être un objet JSON.")]
    if not RULE_ID.match(str(r.get("id", ""))):
        err.append(_("« id » manquant ou invalide."))
    path = str(r.get("path", ""))
    if not re.match(r"^config/[A-Za-z0-9_.\-*/]{1,120}$", path) or ".." in path:
        err.append(_("« path » doit viser un fichier du dossier config/."))
    if not str(r.get("key", "")).strip():
        err.append(_("« key » est obligatoire."))
    if r.get("op") not in OPS:
        err.append(_("« op » invalide."))
    if r.get("severity") not in SEVERITIES:
        err.append(_("« severity » doit valoir « info » ou « warning »."))
    if not str(r.get("title", "")).strip() or not str(r.get("message", "")).strip():
        err.append(_("« title » et « message » sont obligatoires."))
    return err


def load_rules() -> tuple[list[dict], list[str]]:
    rules, errors = [], []
    for path in rules_files():
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            errors.append(f"{os.path.basename(path)} : {exc}")
            continue
        for r in data if isinstance(data, list) else [data]:
            bad = validate_rule(r)
            if bad:
                errors.append(f"{os.path.basename(path)} : {bad[0]}")
            else:
                rules.append(r)
    return rules, errors


# -- lecture -----------------------------------------------------------------------------------------------------------

def _read(path: str) -> str | None:
    try:
        if os.path.getsize(path) > MAX_READ:
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def parse_properties(text: str, sep: str = "=") -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")) or sep not in line:
            continue
        k, v = line.split(sep, 1)
        out[k.strip()] = v.strip()
    return out


def parse_structured(path: str, text: str) -> dict | None:
    low = path.lower()
    try:
        if low.endswith(".toml") and tomllib:
            return tomllib.loads(text)
        if low.endswith((".json", ".json5")):
            return json.loads(text)
        if low.endswith((".properties", ".cfg")):
            return parse_properties(text)
    except (ValueError, TypeError):
        return None
    return None


def lookup(data, dotted: str):
    """Valeur à `a.b.c` (les clés plates contenant des points sont aussi acceptées)."""
    if isinstance(data, dict) and dotted in data:
        return data[dotted], True
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None, False
    return cur, True


def _num(v):
    try:
        return float(str(v).strip().rstrip("fFdD"))
    except ValueError:
        return None


def check(op: str, value, ref) -> bool:
    if op in ("true", "false"):
        s = str(value).strip().lower()
        return (s == "true") if op == "true" else (s == "false")
    if op == "contains":
        return str(ref).lower() in str(value).lower()
    a, b = _num(value), _num(ref)
    if op in ("gt", "ge", "lt", "le"):
        if a is None or b is None:
            return False
        return {"gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]
    if a is not None and b is not None:
        eq = a == b
    else:
        eq = str(value).strip().lower() == str(ref).strip().lower()
    return eq if op == "eq" else not eq


# -- règles intégrées (vanilla + JVM) ----------------------------------------------------------------------------------------

def _f(fid, sev, title, message, fix, file, modids=()):
    return {"id": f"config:{fid}", "severity": sev, "title": title, "message": message, "fix": fix, "file": file, "modids": list(modids)}


def scan_server_properties(text: str, jars: int) -> list[dict]:
    p, out, f = parse_properties(text), [], "server.properties"
    vd, sd = _num(p.get("view-distance")), _num(p.get("simulation-distance"))
    if vd is not None and vd > 16:
        out.append(_f("view-distance", "warning", _("Distance d'affichage du serveur élevée"),
                      _("view-distance vaut {v} : chaque joueur force le serveur à envoyer beaucoup plus de chunks, ce qui coûte du processeur et de la bande passante.", v=int(vd)),
                      _("Descends view-distance vers 10–12 (le jeu de base est à 10)."), f))
    if sd is not None and sd > 12:
        out.append(_f("simulation-distance", "warning", _("Distance de simulation du serveur élevée"),
                      _("simulation-distance vaut {v} : tous les chunks de cette zone sont simulés (mobs, machines, cultures), c'est le réglage qui fait le plus chuter les TPS sur un pack lourd.", v=int(sd)),
                      _("Descends simulation-distance vers 6–8."), f))
    mt = _num(p.get("max-tick-time"))
    if mt is not None and mt < 0:
        out.append(_f("max-tick-time", "info", _("Le chien de garde du serveur est désactivé"),
                      _("max-tick-time vaut -1 : un serveur bloqué ne sera jamais arrêté ni signalé par le watchdog, il restera figé."),
                      _("Remets 60000 (valeur par défaut) pour obtenir un rapport de crash en cas de blocage."), f))
    if str(p.get("online-mode", "")).lower() == "false":
        out.append(_f("online-mode", "info", _("Mode hors-ligne activé"),
                      _("online-mode=false : les comptes ne sont pas vérifiés, n'importe qui peut prendre le pseudo d'un autre (et être opérateur)."),
                      _("Garde online-mode=true sauf derrière un proxy (Velocity/BungeeCord) configuré pour ça."), f))
    ebr = _num(p.get("entity-broadcast-range-percentage"))
    if ebr is not None and ebr > 100:
        out.append(_f("entity-broadcast-range", "info", _("Portée d'affichage des entités augmentée"),
                      _("entity-broadcast-range-percentage vaut {v} % : le serveur envoie les entités de plus loin, ce qui coûte des TPS sur un pack avec beaucoup de mobs.", v=int(ebr)),
                      _("Reste à 100 (ou moins pour gagner en performances)."), f))
    return out


def scan_options(text: str) -> list[dict]:
    p, out, f = parse_properties(text, ":"), [], "options.txt"
    rd, sd = _num(p.get("renderDistance")), _num(p.get("simulationDistance"))
    if rd is not None and rd >= 24:
        out.append(_f("client-render-distance", "info", _("Distance d'affichage client très élevée"),
                      _("renderDistance vaut {v} : sur un gros modpack, c'est une cause fréquente de lags et de manque de mémoire.", v=int(rd)),
                      _("Essaie 12–16, ou garde cette valeur seulement avec un mod d'optimisation (Sodium/Embeddium)."), f))
    if sd is not None and sd >= 16:
        out.append(_f("client-simulation-distance", "info", _("Distance de simulation client élevée"),
                      _("simulationDistance vaut {v} : en solo, le jeu simule tous ces chunks en plus de les afficher.", v=int(sd)),
                      _("Essaie 8–10 si tu as des lags."), f))
    eds = _num(p.get("entityDistanceScaling"))
    if eds is not None and eds > 2:
        out.append(_f("client-entity-distance", "info", _("Distance des entités élevée"),
                      _("entityDistanceScaling vaut {v} : beaucoup plus d'entités sont dessinées, ce qui peut diviser les FPS.", v=eds),
                      _("Reviens vers 1.0–1.5."), f))
    return out


_JVM = re.compile(r"-Xm([sx])(\d+)([kKmMgG])")
_GC = {"-XX:+UseG1GC": "G1", "-XX:+UseZGC": "ZGC", "-XX:+UseParallelGC": "Parallel", "-XX:+UseSerialGC": "Serial",
       "-XX:+UseShenandoahGC": "Shenandoah", "-XX:+UseConcMarkSweepGC": "CMS"}


def _mb(n: str, unit: str) -> float:
    return int(n) * {"k": 1 / 1024, "m": 1, "g": 1024}[unit.lower()]


def scan_jvm(text: str, jars: int, file: str) -> list[dict]:
    out = []
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "REM", "::", "rem"))]
    body = "\n".join(lines)
    mem = {m.group(1): _mb(m.group(2), m.group(3)) for m in _JVM.finditer(body)}
    xmx, xms = mem.get("x"), mem.get("s")
    if xmx is not None:
        if xmx >= 32 * 1024:
            out.append(_f("jvm-xmx-huge", "warning", _("Trop de mémoire allouée à Java"),
                          _("-Xmx vaut {g} Go : au-delà d'environ 31 Go, Java perd une optimisation de mémoire et peut devenir plus lent, avec de longues pauses du ramasse-miettes.", g=round(xmx / 1024)),
                          _("Reste sous 31 Go ; 6–10 Go suffisent pour la plupart des packs."), file))
        elif xmx < 3 * 1024 and jars >= 100:
            out.append(_f("jvm-xmx-low", "warning", _("Mémoire Java probablement insuffisante"),
                          _("-Xmx vaut {g} Go pour {n} mods : risque d'erreurs « OutOfMemory » et de lags.", g=round(xmx / 1024, 1), n=jars),
                          _("Prévois au moins 4–6 Go pour ce pack."), file))
        if xms is not None and xms > xmx:
            out.append(_f("jvm-xms-gt-xmx", "warning", _("-Xms plus grand que -Xmx"),
                          _("Java refuse de démarrer quand la mémoire initiale (-Xms) dépasse le maximum (-Xmx)."),
                          _("Mets -Xms égal ou inférieur à -Xmx."), file))
    gcs = sorted({name for flag, name in _GC.items() if flag in body})
    if len(gcs) > 1:
        out.append(_f("jvm-gc-conflict", "warning", _("Plusieurs ramasse-miettes demandés"),
                      _("Les options demandent à la fois {gcs} : Java refuse de démarrer avec « Conflicting collector combinations ».", gcs=" + ".join(gcs)),
                      _("Garde un seul ramasse-miettes (G1 convient à la plupart des packs)."), file))
    if "-XX:+UseConcMarkSweepGC" in body or re.search(r"-XX:(Max)?PermSize", body):
        out.append(_f("jvm-obsolete-flags", "info", _("Options Java obsolètes"),
                      _("Ces options (CMS, PermSize) n'existent plus dans Java 17/21 : elles sont ignorées ou affichent des avertissements au démarrage."),
                      _("Retire-les ; voir « Lancement optimisé » dans l'onglet Serveur pour des options adaptées."), file))
    return out


# -- règles de données ---------------------------------------------------------------------------------------------------------

def scan_rules(root: str, rules: list[dict], modids: set[str]) -> list[dict]:
    out = []
    cache: dict[str, dict | None] = {}
    for r in rules:
        need = r.get("requires_mod")
        if need and knowledge.normalize_id(need) not in modids:
            continue
        pattern = str(r["path"])
        base = os.path.join(root, "config")
        if not os.path.isdir(base):
            continue
        for dirpath, _d, names in os.walk(base):
            if dirpath[len(base):].count(os.sep) > 2:
                continue
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, "/")
                if not fnmatch.fnmatch(rel, pattern):
                    continue
                if rel not in cache:
                    text = _read(os.path.join(root, *rel.split("/")))
                    cache[rel] = parse_structured(rel, text) if text is not None else None
                data = cache[rel]
                if data is None:
                    continue
                value, found = lookup(data, str(r["key"]))
                if found and check(r["op"], value, r.get("value")):
                    en = r.get("en") if get_lang() == "en" and isinstance(r.get("en"), dict) else {}
                    out.append(_f(r["id"], r["severity"], en.get("title") or r["title"], en.get("message") or r["message"],
                                  en.get("fix") or r.get("fix", ""), rel, [r["requires_mod"]] if r.get("requires_mod") else []))
    return out


def instance_root(mods_dir: str) -> str:
    """Dossier qui contient `mods/` (l'instance ou le serveur)."""
    return os.path.dirname(os.path.abspath(mods_dir)) if os.path.basename(os.path.abspath(mods_dir)).lower() == "mods" else os.path.abspath(mods_dir)


def scan(mods_dir: str, jar_count: int, modids: set[str]) -> tuple[list[dict], list[str]]:
    root = instance_root(mods_dir)
    found: list[dict] = []
    text = _read(os.path.join(root, "server.properties"))
    if text is not None:
        found += scan_server_properties(text, jar_count)
    text = _read(os.path.join(root, "options.txt"))
    if text is not None:
        found += scan_options(text)
    for name in SCRIPT_NAMES:
        text = _read(os.path.join(root, name))
        if text is not None:
            found += scan_jvm(text, jar_count, name)
    rules, errors = load_rules()
    found += scan_rules(root, rules, modids)
    seen, unique = set(), []
    for f in found:                       # un même réglage trouvé dans deux scripts : une seule alerte
        if f["id"] not in seen:
            seen.add(f["id"])
            unique.append(f)
    return unique, errors


def apply(a, mods_dir: str) -> None:
    modids = {knowledge.normalize_id(m["modid"]) for e in a.entries.values() for m in e["mods"] if m.get("modid")}
    findings, errors = scan(mods_dir, a.jar_count, modids)
    for f in findings:
        a.add_issue(f["id"], f["severity"], "config", f["title"], f"{f['message']} ({f['file']})", modids=f["modids"],
                    fix=f["fix"], confidence="heuristic")
    for e in errors[:3]:
        a.notes.append(f"Règles de configuration : {e}")
