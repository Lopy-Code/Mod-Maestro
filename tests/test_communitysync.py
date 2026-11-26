"""Mise à jour de la base communautaire : faux GitHub local, aucune connexion réelle."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import cache, communitysync, knowledge  # noqa: E402

SUB = "core/data/community"
GOOD_SIDE = {"modid": "freshclientmod", "side": "client", "reason": "Mod de caméra."}
GOOD_CONFLICT = {"group": ["modzz", "modyy"], "severity": "warning", "title": "Deux mods", "message": "Ils se gênent."}
# déjà dans la base fournie : ne doit pas être compté deux fois
with open(os.path.join(knowledge.builtin_dir(), "sides", "betterthirdperson.json"), encoding="utf-8") as _fh:
    BUILTIN_SIDE = json.load(_fh)


class FakeGitHub:
    def __init__(self, files, tree_status=200):
        self.files, self.tree_status, self.calls, self.release = files, tree_status, [], None
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                outer.calls.append(self.path)
                if self.path.endswith("/releases/latest"):
                    if outer.release is None:
                        return self._send(404, b"{}")
                    return self._send(200, json.dumps(outer.release).encode())
                if "/git/trees/" in self.path:
                    if outer.tree_status != 200:
                        return self._send(outer.tree_status, b"{}")
                    tree = [{"path": p, "type": "blob"} for p in outer.files]
                    return self._send(200, json.dumps({"tree": tree}).encode())
                i = self.path.find(SUB)
                body = outer.files.get(self.path[i:].split("?")[0]) if i >= 0 else None
                if body is None:
                    return self._send(404, b"no")
                self._send(200, body if isinstance(body, bytes) else json.dumps(body).encode())

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("MODMAESTRO_HOME", "MODMAESTRO_REPO")}
        os.environ["MODMAESTRO_HOME"] = self.tmp.name
        os.environ["MODMAESTRO_REPO"] = "https://github.com/acme/mods"
        cache.reset_default()
        self.files = {
            f"{SUB}/sides/freshclientmod.json": GOOD_SIDE,
            f"{SUB}/sides/betterthirdperson.json": BUILTIN_SIDE,
            f"{SUB}/conflicts/modzz__modyy.json": GOOD_CONFLICT,
            f"{SUB}/sides/broken.json": {"modid": "x", "side": "nope"},          # invalide
            f"{SUB}/sides/garbage.json": b"{pas du json",                         # illisible
            f"{SUB}/sides/huge.json": b"{" + b" " * 70000 + b"}",                 # trop gros
            f"{SUB}/sides/EVIL NAME.json": GOOD_SIDE,                             # nom refusé
            f"{SUB}/sides/../evil.json": GOOD_SIDE,                               # sortie de dossier
            f"{SUB}/other/readme.json": GOOD_SIDE,                                # mauvais dossier
            "core/analyzer.py": b"print('pas de code')",                          # jamais téléchargé
        }
        self.gh = FakeGitHub(self.files)

    def tearDown(self):
        self.gh.close()
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        cache.reset_default()
        self.tmp.cleanup()

    def run_update(self):
        return communitysync.update(api=self.gh.url, raw=self.gh.url)

    def test_downloads_only_valid_data_files(self):
        r = self.run_update()
        self.assertEqual((r["sides"], r["conflicts"]), (2, 1))
        self.assertEqual(sorted(r["skipped"]), ["broken.json", "garbage.json", "huge.json"])
        got = sorted(os.listdir(os.path.join(communitysync.sync_dir(), "sides")))
        self.assertEqual(got, ["betterthirdperson.json", "freshclientmod.json"])
        self.assertFalse([c for c in self.gh.calls if "analyzer.py" in c or "evil" in c or "EVIL" in c])
        # tout reste dans le dossier ModMaestro
        self.assertTrue(communitysync.sync_dir().startswith(self.tmp.name))

    def test_kb_uses_update_without_duplicates(self):
        base = knowledge.load_all(None)["_stats"]
        self.run_update()
        st = knowledge.load_all(None)["_stats"]
        self.assertEqual(st["community_sides"], base["community_sides"] + 1)       # betterthirdperson déjà connu
        self.assertEqual(st["community_conflicts"], base["community_conflicts"] + 1)
        self.assertEqual(st["errors"], [])

    def test_second_update_replaces_and_reset_removes(self):
        self.run_update()
        del self.files[f"{SUB}/sides/freshclientmod.json"]
        self.gh.files = self.files
        r = self.run_update()
        self.assertEqual(r["sides"], 1)
        self.assertEqual(communitysync.status()["last"]["sides"], 1)
        self.assertTrue(communitysync.reset())
        self.assertIsNone(communitysync.status()["last"])
        self.assertFalse(communitysync.reset())

    def test_errors_keep_previous_data(self):
        self.run_update()
        self.gh.tree_status = 404
        with self.assertRaises(ValueError):
            self.run_update()
        self.assertEqual(communitysync.status()["last"]["sides"], 2)
        self.gh.tree_status = 403
        with self.assertRaises(ValueError) as cm:
            self.run_update()
        self.assertIn("limite", str(cm.exception))

    def test_unreachable_and_unconfigured(self):
        with self.assertRaises(ValueError):
            communitysync.update(api="http://127.0.0.1:9", raw="http://127.0.0.1:9")
        os.environ["MODMAESTRO_REPO"] = ""
        self.assertFalse(communitysync.status()["configured"])
        with self.assertRaises(ValueError):
            self.run_update()
        os.environ["MODMAESTRO_REPO"] = "https://example.com/acme/mods"   # seul GitHub est accepté
        with self.assertRaises(ValueError):
            self.run_update()


if __name__ == "__main__":
    unittest.main()
