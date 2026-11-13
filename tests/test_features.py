"""Tests des nouvelles fonctions : comparaison, crash finder, export, kit serveur, conseils, rapport HTML, contribution."""

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import compare, contribute, crashfinder, export, htmlreport, learn, modrinth, pipeline, recommend, serverkit  # noqa: E402
from core.cache import Cache  # noqa: E402
from test_core import make_jar, neo, run  # noqa: E402
from test_online import FakeModrinth, proj, ver  # noqa: E402


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.mods = os.path.join(self.d, "mods")
        os.makedirs(self.mods)

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, n=4, **kw):
        for i in range(n):
            neo(self.mods, f"m{i}.jar", f"m{i}", **kw)
        return run(self.mods)


class CompareTests(Tmp):
    def test_added_removed_updated_and_issues(self):
        a_dir, b_dir = os.path.join(self.d, "a"), os.path.join(self.d, "b")
        os.makedirs(a_dir)
        os.makedirs(b_dir)
        neo(a_dir, "keep.jar", "keep", "1.0")
        neo(a_dir, "gone.jar", "gone", "1.0")
        neo(a_dir, "up.jar", "up", "1.0")
        neo(a_dir, "down.jar", "down", "2.0")
        neo(b_dir, "keep.jar", "keep", "1.0")
        neo(b_dir, "new.jar", "new", "1.0", deps=[("ghost", "required", "*")])
        neo(b_dir, "up.jar", "up", "1.5")
        neo(b_dir, "down.jar", "down", "1.0")
        res = compare.compare(run(a_dir).to_dict(), run(b_dir).to_dict())
        self.assertEqual([m["modid"] for m in res["added"]], ["new"])
        self.assertEqual([m["modid"] for m in res["removed"]], ["gone"])
        self.assertEqual([(m["modid"], m["from"], m["to"]) for m in res["updated"]], [("up", "1.0", "1.5")])
        self.assertEqual([m["modid"] for m in res["downgraded"]], ["down"])
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual([i["id"] for i in res["new_issues"]], ["missing:ghost"])
        self.assertLess(res["score_delta"], 0)

    def test_identical_packs(self):
        a = self.pack(3).to_dict()
        res = compare.compare(a, a)
        self.assertEqual((res["added"], res["removed"], res["updated"], res["new_issues"], res["unchanged"]), ([], [], [], [], 3))


