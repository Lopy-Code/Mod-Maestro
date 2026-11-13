"""Tests HTTP des routes de l'interface (serveur réel sur un port libre, jeton obligatoire)."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import i18n  # noqa: E402
from test_core import neo  # noqa: E402
from web import server  # noqa: E402


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.TemporaryDirectory()
        os.environ["MODMAESTRO_HOME"] = cls.home.name
        from core import cache
        cache.reset_default()
        cls.state = server.State()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cls.state))
        cls.state.port = cls.httpd.server_address[1]
        threading.Thread(target=lambda: cls.httpd.serve_forever(poll_interval=0.01), daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        from core import cache
        cache.reset_default()
        os.environ.pop("MODMAESTRO_HOME", None)
        cls.home.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mods = os.path.join(self.tmp.name, "mods")
        os.makedirs(self.mods)
        for i in range(6):
            neo(self.mods, f"m{i}.jar", f"m{i}")
        neo(self.mods, "needy.jar", "needy", deps=[("ghost", "required", "*")])
        neo(self.mods, "sodium.jar", "sodium")

    def tearDown(self):
        self.tmp.cleanup()
        i18n.set_lang("fr")

    def call(self, path, body=None, token=True, expect=200):
        url = f"http://127.0.0.1:{self.state.port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
        if token:
            req.add_header("X-MM-Token", self.state.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, out = r.status, r.read()
        except urllib.error.HTTPError as exc:
            code, out = exc.code, exc.read()
        self.assertEqual(code, expect, out[:300])
        return json.loads(out)

    def analyze(self, path=None, **kw):
        job = self.call("/api/analyze", {"path": path or self.mods, **kw})["job"]
        for _ in range(200):
            j = self.call(f"/api/job/{job}")
            if j["state"] != "running":
                self.assertEqual(j["state"], "done", j.get("error"))
                return j["result"]
            time.sleep(0.02)
        self.fail("tâche trop longue")

    def wait(self, job):
        for _ in range(300):
            j = self.call(f"/api/job/{job}")
            if j["state"] != "running":
                return j
            time.sleep(0.02)
        self.fail("tâche trop longue")

    def test_token_is_required_everywhere(self):
        for path, body in (("/api/crash/start", {}), ("/api/export/zip", {}), ("/api/serverkit", {}), ("/api/ignore", {}),
                           ("/api/contribute", {}), ("/api/report/html", {}), ("/api/compare", {})):
            self.call(path, body, token=False, expect=403)

    def test_analysis_result_carries_defaults_and_ignored_rows(self):
        r = self.analyze()
        self.assertIn("mrpack", r["suggested"])
        self.assertEqual(r["server_defaults"]["java"], 21)
        self.assertEqual(r["ignored_rows"], {})
        self.assertEqual(r["verdict"], "bad")

    def test_ignore_then_restore(self):
        r = self.analyze()
        self.call("/api/ignore", {"id": "missing:ghost"})
        r2 = self.analyze()
        self.assertEqual((r2["verdict"], r2["counts"]["ignored"]), ("ok", 1))
        row = r2["ignored_rows"]["missing:ghost"]
        self.call("/api/learn/delete", {"id": row})
        self.assertEqual(self.analyze()["verdict"], "bad")
        self.call("/api/ignore", {"all": True, "analysis": r["id"]})  # « ce pack fonctionne »
        self.assertEqual(self.analyze()["verdict"], "ok")
        for rid in self.analyze()["ignored_rows"].values():
            self.call("/api/learn/delete", {"id": rid})

    def test_language_is_applied_per_request(self):
        fr = self.analyze()
        en = self.analyze(lang="en")
        self.assertEqual(fr["id"] != en["id"], True)
        self.assertEqual(self.call("/api/recommend", {"analysis": en["id"], "lang": "en"})["items"][0]["name"],
                         self.call("/api/recommend", {"analysis": fr["id"], "lang": "fr"})["items"][0]["name"])

    def test_compare_job(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other)
        neo(other, "m0.jar", "m0", "2.0")
        job = self.call("/api/compare", {"a": self.mods, "b": other})["job"]
        res = self.wait(job)["result"]
        self.assertEqual([m["modid"] for m in res["updated"]], ["m0"])
        self.assertEqual(len(res["removed"]), 7)

    def test_crash_session_end_to_end(self):
        r = self.analyze()
        st = self.call("/api/crash/start", {"analysis": r["id"], "log_mods": ["needy"]})
        self.assertEqual(st["hint"][0]["file"], "needy.jar")
        out = os.path.join(self.tmp.name, "t1")
        self.call("/api/crash/folder", {"analysis": r["id"], "id": st["id"], "output": out})
        self.assertTrue(os.listdir(out))
        guard = 0
        while not st["done"]:
            guard += 1
            self.assertLess(guard, 12)
            st = self.call("/api/crash/answer", {"analysis": r["id"], "id": st["id"], "outcome": "fine"})
        self.assertIn("summary", st)
        self.call("/api/crash/answer", {"analysis": r["id"], "id": "inconnu", "outcome": "fine"}, expect=400)

    def test_exports_and_server_kit(self):
        r = self.analyze()
        z = self.call("/api/export/zip", {"analysis": r["id"], "output": os.path.join(self.tmp.name, "all"), "server_only": True})
        with zipfile.ZipFile(z["path"]) as zf:
            self.assertNotIn("mods/sodium.jar", zf.namelist())
            self.assertIn("mods/needy.jar", zf.namelist())
        m = self.call("/api/export/mrpack", {"analysis": r["id"], "output": os.path.join(self.tmp.name, "p"), "name": "P",
                                             "loader_version": "21.1.1", "mc": "1.21.1", "loader": "neoforge"})
        self.assertTrue(m["path"].endswith(".mrpack"))
        self.call("/api/export/mrpack", {"analysis": r["id"], "output": os.path.join(self.tmp.name, "q"), "name": "P"}, expect=400)
        k = self.call("/api/serverkit", {"analysis": r["id"], "output": os.path.join(self.tmp.name, "srv"), "with_mods": True,
                                         "eula": True, "ram_gb": 4})
        self.assertEqual((k["ram"], "start.sh" in k["written"]), (4, True))
        self.call("/api/serverkit", {"analysis": r["id"], "output": os.path.join(self.tmp.name, "srv2"), "port": 99999}, expect=400)

    def test_html_report_and_contribute(self):
        r = self.analyze()
        h = self.call("/api/report/html", {"analysis": r["id"], "files": False})
        self.assertTrue(h["html"].startswith("<!doctype html>"))
        self.assertNotIn("needy.jar", h["html"])
        self.call("/api/contribute", {}, expect=400)  # base vide
        self.call("/api/learn", {"kind": "conflict", "a": "x1", "b": "x2", "note": "n"})
        c = self.call("/api/contribute", {"analysis": r["id"]})
        self.assertEqual(c["count"], 1)
        for row in self.call("/api/kb")["learned"]:
            self.call("/api/learn/delete", {"id": row["id"]})

    def test_recommend_route(self):
        r = self.analyze()
        res = self.call("/api/recommend", {"analysis": r["id"]})
        self.assertFalse(res["verified"])
        self.assertTrue(res["note"])


if __name__ == "__main__":
    unittest.main()
