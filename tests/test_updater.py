"""Mise à jour des mods : faux Modrinth + faux hébergeur de fichiers, aucune connexion réelle."""
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import cache as cache_mod, packimport, parser, pipeline, updater  # noqa: E402
from core.cache import Cache  # noqa: E402
from test_core import neo  # noqa: E402
from test_online import FakeModrinth, proj, ver  # noqa: E402
from test_packimport import Host  # noqa: E402


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("MODMAESTRO_HOME")
        os.environ["MODMAESTRO_HOME"] = os.path.join(self.tmp.name, "home")
        cache_mod.reset_default()
        self.mods = os.path.join(self.tmp.name, "mods")
        os.makedirs(self.mods)
        self.old_allowed = packimport._allowed
        packimport._allowed = lambda url: url.startswith("http://127.0.0.1")
        new = os.path.join(self.tmp.name, "new")
        os.makedirs(new)
        neo(self.mods, "g.jar", "modgg", version="1.0.0")
        neo(self.mods, "h.jar", "modhh", version="1.0.0")
        neo(self.mods, "keep.jar", "modkk")
        neo(new, "g2.jar", "modgg", version="2.0.0", deps=[("newlib", "required", "*")])   # exige une bibliothèque absente
        neo(new, "h2.jar", "modhh", version="2.0.0")
        self.bytes = {n: read(os.path.join(new, n)) for n in ("g2.jar", "h2.jar")}
        self.host = Host({f"/{n}": b for n, b in self.bytes.items()})
        self.fake = FakeModrinth()
        for k, pid in (("g", "P-g"), ("h", "P-h"), ("keep", "P-k")):
            fname = {"g": "g.jar", "h": "h.jar", "keep": "keep.jar"}[k]
            h = _sha1(os.path.join(self.mods, fname))
            self.fake.versions[h] = ver(f"v-{k}1", pid, "1.0", date="2024-01-01T00:00:00Z")
            self.fake.projects[pid] = proj(pid, f"mod{k}", f"Mod {k.upper()}")
            if k != "keep":
                nf = f"{k}2.jar"
                v = ver(f"v-{k}2", pid, "2.0", date="2024-06-01T00:00:00Z")
                v["files"] = [{"filename": nf, "url": f"{self.host.url}/{nf}", "size": len(self.bytes[nf]), "primary": True,
                               "hashes": {"sha1": hashlib.sha1(self.bytes[nf]).hexdigest(), "sha512": hashlib.sha512(self.bytes[nf]).hexdigest()}}]
                self.fake.latest[h] = v
        self.cache = Cache(":memory:")
        self.a = pipeline.run_analysis(self.mods, online=True, cache=self.cache, client=self.fake.client())
        self.dl = os.path.join(self.tmp.name, "dl")

    def tearDown(self):
        packimport._allowed = self.old_allowed
        self.host.close()
        self.fake.close()
        self.cache.close()
        cache_mod.reset_default()
        os.environ.pop("MODMAESTRO_HOME", None) if self.old_home is None else os.environ.__setitem__("MODMAESTRO_HOME", self.old_home)
        self.tmp.cleanup()

    def snapshot(self):
        return {f: (os.path.getsize(os.path.join(self.mods, f)), os.path.getmtime(os.path.join(self.mods, f))) for f in os.listdir(self.mods)}

    def test_candidates_carry_download_info(self):
        c = {u["file"]: u for u in updater.candidates(self.a)}
        self.assertEqual(sorted(c), ["g.jar", "h.jar"])
        self.assertEqual(c["g.jar"]["new"]["filename"], "g2.jar")
        self.assertEqual(c["g.jar"]["new"]["sha1"], hashlib.sha1(self.bytes["g2.jar"]).hexdigest())

    def test_compatibility_test_flags_the_risky_update(self):
        before = self.snapshot()
        res = updater.test(self.a, ["g.jar", "h.jar"], self.dl)
        by = {r["file"]: r for r in res["results"]}
        self.assertEqual((by["g.jar"]["verdict"], by["h.jar"]["verdict"]), ("risky", "ok"))
        self.assertTrue(any("newlib" in p["message"] or "newlib" in p["title"] for p in by["g.jar"]["problems"]))
        self.assertEqual(res["tested"], ["g.jar", "h.jar"])
        self.assertEqual(self.snapshot(), before)                      # le dossier d'origine n'a pas bougé
        res = updater.test(self.a, ["h.jar"], self.dl)                  # sans la mise à jour risquée : plus de problème
        self.assertEqual((res["results"][0]["verdict"], res["new_issues"]), ("ok", []))

    def test_apply_builds_a_new_folder_only(self):
        before = self.snapshot()
        updater.test(self.a, ["h.jar"], self.dl)
        out = os.path.join(self.tmp.name, "mods_updated")
        r = updater.apply(self.a, ["h.jar"], self.dl, out)
        self.assertEqual(sorted(os.listdir(out)), ["g.jar", "h2.jar", "keep.jar"])
        self.assertEqual((r["replaced"], r["kept"], r["added"]), (1, 2, ["h2.jar"]))
        self.assertFalse(any(os.path.islink(os.path.join(out, f)) for f in os.listdir(out)))   # vraies copies
        self.assertEqual(read(os.path.join(out, "h2.jar")), self.bytes["h2.jar"])
        self.assertEqual(self.snapshot(), before)
        suggested = updater.apply(self.a, ["h.jar"], self.dl)           # nom proposé automatiquement : à côté, jamais dedans
        self.assertEqual(os.path.dirname(suggested["output"]), self.tmp.name)
        with self.assertRaises(FileExistsError):
            updater.apply(self.a, ["h.jar"], self.dl, out)              # dossier non vide : refusé
        with self.assertRaises(ValueError):
            updater.apply(self.a, ["h.jar"], self.dl, os.path.join(self.mods, "sub"))   # dans le dossier source : refusé

    def test_bad_hash_or_host_or_selection(self):
        self.host.files["/h2.jar"] = self.bytes["h2.jar"] + b"corrompu"
        with self.assertRaises(ValueError):
            updater.test(self.a, ["h.jar"], self.dl)
        self.assertFalse([f for f in os.listdir(self.dl) if f.endswith("h2.jar")])   # rien de corrompu n'est gardé
        with self.assertRaises(ValueError):
            updater.test(self.a, [], self.dl)
        with self.assertRaises(ValueError):
            updater.test(self.a, ["keep.jar"], self.dl)                 # pas de mise à jour pour ce mod
        packimport._allowed = lambda url: False                         # hébergeur non autorisé : aucune mise à jour proposée
        self.assertEqual(updater.candidates(self.a), [])

    def test_temp_pack_is_removed(self):
        before = set(os.listdir(os.path.dirname(parser._temp_dir("modmaestro_probe_"))))
        updater.test(self.a, ["h.jar"], self.dl)
        after = set(os.listdir(os.path.dirname(parser._temp_dir("modmaestro_probe_"))))
        self.assertEqual([d for d in after - before if d.startswith("modmaestro_upd_")], [])


def _sha1(path):
    return hashlib.sha1(read(path)).hexdigest()


if __name__ == "__main__":
    unittest.main()
