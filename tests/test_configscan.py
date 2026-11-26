"""Analyse des fichiers de configuration."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import cache, configscan, i18n, pipeline  # noqa: E402
from test_core import neo  # noqa: E402


def ids(found):
    return sorted(f["id"] for f in found)


class Scanners(unittest.TestCase):
    def test_server_properties(self):
        txt = "view-distance=24\nsimulation-distance=16\nmax-tick-time=-1\nonline-mode=false\nentity-broadcast-range-percentage=200\n"
        self.assertEqual(ids(configscan.scan_server_properties(txt, 10)),
                         ["config:entity-broadcast-range", "config:max-tick-time", "config:online-mode",
                          "config:simulation-distance", "config:view-distance"])
        ok = "view-distance=10\nsimulation-distance=8\nmax-tick-time=60000\nonline-mode=true\n# view-distance=40\n"
        self.assertEqual(configscan.scan_server_properties(ok, 10), [])

    def test_client_options(self):
        found = configscan.scan_options("renderDistance:32\nsimulationDistance:16\nentityDistanceScaling:3.0\n")
        self.assertEqual(ids(found), ["config:client-entity-distance", "config:client-render-distance", "config:client-simulation-distance"])
        self.assertEqual(configscan.scan_options("renderDistance:12\nsimulationDistance:8\nentityDistanceScaling:1.0\n"), [])

    def test_jvm_arguments(self):
        f = lambda t, n=150: ids(configscan.scan_jvm(t, n, "user_jvm_args.txt"))  # noqa: E731
        self.assertEqual(f("-Xms4G -Xmx8G -XX:+UseG1GC"), [])
        self.assertEqual(f("-Xmx48G"), ["config:jvm-xmx-huge"])
        self.assertEqual(f("-Xmx2G"), ["config:jvm-xmx-low"])
        self.assertEqual(f("-Xmx2G", 20), [])                       # petit pack : 2 Go acceptable
        self.assertEqual(f("-Xms8G -Xmx4G"), ["config:jvm-xms-gt-xmx"])
        self.assertEqual(f("-XX:+UseG1GC -XX:+UseZGC -Xmx8G"), ["config:jvm-gc-conflict"])
        self.assertEqual(f("-Xmx8G -XX:+UseConcMarkSweepGC"), ["config:jvm-obsolete-flags"])
        self.assertEqual(f("# -Xmx48G\nREM -XX:+UseZGC -XX:+UseG1GC\n-Xmx8G"), [])   # commentaires ignorés
        self.assertEqual(f("-Xmx4096M"), [])
        self.assertEqual(f("-Xmx32768M"), ["config:jvm-xmx-huge"])


class Rules(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.d.name, "config"))
        self.old = os.environ.get("MODMAESTRO_HOME")
        os.environ["MODMAESTRO_HOME"] = self.d.name
        cache.reset_default()

    def tearDown(self):
        os.environ.pop("MODMAESTRO_HOME", None) if self.old is None else os.environ.__setitem__("MODMAESTRO_HOME", self.old)
        cache.reset_default()
        self.d.cleanup()

    def write(self, rel, text):
        with open(os.path.join(self.d.name, *rel.split("/")), "w", encoding="utf-8") as fh:
            fh.write(text)

    def rule(self, **kw):
        base = {"id": "r1", "path": "config/mymod.toml", "key": "general.radius", "op": "gt", "value": 8, "severity": "warning",
                "title": "Rayon trop grand", "message": "Le rayon est excessif.", "fix": "Baisse-le."}
        return {**base, **kw}

    def test_toml_json_properties_and_ops(self):
        self.write("config/mymod.toml", "[general]\nradius = 16\nenabled = true\nmode = \"Fast\"\n")
        self.write("config/other.json", json.dumps({"a": {"b": 5}, "flat.key": 7}))
        self.write("config/old.properties", "# c\nlevel=3\n")
        mk = lambda **kw: configscan.scan_rules(self.d.name, [self.rule(**kw)], {"mymod"})  # noqa: E731
        self.assertEqual(len(mk()), 1)
        self.assertEqual(mk(value=20), [])
        self.assertEqual(len(mk(key="general.enabled", op="true")), 1)
        self.assertEqual(mk(key="general.enabled", op="false"), [])
        self.assertEqual(len(mk(key="general.mode", op="eq", value="fast")), 1)
        self.assertEqual(len(mk(key="general.mode", op="contains", value="as")), 1)
        self.assertEqual(len(mk(path="config/other.json", key="a.b", op="le", value=5)), 1)
        self.assertEqual(len(mk(path="config/other.json", key="flat.key", op="eq", value=7)), 1)
        self.assertEqual(len(mk(path="config/*.properties", key="level", op="ge", value=3)), 1)
        self.assertEqual(mk(key="absent.key"), [])
        self.assertEqual(mk(path="config/missing.toml"), [])

    def test_rule_needs_installed_mod_and_bad_files_are_skipped(self):
        self.write("config/mymod.toml", "[general]\nradius = 16\n")
        r = self.rule(requires_mod="mymod")
        self.assertEqual(len(configscan.scan_rules(self.d.name, [r], {"mymod"})), 1)
        self.assertEqual(configscan.scan_rules(self.d.name, [r], {"autre"}), [])
        self.write("config/mymod.toml", "[general\nradius = ")      # fichier cassé : pas de plantage
        self.assertEqual(configscan.scan_rules(self.d.name, [r], {"mymod"}), [])

    def test_validation_and_user_rules(self):
        self.assertTrue(configscan.validate_rule(self.rule(path="../../etc/passwd")))
        self.assertTrue(configscan.validate_rule(self.rule(path="mods/x.toml")))
        self.assertTrue(configscan.validate_rule(self.rule(op="exec")))
        self.assertTrue(configscan.validate_rule(self.rule(severity="error")))
        self.assertTrue(configscan.validate_rule(self.rule(id="Bad Id")))
        self.assertEqual(configscan.validate_rule(self.rule()), [])
        os.makedirs(os.path.join(self.d.name, "configrules"))
        self.write("configrules/mine.json", json.dumps([self.rule(), self.rule(id="r2", op="bad")]))
        rules, errors = configscan.load_rules()
        self.assertEqual([r["id"] for r in rules], ["r1"])
        self.assertEqual(len(errors), 1)

    def test_english_text_for_rules(self):
        self.write("config/mymod.toml", "[general]\nradius = 16\n")
        r = self.rule(en={"title": "Radius too large", "message": "Too wide.", "fix": "Lower it."})
        i18n.set_lang("en")
        try:
            f = configscan.scan_rules(self.d.name, [r], set())[0]
        finally:
            i18n.set_lang("fr")
        self.assertEqual((f["title"], f["fix"]), ("Radius too large", "Lower it."))


class Integration(unittest.TestCase):
    def test_instance_folder_gets_config_issues(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("MODMAESTRO_HOME")
            os.environ["MODMAESTRO_HOME"] = os.path.join(d, "home")
            cache.reset_default()
            try:
                mods = os.path.join(d, "inst", "mods")
                os.makedirs(mods)
                neo(mods, "a.jar", "alpha")
                with open(os.path.join(d, "inst", "server.properties"), "w") as fh:
                    fh.write("view-distance=32\n")
                with open(os.path.join(d, "inst", "user_jvm_args.txt"), "w") as fh:
                    fh.write("-Xmx64G\n")
                for target in (mods, os.path.join(d, "inst")):       # le dossier mods ou l'instance : même résultat
                    a = pipeline.run_analysis(target)
                    got = {i["id"]: i for i in a.issues if i["category"] == "config"}
                    self.assertEqual(sorted(got), ["config:jvm-xmx-huge", "config:view-distance"])
                    self.assertTrue(all(i["confidence"] == "heuristic" and i["severity"] in ("info", "warning") for i in got.values()))
                    self.assertNotIn(d, json.dumps(a.to_dict()["issues"]))     # aucun chemin local dans les alertes
                    self.assertIn("(server.properties)", got["config:view-distance"]["message"])
                a.ignored_ids.add("config:view-distance")
                self.assertNotIn("config:view-distance", [i["id"] for i in a.active_issues()])
                bare = os.path.join(d, "bare", "mods")
                os.makedirs(bare)
                neo(bare, "a.jar", "alpha")
                self.assertEqual([i for i in pipeline.run_analysis(bare).issues if i["category"] == "config"], [])
            finally:
                cache.reset_default()
                os.environ.pop("MODMAESTRO_HOME", None) if old is None else os.environ.__setitem__("MODMAESTRO_HOME", old)


if __name__ == "__main__":
    unittest.main()