class CrashFinderTests(Tmp):
    def build(self, n, culprit=None, deps=None):
        for i in range(n):
            neo(self.mods, f"m{i:02d}.jar", f"m{i:02d}", deps=(deps or {}).get(i, ()))
        return run(self.mods)

    def play(self, a, culprit_files):
        """Simule l'utilisateur : le jeu plante si un fichier fautif est dans le test. Retourne (état, nb d'essais)."""
        st = crashfinder.start(a)
        guard = 0
        while not st["done"]:
            guard += 1
            self.assertLess(guard, 30)
            files = set(st["pending"]["files"])
            st = crashfinder.answer(a, st, "crash" if files & set(culprit_files) else "fine")
        return st, guard

    def test_finds_a_single_culprit_in_log2_steps(self):
        a = self.build(64)
        st, tries = self.play(a, {"m37.jar"})
        self.assertEqual(st["result"], {"kind": "single", "files": ["m37.jar"], "confirmed": True})
        self.assertLessEqual(tries, 8)  # 6 coupes + la contre-épreuve

    def test_dependencies_are_kept_with_their_half(self):
        deps = {10: [("m50", "required", "*")]}  # m10 a besoin de m50
        a = self.build(64, deps=deps)
        st = crashfinder.start(a)
        first = st["pending"]["files"]
        if "m10.jar" in first:
            self.assertIn("m50.jar", first)  # sans sa dépendance, le test serait faussé
        st, _ = self.play(a, {"m10.jar"})
        self.assertIn("m10.jar", st["result"]["files"])

    def test_a_culprit_in_a_dependency_chain_ends_as_a_group_or_single(self):
        deps = {i: [(f"m{i + 1:02d}", "required", "*")] for i in range(0, 5)}
        a = self.build(8, deps=deps)
        st, _ = self.play(a, {"m03.jar"})
        self.assertTrue(st["done"])
        self.assertIn("m03.jar", st["result"]["files"])

    def test_a_pair_of_mods_is_resolved_by_removing_either_one(self):
        a = self.build(16)
        st = crashfinder.start(a)
        while not st["done"]:
            files = set(st["pending"]["files"])
            st = crashfinder.answer(a, st, "crash" if {"m02.jar", "m13.jar"} <= files else "fine")
        self.assertEqual(st["result"]["kind"], "single")  # retirer l'un des deux suffit : c'est un vrai correctif
        self.assertTrue(st["result"]["confirmed"])

    def test_a_crash_that_is_not_caused_by_a_mod_is_never_blamed_on_one(self):
        a = self.build(16)
        st = crashfinder.start(a)
        while not st["done"]:
            st = crashfinder.answer(a, st, "crash")  # plante quoi qu'on fasse (Java, mémoire…)
        self.assertEqual(st["result"]["kind"], "unconfirmed")
        self.assertIn("pas un mod", crashfinder.summary(a, st))

    def test_test_folder_is_a_copy_and_never_the_source(self):
        a = self.build(8)
        st = crashfinder.start(a)
        out = os.path.join(self.d, "test1")
        res = crashfinder.build_test_folder(a, st, out)
        self.assertEqual(sorted(os.listdir(out)), sorted(st["pending"]["files"]))
        self.assertEqual(res["copied"], len(st["pending"]["files"]))
        self.assertEqual(len(os.listdir(self.mods)), 8)  # source intacte
        with self.assertRaises(FileExistsError):
            crashfinder.build_test_folder(a, st, out)
        with self.assertRaises(ValueError):
            crashfinder.build_test_folder(a, st, self.mods)
        with self.assertRaises(ValueError):
            crashfinder.build_test_folder(a, st, os.path.join(self.mods, "sub"))

    def test_skip_does_not_loop_and_bad_answers_are_refused(self):
        a = self.build(8)
        st = crashfinder.start(a)
        st = crashfinder.answer(a, st, "skip")
        self.assertFalse(st["done"])
        with self.assertRaises(ValueError):
            crashfinder.answer(a, st, "maybe")

    def test_quick_suspects_use_the_log_then_recent_files(self):
        a = self.build(6)
        old = time.time() - 30 * 86400
        for i in range(6):
            os.utime(os.path.join(self.mods, f"m{i:02d}.jar"), (old, old))
        os.utime(os.path.join(self.mods, "m04.jar"), None)
        a = run(self.mods)
        rows = crashfinder.quick_suspects(a, log_mods=["m01"])
        self.assertEqual(rows[0]["file"], "m01.jar")
        self.assertIn("m04.jar", [r["file"] for r in rows])


