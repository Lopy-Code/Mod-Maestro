"""Régressions « faux positifs » : des packs qui fonctionnent ne doivent pas être déclarés cassés."""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analyzer, demo, learn, logscan, parser, pipeline  # noqa: E402
from core import versions as V  # noqa: E402
from core.cache import Cache  # noqa: E402
from test_core import ids, make_jar, neo, run  # noqa: E402


def toml_dep(modid, dep, rng="*", kind="required", side="BOTH", version="1.0.0"):
    return "\n".join([
        'modLoader="javafml"', 'loaderVersion="[4,)"', 'license="MIT"', "",
        "[[mods]]", f'modId="{modid}"', f'version="{version}"', f'displayName="{modid}"', "",
        f"[[dependencies.{modid}]]", 'modId="minecraft"', 'type="required"', 'versionRange="[1.21,1.22)"',
        'ordering="NONE"', 'side="BOTH"', "",
        f"[[dependencies.{modid}]]", f'modId="{dep}"', f'type="{kind}"', f'versionRange="{rng}"',
        'ordering="NONE"', f'side="{side}"', ""])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()


class VersionLeniencyTests(unittest.TestCase):
    def test_minecraft_prefixed_versions_satisfy_ranges_on_the_mod_number(self):
        self.assertTrue(V.satisfies("maven", "[47,)", "1.20.1-47.1.3"))
        self.assertTrue(V.satisfies("maven", "[0.5,)", "mc1.20.1-0.5.2"))
        self.assertTrue(V.satisfies("maven", "[2.0,3.0)", "2.4+1.20.1"))
        self.assertTrue(V.satisfies("maven", "[2.0,3.0)", "2.4-1.20.1"))

    def test_real_mismatches_are_still_reported(self):
        self.assertFalse(V.satisfies("maven", "[3.0,)", "1.20.1-2.5"))
        self.assertFalse(V.satisfies("maven", "[2.0,3.0)", "3.1"))
        self.assertFalse(V.satisfies("fabric", ">=0.5.0", "0.4.9"))

    def test_prefixed_version_gives_no_version_issue(self):
        neo(self.d if False else tempfile.mkdtemp(), "x.jar", "x")  # (dossier jetable : garde le helper utilisé)
        d = tempfile.mkdtemp()
        make_jar(d, "lib.jar", {"META-INF/neoforge.mods.toml": demo._toml("lib", "Lib", "1.21-47.1.3")})
        make_jar(d, "user.jar", {"META-INF/neoforge.mods.toml": toml_dep("user", "lib", "[47,)")})
        self.assertEqual(ids(run(d), "version:"), [])


class LibraryTests(Base):
    def test_declared_library_is_silent_and_plain_jar_is_only_info(self):
        for i in range(3):
            neo(self.d, f"n{i}.jar", f"n{i}")
        make_jar(self.d, "kotlinlib.jar", {"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nFMLModType: GAMELIBRARY\n"})
        make_jar(self.d, "plainlib.jar", {"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\n", "a/B.class": "x"})
        a = run(self.d)
        self.assertEqual(ids(a, "nometa:kotlinlib"), [])
        (i,) = ids(a, "nometa:plainlib")
        self.assertEqual(i["severity"], "info")
        self.assertEqual(a.score(), 100)  # ne coûte aucun point
        self.assertEqual(a.verdict(), "ok")


class BridgeTests(Base):
    def test_connector_decides_the_loader_even_when_fabric_mods_are_the_majority(self):
        neo(self.d, "connector.jar", "connector")
        neo(self.d, "native.jar", "native")
        for i in range(6):
            make_jar(self.d, f"fab{i}.jar", {"fabric.mod.json": json.dumps({"id": f"fab{i}", "version": "1"})})
        a = run(self.d)
        self.assertEqual(a.loader, "neoforge")
        self.assertEqual([i["severity"] for i in ids(a, "loader:")], ["info"] * 6)
        self.assertEqual(a.verdict(), "ok")

    def test_without_connector_fabric_majority_still_wins(self):
        for i in range(4):
            make_jar(self.d, f"fab{i}.jar", {"fabric.mod.json": json.dumps({"id": f"fab{i}", "version": "1"})})
        neo(self.d, "native.jar", "native")
        self.assertEqual(run(self.d).loader, "fabric")


