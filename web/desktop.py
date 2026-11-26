"""Fenêtre de l'application (pywebview) — facultative, avec repli automatique sur le navigateur.

L'interface est la même que dans le navigateur : le serveur local (127.0.0.1) tourne dans un fil et la fenêtre l'affiche.
Si pywebview n'est pas installé, ou si la fenêtre ne peut pas s'ouvrir (moteur web absent, pas d'écran…), `run` renvoie
False et `main.py` ouvre le navigateur comme avant. Rien de plus n'est envoyé ni installé.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading

from . import server
from core.i18n import _

TITLE = "ModMaestro"
SIZE = (1280, 820)
MIN_SIZE = (900, 600)


def icon_path() -> str | None:
    path = os.path.join(server.ASSETS, "logo-256.png")
    return path if os.path.isfile(path) else None


def prepare_console() -> None:
    """Windows, exécutable sans console : sans cela print() et input() échouent. On se rattache au terminal appelant."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None and sys.stdin is not None:
        return
    attached = False
    try:
        import ctypes
        attached = bool(ctypes.windll.kernel32.AttachConsole(-1))   # -1 : console du processus parent
    except Exception:  # noqa: BLE001
        pass
    for name, target, mode in (("stdout", "CONOUT$", "w"), ("stderr", "CONOUT$", "w"), ("stdin", "CONIN$", "r")):
        if getattr(sys, name) is not None:
            continue
        try:
            stream = open(target if attached else os.devnull, mode, encoding="utf-8", errors="replace")
        except OSError:
            stream = open(os.devnull, mode, encoding="utf-8")
        setattr(sys, name, stream)


def _save_dialog(webview, window):
    kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or getattr(webview, "SAVE_DIALOG", None)

    def ask(name: str):
        res = window.create_file_dialog(kind, save_filename=name)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]
    return ask


def run(initial_path: str | None = None, port: int = 8765, webview_module=None) -> bool:
    """Ouvre la fenêtre et attend sa fermeture. Renvoie False si elle n'a pas pu s'ouvrir (on utilise alors le navigateur)."""
    try:
        webview = webview_module or importlib.import_module("webview")
    except Exception:  # noqa: BLE001 — pywebview absent ou cassé : ce n'est pas une erreur
        return False
    httpd, state, url = server.start(initial_path, port, desktop=True)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    shown = False
    try:
        settings = getattr(webview, "settings", None)
        if isinstance(settings, dict):       # les liens externes et l'enregistrement passent par notre serveur
            settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
        window = webview.create_window(TITLE, url, width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE)
        state.save_dialog = _save_dialog(webview, window)
        icon = icon_path()
        try:
            webview.start(icon=icon) if icon else webview.start()
        except TypeError:                    # ancienne version de pywebview sans l'option d'icône
            webview.start()
        shown = True
    except Exception as exc:  # noqa: BLE001
        print("  " + _("La fenêtre n'a pas pu s'ouvrir ({exc}) : ouverture dans le navigateur.", exc=exc), file=sys.stderr)
    finally:
        httpd.shutdown()
        httpd.server_close()
        server.clean_uploads(state)
    return shown