class ExportTests(Tmp):
    def online_pack(self):
        fake = FakeModrinth()
        self.addCleanup(fake.close)
        for k in "ab":
            neo(self.mods, f"{k}.jar", f"mod{k}")
            sha = modrinth.sha1_file(os.path.join(self.mods, f"{k}.jar"))
            fake.versions[sha] = ver(f"v-{k}", f"P-{k}", "1.0", file_hash=sha)
            fake.projects[f"P-{k}"] = proj(f"P-{k}", f"slug-{k}", f"Mod {k}", cs="required", ss="unsupported" if k == "b" else "required")
        neo(self.mods, "private.jar", "privatemod")  # inconnu de Modrinth
        cache = Cache(":memory:")
        self.addCleanup(cache.close)
        a = pipeline.run_analysis(self.mods, online=True, cache=cache, client=fake.client())
        return a

    def test_mrpack_is_valid_and_references_known_mods(self):
        a = self.online_pack()
        out = os.path.join(self.d, "out", "pack.mrpack")
        res = export.export_mrpack(a, out, name="Mon pack", mc="1.21.1", loader="neoforge", loader_version="21.1.172")
        self.assertEqual((res["referenced"], res["embedded"]), (2, 1))
        with zipfile.ZipFile(res["path"]) as zf:
            idx = json.loads(zf.read("modrinth.index.json"))
            self.assertIn("overrides/mods/private.jar", zf.namelist())
        self.assertEqual(idx["formatVersion"], 1)
        self.assertEqual(idx["dependencies"], {"minecraft": "1.21.1", "neoforge": "21.1.172"})
        f = {x["path"]: x for x in idx["files"]}["mods/b.jar"]
        self.assertEqual(f["env"], {"client": "required", "server": "unsupported"})
        self.assertTrue(f["downloads"][0].startswith("https://cdn.modrinth.com/"))
        self.assertEqual(len(f["hashes"]["sha512"]), 128)
        self.assertEqual(f["hashes"]["sha1"], modrinth.sha1_file(os.path.join(self.mods, "b.jar")))  # empreinte locale, pas celle de l'API

    def test_unknown_mods_can_be_left_out(self):
        a = self.online_pack()
        res = export.export_mrpack(a, os.path.join(self.d, "p.mrpack"), name="x", mc="1.21.1", loader="neoforge",
                                   loader_version="1", include_unknown=False)
        self.assertEqual((res["embedded"], res["skipped"]), (0, ["private.jar"]))

    def test_hosts_not_allowed_by_the_spec_are_never_referenced(self):
        a = self.online_pack()
        for e in a.entries.values():
            if e.get("online"):
                e["online"]["download"] = {"url": "https://evil.example/x.jar", "size": 1}
        res = export.export_mrpack(a, os.path.join(self.d, "p.mrpack"), name="x", mc="1.21.1", loader="neoforge", loader_version="1")
        self.assertEqual((res["referenced"], res["embedded"]), (0, 3))

    def test_validation_and_safety(self):
        a = self.pack(2)
        with self.assertRaises(ValueError):
            export.export_mrpack(a, os.path.join(self.d, "p.mrpack"), name="x", loader_version="")
        with self.assertRaises(ValueError):
            export.export_mrpack(a, os.path.join(self.mods, "p.mrpack"), name="x", loader_version="1")
        out = os.path.join(self.d, "p.mrpack")
        res = export.export_mrpack(a, out, name="x", loader_version="1")
        self.assertTrue(res["warnings"])  # hors ligne : tout est embarqué, et c'est dit
        with self.assertRaises(FileExistsError):
            export.export_mrpack(a, out, name="x", loader_version="1")

    def test_zip_export(self):
        a = self.pack(3)
        res = export.export_zip(a, os.path.join(self.d, "z"), ["m0.jar", "m1.jar", "nope.jar"])
        with zipfile.ZipFile(res["path"]) as zf:
            self.assertEqual(sorted(zf.namelist()), ["mods/m0.jar", "mods/m1.jar"])

    def test_detect_prism_instance(self):
        inst = os.path.join(self.d, "inst")
        os.makedirs(os.path.join(inst, "minecraft", "mods"))
        Path(os.path.join(inst, "mmc-pack.json")).write_text(json.dumps({"components": [{"uid": "net.minecraft", "version": "1.21.1"}, {"uid": "net.neoforged", "version": "21.1.172"}]}))
        self.assertEqual(export.detect_instance(os.path.join(inst, "minecraft", "mods")),
                         {"mc": "1.21.1", "loader": "neoforge", "loader_version": "21.1.172"})
        self.assertEqual(export.detect_instance(self.mods), {})


