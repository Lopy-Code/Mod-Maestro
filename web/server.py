"""Serveur local de l'interface ModMaestro (bibliothèque standard uniquement).

Sécurité : le serveur n'écoute que sur 127.0.0.1, vérifie l'en-tête Host (anti DNS-rebinding)
et exige un jeton aléatoire, généré à chaque lancement, pour toute requête /api/.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import socket
import sys
import tempfile
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import sqlite3

from core import (__version__, builder, compare, contribute, crashfinder, demo, export, htmlreport, i18n, knowledge,
                  learn, logscan, parser, pipeline, recommend, report, serverkit)
from core.i18n import _
from core.analyzer import Analysis, compute_plan
from core.cache import get_cache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "web", "static")
ASSETS = os.path.join(ROOT, "assets")


class State:
    def __init__(self, initial_path: str | None = None):
        self.token = secrets.token_urlsafe(18)
        self.port = 0
        self.initial_path = initial_path
        self.jobs: dict[str, dict] = {}
        self.analyses: dict[str, Analysis] = {}
        self.crash: dict[str, dict] = {}  # sessions du chercheur de crash
        self.demo_dir: str | None = None
        self.lock = threading.Lock()


# --------------------------------------------------------------------------
# Explorateur de dossiers (le navigateur ne donne pas accès au disque)
# --------------------------------------------------------------------------

def _shortcuts() -> list[dict]:
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    cands = [
        ("Dossier personnel", home),
        ("Bureau", os.path.join(home, "Desktop")),
        ("Téléchargements", os.path.join(home, "Downloads")),
        ("Minecraft", os.path.join(home, ".minecraft")),
        ("Minecraft", os.path.join(appdata, ".minecraft") if appdata else ""),
        ("Minecraft", os.path.join(home, "Library", "Application Support", "minecraft")),
        ("Prism Launcher", os.path.join(home, ".local", "share", "PrismLauncher", "instances")),
        ("Prism Launcher", os.path.join(appdata, "PrismLauncher", "instances") if appdata else ""),
        ("CurseForge", os.path.join(home, "curseforge", "minecraft", "Instances")),
        ("CurseForge", os.path.join(home, "Documents", "curseforge", "minecraft", "Instances")),
        ("Modrinth App", os.path.join(appdata, "ModrinthApp", "profiles") if appdata else ""),
        ("Modrinth App", os.path.join(home, ".local", "share", "ModrinthApp", "profiles")),
    ]
    out, seen = [], set()
    for label, p in cands:
        if p and os.path.isdir(p) and p not in seen:
            seen.add(p)
            out.append({"label": label, "path": p})
    if sys.platform.startswith("win"):
        for letter in "CDEFG":
            if os.path.isdir(f"{letter}:\\"):
                out.append({"label": f"Disque {letter}:", "path": f"{letter}:\\"})
    return out


def browse(path: str | None) -> dict:
    path = os.path.abspath(os.path.expanduser(path or "~"))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise ValueError(_("Ce dossier n'existe pas."))
    entries = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir() and (not e.name.startswith(".") or e.name == ".minecraft"):
                        entries.append({"name": e.name, "path": e.path, "kind": "dir",
                                        "jars": parser.count_jars(e.path, cap=999)})
                    elif e.is_file() and e.name.lower().endswith(".zip"):
                        entries.append({"name": e.name, "path": e.path, "kind": "zip", "jars": 0})
                except OSError:
                    continue
    except PermissionError as exc:
        raise ValueError(_("Accès refusé à ce dossier.")) from exc
    entries.sort(key=lambda x: (x["kind"] != "dir", x["name"].lower()))
    parent = os.path.dirname(path)
    return {
        "path": path,
        "parent": parent if parent != path else None,
        "jars": parser.count_jars(path, cap=9999),
        "has_mods_dir": os.path.isdir(os.path.join(path, "mods")),
        "entries": entries[:400],
        "shortcuts": _shortcuts(),
    }


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

def _remember(state: State, a: Analysis) -> None:
    with state.lock:
        state.analyses[a.id] = a
        while len(state.analyses) > 10:
            state.analyses.pop(next(iter(state.analyses)))


def _full_result(a: Analysis) -> dict:
    """L'analyse + tout ce dont l'interface a besoin pour proposer des chemins par défaut."""
    mods_dir = a.mods_dir
    result = a.to_dict()
    result["suggested_output"] = builder.suggest_output_dir(mods_dir)
    result["suggested"] = {
        "server": builder.suggest_output_dir(mods_dir), "kit": builder.suggest_output_dir(mods_dir, "server_kit"),
        "mrpack": builder.suggest_file(mods_dir, "modpack", ".mrpack"), "zip": builder.suggest_file(mods_dir, "modpack", ".zip"),
        "test": builder.suggest_output_dir(mods_dir, "modmaestro_test")}
    result["instance"] = export.detect_instance(mods_dir)
    result["server_defaults"] = {"ram": serverkit.estimate_ram_gb(len(result["plan"]["keep"])),
                                 "java": serverkit.java_for_mc(a.mc_version)}
    result["logs"] = logscan.find_logs(mods_dir)
    result["ignored_rows"] = {r["a"]: r["id"] for r in get_cache().list_learned() if r["kind"] == "ignore"}
    return result


def _run_job(state: State, fn, lang: str) -> str:
    """Exécute `fn(job)` dans un thread ; `fn` renvoie le résultat. Les erreurs deviennent un message lisible."""
    job_id = secrets.token_hex(6)
    job = {"state": "running", "phase": "scan", "done": 0, "total": 0, "result": None, "error": None}
    state.jobs[job_id] = job

    def work():
        i18n.set_lang(lang)
        try:
            job["result"], job["state"] = fn(job), "done"
        except (ValueError, FileExistsError, PermissionError) as exc:
            job["error"], job["state"] = str(exc), "error"
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            job["error"], job["state"] = _("Erreur inattendue : {exc}", exc=exc), "error"

    threading.Thread(target=work, daemon=True).start()
    return job_id


def _progress(job):
    def prog(stage, done, total):
        job["phase"], job["done"], job["total"] = stage, done, total
    return prog


def start_analysis(state: State, path: str, online: bool = False, lang: str = "fr") -> str:
    def fn(job):
        a = pipeline.run_analysis(path, online=online, progress=_progress(job), cache=get_cache())
        _remember(state, a)
        return _full_result(a)
    return _run_job(state, fn, lang)


def start_compare(state: State, path_a: str, path_b: str, online: bool = False, lang: str = "fr") -> str:
    def fn(job):
        job["step"] = "A"
        a = pipeline.run_analysis(path_a, online=online, progress=_progress(job), cache=get_cache())
        job["step"] = "B"
        b = pipeline.run_analysis(path_b, online=online, progress=_progress(job), cache=get_cache())
        _remember(state, a)
        _remember(state, b)
        res = compare.compare(a.to_dict(), b.to_dict())
        res["ids"] = {"a": a.id, "b": b.id}
        return res
    return _run_job(state, fn, lang)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ModMaestro/" + __version__

        def log_message(self, fmt, *args):  # silence
            pass

        # -- helpers --------------------------------------------------------
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{state.port}", f"localhost:{state.port}")

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _err(self, msg: str, code: int = 400):
            self._json({"error": msg}, code)

        def _api_allowed(self) -> bool:
            if self.headers.get("X-MM-Token") != state.token:
                self._err(_("Jeton invalide : relance ModMaestro et recharge la page."), 403)
                return False
            return True

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 5_000_000:
                raise ValueError(_("Requête trop volumineuse."))
            return json.loads(self.rfile.read(n) or b"{}")

        # -- GET ------------------------------------------------------------
        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._err(_("Hôte non autorisé."), 403)
            url = urlparse(self.path)
            path = unquote(url.path)
            try:
                if path == "/":
                    return self._index()
                if path.startswith("/static/"):
                    return self._file(STATIC, path[len("/static/"):])
                if path.startswith("/assets/"):
                    return self._file(ASSETS, path[len("/assets/"):])
                if path == "/favicon.ico":
                    return self._file(ASSETS, "favicon.ico")
                if path.startswith("/api/"):
                    if not self._api_allowed():
                        return None
                    q = {k: v[0] for k, v in parse_qs(url.query).items()}
                    i18n.set_lang(q.get("lang"))
                    if path == "/api/browse":
                        return self._json(browse(q.get("path")))
                    if path == "/api/kb":
                        cache = get_cache()
                        kb = knowledge.load_all(cache)
                        return self._json({
                            "stats": kb["_stats"], "learned": cache.list_learned(), "cache": cache.stats(),
                            "user_dir": knowledge.user_community_dir()})
                    if path.startswith("/api/job/"):
                        job = state.jobs.get(path.rsplit("/", 1)[-1])
                        if not job:
                            return self._err(_("Tâche inconnue."), 404)
                        return self._json(job)
                return self._err(_("Introuvable."), 404)
            except ValueError as exc:
                return self._err(str(exc))
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                return self._err(_("Erreur inattendue : {exc}", exc=exc), 500)

        def _analysis(self, body: dict) -> Analysis:
            a = state.analyses.get(str(body.get("analysis")))
            if not a:
                raise ValueError(_("Analyse expirée : relance l'analyse."))
            return a

        def _crash_view(self, a: Analysis, st: dict) -> dict:
            view = crashfinder.describe(a, st)
            view["hint"] = st.get("suspects_hint", [])
            view["suggested_output"] = builder.suggest_output_dir(a.mods_dir, "modmaestro_test")
            if st["done"]:
                view["summary"] = crashfinder.summary(a, st)
            return view

        def _learn(self, body: dict) -> dict:
            kind = body.get("kind")
            if kind == "conflict":
                return learn.add_conflict(get_cache(), body.get("a", ""), body.get("b", ""), body.get("note", ""),
                                          body.get("severity") or "error")
            if kind == "side":
                return learn.add_side(get_cache(), body.get("a", ""), body.get("side") or "client", body.get("note", ""))
            raise ValueError(_("Type inconnu : « conflict » ou « side »."))

        def _index(self):
            with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
                html = fh.read()
            cfg = json.dumps({"token": state.token, "version": __version__, "initial": state.initial_path or ""})
            html = html.replace("/*__MM_CONFIG__*/{}", cfg.replace("</", "<\\/"))
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

        def _file(self, base: str, rel: str):
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
                return self._err(_("Introuvable."), 404)
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8" if "charset" not in ctype else ""
            with open(full, "rb") as fh:
                return self._send(200, fh.read(), ctype)

        # -- POST -----------------------------------------------------------
        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return self._err(_("Hôte non autorisé."), 403)
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{state.port}", f"http://localhost:{state.port}"):
                return self._err(_("Origine non autorisée."), 403)
            if not self._api_allowed():
                return None
            path = urlparse(self.path).path
            try:
                body = self._body()
                lang = i18n.set_lang(body.get("lang"))
                if path == "/api/analyze":
                    p = str(body.get("path", "")).strip()
                    if not p:
                        return self._err(_("Indique un dossier à analyser."))
                    return self._json({"job": start_analysis(state, p, online=bool(body.get("online")), lang=lang)})
                if path == "/api/compare":
                    pa, pb = str(body.get("a", "")).strip(), str(body.get("b", "")).strip()
                    if not pa or not pb:
                        return self._err(_("Indique les deux dossiers à comparer."))
                    return self._json({"job": start_compare(state, pa, pb, bool(body.get("online")), lang)})
                if path == "/api/ignore":
                    cache = get_cache()
                    if body.get("all"):
                        a = self._analysis(body)
                        ids = [i["id"] for i in a.active_issues() if i["severity"] != "info"]
                    else:
                        ids = [str(body.get("id", ""))]
                    n = learn.ignore_all(cache, ids, str(body.get("note", "")))
                    return self._json({"ignored": n})
                if path == "/api/recommend":
                    a = self._analysis(body)
                    return self._json(recommend.run(a, online=bool(body.get("online")), cache=get_cache()))
                if path == "/api/crash/start":
                    a = self._analysis(body)
                    st = crashfinder.start(a)
                    st["suspects_hint"] = crashfinder.quick_suspects(a, body.get("log_mods") or [])
                    state.crash[st["id"]] = st
                    return self._json(self._crash_view(a, st))
                if path == "/api/crash/answer":
                    a = self._analysis(body)
                    st = state.crash.get(str(body.get("id")))
                    if not st:
                        return self._err(_("Session inconnue : recommence la recherche."))
                    return self._json(self._crash_view(a, crashfinder.answer(a, st, str(body.get("outcome", "")))))
                if path == "/api/crash/folder":
                    a = self._analysis(body)
                    st = state.crash.get(str(body.get("id")))
                    if not st:
                        return self._err(_("Session inconnue : recommence la recherche."))
                    return self._json(crashfinder.build_test_folder(a, st, str(body.get("output", ""))))
                if path == "/api/export/mrpack":
                    a = self._analysis(body)
                    return self._json(export.export_mrpack(
                        a, str(body.get("output", "")), name=str(body.get("name", "")), version=str(body.get("version", "1.0.0")),
                        mc=str(body.get("mc", "")), loader=str(body.get("loader", "")),
                        loader_version=str(body.get("loader_version", "")), include_unknown=bool(body.get("include_unknown", True)),
                        exclude=body.get("exclude") or []))
                if path == "/api/export/zip":
                    a = self._analysis(body)
                    plan = compute_plan(a, body.get("exclude") or [], body.get("include") or [])
                    files = plan["keep"] if body.get("server_only") else [f for f, e in a.entries.items() if e["status"] in ("ok", "no-metadata")]
                    return self._json(export.export_zip(a, str(body.get("output", "")), files))
                if path == "/api/serverkit":
                    a = self._analysis(body)
                    return self._json(serverkit.generate(
                        a, str(body.get("output", "")), ram_gb=int(body["ram_gb"]) if body.get("ram_gb") else None,
                        eula=bool(body.get("eula")), port=int(body.get("port") or 25565),
                        max_players=int(body.get("max_players") or 20), motd=str(body.get("motd", "")),
                        view_distance=int(body.get("view_distance") or 10), simulation_distance=int(body.get("simulation_distance") or 8),
                        with_mods=bool(body.get("with_mods")), exclude=body.get("exclude") or [], include=body.get("include") or []))
                if path == "/api/report/html":
                    a = self._analysis(body)
                    out = htmlreport.to_html(a.to_dict(), include_files=bool(body.get("files", True)),
                                             include_source=bool(body.get("source", False)))
                    return self._json({"html": out, "filename": "modmaestro-rapport.html"})
                if path == "/api/contribute":
                    a = state.analyses.get(str(body.get("analysis")))
                    ctx = {"loader": a.loader, "mc_version": a.mc_version} if a else {}
                    return self._json(contribute.build(get_cache(), body.get("ids") or None, ctx))
                if path == "/api/learn":
                    return self._json({"item": self._learn(body)})
                if path == "/api/learn/delete":
                    return self._json({"ok": learn.remove(get_cache(), int(body.get("id", 0)))})
                if path == "/api/learn/export":
                    return self._json({"bundle": learn.to_bundle(get_cache())})
                if path == "/api/learn/import":
                    return self._json(learn.import_bundle(get_cache(), body.get("bundle")))
                if path == "/api/cache/clear":
                    get_cache().clear_online()
                    return self._json({"cache": get_cache().stats()})
                if path == "/api/demo":
                    with state.lock:
                        if not state.demo_dir or not os.path.isdir(state.demo_dir):
                            state.demo_dir = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
                    return self._json({"job": start_analysis(state, state.demo_dir, lang=i18n.set_lang(body.get("lang"))), "path": state.demo_dir})
                if path == "/api/build":
                    a = self._analysis(body)
                    res = builder.build_server(
                        a, str(body.get("output", "")), exclude=body.get("exclude") or [],
                        include=body.get("include") or [], make_zip=bool(body.get("zip")),
                        dry_run=bool(body.get("dry_run")))
                    return self._json(res)
                if path == "/api/plan":
                    a = self._analysis(body)
                    plan = compute_plan(a, body.get("exclude") or [], body.get("include") or [])
                    size = sum(a.entries[f]["size"] for f in plan["keep"])
                    return self._json({"plan": plan, "bytes": size})
                if path == "/api/report":
                    a = self._analysis(body)
                    return self._json({"markdown": report.to_markdown(a.to_dict())})
                if path == "/api/logscan":
                    text = body.get("text") or logscan.read_log(str(body.get("path", "")))
                    findings = logscan.scan_text(text)
                    a = state.analyses.get(str(body.get("analysis")))
                    installed = [{"modid": m["modid"], "side": m["side"]} for m in a.to_dict()["mods"]] if a else []
                    return self._json({"findings": findings, "chars": len(text),
                                       "suggestions": learn.suggest(findings, installed)})
                return self._err(_("Introuvable."), 404)
            except (ValueError, FileExistsError, PermissionError, json.JSONDecodeError) as exc:
                return self._err(str(exc))
            except sqlite3.Error as exc:
                return self._err(_("Erreur de la base locale : {exc}", exc=exc))
            except OSError as exc:
                return self._err(_("Erreur disque : {exc}", exc=exc))
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                return self._err(_("Erreur inattendue : {exc}", exc=exc), 500)

    return Handler


def _free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 30)) + [0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if not sys.platform.startswith("win"):  # tolère TIME_WAIT après une relance rapide
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError(_("Aucun port libre."))


def serve(initial_path: str | None = None, port: int = 8765, open_browser: bool = True) -> None:
    state = State(initial_path)
    state.port = _free_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", state.port), make_handler(state))
    url = f"http://127.0.0.1:{state.port}/"
    print("\n  " + _("ModMaestro {version} — interface disponible sur {url}", version=__version__, url=url))
    print("  " + _("(Ctrl+C pour arrêter)") + "\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  " + _("À bientôt !"))
    finally:
        httpd.server_close()
