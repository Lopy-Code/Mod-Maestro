"""Lecture fine des crashs : pile d'erreur -> mod fautif."""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import cache, pipeline, stacktrace  # noqa: E402
from test_core import neo  # noqa: E402

JARS = {"mymod-1.0.jar": {"modids": ["mymod"], "name": "My Mod"},
        "other-2.0.jar": {"modids": ["othermod"], "name": "Other Mod"},
        "lib-1.jar": {"modids": ["somelib"], "name": "Some Lib"}}


def crash(*frames, exc="java.lang.NullPointerException: boom", extra=""):
    return "---- Minecraft Crash Report ----\nDescription: Ticking entity\n\n" + exc + "\n" + "\n".join("\t" + f for f in frames) + "\n" + extra


def top(res):
    return [(s["modid"], s["confidence"]) for s in res["suspects"]]


class Attribution(unittest.TestCase):
    def test_suspected_mods_section_is_certain(self):
        text = crash("at net.minecraft.world.Level.tick(Level.java:1)",
                     extra="\nSuspected Mods: \n\tMy Mod (mymod), Version: 1.0\n\t\tIssue tracker URL: https://x\n")
        res = stacktrace.attribute(text, None, JARS)
        self.assertEqual(top(res)[0], ("mymod", "certain"))
        self.assertEqual(stacktrace.attribute(crash("at a.B.c(B.java:1)", extra="\nSuspected Mods: \n\tNone\n"), None, JARS)["suspects"], [])

    def test_jar_name_and_module_hints(self):
        text = crash("at knot//com.x.Foo.tick(Foo.java:42) ~[mymod-1.0.jar%23123!/:1.0] {re:classloading}",
                     "at net.minecraft.server.Main.run(Main.java:1) ~[client-extra.jar:?] {re:mixin}",
                     "at TRANSFORMER/othermod@2.0/com.o.Bar.run(Bar.java:5)")
        res = stacktrace.attribute(text, None, JARS)
        self.assertEqual({s["modid"] for s in res["suspects"]}, {"mymod", "othermod"})   # client-extra.jar : inconnu, ignoré
        self.assertTrue(all(s["confidence"] == "likely" for s in res["suspects"]))
        self.assertIn("mymod-1.0.jar", res["suspects"][0]["evidence"][0] + res["suspects"][1]["evidence"][0])

    def test_mixin_handler_names(self):
        text = crash("at net.minecraft.server.Main.handler$zbc000$othermod$onTick(Main.java:1)",
                     "at net.minecraft.server.Main.mymod$inject(Main.java:2)", "at net.minecraft.server.Main.tick(Main.java:3)")
        self.assertEqual({s["modid"] for s in stacktrace.attribute(text, None, JARS)["suspects"]}, {"othermod", "mymod"})

    def test_root_cause_outweighs_wrapper_and_library_frames_are_ignored(self):
        text = ("java.lang.RuntimeException: wrapper\n\tat TRANSFORMER/mymod@1.0/com.m.Wrap.go(Wrap.java:1)\n"
                "\tat java.base/java.lang.Thread.run(Thread.java:840)\n"
                "Caused by: java.lang.IllegalStateException: real\n\tat TRANSFORMER/othermod@2.0/com.o.Real.go(Real.java:9)\n"
                "\tat org.spongepowered.asm.mixin.Foo.bar(Foo.java:1)\n\t... 12 more\n")
        res = stacktrace.attribute(text, None, JARS)
        self.assertEqual(res["suspects"][0]["modid"], "othermod")
        self.assertTrue(res["root"].startswith("Caused by: java.lang.IllegalStateException"))
        self.assertNotIn("minecraft", {s["modid"] for s in res["suspects"]})

    def test_repeated_log_spam_counts_once(self):
        one = crash("at TRANSFORMER/mymod@1.0/com.m.A.go(A.java:1)")
        two = crash("at TRANSFORMER/othermod@2.0/com.o.B.go(B.java:1)")
        res = stacktrace.attribute(one * 50 + two, None, JARS)
        self.assertEqual({s["modid"]: s["score"] for s in res["suspects"]}["mymod"], {s["modid"]: s["score"] for s in res["suspects"]}["othermod"])

    def test_package_segment_fallback_without_index(self):
        text = crash("at com.example.createaddition.Foo.tick(Foo.java:1)")
        res = stacktrace.attribute(text, None, None, modids={"createaddition", "a"})
        self.assertEqual(top(res), [("createaddition", "likely")])
        self.assertEqual(stacktrace.attribute(text)["suspects"], [])   # aucun mod connu : aucune devinette

    def test_class_index_and_shared_packages(self):
        index = {"com.m.entity": {"mymod-1.0.jar"}, "com.shared": {"mymod-1.0.jar", "other-2.0.jar"}}
        res = stacktrace.attribute(crash("at com.m.entity.Foo.tick(Foo.java:1)"), index, JARS)
        self.assertEqual(top(res), [("mymod", "likely")])
        self.assertEqual(stacktrace.attribute(crash("at com.shared.Foo.tick(Foo.java:1)"), index, JARS)["suspects"], [])  # ambigu

    def test_garbage_input(self):
        for text in ("", "rien à voir", "\tat \n\tat (\n" * 5, "Caused by: \n" * 3):
            self.assertEqual(stacktrace.attribute(text, None, JARS)["suspects"], [])


class Integration(unittest.TestCase):
    def test_real_jar_index_and_boot_crash_message(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("MODMAESTRO_HOME")
            os.environ["MODMAESTRO_HOME"] = os.path.join(d, "home")
            cache.reset_default()
            try:
                inst = os.path.join(d, "inst")
                mods = os.path.join(inst, "mods")
                os.makedirs(mods)
                os.makedirs(os.path.join(inst, "logs"))
                neo(mods, "alpha.jar", "alpha")
                neo(mods, "beta.jar", "beta")
                with zipfile.ZipFile(os.path.join(mods, "alpha.jar"), "a") as zf:
                    zf.writestr("net/alpha/core/Thing.class", b"\xca\xfe")
                with zipfile.ZipFile(os.path.join(mods, "beta.jar"), "a") as zf:
                    zf.writestr("org/beta/Other.class", b"\xca\xfe")
                log = crash("at net.alpha.core.Thing.tick(Thing.java:7)", "at net.minecraft.server.Main.run(Main.java:1)",
                            exc="java.lang.IllegalStateException: Cannot load")
                with open(os.path.join(inst, "logs", "latest.log"), "w") as fh:
                    fh.write(log + "\n[main/ERROR]: Crash report saved\n")
                a = pipeline.run_analysis(mods)
                res = stacktrace.from_analysis(a, log)
                self.assertEqual([(s["modid"], s["file"]) for s in res["suspects"]], [("alpha", "alpha.jar")])
                self.assertIn("alpha.jar", res["suspects"][0]["evidence"][0])
                self.assertEqual(sorted(a._class_index["net.alpha.core"]), ["alpha.jar"])
                self.assertEqual(a.boot is None or a.boot.get("status") in ("crashed", "unknown", None), True)
            finally:
                cache.reset_default()
                os.environ.pop("MODMAESTRO_HOME", None) if old is None else os.environ.__setitem__("MODMAESTRO_HOME", old)


if __name__ == "__main__":
    unittest.main()