class ServerKitTests(Tmp):
    def test_kit_files_and_rules(self):
        a = self.pack(5)
        neo(self.mods, "client.jar", "sodium")
        a = run(self.mods)
        out = os.path.join(self.d, "srv")
        res = serverkit.generate(a, out, with_mods=True, eula=False, port=25570, max_players=8, motd="Mon = serveur\n#x")
        self.assertEqual((res["mode"], res["java"]), ("modern", 21))
        self.assertNotIn("client.jar", os.listdir(os.path.join(out, "mods")))  # mod client exclu du serveur
        self.assertIn("eula=false", Path(os.path.join(out, "eula.txt")).read_text())
        props = Path(os.path.join(out, "server.properties")).read_text()
        self.assertIn("server-port=25570", props)
        self.assertIn("motd=Mon  serveurx\n", props)  # = # \\ : retirés pour ne pas casser le fichier
        self.assertIn("-Xms3G", Path(os.path.join(out, "user_jvm_args.txt")).read_text())
        self.assertTrue(os.stat(os.path.join(out, "start.sh")).st_mode & stat.S_IXUSR)
        self.assertEqual(len(os.listdir(self.mods)), 6)  # source intacte

    def test_eula_only_when_accepted_and_existing_files_are_kept(self):
        a = self.pack(2)
        out = os.path.join(self.d, "srv")
        os.makedirs(out)
        Path(os.path.join(out, "server.properties")).write_text("mine")
        res = serverkit.generate(a, out, eula=True)
        self.assertIn("eula=true", Path(os.path.join(out, "eula.txt")).read_text())
        self.assertEqual(Path(os.path.join(out, "server.properties")).read_text(), "mine")
        self.assertEqual(res["skipped"], ["server.properties"])

    def test_inputs_are_validated(self):
        a = self.pack(2)
        for bad in ({"port": 0}, {"port": 70000}, {"max_players": 0}, {"ram_gb": 999}, {"view_distance": 1}):
            with self.assertRaises(ValueError):
                serverkit.generate(a, os.path.join(self.d, "x"), **bad)
        with self.assertRaises(ValueError):
            serverkit.generate(a, self.mods)

    def test_java_ram_and_modes(self):
        self.assertEqual([serverkit.java_for_mc(v) for v in ("1.21.1", "1.20.4", "1.20.5", "1.17.1", "1.16.5")], [21, 17, 21, 16, 8])
        self.assertEqual((serverkit.estimate_ram_gb(5), serverkit.estimate_ram_gb(100), serverkit.estimate_ram_gb(9999)), (3, 6, 16))
        self.assertIn("-XX:G1HeapRegionSize=16M", serverkit.jvm_flags(16))
        self.assertIn("-XX:G1HeapRegionSize=8M", serverkit.jvm_flags(6))
        self.assertEqual([serverkit._mode(l, m) for l, m in (("fabric", "1.21"), ("forge", "1.16.5"), ("forge", "1.20.1"), ("neoforge", "1.21"))],
                         ["fabric", "legacy", "modern", "modern"])

    @unittest.skipIf(sys.platform.startswith("win"), "bash requis")
    def test_start_script_checks_java_and_runs_the_loader_script(self):
        a = self.pack(2)
        out = os.path.join(self.d, "srv")
        serverkit.generate(a, out)
        fakebin = os.path.join(self.d, "bin")
        os.makedirs(fakebin)
        for ver_text, name in (('openjdk version "17.0.2" 2022', "old"), ('openjdk version "21.0.1" 2023', "new")):
            os.makedirs(os.path.join(fakebin, name))
            p = os.path.join(fakebin, name, "java")
            Path(p).write_text(f"#!/bin/sh\necho '{ver_text}' >&2\n")
            os.chmod(p, 0o755)
        Path(os.path.join(out, "run.sh")).write_text("echo STARTED \"$@\"\n")
        env = {**os.environ}
        r_old = subprocess.run(["bash", os.path.join(out, "start.sh")], capture_output=True, text=True,
                               env={**env, "PATH": os.path.join(fakebin, "old") + os.pathsep + env["PATH"]})
        self.assertNotEqual(r_old.returncode, 0)
        self.assertNotIn("STARTED", r_old.stdout)
        r_new = subprocess.run(["bash", os.path.join(out, "start.sh")], capture_output=True, text=True,
                               env={**env, "PATH": os.path.join(fakebin, "new") + os.pathsep + env["PATH"]})
        self.assertEqual(r_new.returncode, 0, r_new.stderr)
        self.assertIn("STARTED nogui", r_new.stdout)