class MinecraftVersionTests(Base):
    def test_narrow_ranges_break_ties_and_nothing_is_flagged(self):
        for i in range(3):
            neo(self.d, f"exact{i}.jar", f"exact{i}", mc="[1.20.1]")
        for i in range(3):
            neo(self.d, f"open{i}.jar", f"open{i}", mc="[1.20,)")
        a = run(self.d)
        self.assertEqual(a.mc_version, "1.20.1")
        self.assertEqual(ids(a, "mc-versions"), [])

    def test_tie_prefers_the_version_the_most_precise_ranges_point_to(self):
        neo(self.d, "exact.jar", "exact", mc="[1.20.1]")
        neo(self.d, "later.jar", "later", mc="[1.20.4,1.21)")
        neo(self.d, "open1.jar", "open1", mc="[1.20,)")
        neo(self.d, "open2.jar", "open2", mc="[1.20,)")
        self.assertEqual(run(self.d).mc_version, "1.20.1")  # avant : la plus récente (1.20.4) à égalité

    def test_many_offenders_make_one_issue_and_the_score_survives(self):
        for i in range(10):
            neo(self.d, f"ok{i}.jar", f"ok{i}", mc="[1.21,1.22)")
        for i in range(8):
            neo(self.d, f"odd{i}.jar", f"odd{i}", mc="[1.20.1,1.20.2)")
        a = run(self.d)
        (m,) = ids(a, "mc-versions")
        self.assertEqual(len(m["data"]["items"]), 8)
        self.assertEqual(m["confidence"], "heuristic")  # 10/18 : majorité peu nette → simple estimation
        self.assertGreaterEqual(a.score(), 60)
        self.assertNotEqual(a.verdict(), "bad")


class ScoreTests(Base):
    def test_certain_problems_weigh_more_than_estimates(self):
        a = analyzer.Analysis("x", "x")
        a.add_issue("1", "error", "compat", "t", "m", confidence="certain")
        s_certain = a.score()
        b = analyzer.Analysis("x", "x")
        b.add_issue("1", "error", "compat", "t", "m", confidence="heuristic")
        self.assertLess(s_certain, b.score())
        self.assertEqual(a.verdict(), "bad")
        self.assertEqual(b.verdict(), "warn")

    def test_score_never_collapses_to_zero_with_a_few_estimates_and_is_monotonic(self):
        a = analyzer.Analysis("x", "x")
        last = 101
        for k in range(30):
            a.add_issue(str(k), "warning", "compat", "t", "m", confidence="heuristic")
            s = a.score()
            self.assertLessEqual(s, last)
            last = s
        self.assertGreater(last, 30)

    def test_real_problems_still_give_a_bad_score(self):
        for i in range(6):
            neo(self.d, f"a{i}.jar", "same", version=f"1.{i}")  # 6 fichiers, même modid
        neo(self.d, "b.jar", "needy", deps=[("ghost", "required", "*")])
        a = run(self.d)
        self.assertEqual(a.verdict(), "bad")
        self.assertLess(a.score(), 85)

    def test_ignored_issues_do_not_count(self):
        neo(self.d, "b.jar", "needy", deps=[("ghost", "required", "*")])
        a = run(self.d)
        self.assertEqual(a.verdict(), "bad")
        a.ignored_ids = {"missing:ghost"}
        self.assertEqual((a.verdict(), a.score(), a.counts()["errors"], a.counts()["ignored"]), ("ok", 100, 0, 1))
        d = a.to_dict()
        (i,) = [x for x in d["issues"] if x["id"] == "missing:ghost"]
        self.assertTrue(i["ignored"])

    def test_one_sided_dependency_is_only_a_likely_warning(self):
        make_jar(self.d, "u.jar", {"META-INF/neoforge.mods.toml": toml_dep("u", "serverlib", side="SERVER")})
        (i,) = ids(run(self.d), "missing:")
        self.assertEqual((i["severity"], i["confidence"]), ("warning", "likely"))

    def test_forge_mod_in_neoforge_pack_is_info_on_old_minecraft(self):
        for i in range(3):
            neo(self.d, f"n{i}.jar", f"n{i}", mc="[1.20.1]")
        make_jar(self.d, "forge.jar", {"META-INF/mods.toml": demo._forge_toml("fg", "Fg", "1.0")})
        (i,) = ids(run(self.d), "loader:")
        self.assertEqual(i["severity"], "info")
        self.assertEqual(ids(run(self.d), "mc-versions"), [])


