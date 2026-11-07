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

from core import __version__, builder, demo, logscan, parser, report
from core.analyzer import Analysis, analyze, compute_plan

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
        raise ValueError("Ce dossier n'existe pas.")
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
        raise ValueError("Accès refusé à ce dossier.") from exc
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

def start_analysis(state: State, path: str) -> str:
    job_id = secrets.token_hex(6)
    job = {"state": "running", "done": 0, "total": 0, "result": None, "error": None}
    state.jobs[job_id] = job

    def work():
        try:
            mods_dir, notes = parser.resolve_source(path)

            def prog(done, total):
                job["done"], job["total"] = done, total

            jars, extras = parser.scan_folder(mods_dir, progress=prog)
            a = analyze(jars, extras, source=path, mods_dir=mods_dir, notes=notes)
            with state.lock:
                state.analyses[a.id] = a
                while len(state.analyses) > 6:
                    state.analyses.pop(next(iter(state.analyses)))
            result = a.to_dict()
            result["suggested_output"] = builder.suggest_output_dir(mods_dir)
            result["logs"] = logscan.find_logs(mods_dir)
            job["result"], job["state"] = result, "done"
        except ValueError as exc:
            job["error"], job["state"] = str(exc), "error"
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            job["error"], job["state"] = f"Erreur inattendue : {exc}", "error"

    threading.Thread(target=work, daemon=True).start()
    return job_id


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
                self._err("Jeton invalide : relance ModMaestro et recharge la page.", 403)
                return False
            return True

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 5_000_000:
                raise ValueError("Requête trop volumineuse.")
            return json.loads(self.rfile.read(n) or b"{}")

        # -- GET ------------------------------------------------------------
        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._err("Hôte non autorisé.", 403)
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
                    if path == "/api/browse":
                        return self._json(browse(q.get("path")))
                    if path.startswith("/api/job/"):
                        job = state.jobs.get(path.rsplit("/", 1)[-1])
                        if not job:
                            return self._err("Tâche inconnue.", 404)
                        return self._json(job)
                return self._err("Introuvable.", 404)
            except ValueError as exc:
                return self._err(str(exc))
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                return self._err(f"Erreur inattendue : {exc}", 500)

        def _index(self):
            with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
                html = fh.read()
            cfg = json.dumps({"token": state.token, "version": __version__, "initial": state.initial_path or ""})
            html = html.replace("/*__MM_CONFIG__*/{}", cfg.replace("</", "<\\/"))
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

        def _file(self, base: str, rel: str):
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
                return self._err("Introuvable.", 404)
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
                ctype += "; charset=utf-8" if "charset" not in ctype else ""
            with open(full, "rb") as fh:
                return self._send(200, fh.read(), ctype)

        # -- POST -----------------------------------------------------------
        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return self._err("Hôte non autorisé.", 403)
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{state.port}", f"http://localhost:{state.port}"):
                return self._err("Origine non autorisée.", 403)
            if not self._api_allowed():
                return None
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/analyze":
                    p = str(body.get("path", "")).strip()
                    if not p:
                        return self._err("Indique un dossier à analyser.")
                    return self._json({"job": start_analysis(state, p)})
                if path == "/api/demo":
                    with state.lock:
                        if not state.demo_dir or not os.path.isdir(state.demo_dir):
                            state.demo_dir = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
                    return self._json({"job": start_analysis(state, state.demo_dir), "path": state.demo_dir})
                if path == "/api/build":
                    a = state.analyses.get(str(body.get("analysis")))
                    if not a:
                        return self._err("Analyse expirée : relance l'analyse.")
                    res = builder.build_server(
                        a, str(body.get("output", "")), exclude=body.get("exclude") or [],
                        include=body.get("include") or [], make_zip=bool(body.get("zip")),
                        dry_run=bool(body.get("dry_run")))
                    return self._json(res)
                if path == "/api/plan":
                    a = state.analyses.get(str(body.get("analysis")))
                    if not a:
                        return self._err("Analyse expirée : relance l'analyse.")
                    plan = compute_plan(a, body.get("exclude") or [], body.get("include") or [])
                    size = sum(a.entries[f]["size"] for f in plan["keep"])
                    return self._json({"plan": plan, "bytes": size})
                if path == "/api/report":
                    a = state.analyses.get(str(body.get("analysis")))
                    if not a:
                        return self._err("Analyse expirée : relance l'analyse.")
                    return self._json({"markdown": report.to_markdown(a.to_dict())})
                if path == "/api/logscan":
                    text = body.get("text") or logscan.read_log(str(body.get("path", "")))
                    return self._json({"findings": logscan.scan_text(text), "chars": len(text)})
                return self._err("Introuvable.", 404)
            except (ValueError, FileExistsError, PermissionError, json.JSONDecodeError) as exc:
                return self._err(str(exc))
            except OSError as exc:
                return self._err(f"Erreur disque : {exc}")
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                return self._err(f"Erreur inattendue : {exc}", 500)

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
    raise OSError("Aucun port libre.")


def serve(initial_path: str | None = None, port: int = 8765, open_browser: bool = True) -> None:
    state = State(initial_path)
    state.port = _free_port(port)
    httpd = ThreadingHTTPServer(("127.0.0.1", state.port), make_handler(state))
    url = f"http://127.0.0.1:{state.port}/"
    print(f"\n  ModMaestro {__version__} — interface disponible sur {url}")
    print("  (Ctrl+C pour arrêter)\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  À bientôt !")
    finally:
        httpd.server_close()