class RecommendTests(Tmp):
    def test_suggestions_follow_the_pack(self):
        a = self.pack(25)
        ids = [i["id"] for i in recommend.run(a)["items"]]
        self.assertIn("modernfix", ids)
        self.assertIn("sodium", ids)       # NeoForge : Sodium existe
        self.assertNotIn("embeddium", ids)  # un seul moteur de rendu proposé
        self.assertEqual([i["alternatives"] for i in recommend.run(a)["items"] if i["id"] == "sodium"], [["Embeddium"]])
        self.assertNotIn("iris", ids)       # Iris demande Sodium installé
        neo(self.mods, "sodium.jar", "sodium")
        ids = [i["id"] for i in recommend.run(run(self.mods))["items"]]
        self.assertNotIn("sodium", ids)
        self.assertIn("iris", ids)
        self.assertIn("sodium-extra", ids)

    def test_installed_or_conflicting_mods_are_not_suggested(self):
        neo(self.mods, "o.jar", "optifine")
        for i in range(25):
            neo(self.mods, f"m{i}.jar", f"m{i}")
        neo(self.mods, "mf.jar", "modernfix")
        ids = [i["id"] for i in recommend.run(run(self.mods))["items"]]
        self.assertNotIn("sodium", ids)
        self.assertNotIn("modernfix", ids)

    def test_bridge_is_suggested_only_with_foreign_mods(self):
        for i in range(3):
            neo(self.mods, f"n{i}.jar", f"n{i}")
        self.assertNotIn("connector", [i["id"] for i in recommend.run(run(self.mods))["items"]])
        make_jar(self.mods, "fab.jar", {"fabric.mod.json": json.dumps({"id": "fab", "version": "1"})})
        self.assertIn("connector", [i["id"] for i in recommend.run(run(self.mods))["items"]])

    def test_online_verification_marks_availability_and_uses_cache(self):
        fake = FakeModrinth()
        self.addCleanup(fake.close)
        a = self.pack(25)
        a.mc_version = "1.21.1"
        fake.by_slug["modernfix"] = [ver("v1", "P", "5.0", gv=("1.21.1",))]
        cache = Cache(":memory:")
        self.addCleanup(cache.close)
        res = recommend.run(a, online=True, client=fake.client(), cache=cache)
        by = {i["id"]: i for i in res["items"]}
        self.assertTrue(by["modernfix"]["available"])
        self.assertEqual(by["modernfix"]["version"], "5.0")
        self.assertFalse(by["ferritecore"]["available"])
        self.assertTrue(res["verified"])
        self.assertEqual(res["items"][-1]["available"], False)  # indisponibles en dernier
        # le groupe « moteur de rendu » : Sodium indisponible, Embeddium disponible → c'est Embeddium qui est proposé
        fake.by_slug["embeddium"] = [ver("e1", "P", "1.0", gv=("1.21.1",))]
        cache2 = Cache(":memory:")
        self.addCleanup(cache2.close)
        res2 = recommend.run(a, online=True, client=fake.client(), cache=cache2)
        self.assertEqual([i["id"] for i in res2["items"] if i["group"] == "renderer"], ["embeddium"])
        n = len(fake.calls)
        recommend.run(a, online=True, client=fake.client(), cache=cache)
        self.assertEqual(len(fake.calls), n)  # tout vient du cache

    def test_data_file_is_consistent(self):
        rules = recommend.load_rules()
        self.assertEqual(len({r["id"] for r in rules}), len(rules))
        for r in rules:
            self.assertTrue(r["why"] and r["why_en"], r["id"])
            self.assertIn(r["category"], recommend.CATEGORIES)
            self.assertTrue(r["loaders"] and set(r["loaders"]) <= {"neoforge", "forge", "fabric", "quilt"})
            self.assertIn(r["side"], ("client", "server", "both"))