class BootEvidenceTests(Base):
    def make_instance(self, log_text, age=0):
        mods = os.path.join(self.d, "mods")
        os.makedirs(mods)
        neo(mods, "needy.jar", "needy", deps=[("ghost", "required", "*")])
        os.makedirs(os.path.join(self.d, "logs"))
        p = os.path.join(self.d, "logs", "latest.log")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(log_text)
        t = time.time() + age
        os.utime(p, (t, t))
        return mods

    def analysis(self, mods):
        cache = Cache(":memory:")
        try:
            return pipeline.run_analysis(mods, cache=cache)
        finally:
            cache.close()

    def test_a_pack_that_booted_is_not_called_broken(self):
        mods = self.make_instance('[12:00:00] [Render thread/INFO]: Sound engine started\n', age=+10)
        a = self.analysis(mods)
        self.assertEqual(a.boot["status"], "ok")
        self.assertNotEqual(a.verdict(), "bad")
        self.assertGreaterEqual(a.score(), 85)
        self.assertEqual(a.to_dict()["boot"]["status"], "ok")

    def test_a_stale_log_is_ignored_for_the_score(self):
        mods = self.make_instance('[12:00:00] [Render thread/INFO]: Sound engine started\n', age=-3600)
        a = self.analysis(mods)
        self.assertFalse(a.boot["fresh"])
        self.assertEqual(a.verdict(), "bad")

    def test_a_failed_launch_is_reported(self):
        mods = self.make_instance("Loading errors encountered: [\n\tMissing or unsupported mandatory dependencies:\n"
                                  "\tMod ID: 'ghost', Requested by: 'needy', Expected range: '*', Actual version: '[MISSING]'\n]\n",
                                  age=+10)
        a = self.analysis(mods)
        self.assertEqual(a.boot["status"], "crashed")
        self.assertEqual(len(ids(a, "boot-crash")), 1)
        self.assertEqual(a.verdict(), "bad")

    def test_no_log_means_no_evidence(self):
        mods = os.path.join(self.d, "mods")
        os.makedirs(mods)
        neo(mods, "a.jar", "a")
        self.assertIsNone(self.analysis(mods).boot)


class IgnoreStorageTests(Base):
    def test_ignore_is_persisted_applied_and_reversible(self):
        mods = os.path.join(self.d, "mods")
        os.makedirs(mods)
        neo(mods, "needy.jar", "needy", deps=[("ghost", "required", "*")])
        cache = Cache(":memory:")
        self.assertEqual(pipeline.run_analysis(mods, cache=cache).verdict(), "bad")
        row = learn.add_ignore(cache, "missing:ghost")
        a = pipeline.run_analysis(mods, cache=cache)
        self.assertEqual(a.verdict(), "ok")
        self.assertEqual(a.counts()["ignored"], 1)
        self.assertTrue(learn.remove(cache, row["id"]))
        self.assertEqual(pipeline.run_analysis(mods, cache=cache).verdict(), "bad")
        with self.assertRaises(ValueError):
            learn.add_ignore(cache, "  ")
        self.assertEqual(learn.to_bundle(cache)["conflicts"], [])  # un « ignorer » ne s'exporte pas comme conflit
        cache.close()


if __name__ == "__main__":
    unittest.main()
