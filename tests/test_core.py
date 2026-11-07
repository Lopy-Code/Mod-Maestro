"""Tests du moteur ModMaestro — `python -m unittest discover -s tests -v`."""

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analyzer, builder, demo, logscan, parser, report  # noqa: E402
from core import versions as V  # noqa: E402


def make_jar(folder, name, files):
    path = os.path.join(folder, name)
    with zipfile.ZipFile(path, "w") as zf:
        for n, c in files.items():
            zf.writestr(n, c)
    return path


def neo(folder, fname, modid, version="1.0.0", deps=(), side="BOTH", mc="[1.21,1.22)", name=None):
    make_jar(folder, fname, {"META-INF/neoforge.mods.toml": demo._toml(modid, name or modid, version, deps, side, mc)})


def run(folder):
    jars, extras = parser.scan_folder(folder)
    return analyzer.analyze(jars, extras, folder, folder)


def ids(a, prefix):
    return [i for i in a.issues if i["id"].startswith(prefix)]


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertGreater(V.compare("1.10", "1.9"), 0)
        self.assertEqual(V.compare("1.21", "1.21.0"), 0)
        self.assertGreater(V.compare("1.0", "1.0-beta"), 0)
        self.assertGreater(V.compare("1.21.1-4.6.0", "1.21.1-4.4.0"), 0)
        self.assertEqual(V.compare("1.2.3+build5", "1.2.3"), 0)

    def test_maven(self):
        self.assertTrue(V.maven_contains("[1.21,1.22)", "1.21.1"))
        self.assertFalse(V.maven_contains("[1.21,1.22)", "1.22"))
        self.assertFalse(V.maven_contains("[1.20.1]", "1.21"))
        self.assertTrue(V.maven_contains("[4.0,)", "99"))
        self.assertTrue(V.maven_contains("(,2.0]", "2.0"))
        self.assertFalse(V.maven_contains("(,2.0)", "2.0"))
        self.assertTrue(V.maven_contains("[1,2),[5,6)", "5.5"))
        self.assertTrue(V.maven_contains("1.0", "0.1"))  # bare version = souple
        self.assertTrue(V.maven_contains("[4.0,)", None))

    def test_fabric(self):
        self.assertTrue(V.fabric_satisfies(">=0.15.0", "0.16.2"))
        self.assertFalse(V.fabric_satisfies(">=0.15.0 <0.16", "0.16.2"))
        self.assertTrue(V.fabric_satisfies("~1.21", "1.21.1"))
        self.assertFalse(V.fabric_satisfies("~1.21", "1.22"))
        self.assertTrue(V.fabric_satisfies("^1.2.3", "1.9.0"))
        self.assertFalse(V.fabric_satisfies("^1.2.3", "2.0.0"))
        self.assertTrue(V.fabric_satisfies("1.21.x", "1.21.4"))
        self.assertTrue(V.fabric_satisfies(["1.20.1", "1.21.x"], "1.21.1"))
        self.assertTrue(V.fabric_satisfies("*", "3"))


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_neoforge_basic(self):
        neo(self.d, "a.jar", "alpha", "2.0", deps=[("beta", "required", "[1,)"), ("gamma", "optional", "*")])
        j = parser.read_jar(os.path.join(self.d, "a.jar"))
        self.assertEqual(j.status, "ok")
        m = j.mods[0]
        self.assertEqual((m.modid, m.version, m.loader), ("alpha", "2.0", "neoforge"))
        kinds = {(d.modid, d.kind) for d in m.deps}
        self.assertIn(("beta", "required"), kinds)
        self.assertIn(("gamma", "optional"), kinds)

    def test_version_placeholder_uses_manifest(self):
        toml = demo._toml("alpha", "Alpha", "${file.jarVersion}")
        make_jar(self.d, "a.jar", {"META-INF/neoforge.mods.toml": toml,
                                   "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 7.7.7\n"})
        self.assertEqual(parser.read_jar(os.path.join(self.d, "a.jar")).mods[0].version, "7.7.7")

    def test_fabric(self):
        make_jar(self.d, "f.jar", {"fabric.mod.json": json.dumps({
            "schemaVersion": 1, "id": "fab", "version": "1.0", "name": "Fab", "environment": "client",
            "depends": {"fabricloader": ">=0.15", "libx": "*"}, "breaks": {"badmod": "<2"},
            "provides": ["fab-alias"]})})
        m = parser.read_jar(os.path.join(self.d, "f.jar")).mods[0]
        self.assertEqual(m.loader, "fabric")
        self.assertEqual(m.env, "client")
        self.assertIn("fab-alias", m.provides)
        self.assertIn(("badmod", "incompatible"), {(d.modid, d.kind) for d in m.deps})

    def test_fabric_client_entrypoint_only(self):
        make_jar(self.d, "f.jar", {"fabric.mod.json": json.dumps({
            "id": "cl", "version": "1", "entrypoints": {"client": ["x.Y"]}})})
        self.assertEqual(parser.read_jar(os.path.join(self.d, "f.jar")).mods[0].env, "client")

    def test_quilt(self):
        make_jar(self.d, "q.jar", {"quilt.mod.json": json.dumps({"quilt_loader": {
            "id": "qm", "version": "1.0", "metadata": {"name": "Q"},
            "depends": ["libz", {"id": "opt", "optional": True}]}})})
        m = parser.read_jar(os.path.join(self.d, "q.jar")).mods[0]
        self.assertEqual(m.loader, "quilt")
        self.assertIn(("opt", "optional"), {(d.modid, d.kind) for d in m.deps})

    def test_jar_in_jar(self):
        inner = demo._inner_jar({"META-INF/neoforge.mods.toml": demo._toml("inner", "Inner", "1.0")})
        make_jar(self.d, "outer.jar", {"META-INF/neoforge.mods.toml": demo._toml("outer", "Outer", "1.0"),
                                       "META-INF/jarjar/inner.jar": inner})
        j = parser.read_jar(os.path.join(self.d, "outer.jar"))
        self.assertEqual([b.modid for b in j.bundled], ["inner"])

    def test_corrupt_and_empty(self):
        with open(os.path.join(self.d, "bad.jar"), "wb") as fh:
            fh.write(b"not a zip")
        open(os.path.join(self.d, "empty.jar"), "wb").close()
        self.assertEqual(parser.read_jar(os.path.join(self.d, "bad.jar")).status, "corrupt")
        self.assertEqual(parser.read_jar(os.path.join(self.d, "empty.jar")).status, "corrupt")

    def test_no_metadata(self):
        make_jar(self.d, "lib.jar", {"a/B.class": b"x"})
        self.assertEqual(parser.read_jar(os.path.join(self.d, "lib.jar")).status, "no-metadata")

    def test_resolve_source_instance_root(self):
        os.makedirs(os.path.join(self.d, "mods"))
        neo(os.path.join(self.d, "mods"), "a.jar", "alpha")
        folder, notes = parser.resolve_source(self.d)
        self.assertTrue(folder.endswith("mods"))
        self.assertTrue(notes)

    def test_zip_with_manifest_only(self):
        z = os.path.join(self.d, "pack.zip")
        make_jar(self.d, "pack.zip", {"manifest.json": "{}"})
        with self.assertRaises(ValueError) as cm:
            parser.resolve_source(z)
        self.assertIn("manifest", str(cm.exception))

    def test_zip_with_mods(self):
        src = os.path.join(self.d, "src")
        os.makedirs(src)
        neo(src, "a.jar", "alpha")
        z = os.path.join(self.d, "pack.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(os.path.join(src, "a.jar"), "overrides/mods/a.jar")
        folder, _ = parser.resolve_source(z)
        self.assertEqual(os.listdir(folder), ["a.jar"])


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_pack(self):
        neo(self.d, "a.jar", "alpha", deps=[("beta", "required", "[1,)")])
        neo(self.d, "b.jar", "beta", "2.0")
        a = run(self.d)
        self.assertEqual(a.issues, [])
        self.assertEqual(a.verdict(), "ok")
        self.assertEqual(a.score(), 100)

    def test_duplicate_keeps_newest(self):
        neo(self.d, "lib-1.0.jar", "lib", "1.0")
        neo(self.d, "lib-1.10.jar", "lib", "1.10")
        neo(self.d, "lib-1.9.jar", "lib", "1.9")
        a = run(self.d)
        (dup,) = ids(a, "dup:")
        self.assertEqual(dup["data"]["keep"], "lib-1.10.jar")
        self.assertEqual(sorted(dup["data"]["remove"]), ["lib-1.0.jar", "lib-1.9.jar"])
        plan = a.to_dict()["plan"]
        self.assertEqual(plan["keep"], ["lib-1.10.jar"])

    def test_missing_dependency_aggregated(self):
        neo(self.d, "a.jar", "a", deps=[("core", "required", "[1,)")])
        neo(self.d, "b.jar", "b", deps=[("core", "required", "[1,)")])
        a = run(self.d)
        (m,) = ids(a, "missing:")
        self.assertEqual(sorted(m["data"]["required_by"]), ["a", "b"])
        self.assertEqual(m["severity"], "error")

    def test_optional_missing_is_not_reported(self):
        neo(self.d, "a.jar", "a", deps=[("nice", "optional", "*")])
        self.assertEqual(run(self.d).issues, [])

    def test_bundled_dependency_not_missing(self):
        inner = demo._inner_jar({"META-INF/neoforge.mods.toml": demo._toml("inner", "Inner", "1.0")})
        make_jar(self.d, "outer.jar", {
            "META-INF/neoforge.mods.toml": demo._toml("outer", "Outer", "1.0"),
            "META-INF/jarjar/inner.jar": inner})
        neo(self.d, "user.jar", "user", deps=[("inner", "required", "[1,)")])
        self.assertEqual(ids(run(self.d), "missing:"), [])

    def test_dependency_version_out_of_range(self):
        neo(self.d, "a.jar", "a", deps=[("lib", "required", "[2.0,)")])
        neo(self.d, "lib.jar", "lib", "1.5")
        (v,) = ids(run(self.d), "version:")
        self.assertEqual(v["severity"], "error")

    def test_declared_incompatibility(self):
        neo(self.d, "a.jar", "a", deps=[("b", "incompatible", "*")])
        neo(self.d, "b.jar", "b")
        (i,) = ids(run(self.d), "incompat:")
        self.assertEqual(i["severity"], "error")

    def test_known_conflict_and_client_removal(self):
        neo(self.d, "sodium.jar", "sodium", side="CLIENT")
        neo(self.d, "embeddium.jar", "embeddium", side="CLIENT")
        a = run(self.d)
        self.assertEqual(len(ids(a, "known:")), 1)
        self.assertEqual(a.to_dict()["plan"]["keep"], [])

    def test_loader_mismatch(self):
        for i in range(3):
            neo(self.d, f"n{i}.jar", f"n{i}")
        make_jar(self.d, "fab.jar", {"fabric.mod.json": json.dumps({"id": "fab", "version": "1"})})
        a = run(self.d)
        self.assertEqual(a.loader, "neoforge")
        (m,) = ids(a, "loader:")
        self.assertEqual(m["severity"], "error")
        removed = {r["file"]: r["kind"] for r in a.to_dict()["plan"]["remove"]}
        self.assertEqual(removed["fab.jar"], "loader")

    def test_minecraft_version_mismatch(self):
        for i in range(4):
            neo(self.d, f"n{i}.jar", f"n{i}", mc="[1.21,1.22)")
        neo(self.d, "old.jar", "old", mc="[1.20.1,1.20.2)")
        a = run(self.d)
        self.assertEqual(a.mc_version, "1.21")
        (m,) = ids(a, "mc:")
        self.assertEqual(m["severity"], "error")

    def test_multi_loader_jar_uses_matching_loader(self):
        for i in range(3):
            neo(self.d, f"n{i}.jar", f"n{i}")
        make_jar(self.d, "multi.jar", {
            "META-INF/neoforge.mods.toml": demo._toml("multi", "Multi", "1.0"),
            "fabric.mod.json": json.dumps({"id": "multi", "version": "1.0"})})
        self.assertEqual(ids(run(self.d), "loader:"), [])

    def test_provides_satisfies_dependency(self):
        make_jar(self.d, "p.jar", {"fabric.mod.json": json.dumps(
            {"id": "real", "version": "1", "provides": ["alias"]})})
        make_jar(self.d, "u.jar", {"fabric.mod.json": json.dumps(
            {"id": "user", "version": "1", "depends": {"alias": "*"}})})
        self.assertEqual(ids(run(self.d), "missing:"), [])

    def test_server_plan_restores_required_client_mod(self):
        neo(self.d, "ui.jar", "uilib", side="CLIENT")
        neo(self.d, "core.jar", "core", deps=[("uilib", "required", "*")], name="Core")
        a = run(self.d)
        plan = a.to_dict()["plan"]
        self.assertIn("ui.jar", plan["keep"])
        self.assertEqual(plan["restored"][0]["file"], "ui.jar")

    def test_manual_exclusion_warns_about_broken_dependency(self):
        neo(self.d, "lib.jar", "lib")
        neo(self.d, "user.jar", "user", deps=[("lib", "required", "*")])
        a = run(self.d)
        plan = analyzer.compute_plan(a, exclude=["lib.jar"])
        self.assertEqual(plan["warnings"][0]["missing"], "lib")
        self.assertNotIn("lib.jar", plan["keep"])

    def test_manual_include_overrides(self):
        neo(self.d, "sodium.jar", "sodium", side="CLIENT")
        a = run(self.d)
        plan = analyzer.compute_plan(a, include=["sodium.jar"])
        self.assertIn("sodium.jar", plan["keep"])

    def test_report_markdown(self):
        neo(self.d, "a.jar", "a", deps=[("core", "required", "*")])
        md = report.to_markdown(run(self.d).to_dict())
        self.assertIn("# Rapport ModMaestro", md)
        self.assertIn("Dépendance manquante", md)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.mods = os.path.join(self.root, "mods")
        os.makedirs(self.mods)
        neo(self.mods, "keep.jar", "keep")
        neo(self.mods, "sodium.jar", "sodium", side="CLIENT")
        self.a = run(self.mods)

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_zip(self):
        out = os.path.join(self.root, "server_mods")
        r = builder.build_server(self.a, out, make_zip=True)
        self.assertEqual(sorted(os.listdir(out)), ["keep.jar"])
        self.assertEqual(sorted(os.listdir(self.mods)), ["keep.jar", "sodium.jar"])  # source intacte
        with zipfile.ZipFile(r["zip"]) as zf:
            self.assertEqual(zf.namelist(), ["mods/keep.jar"])

    def test_dry_run_writes_nothing(self):
        out = os.path.join(self.root, "nope")
        r = builder.build_server(self.a, out, dry_run=True)
        self.assertEqual(r["copied"], 1)
        self.assertFalse(os.path.exists(out))

    def test_refuses_output_inside_mods(self):
        with self.assertRaises(ValueError):
            builder.build_server(self.a, os.path.join(self.mods, "out"))
        with self.assertRaises(ValueError):
            builder.build_server(self.a, self.mods)

    def test_refuses_non_empty_output(self):
        out = os.path.join(self.root, "full")
        os.makedirs(out)
        open(os.path.join(out, "x.txt"), "w").close()
        with self.assertRaises(FileExistsError):
            builder.build_server(self.a, out)

    def test_suggest_output_dir_is_free(self):
        first = builder.suggest_output_dir(self.mods)
        os.makedirs(first)
        self.assertNotEqual(builder.suggest_output_dir(self.mods), first)

    def test_include_exclude(self):
        out = os.path.join(self.root, "o")
        builder.build_server(self.a, out, exclude=["keep.jar"], include=["sodium.jar"])
        self.assertEqual(os.listdir(out), ["sodium.jar"])


class LogTests(unittest.TestCase):
    def test_neoforge_missing_and_wrong_version(self):
        text = (
            "Missing or unsupported mandatory dependencies:\n"
            "\tMod ID: 'arch', Requested by: 'x', Expected range: '[13,)', Actual version: '[MISSING]'\n"
            "\tMod ID: 'curios', Requested by: 'y', Expected range: '[10,)', Actual version: '9.0'\n")
        codes = {f["code"] for f in logscan.scan_text(text)}
        self.assertEqual(codes, {"missing-dep", "wrong-version"})

    def test_fabric_missing(self):
        text = "Mod 'Foo' (foo) 1.0 requires any version of mod 'Bar' (bar), which is missing!"
        (f,) = logscan.scan_text(text)
        self.assertEqual(f["mods"], ["bar", "foo"])

    def test_java_and_memory_and_dist(self):
        text = ("UnsupportedClassVersionError: x has been compiled by a more recent version "
                "(class file version 65.0)\njava.lang.OutOfMemoryError: Java heap space\n"
                "Attempted to load class net/minecraft/client/gui/Screen for invalid dist DEDICATED_SERVER")
        codes = {f["code"] for f in logscan.scan_text(text)}
        self.assertEqual(codes, {"java", "memory", "client-on-server"})

    def test_clean_log(self):
        self.assertEqual(logscan.scan_text("[INFO] Done (3.2s)! For help, type \"help\""), [])


class DemoEndToEnd(unittest.TestCase):
    def test_demo_pack(self):
        with tempfile.TemporaryDirectory() as d:
            demo.build_demo(d)
            folder, _ = parser.resolve_source(d)
            jars, extras = parser.scan_folder(folder)
            a = analyzer.analyze(jars, extras, d, folder)
            res = a.to_dict()
            self.assertEqual(res["loader"], "neoforge")
            kinds = {i["id"].split(":")[0] for i in res["issues"]}
            self.assertTrue({"dup", "missing", "version", "incompat", "known", "loader", "mc", "file", "nometa"} <= kinds)
            self.assertEqual(ids(a, "missing:gearlib"), [])  # fourni en jar-in-jar
            self.assertTrue(logscan.find_logs(folder))


if __name__ == "__main__":
    unittest.main()
