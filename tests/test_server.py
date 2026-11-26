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
        server.clean_uploads(cls.state)
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
                           ("/api/contribute", {}), ("/api/falsepositive", {}), ("/api/update/check", {}), ("/api/upload", {}), ("/api/monitor/start", {}), ("/api/monitor/poll", {}), ("/api/monitor/stop", {}), ("/api/community/update", {}), ("/api/community/reset", {}), ("/api/updates/test", {}), ("/api/open-external", {}), ("/api/desktop/save", {}), ("/api/updates/apply", {}), ("/api/report/html", {}), ("/api/compare", {})):
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

    def test_false_positive_report_is_anonymous(self):
        r = self.analyze()
        os.environ.pop("MODMAESTRO_REPO", None)
        rep = self.call("/api/falsepositive", {"analysis": r["id"], "id": "missing:ghost", "note": "Le mod est dans le pack."})
        self.assertIn("missing:ghost", rep["body"])
        self.assertIn("ghost", rep["data"]["mods"])
        self.assertIn("Le mod est dans le pack.", rep["body"])
        self.assertIsNone(rep["url"])  # dépôt non configuré : on copie seulement
        for leak in ("needy.jar", "sodium.jar", self.mods, self.tmp.name, ".jar"):
            self.assertNotIn(leak, rep["body"])
        self.assertEqual(self.analyze()["verdict"], "bad")  # rien n'est ignoré sans la case cochée
        os.environ["MODMAESTRO_REPO"] = "https://github.com/acme/mods"
        try:
            rep = self.call("/api/falsepositive", {"analysis": r["id"], "id": "missing:ghost", "note": "x" * 5000})
            self.assertTrue(rep["url"].startswith("https://github.com/acme/mods/issues/new?title="))
            self.assertIn("x" * 1000, rep["body"])
            self.assertNotIn("x" * 1001, rep["body"])  # note tronquée à 1000 caractères
        finally:
            os.environ.pop("MODMAESTRO_REPO", None)

    def test_false_positive_ids_with_file_names_are_reduced(self):
        r = self.analyze()
        ids = [i["id"] for i in r["issues"] if i["id"].split(":")[0] in ("file", "loader", "nometa")]
        for iid in ids:
            rep = self.call("/api/falsepositive", {"analysis": r["id"], "id": iid})
            self.assertEqual(rep["data"]["rule"], iid.split(":")[0])
            self.assertNotIn(iid.split(":", 1)[1], rep["body"])

    def test_false_positive_unknown_alert_and_optional_ignore(self):
        r = self.analyze()
        self.call("/api/falsepositive", {"analysis": r["id"], "id": "nope:zzz"}, expect=400)
        self.call("/api/falsepositive", {"analysis": "inconnue", "id": "missing:ghost"}, expect=400)
        self.call("/api/falsepositive", {"analysis": r["id"], "id": "missing:ghost", "ignore": True})
        r2 = self.analyze()
        self.assertEqual(r2["verdict"], "ok")
        for rid in r2["ignored_rows"].values():
            self.call("/api/learn/delete", {"id": rid})

    def test_community_update_routes(self):
        from test_communitysync import GOOD_SIDE, SUB, FakeGitHub
        gh = FakeGitHub({f"{SUB}/sides/freshclientmod.json": GOOD_SIDE})
        keys = ("MODMAESTRO_REPO", "MODMAESTRO_GITHUB_API", "MODMAESTRO_RAW_URL")
        old = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["MODMAESTRO_REPO"] = ""
            self.assertFalse(self.call("/api/kb")["sync"]["configured"])
            self.call("/api/community/update", {}, expect=400)
            os.environ.update({"MODMAESTRO_REPO": "https://github.com/acme/mods",
                               "MODMAESTRO_GITHUB_API": gh.url, "MODMAESTRO_RAW_URL": gh.url})
            r = self.call("/api/community/update", {})
            self.assertEqual((r["sides"], r["added_sides"], r["skipped"]), (1, 1, []))
            self.assertEqual(self.call("/api/kb")["sync"]["last"]["sides"], 1)
            self.assertTrue(self.call("/api/community/reset", {})["removed"])
            self.assertIsNone(self.call("/api/kb")["sync"]["last"])
        finally:
            gh.close()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def upload(self, rel, data, session="", token=True, expect=200):
        from urllib.parse import quote
        url = f"http://127.0.0.1:{self.state.port}/api/upload?session={session}&rel={quote(rel)}"
        req = urllib.request.Request(url, data=data, method="POST")
        if token:
            req.add_header("X-MM-Token", self.state.token)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, out = r.status, r.read()
        except urllib.error.HTTPError as exc:
            code, out = exc.code, exc.read()
        self.assertEqual(code, expect, out[:300])
        return json.loads(out)

    def test_drop_folder_upload_then_analyze(self):
        session, root = "", ""
        for name in sorted(os.listdir(self.mods)):
            with open(os.path.join(self.mods, name), "rb") as fh:
                r = self.upload("mods/" + name, fh.read(), session)
            session, root = r["session"], r["root"]
        self.upload("logs/latest.log", b"[main/INFO]: Done", session)
        self.upload("server.properties", b"view-distance=32\n", session)
        self.upload("config/sub/x.toml", b"a=1", session)
        for bad in ("config/x.exe", "config/a/b/c/x.toml", "other.properties"):
            self.upload(bad, b"x", session, expect=400)
        self.assertTrue(os.path.isfile(os.path.join(root, "logs", "latest.log")))
        direct, dropped = self.analyze(), self.analyze(root)
        self.assertEqual(len(dropped["mods"]), len(direct["mods"]))
        self.assertEqual([i["id"] for i in dropped["issues"] if i["category"] == "config"], ["config:view-distance"])
        self.assertEqual([i["id"] for i in dropped["issues"] if i["id"].startswith("missing:")], ["missing:ghost"])
        self.assertEqual(len(os.listdir(self.mods)), 8)  # le dossier d'origine n'a pas bougé

    def test_drop_zip_and_new_drop_replaces_old(self):
        import zipfile
        zpath = os.path.join(self.tmp.name, "pack.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            for name in os.listdir(self.mods):
                zf.write(os.path.join(self.mods, name), "mods/" + name)
        with open(zpath, "rb") as fh:
            first = self.upload("pack.zip", fh.read())
        self.assertEqual(len(self.analyze(first["path"])["mods"]), 8)
        second = self.upload("mods/a.jar", b"PK")
        self.assertNotEqual(first["session"], second["session"])
        self.assertFalse(os.path.exists(first["root"]))   # l'ancien dépôt temporaire est supprimé

    def test_drop_rejects_bad_files(self):
        for rel in ("../evil.jar", "mods/../../evil.jar", "/etc/passwd", "mods/run.exe", "notes.txt", "mods//a.jar",
                    "C:\\x\\a.jar", "logs/other.log", "mods/a/b/c/d.jar"):
            self.upload(rel, b"x", expect=400)
        self.upload("mods/a.jar", b"x", token=False, expect=403)
        self.upload("mods/a.jar", b"x", session="inconnue", expect=400)
        self.assertEqual(self.upload("mods/ok.jar.disabled", b"x")["path"].split(os.sep)[-2:], ["mods", "ok.jar.disabled"])

    def test_logscan_returns_stack_trace_suspects(self):
        r = self.analyze()
        text = "java.lang.IllegalStateException: boom\n\tat TRANSFORMER/needy@1.0/com.n.Foo.tick(Foo.java:3)\n"
        out = self.call("/api/logscan", {"text": text, "analysis": r["id"]})
        self.assertEqual([s["modid"] for s in out["suspects"]], ["needy"])
        self.assertTrue(out["root"].startswith("java.lang.IllegalStateException"))
        self.assertEqual(self.call("/api/logscan", {"text": text})["suspects"], [])   # sans analyse : aucun mod connu

    def test_updates_routes_gate(self):
        r = self.analyze()
        self.call("/api/updates/apply", {"analysis": r["id"], "files": ["m0.jar"]}, expect=400)   # pas testé
        job = self.call("/api/updates/test", {"analysis": r["id"], "files": ["m0.jar"]})["job"]
        self.assertEqual(self.wait(job)["state"], "error")     # hors ligne : aucune mise à jour disponible
        self.call("/api/updates/apply", {"analysis": r["id"], "files": ["m0.jar"]}, expect=400)

    def test_open_external_only_opens_plain_https(self):
        opened = []
        real = server.webbrowser.open
        server.webbrowser.open = lambda url: opened.append(url) or True
        try:
            self.assertTrue(self.call("/api/open-external", {"url": "https://github.com/acme/mods/releases"})["opened"])
            for bad in ("http://github.com", "javascript:alert(1)", "file:///etc/passwd", "https://a@evil.test/", "https:///x",
                        "https://github.com/a b", "", "https://x.test/" + "a" * 2100):
                self.call("/api/open-external", {"url": bad}, expect=400)
        finally:
            server.webbrowser.open = real
        self.assertEqual(opened, ["https://github.com/acme/mods/releases"])

    def test_update_check_offers_the_asset_for_this_system(self):
        from core import updatecheck
        from test_communitysync import FakeGitHub
        gh = FakeGitHub({})
        base = "https://github.com/acme/mods/releases/download/v99.0.0/"
        gh.release = {"tag_name": "v99.0.0", "assets": [
            {"name": "ModMaestro-Windows-x64.zip", "browser_download_url": base + "ModMaestro-Windows-x64.zip", "size": 1234},
            {"name": "ModMaestro-Linux-x64.tar.gz", "browser_download_url": "https://evil.test/ModMaestro-Linux-x64.tar.gz", "size": 1},
            {"name": "ModMaestro-macOS-arm64.zip", "browser_download_url": base + "ModMaestro-macOS-arm64.zip"}, "bizarre"]}
        old = {k: os.environ.get(k) for k in ("MODMAESTRO_REPO", "MODMAESTRO_GITHUB_API")}
        real = updatecheck._platform
        try:
            os.environ.update({"MODMAESTRO_REPO": "https://github.com/acme/mods", "MODMAESTRO_GITHUB_API": gh.url})
            updatecheck._platform = lambda: "win32"
            self.assertEqual(self.call("/api/update/check", {})["asset"],
                             {"name": "ModMaestro-Windows-x64.zip", "url": base + "ModMaestro-Windows-x64.zip", "size": 1234})
            updatecheck._platform = lambda: "darwin"
            self.assertEqual(self.call("/api/update/check", {})["asset"]["size"], 0)
            updatecheck._platform = lambda: "linux"
            self.assertIsNone(self.call("/api/update/check", {})["asset"])        # hôte inattendu : pas de lien direct
        finally:
            updatecheck._platform = real
            gh.close()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_monitor_routes(self):
        r = self.analyze()
        logs = os.path.join(self.tmp.name, "srv", "logs")
        os.makedirs(logs)
        log = os.path.join(logs, "latest.log")
        with open(log, "w") as fh:
            fh.write("")
        first = self.call("/api/monitor/start", {"analysis": r["id"], "path": os.path.dirname(logs)})
        self.assertEqual((first["status"], first["alerts"]), ("active", []))
        with open(log, "a") as fh:
            fh.write("[12:00:00] [Server thread/ERROR] [needy/]: Failed to tick\n" * 5)
        self.call("/api/monitor/poll", {"id": first["id"]})
        snap = self.call("/api/monitor/poll", {"id": first["id"]})
        self.assertEqual([a["id"] for a in snap["alerts"]], ["mod:needy"])
        self.assertIn("needy", snap["mods"])
        self.assertTrue(self.call("/api/monitor/stop", {"id": first["id"]})["stopped"])
        self.call("/api/monitor/poll", {"id": first["id"]}, expect=400)
        self.call("/api/monitor/start", {"path": os.path.join(self.tmp.name, "absent")}, expect=400)
        self.call("/api/monitor/start", {}, expect=400)
        for _ in range(6):                                   # au plus 4 surveillances à la fois
            last = self.call("/api/monitor/start", {"path": log})
        self.assertEqual(len(self.state.monitors), 4)
        self.call("/api/monitor/stop", {"id": last["id"]})

    def test_update_check_route(self):
        from core import __version__
        from test_communitysync import FakeGitHub
        gh = FakeGitHub({})
        keys = ("MODMAESTRO_REPO", "MODMAESTRO_GITHUB_API")
        old = {k: os.environ.get(k) for k in keys}
        try:
            os.environ["MODMAESTRO_REPO"] = ""
            self.call("/api/update/check", {}, expect=400)
            os.environ.update({"MODMAESTRO_REPO": "https://github.com/acme/mods", "MODMAESTRO_GITHUB_API": gh.url})
            for tag, newer in (("v99.0.0", True), ("v" + __version__, False), ("v0.0.1", False)):
                gh.release = {"tag_name": tag, "body": "Notes"}
                r = self.call("/api/update/check", {})
                self.assertEqual((r["newer"], r["latest"]), (newer, tag[1:]))
            self.assertEqual(self.call("/api/update/check", {})["url"], "https://github.com/acme/mods/releases/tag/v0.0.1")
            gh.release = {"tag_name": "../../evil"}
            self.call("/api/update/check", {}, expect=400)
            gh.release = None   # 404 : aucune Release
            self.assertIsNone(self.call("/api/update/check", {})["latest"])
        finally:
            gh.close()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_recommend_route(self):
        r = self.analyze()
        res = self.call("/api/recommend", {"analysis": r["id"]})
        self.assertFalse(res["verified"])
        self.assertTrue(res["note"])


if __name__ == "__main__":
    unittest.main()
