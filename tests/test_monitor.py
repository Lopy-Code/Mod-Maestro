"""Surveillance d'un serveur en cours (lecture de latest.log au fil de l'eau)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import monitor  # noqa: E402

JARS = {"create-1.jar": {"modids": ["create"], "name": "Create"}, "lib-1.jar": {"modids": ["somelib"], "name": "Some Lib"}}


def hdr(level, msg, logger="minecraft/MinecraftServer", t="12:00:00", thread="Server thread"):
    return f"[{t}] [{thread}/{level}] [{logger}]: {msg}\n"


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.d.name, "logs", "latest.log")
        os.makedirs(os.path.dirname(self.log))
        self.write("")
        self.m = monitor.Monitor(self.log, JARS)

    def tearDown(self):
        self.d.cleanup()

    def write(self, text, mode="w"):
        with open(self.log, mode, encoding="utf-8") as fh:
            fh.write(text)

    def add(self, text):
        self.write(text, "a")
        return self.m.poll()

    def alerts(self, snap):
        return {a["id"]: a for a in snap["alerts"]}

    def test_waiting_then_active(self):
        os.remove(self.log)
        self.assertEqual(self.m.poll()["status"], "waiting")
        self.write(hdr("INFO", 'Done (4.2s)! For help, type "help"'))
        s = self.m.poll()
        self.assertEqual((s["status"], s["stats"]["started"]), ("active", True))

    def test_lag_and_hang_and_memory(self):
        s = self.add(hdr("WARN", "Can't keep up! Is the server overloaded? Running 5123ms or 102 ticks behind") * 3
                     + hdr("WARN", "A single server tick took 60.00 seconds (should be max 0.05)")
                     + hdr("ERROR", "Server crashed") + "java.lang.OutOfMemoryError: Java heap space\n")
        s = self.m.poll()   # 2e relève : la pile en attente est analysée
        a = self.alerts(s)
        self.assertEqual(a["lag"]["count"], 3)
        self.assertEqual(s["stats"]["lag"], 3)
        self.assertEqual(a["hang"]["severity"], "error")
        self.assertIn("memory", a)

    def test_logger_blames_installed_mod_and_escalates(self):
        for i in range(5):
            s = self.add(hdr("ERROR", f"Failed to tick block entity {i}", logger="Create/"))
        s = self.m.poll()
        self.m.poll()
        a = self.alerts(self.m.snapshot())
        self.assertIn("mod:create", a)
        self.assertEqual((a["mod:create"]["severity"], a["mod:create"]["mods"]), ("warning", ["create"]))
        for i in range(20):
            self.add(hdr("ERROR", "again", logger="com.simibubi.create.Foo/".replace("com.simibubi.", "")))
        self.m.poll(); self.m.poll()
        self.assertEqual(self.alerts(self.m.snapshot())["mod:create"]["severity"], "error")

    def test_stack_trace_attribution_across_polls(self):
        self.add(hdr("ERROR", "Encountered an unexpected exception") + "java.lang.IllegalStateException: boom\n")
        s = self.add("\tat TRANSFORMER/create@1.0/com.x.Foo.tick(Foo.java:3)\n\tat net.minecraft.server.Main.run(Main.java:1)\n")
        for _ in range(3):
            s = self.m.poll()
        self.assertEqual(self.m.errors_by_mod, {"create": 1})
        self.assertNotIn("mod:create", self.alerts(s))                    # 1 erreur : pas encore d'alerte (seuil 5)
        for i in range(4):
            self.add(hdr("ERROR", "x") + "java.lang.IllegalStateException: boom\n\tat TRANSFORMER/create@1.0/a.B.c(B.java:1)\n")
        for _ in range(3):
            s = self.m.poll()
        self.assertEqual(self.alerts(s)["mod:create"]["count"], 1)
        self.assertIn("create", self.alerts(s)["mod:create"]["mods"])

    def test_unknown_errors_are_grouped_without_numbers(self):
        for i in range(4):
            self.add(hdr("ERROR", f"Could not save chunk [{i}, {i * 7}]", logger="minecraft/Chunk"))
        self.m.poll(); s = self.m.poll()
        generic = [a for a in s["alerts"] if a["code"] == "error"]
        self.assertEqual((len(generic), generic[0]["count"]), (1, 4))
        self.assertEqual(generic[0]["mods"], [])

    def test_partial_lines_wait_for_newline(self):
        self.write(hdr("WARN", "Can't keep up! Running 3000ms or 60 ticks behind").rstrip("\n"), "w")   # pas de \n final
        self.assertEqual(self.m.poll()["stats"]["lag"], 0)
        self.write("\n", "a")
        self.assertEqual(self.m.poll()["stats"]["lag"], 1)
        self.assertEqual(self.m.poll()["stats"]["lag"], 1)                  # jamais relu deux fois

    def test_restart_resets_offset_and_notes_it(self):
        self.add(hdr("INFO", "x") * 50)
        self.write(hdr("INFO", 'Done (1.0s)! For help, type "help"'))        # fichier recréé, plus court
        s = self.m.poll()
        self.assertEqual(s["stats"]["restarts"], 1)
        self.assertTrue(s["stats"]["started"])
        self.assertIn("restart:1", self.alerts(s))

    def test_backlog_only_reads_the_end_and_skips_cut_line(self):
        old = monitor.BACKLOG
        monitor.BACKLOG = 400
        try:
            self.write("".join(hdr("WARN", f"Can't keep up! Running {i}ms or 60 ticks behind") for i in range(200)))
            m = monitor.Monitor(self.log, JARS)
            s = m.poll()
            self.assertLess(s["stats"]["lag"], 10)
            self.assertGreater(s["stats"]["lag"], 0)
            self.assertIn("199 ms", self.alerts(s)["lag"]["message"])
        finally:
            monitor.BACKLOG = old

    def test_resolve_log(self):
        root = self.d.name
        os.makedirs(os.path.join(root, "mods"))
        self.assertEqual(monitor.resolve_log(root), self.log)
        self.assertEqual(monitor.resolve_log(os.path.join(root, "mods")), self.log)
        self.assertEqual(monitor.resolve_log(os.path.join(root, "logs")), self.log)
        self.assertEqual(monitor.resolve_log(self.log), self.log)
        self.assertEqual(monitor.resolve_log("", os.path.join(root, "mods")), self.log)
        for bad in ("", os.path.join(root, "nope")):
            with self.assertRaises(ValueError):
                monitor.resolve_log(bad)
        secret = os.path.join(root, "id_rsa")
        open(secret, "w").close()
        with self.assertRaises(ValueError):
            monitor.resolve_log(secret)                                      # seuls les .log / .txt


if __name__ == "__main__":
    unittest.main()
