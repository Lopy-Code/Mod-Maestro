"""Tests de l'intégration Modrinth, avec un FAUX serveur Modrinth local (aucun accès réseau réel)."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import modrinth, pipeline  # noqa: E402
from core.cache import Cache  # noqa: E402
from test_core import neo  # noqa: E402


def ver(vid, pid, number, date="2024-01-01T00:00:00Z", vtype="release", gv=("1.21.1",), deps=(), loaders=("neoforge",),
        file_hash=None):
    f = {"filename": f"{vid}.jar", "url": f"https://cdn.modrinth.com/data/{pid}/versions/{vid}/{vid}.jar", "size": 1,
         "hashes": {"sha1": file_hash or "0" * 40, "sha512": "0" * 128}}
    return {"id": vid, "project_id": pid, "version_number": number, "version_type": vtype,
            "date_published": date, "game_versions": list(gv), "loaders": list(loaders),
            "dependencies": [{"project_id": p, "version_id": None, "dependency_type": t} for p, t in deps],
            "files": [f]}


def proj(pid, slug, title, cs="required", ss="required"):
    return {"id": pid, "slug": slug, "title": title, "client_side": cs, "server_side": ss, "project_type": "mod"}


class FakeModrinth:
    """Imite les trois routes utilisées : /version_files, /projects, /version_files/update."""

    def __init__(self):
        self.versions, self.projects, self.latest = {}, {}, {}
        self.by_slug: dict = {}  # slug -> liste de versions (route /project/<slug>/version)
        self.calls: list[str] = []
        self.agents: list[str] = []
        self.fail: list[int] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj, headers=None):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, body):
                path = urlparse(self.path).path
                outer.calls.append(path)
                outer.agents.append(self.headers.get("User-Agent", ""))
                if outer.fail:
                    code = outer.fail.pop(0)
                    return self._reply(code, {"error": "x"}, {"Retry-After": "0"} if code == 429 else None)
                if path == "/version_files":
                    return self._reply(200, {h: outer.versions[h] for h in body["hashes"] if h in outer.versions})
                if path == "/version_files/update":
                    return self._reply(200, {h: outer.latest[h] for h in body["hashes"] if h in outer.latest})
                if path == "/projects":
                    ids = json.loads(parse_qs(urlparse(self.path).query)["ids"][0])
                    return self._reply(200, [outer.projects[i] for i in ids if i in outer.projects])
                if path.startswith("/project/") and path.endswith("/version"):
                    slug = path.split("/")[2]
                    q = parse_qs(urlparse(self.path).query)
                    loaders = json.loads(q.get("loaders", ["[]"])[0])
                    gvs = json.loads(q.get("game_versions", ["[]"])[0])
                    rows = [v for v in outer.by_slug.get(slug, [])
                            if (not loaders or set(loaders) & set(v["loaders"])) and (not gvs or set(gvs) & set(v["game_versions"]))]
                    return self._reply(200, rows)
                return self._reply(404, {})

            def do_GET(self):
                self._handle({})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._handle(json.loads(self.rfile.read(n) or b"{}"))

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True).start()

    def client(self, sleeps=None):
        return modrinth.Modrinth(base_url=self.url, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class OnlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._home = tempfile.TemporaryDirectory()
        os.environ["MODMAESTRO_HOME"] = cls._home.name

    @classmethod
    def tearDownClass(cls):
        cls._home.cleanup()
        os.environ.pop("MODMAESTRO_HOME", None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.fake = FakeModrinth()
        self.cache = Cache(":memory:")

        def jar(fname, modid, deps=(), name=None):
            neo(self.d, fname, modid, deps=deps, name=name)
            return modrinth.sha1_file(os.path.join(self.d, fname))

        h = {}
        h["sod"] = jar("sod.jar", "sodiumx")
        h["map"] = jar("minimap.jar", "minimapper", name="Minimapper")
        h["a"] = jar("a.jar", "modaa")
        h["b"] = jar("b.jar", "modbb")
        h["c"] = jar("c.jar", "modcc")
        h["e"] = jar("e.jar", "modee")
        h["l"] = jar("locallib.jar", "locallib")
        h["g"] = jar("g.jar", "modgg")
        h["h"] = jar("h.jar", "modhh")
        h["i"] = jar("i.jar", "modii")
        h["x"] = jar("x.jar", "modxx", deps=[("modyy", "incompatible", "*")])
        h["y"] = jar("y.jar", "modyy")
        jar("mystery.jar", "mystery")  # inconnu de Modrinth
        self.h = h

        V, P = self.fake.versions, self.fake.projects
        V[h["sod"]] = ver("v-sod", "P-sod", "1.0")
        P["P-sod"] = proj("P-sod", "sodiumx", "Sodium X", cs="required", ss="unsupported")
        V[h["map"]] = ver("v-map", "P-map", "1.0")
        P["P-map"] = proj("P-map", "minimapper", "Minimapper", cs="required", ss="optional")
        V[h["a"]] = ver("v-a", "P-a", "1.0", deps=[("P-b", "incompatible")])
        V[h["b"]] = ver("v-b", "P-b", "1.0")
        P["P-a"], P["P-b"] = proj("P-a", "modaa", "Mod A"), proj("P-b", "modbb", "Mod B")
        V[h["c"]] = ver("v-c", "P-c", "1.0", deps=[("P-d", "required"), ("P-emb", "embedded")])
        P["P-c"], P["P-d"] = proj("P-c", "modcc", "Mod C"), proj("P-d", "somelib", "Some Lib")
        V[h["e"]] = ver("v-e", "P-e", "1.0", deps=[("P-l", "required")])
        V[h["l"]] = ver("v-l", "P-l", "1.0")
        P["P-e"], P["P-l"] = proj("P-e", "modee", "Mod E"), proj("P-l", "locallib", "Local Lib")
        V[h["g"]] = ver("v-g1", "P-g", "1.0", date="2024-01-01T00:00:00Z")
        V[h["h"]] = ver("v-h1", "P-h", "1.0", date="2024-01-01T00:00:00Z")
        V[h["i"]] = ver("v-i1", "P-i", "1.0", date="2024-01-01T00:00:00Z")
        for k, pid in (("g", "P-g"), ("h", "P-h"), ("i", "P-i")):
            P[pid] = proj(pid, f"mod{k}{k}", f"Mod {k.upper()}")
        self.fake.latest[h["g"]] = ver("v-g2", "P-g", "1.2", date="2024-06-01T00:00:00Z")
        self.fake.latest[h["h"]] = ver("v-h2", "P-h", "2.0-beta", date="2024-06-01T00:00:00Z", vtype="beta")
        self.fake.latest[h["i"]] = ver("v-i1", "P-i", "1.0", date="2024-01-01T00:00:00Z")
        V[h["x"]] = ver("v-x", "P-x", "1.0", deps=[("P-y", "incompatible")])
        V[h["y"]] = ver("v-y", "P-y", "1.0")
        P["P-x"], P["P-y"] = proj("P-x", "modxx", "Mod X"), proj("P-y", "modyy", "Mod Y")

    def tearDown(self):
        self.fake.close()
        self.tmp.cleanup()
        self.cache.close()

    def run_pack(self, **kw):
        return pipeline.run_analysis(self.d, online=True, cache=self.cache, client=kw.get("client") or self.fake.client())

    def ids(self, a, prefix):
        return [i for i in a.issues if i["id"].startswith(prefix)]

    # -- reconnaissance ---------------------------------------------------------------------------
    def test_identification_and_stats(self):
        a = self.run_pack()
        o = a.online
        self.assertTrue(o["enabled"])
        self.assertEqual(o["total"], 13)
        self.assertEqual(o["identified"], 12)
        self.assertEqual(o["unknown"], 1)
        self.assertIsNone(o["error"])
        self.assertEqual(a.entries["a.jar"]["online"]["title"], "Mod A")
        self.assertTrue(a.entries["a.jar"]["online"]["url"].endswith("/project/modaa"))

    def test_only_hashes_are_sent(self):
        self.run_pack()
        self.assertTrue(all(ua.startswith("ModMaestro/") for ua in self.fake.agents))

    # -- côté client / serveur -------------------------------------------------------------------------
    def test_modrinth_marks_server_unsupported_as_client(self):
        a = self.run_pack()
        e = a.entries["sod.jar"]
        self.assertEqual((e["side"]["value"], e["side"]["confidence"]), ("client", "modrinth"))
        self.assertEqual(e["server"]["action"], "remove")
        self.assertIn("sod.jar", [r["file"] for r in a.to_dict()["plan"]["remove"]])

    def test_modrinth_clears_keyword_guess(self):
        # « minimap » dans le nom => « à vérifier » hors ligne ; Modrinth dit que le serveur est géré => on garde
        offline = pipeline.run_analysis(self.d, online=False, cache=self.cache)
        self.assertEqual(offline.entries["minimap.jar"]["side"]["value"], "unsure")
        online = self.run_pack()
        self.assertEqual(online.entries["minimap.jar"]["side"]["value"], "both")
        self.assertNotIn("minimap.jar", [u["file"] for u in online.to_dict()["plan"]["unsure"]])

    # -- incompatibilités ---------------------------------------------------------------------------------
    def test_incompatibility_from_modrinth(self):
        a = self.run_pack()
        (i,) = self.ids(a, "mr-incompat:P-a")
        self.assertEqual(i["severity"], "error")
        self.assertEqual(sorted(i["files"]), ["a.jar", "b.jar"])
        self.assertEqual(i["data"]["source"], "modrinth")

    def test_incompatibility_not_duplicated_when_already_declared_locally(self):
        a = self.run_pack()
        involving = [i for i in a.issues if i["category"] == "compat" and set(i["files"]) == {"x.jar", "y.jar"}]
        self.assertEqual(len(involving), 1)

    # -- dépendances ---------------------------------------------------------------------------------------------
    def test_missing_dependency_from_modrinth(self):
        a = self.run_pack()
        (i,) = self.ids(a, "mr-missing:")
        self.assertEqual(i["severity"], "warning")
        self.assertIn("Some Lib", i["title"])
        self.assertEqual(i["links"][0]["url"], "https://modrinth.com/project/somelib")
        self.assertEqual(i["files"], ["c.jar"])  # « embedded » ignoré, dépendance déjà installée ignorée

    # -- mises à jour -----------------------------------------------------------------------------------------------
    def test_updates(self):
        a = self.run_pack()
        (u,) = self.ids(a, "updates")
        self.assertEqual(u["severity"], "info")
        self.assertEqual([x["file"] for x in u["data"]["updates"]], ["g.jar"])  # pas la bêta, pas la même version
        self.assertEqual(u["data"]["updates"][0]["latest"], "1.2")
        self.assertEqual(a.online["updates"], 1)

    # -- cache ----------------------------------------------------------------------------------------------------------
    def test_second_run_uses_cache_only(self):
        self.run_pack()
        n = len(self.fake.calls)
        self.assertGreater(n, 0)
        a = self.run_pack()
        self.assertEqual(len(self.fake.calls), n)  # y compris pour le fichier inconnu (cache négatif)
        self.assertEqual(a.online["queried"], 0)
        self.assertEqual(a.online["from_cache"], 13)
        self.assertEqual(len(self.ids(a, "updates")), 1)

    def test_cache_ttl(self):
        now = [1000.0]
        c = Cache(":memory:", clock=lambda: now[0])
        c.put_files({"aa": {"id": "v"}, "bb": None})
        self.assertEqual(c.get_files(["aa", "bb"]), {"aa": {"id": "v"}, "bb": None})
        now[0] += 2 * 86400
        self.assertEqual(c.get_files(["aa", "bb"]), {"aa": {"id": "v"}})  # l'inconnu expire après 1 jour
        now[0] += 6 * 86400
        self.assertEqual(c.get_files(["aa", "bb"]), {})
        c.close()

    def test_clear_online_keeps_learned(self):
        self.run_pack()
        self.cache.add_learned("side", "foo", side="client")
        self.cache.clear_online()
        st = self.cache.stats()
        self.assertEqual((st["files"], st["projects"], st["learned"]), (0, 0, 1))

    # -- pannes ----------------------------------------------------------------------------------------------------------
    def test_rate_limit_is_retried(self):
        sleeps = []
        self.fake.fail = [429]
        a = self.run_pack(client=self.fake.client(sleeps))
        self.assertEqual(a.online["identified"], 12)
        self.assertEqual(sleeps, [0.0])

    def test_server_error_falls_back_to_offline(self):
        self.fake.fail = [500] * 30
        a = self.run_pack()
        self.assertEqual(a.online["identified"], 0)
        self.assertIn("erreur 500", a.online["error"])
        self.assertTrue(any("erreur 500" in n for n in a.notes))
        self.assertGreaterEqual(len(a.issues), 1)  # l'audit local est bien produit
        self.assertEqual(self.ids(a, "mr-"), [])

    def test_unreachable_network(self):
        self.fake.close()
        client = modrinth.Modrinth(base_url=self.fake.url, sleep=lambda s: None)
        a = pipeline.run_analysis(self.d, online=True, cache=self.cache, client=client)
        self.assertIn("injoignable", a.online["error"])
        self.fake = FakeModrinth()  # pour tearDown

    def test_corrupt_response(self):
        self.fake.versions = {}
        orig = self.fake.client()
        orig._request = lambda *a, **k: (_ for _ in ()).throw(modrinth.ModrinthError("Réponse inattendue de Modrinth."))
        a = pipeline.run_analysis(self.d, online=True, cache=self.cache, client=orig)
        self.assertIn("inattendue", a.online["error"])

    def test_offline_is_default_and_makes_no_request(self):
        pipeline.run_analysis(self.d, online=False, cache=self.cache, client=self.fake.client())
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()
