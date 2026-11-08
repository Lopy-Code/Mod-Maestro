"""Tests de la base de connaissances : communautaire, apprise, export/import, passerelles de loader."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import knowledge, learn, parser, pipeline  # noqa: E402
from core.cache import Cache  # noqa: E402
from test_core import make_jar, neo  # noqa: E402


class Base(unittest.TestCase):
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
        self.cache = Cache(":memory:")

    def tearDown(self):
        self.tmp.cleanup()
        self.cache.close()

    def run_pack(self):
        return pipeline.run_analysis(self.d, cache=self.cache)


class CommunityBaseTests(Base):
    def test_builtin_community_files_are_valid(self):
        loaded = knowledge.load_dir(knowledge.builtin_dir())
        self.assertEqual(loaded["errors"], [])
        self.assertGreaterEqual(len(loaded["sides"]), 1)
        self.assertGreaterEqual(len(loaded["conflicts"]), 1)

    def test_validation_rejects_bad_entries(self):
        self.assertTrue(knowledge.validate_side({"modid": "Bad Id!", "side": "client", "reason": "x"}))
        self.assertTrue(knowledge.validate_side({"modid": "ok", "side": "server", "reason": "x"}))
        self.assertTrue(knowledge.validate_side({"modid": "ok", "side": "client", "reason": " "}))
        self.assertEqual(knowledge.validate_side({"modid": "ok", "side": "client", "reason": "x"}), [])
        base = {"severity": "error", "title": "t", "message": "m"}
        self.assertTrue(knowledge.validate_conflict({**base, "group": ["only-one"]}))
        self.assertTrue(knowledge.validate_conflict({**base}))
        self.assertTrue(knowledge.validate_conflict({**base, "group": ["a", "b"], "severity": "fatal"}))
        self.assertEqual(knowledge.validate_conflict({**base, "a": ["x"], "b": ["y"]}), [])
        self.assertEqual(knowledge.validate_conflict({**base, "group": ["a", "b"]}), [])

    def test_user_folder_is_loaded_and_errors_are_reported_not_fatal(self):
        user = os.path.join(self.d, "community")
        os.makedirs(os.path.join(user, "sides"))
        with open(os.path.join(user, "sides", "good.json"), "w", encoding="utf-8") as fh:
            json.dump({"modid": "myclientmod", "side": "client", "reason": "test"}, fh)
        with open(os.path.join(user, "sides", "bad.json"), "w", encoding="utf-8") as fh:
            fh.write("{ pas du json")
        kb = knowledge.load_all(None, community_dirs=[user])
        self.assertIn("myclientmod", kb["client_only"]["ids"])
        self.assertEqual(len(kb["_stats"]["errors"]), 1)
        self.assertIn("bad.json", kb["_stats"]["errors"][0])

    def test_community_side_removes_mod_from_server_plan(self):
        neo(self.d, "tp.jar", "betterthirdperson")  # entrée communautaire fournie
        neo(self.d, "keep.jar", "keepme")
        plan = self.run_pack().to_dict()["plan"]
        self.assertEqual([r["file"] for r in plan["remove"]], ["tp.jar"])

    def test_community_conflict_is_reported_with_source(self):
        neo(self.d, "s.jar", "starlight")
        neo(self.d, "p.jar", "phosphor")
        a = self.run_pack()
        (i,) = [x for x in a.issues if x["id"].startswith("known:")]
        self.assertEqual(i["severity"], "warning")
        self.assertIn("source", i["message"])
        self.assertEqual(i["data"]["source"], "ModMaestro (entrée de départ)")

    def test_force_both_overrides_a_wrong_guess(self):
        neo(self.d, "sodium.jar", "sodium")  # connu comme client…
        self.assertEqual(len(self.run_pack().to_dict()["plan"]["remove"]), 1)
        learn.add_side(self.cache, "sodium", "both", "je le veux sur mon serveur")  # …mais l'utilisateur dit non
        self.assertEqual(self.run_pack().to_dict()["plan"]["remove"], [])


class LearnTests(Base):
    def test_learned_conflict_is_applied(self):
        neo(self.d, "a.jar", "mod-a")
        neo(self.d, "b.jar", "mod-b")
        self.assertEqual([i for i in self.run_pack().issues if i["id"].startswith("known:")], [])
        row = learn.add_conflict(self.cache, "mod-b", "mod-a", "plante au chargement du monde")
        self.assertEqual((row["a"], row["b"]), ("mod-a", "mod-b"))  # ordre normalisé
        (i,) = [x for x in self.run_pack().issues if x["id"].startswith("known:")]
        self.assertEqual(i["severity"], "error")
        self.assertIn("plante au chargement du monde", i["message"])
        self.assertIn("ta base personnelle", i["message"])

    def test_learned_client_side(self):
        neo(self.d, "x.jar", "mystery-ui")
        self.assertEqual(self.run_pack().to_dict()["plan"]["remove"], [])
        learn.add_side(self.cache, "mystery-ui", "client")
        plan = self.run_pack().to_dict()["plan"]
        self.assertEqual([r["file"] for r in plan["remove"]], ["x.jar"])

    def test_duplicates_are_merged_and_removal_works(self):
        learn.add_conflict(self.cache, "a", "b", "v1")
        learn.add_conflict(self.cache, "b", "a", "v2", "warning")
        rows = learn.list_learned(self.cache)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["note"], rows[0]["severity"]), ("v2", "warning"))
        self.assertTrue(learn.remove(self.cache, rows[0]["id"]))
        self.assertFalse(learn.remove(self.cache, rows[0]["id"]))
        self.assertEqual(learn.list_learned(self.cache), [])

    def test_invalid_input_is_refused(self):
        with self.assertRaises(ValueError):
            learn.add_conflict(self.cache, "a", "a")
        with self.assertRaises(ValueError):
            learn.add_conflict(self.cache, "../etc", "b")
        with self.assertRaises(ValueError):
            learn.add_conflict(self.cache, "a", "b", severity="fatal")
        with self.assertRaises(ValueError):
            learn.add_side(self.cache, "a", "server")
        self.assertEqual(learn.list_learned(self.cache), [])

    def test_bundle_roundtrip(self):
        learn.add_conflict(self.cache, "a", "b", "note", "warning")
        learn.add_side(self.cache, "c", "client", "raison")
        bundle = learn.to_bundle(self.cache)
        self.assertEqual(bundle["format"], "modmaestro-community")
        other = Cache(":memory:")
        res = learn.import_bundle(other, json.loads(json.dumps(bundle)))
        self.assertEqual((res["added"], res["errors"]), (2, []))
        kinds = sorted((r["kind"], r["a"], r["b"]) for r in other.list_learned())
        self.assertEqual(kinds, [("conflict", "a", "b"), ("side", "c", "")])
        other.close()

    def test_import_validates_and_rejects_foreign_files(self):
        with self.assertRaises(ValueError):
            learn.import_bundle(self.cache, {"hello": "world"})
        res = learn.import_bundle(self.cache, {
            "format": "modmaestro-community", "version": 1,
            "sides": [{"modid": "ok", "side": "client", "reason": "x"}, {"modid": "Mauvais Id", "side": "client", "reason": "x"}],
            "conflicts": [{"a": ["x"], "b": ["y"], "severity": "boom", "title": "t", "message": "m"}]})
        self.assertEqual(res["added"], 1)
        self.assertEqual(len(res["errors"]), 2)

    def test_import_expands_groups_with_a_cap(self):
        group = [f"m{i}" for i in range(20)]  # 190 paires possibles
        res = learn.import_bundle(self.cache, {"format": "modmaestro-community", "version": 1, "conflicts": [
            {"group": group, "severity": "info", "title": "t", "message": "m"}]})
        self.assertEqual(res["added"], knowledge.MAX_PAIRS)

    def test_export_files_match_community_format(self):
        learn.add_conflict(self.cache, "a", "b", "n")
        learn.add_side(self.cache, "c", "client")
        out = os.path.join(self.d, "export")
        written = learn.export_files(self.cache, out)
        self.assertEqual(sorted(os.path.relpath(p, out) for p in written),
                         [os.path.join("conflicts", "a__b.json"), os.path.join("sides", "c.json")])
        loaded = knowledge.load_dir(out)
        self.assertEqual((loaded["errors"], len(loaded["sides"]), len(loaded["conflicts"])), ([], 1, 1))

    def test_suggestions_from_log_findings(self):
        findings = [
            {"code": "mixin", "title": "Un mixin n'a pas pu s'appliquer", "mods": ["modx"]},
            {"code": "client-on-server", "title": "Client sur serveur", "mods": []},
            {"code": "java", "title": "Java", "mods": []},
        ]
        installed = [{"modid": "modx", "side": "both"}, {"modid": "sodium", "side": "client"}, {"modid": "mody", "side": "both"}]
        s = learn.suggest(findings, installed)
        self.assertEqual([x["kind"] for x in s], ["conflict", "side"])
        self.assertEqual(s[0]["a"], "modx")
        self.assertEqual(s[1]["candidates"], ["modx", "mody"])  # les mods déjà « client » ne sont pas proposés


class LoaderBridgeTests(Base):
    def test_fabric_mod_is_error_without_connector(self):
        for i in range(3):
            neo(self.d, f"n{i}.jar", f"n{i}")
        make_jar(self.d, "fab.jar", {"fabric.mod.json": json.dumps({"id": "fab", "version": "1"})})
        a = self.run_pack()
        self.assertEqual([i["severity"] for i in a.issues if i["id"] == "loader:fab.jar"], ["error"])

    def test_fabric_mod_is_info_with_sinytra_connector(self):
        for i in range(3):
            neo(self.d, f"n{i}.jar", f"n{i}")
        neo(self.d, "connector.jar", "connector")
        make_jar(self.d, "fab.jar", {"fabric.mod.json": json.dumps({"id": "fab", "version": "1"})})
        a = self.run_pack()
        (i,) = [x for x in a.issues if x["id"] == "loader:fab.jar"]
        self.assertEqual(i["severity"], "info")
        self.assertIn("Sinytra Connector", i["title"])
        self.assertEqual(a.entries["fab.jar"]["compat"], "bridged")
        self.assertIn("fab.jar", a.to_dict()["plan"]["keep"])  # n'est pas retiré du serveur


if __name__ == "__main__":
    unittest.main()
