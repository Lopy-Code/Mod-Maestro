"""Fenêtre de l'application : faux pywebview, aucune vraie fenêtre ; repli sur le navigateur."""
import json
import os
import re
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from web import desktop  # noqa: E402


class FakeWindow:
    def __init__(self, dest):
        self.dest, self.asked = dest, []

    def create_file_dialog(self, kind, save_filename=""):
        self.asked.append((kind, save_filename))
        return (self.dest,) if self.dest else None


class FakeWebview:
    """Se comporte comme pywebview : create_window puis start() qui bloque jusqu'à la fermeture."""
    class FileDialog:
        SAVE = 15

    def __init__(self, dest=None, fail=False, icon=True):
        self.settings, self.dest, self.fail, self.takes_icon = {}, dest, fail, icon
        self.window, self.url, self.page, self.saved, self.icons, self.port = None, None, "", None, [], 0

    def create_window(self, title, url, **kw):
        self.title, self.url, self.kw = title, url, kw
        self.window = FakeWindow(self.dest)
        return self.window

    def _use(self):
        with urllib.request.urlopen(self.url, timeout=10) as r:
            self.page = r.read().decode()
        token = re.search(r'"token": "([^"]+)"', self.page).group(1)
        req = urllib.request.Request(self.url + "api/desktop/save", method="POST",
                                     data=json.dumps({"name": "../rapport.html", "text": "<b>é</b>"}).encode(),
                                     headers={"X-MM-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.saved = json.loads(r.read())

    def start(self, **kw):
        if self.fail:
            raise RuntimeError("pas de moteur web")
        if kw and not self.takes_icon:
            raise TypeError("icon")
        self.icons.append(kw.get("icon"))
        self._use()


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("MODMAESTRO_HOME")
        os.environ["MODMAESTRO_HOME"] = os.path.join(self.tmp.name, "home")
        from core import cache
        cache.reset_default()

    def tearDown(self):
        from core import cache
        cache.reset_default()
        os.environ.pop("MODMAESTRO_HOME", None) if self.old_home is None else os.environ.__setitem__("MODMAESTRO_HOME", self.old_home)
        self.tmp.cleanup()

    def closed(self, url):
        port = int(url.rsplit(":", 1)[1].strip("/"))
        with socket.socket() as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) != 0

    def test_without_pywebview_falls_back(self):
        real = desktop.importlib.import_module
        desktop.importlib.import_module = lambda name: (_ for _ in ()).throw(ImportError(name))
        try:
            self.assertFalse(desktop.run())
        finally:
            desktop.importlib.import_module = real

    def test_window_serves_ui_and_saves_through_native_dialog(self):
        dest = os.path.join(self.tmp.name, "out.html")
        wv = FakeWebview(dest)
        self.assertTrue(desktop.run(port=18765, webview_module=wv))
        self.assertIn('"desktop": true', wv.page)
        self.assertEqual((wv.title, wv.kw["min_size"]), ("ModMaestro", desktop.MIN_SIZE))
        self.assertEqual(wv.window.asked, [(15, "rapport.html")])            # nom nettoyé : jamais de chemin venant de la page
        self.assertEqual(wv.saved, {"saved": True, "path": dest})
        with open(dest, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "<b>é</b>")
        self.assertFalse(wv.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"])
        self.assertTrue(wv.icons[0] and wv.icons[0].endswith("logo-256.png"))
        self.assertTrue(self.closed(wv.url))                                  # le serveur s'arrête avec la fenêtre

    def test_cancelled_dialog_writes_nothing(self):
        wv = FakeWebview(None)
        self.assertTrue(desktop.run(port=18780, webview_module=wv))
        self.assertEqual(wv.saved, {"saved": False, "path": ""})

    def test_old_pywebview_without_icon_option(self):
        wv = FakeWebview(os.path.join(self.tmp.name, "x.txt"), icon=False)
        self.assertTrue(desktop.run(port=18790, webview_module=wv))
        self.assertEqual(wv.icons, [None])

    def test_window_failure_falls_back_and_cleans_up(self):
        wv = FakeWebview(fail=True)
        self.assertFalse(desktop.run(port=18800, webview_module=wv))
        self.assertTrue(self.closed(wv.url))

    def test_prepare_console_is_noop_outside_windows_exe(self):
        out = sys.stdout
        desktop.prepare_console()
        self.assertIs(sys.stdout, out)

    def test_save_route_refused_in_browser_mode(self):
        from web import server
        httpd, state, url = server.start(port=18810)
        try:
            import threading
            threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
            req = urllib.request.Request(url + "api/desktop/save", method="POST", data=b"{}",
                                         headers={"X-MM-Token": state.token, "Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=5)
            cm.exception.close()
            self.assertEqual(cm.exception.code, 400)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