class HtmlReportTests(Tmp):
    def test_report_is_standalone_escaped_and_private(self):
        neo(self.mods, "evil.jar", "evil", name='<script>alert(1)</script>', deps=[("ghost", "required", "*")])
        for i in range(3):
            neo(self.mods, f"m{i}.jar", f"m{i}")
        d = run(self.mods).to_dict()
        html = htmlreport.to_html(d)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn(self.d, html)  # pas de chemin local
        self.assertNotRegex(html, r'(src|href)="https?://')  # aucune ressource externe
        self.assertIn("ghost", html)
        self.assertIn("evil.jar", html)
        hidden = htmlreport.to_html(d, include_files=False)
        self.assertNotIn("evil.jar", hidden)
        with_src = htmlreport.to_html(d, include_source=True)
        self.assertIn(e_(d["source"]), with_src)

    def test_summary_text(self):
        neo(self.mods, "b.jar", "needy", deps=[("ghost", "required", "*")])
        s = htmlreport.discord_summary(run(self.mods).to_dict())
        self.assertIn("ModMaestro", s)
        self.assertIn("Dépendance manquante", s)

    def test_ignored_issues_are_not_listed_as_problems(self):
        neo(self.mods, "b.jar", "needy", deps=[("ghost", "required", "*")])
        a = run(self.mods)
        a.ignored_ids = {"missing:ghost"}
        html = htmlreport.to_html(a.to_dict())
        self.assertNotIn("Dépendance manquante", html)
        self.assertIn("ignorée", html)


def e_(s):
    import html
    return html.escape(s, quote=True)


class ContributeTests(unittest.TestCase):
    def setUp(self):
        self.cache = Cache(":memory:")
        self.env = dict(os.environ)

    def tearDown(self):
        self.cache.close()
        os.environ.clear()
        os.environ.update(self.env)

    def test_empty_base_is_refused(self):
        with self.assertRaises(ValueError):
            contribute.build(self.cache)

    def test_builds_issue_and_files_without_leaking_paths(self):
        os.environ["MODMAESTRO_REPO"] = "https://github.com/me/Mod-Maestro/"
        learn.add_conflict(self.cache, "a", "b", "plante au démarrage")
        learn.add_side(self.cache, "c", "client")
        learn.add_ignore(self.cache, "missing:x")  # ne doit jamais être proposé
        res = contribute.build(self.cache, context={"loader": "neoforge", "mc_version": "1.21.1"})
        self.assertEqual(res["count"], 2)
        self.assertEqual(sorted(res["files"]), ["conflicts/a__b.json", "sides/c.json"])
        self.assertTrue(res["url"].startswith("https://github.com/me/Mod-Maestro/issues/new?title="))
        self.assertTrue(res["body_in_url"])
        self.assertIn("plante au démarrage", res["body"])
        self.assertNotIn("missing:x", res["body"])

    def test_without_repo_there_is_no_url_and_long_bodies_drop_the_body_from_the_url(self):
        os.environ.pop("MODMAESTRO_REPO", None)
        learn.add_conflict(self.cache, "a", "b", "x")
        self.assertIsNone(contribute.build(self.cache)["url"])
        os.environ["MODMAESTRO_REPO"] = "https://github.com/me/r"
        for i in range(80):
            learn.add_conflict(self.cache, f"mod{i}", f"other{i}", "long " * 20)
        res = contribute.build(self.cache)
        self.assertFalse(res["body_in_url"])
        self.assertLess(len(res["url"]), contribute.MAX_URL)


if __name__ == "__main__":
    unittest.main()
