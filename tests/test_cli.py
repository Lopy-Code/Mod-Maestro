"""Tests de la ligne de commande (sous-processus réels) : options v1.2, langue, et surtout :
aucune commande n'écrit dans le dossier de mods analysé."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_core import neo  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def snapshot(folder):
    out = {}
    for d, _dirs, files in os.walk(folder):
        for f in files:
            p = os.path.join(d, f)
            st = os.stat(p)
            out[os.path.relpath(p, folder)] = (st.st_size, st.st_mtime_ns)
    return out


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = cls.tmp.name
        cls.home = os.path.join(base, "home")
        os.makedirs(cls.home)
        cls.a = os.path.join(base, "pack_a", "mods")
        cls.b = os.path.join(base, "pack_b", "mods")
        for d in (cls.a, cls.b):
            os.makedirs(d)
            for k in ("alpha", "beta", "gamma", "delta"):
                neo(d, f"{k}.jar", k, version="1.0.0")
        neo(cls.b, "epsilon.jar", "epsilon")
        neo(cls.b, "alpha.jar", "alpha", version="1.1.0")  # mis à jour dans B

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cli(self, *args, stdin="", lang="en"):
        env = {**os.environ, "MODMAESTRO_HOME": self.home, "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1", "TERM": "dumb"}
        env.pop("MODMAESTRO_LANG", None)
        return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "main.py"), "--lang", lang, *args], input=stdin,
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=self.tmp.name, timeout=90)

    def test_compare_en_and_fr(self):
        r = self.cli("--compare", self.a, self.b)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Mods added (1)", r.stdout)
        self.assertIn("Mods updated (1)", r.stdout)
        self.assertIn("1.0.0 → 1.1.0", r.stdout)
        fr = self.cli("--compare", self.a, self.b, lang="fr")
        self.assertEqual(fr.returncode, 0, fr.stderr)
        self.assertIn("Mods ajoutés (1)", fr.stdout)
        self.assertNotIn("Mods added", fr.stdout)

    def test_help_is_translated(self):
        en = self.cli("--help")
        self.assertIn("Minecraft modpack audit.", en.stdout)
        self.assertIn("--find-crash", en.stdout)
        fr = self.cli("--help", lang="fr")
        self.assertIn("Audit de modpacks Minecraft.", fr.stdout)

    def test_missing_folder_is_an_error(self):
        r = self.cli("--html", os.path.join(self.tmp.name, "x.html"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("--html needs a folder", r.stderr)

    def test_html_report(self):
        before = snapshot(self.a)
        out = os.path.join(self.tmp.name, "rapport.html")
        r = self.cli(self.a, "--html", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = read(out)
        self.assertIn("alpha", html)
        self.assertNotIn(self.a, html)
        self.assertEqual(snapshot(self.a), before)
        again = self.cli(self.a, "--html", out)  # ne remplace jamais un fichier existant
        self.assertEqual(again.returncode, 2)
        self.assertIn("already exists", again.stdout)

    def test_destination_inside_mods_is_refused(self):
        before = snapshot(self.a)
        for opt, dest in (("--html", os.path.join(self.a, "r.html")), ("--export-mrpack", os.path.join(self.a, "p.mrpack")),
                          ("--server-kit", os.path.join(self.a, "kit"))):
            r = self.cli(self.a, opt, dest, "--mc", "1.21", "--loader-version", "21.1.1")
            self.assertEqual(r.returncode, 2, (opt, r.stdout, r.stderr))
        self.assertEqual(snapshot(self.a), before)

    def test_export_mrpack(self):
        before = snapshot(self.a)
        out = os.path.join(self.tmp.name, "pack.mrpack")
        no_ver = self.cli(self.a, "--export-mrpack", os.path.join(self.tmp.name, "nover.mrpack"))
        self.assertEqual(no_ver.returncode, 2)  # la version du loader est nécessaire
        r = self.cli(self.a, "--export-mrpack", out, "--mc", "1.21", "--loader-version", "21.1.172")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with zipfile.ZipFile(out) as z:
            index = json.loads(z.read("modrinth.index.json"))
        self.assertEqual(index["dependencies"]["minecraft"], "1.21")
        self.assertIn("neoforge", index["dependencies"])
        self.assertEqual(snapshot(self.a), before)

    def test_server_kit(self):
        before = snapshot(self.a)
        out = os.path.join(self.tmp.name, "kit")
        r = self.cli(self.a, "--server-kit", out, "--ram", "6")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("eula=false", read(os.path.join(out, "eula.txt")))
        self.assertTrue(os.path.isfile(os.path.join(out, "start.sh")))
        self.assertIn("6", r.stdout)
        out2 = os.path.join(self.tmp.name, "kit2")
        self.assertEqual(self.cli(self.a, "--server-kit", out2, "--accept-eula").returncode, 0)
        self.assertIn("eula=true", read(os.path.join(out2, "eula.txt")))
        self.assertEqual(snapshot(self.a), before)

    def test_recommend(self):
        r = self.cli(self.a, "--recommend")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip())

    def test_find_crash_interactive(self):
        before = snapshot(self.a)
        test_dir = os.path.join(self.tmp.name, "essai1")
        # 1er essai : on crée le dossier de test et on dit « ça marche » ; ensuite on ne crée rien et « ça plante » à chaque fois
        stdin = f"o\n{test_dir}\nf\n" + "n\nc\n" * 40
        r = self.cli(self.a, "--find-crash", stdin=stdin)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isdir(test_dir) and os.listdir(test_dir))
        self.assertIn("Trial 1", r.stdout)
        self.assertNotIn("interrupted", r.stdout)
        self.assertEqual(snapshot(self.a), before)

    def test_find_crash_without_answers_stops_cleanly(self):
        r = self.cli(self.a, "--find-crash", stdin="")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Search interrupted", r.stdout)

    def test_french_default_and_menu_language_switch(self):
        r = self.cli("--audit", self.a, lang="fr")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("santé", r.stdout)
        r = self.cli("--audit", self.a, lang="en")
        self.assertIn("health", r.stdout)
        self.assertNotIn("santé", r.stdout)


if __name__ == "__main__":
    unittest.main()
