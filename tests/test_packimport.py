"""Import d'un .mrpack / zip CurseForge : faux hébergeur local, aucune connexion réelle."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import packimport, parser  # noqa: E402
from test_core import neo  # noqa: E402


class Host:
    def __init__(self, files):
        self.files, self.hits = files, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                outer.hits.append(self.path)
                body = outer.files.get(self.path)
                self.send_response(200 if body is not None else 404)
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def jar_bytes(d, name, modid):
    neo(d, name, modid)
    with open(os.path.join(d, name), "rb") as fh:
        return fh.read()


class PackTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.old_allowed, self.old_max = packimport._allowed, packimport.MAX_JAR
        packimport._allowed = lambda url: url.startswith("http://127.0.0.1")   # le faux hébergeur
        src = os.path.join(self.d.name, "src")
        os.makedirs(src)
        self.a, self.b = jar_bytes(src, "a.jar", "alpha"), jar_bytes(src, "b.jar", "beta")
        self.host = Host({"/a.jar": self.a, "/b.jar": self.b + b"corrompu"})

    def tearDown(self):
        packimport._allowed, packimport.MAX_JAR = self.old_allowed, self.old_max
        self.host.close()
        self.d.cleanup()

    def pack(self, files, name="p.mrpack", extra=None):
        path = os.path.join(self.d.name, name)
        idx = {"formatVersion": 1, "game": "minecraft", "name": "Mon pack", "dependencies": {"minecraft": "1.21.1", "neoforge": "21.1.0"}, "files": files}
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("modrinth.index.json", json.dumps(idx))
            for k, v in (extra or {}).items():
                zf.writestr(k, v)
        return path

    def entry(self, name, data, url=None):
        return {"path": f"mods/{name}", "hashes": {"sha1": hashlib.sha1(data).hexdigest(), "sha512": hashlib.sha512(data).hexdigest()},
                "downloads": [url or f"{self.host.url}/{name}"], "fileSize": len(data)}

    def test_offline_refuses_to_download(self):
        path = self.pack([self.entry("a.jar", self.a)])
        with self.assertRaises(ValueError) as cm:
            parser.resolve_source(path, online=False)
        self.assertIn("Modrinth", str(cm.exception))
        self.assertEqual(self.host.hits, [])

    def test_online_downloads_verifies_and_skips_bad(self):
        path = self.pack([self.entry("a.jar", self.a), self.entry("b.jar", self.b),   # b : empreinte fausse sur l'hébergeur
                          self.entry("c.jar", b"x"), self.entry("d.jar", b"x", url="https://evil.example/d.jar")],
                         extra={"overrides/mods/own.jar": jar_bytes(self.d.name, "own.jar", "own"), "overrides/config/x.toml": "a=1"})
        seen = []
        folder, notes = parser.resolve_source(path, online=True, progress=lambda s, d, t: seen.append((s, d, t)))
        self.assertEqual(sorted(os.listdir(folder)), ["a.jar", "own.jar"])
        self.assertTrue(any("Mon pack" in n and "1.21.1" in n and "NeoForge" in n for n in notes))
        self.assertTrue(any("3 mods n'ont pas pu" in n for n in notes))
        self.assertEqual(seen[-1], ("download", 4, 4))
        self.assertFalse([h for h in self.host.hits if "evil" in h or "d.jar" in h])   # hébergeur non autorisé : jamais appelé

    def test_size_limits(self):
        packimport.MAX_JAR = 10
        path = self.pack([], extra={"overrides/mods/big.jar": b"x" * 100})
        with self.assertRaises(ValueError):
            parser.resolve_source(path)

    def test_curseforge_zip(self):
        man = {"minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.2.0", "primary": True}]}, "manifestType": "minecraftModpack",
               "name": "CF pack", "files": [{"projectID": 1, "fileID": 2}, {"projectID": 3, "fileID": 4}]}
        path = os.path.join(self.d.name, "cf.zip")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(man))
            zf.writestr("overrides/mods/own.jar", jar_bytes(self.d.name, "own.jar", "own"))
        folder, notes = parser.resolve_source(path)
        self.assertEqual(os.listdir(folder), ["own.jar"])
        self.assertTrue(any("CF pack" in n and "Forge" in n for n in notes))
        self.assertTrue(any("2 mods listés par CurseForge" in n for n in notes))
        only = os.path.join(self.d.name, "only.zip")
        with zipfile.ZipFile(only, "w") as zf:
            zf.writestr("manifest.json", json.dumps(man))
        with self.assertRaises(ValueError) as cm:
            parser.resolve_source(only)
        self.assertIn("manifest", str(cm.exception))

    def test_corrupt_inputs(self):
        bad = os.path.join(self.d.name, "bad.mrpack")
        with open(bad, "wb") as fh:
            fh.write(b"pas un zip")
        with self.assertRaises(ValueError):
            parser.resolve_source(bad)
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("modrinth.index.json", "[1, 2")
        with self.assertRaises(ValueError):
            parser.resolve_source(bad)

    def test_temp_folders_are_registered_for_cleanup(self):
        path = self.pack([], extra={"overrides/mods/own.jar": jar_bytes(self.d.name, "own.jar", "own")})
        folder, _ = parser.resolve_source(path)
        self.assertIn(folder, parser._TEMP_DIRS)


if __name__ == "__main__":
    unittest.main()
