"""Traductions : chaque texte français passé à `_()` / `ng()` doit avoir son anglais, avec les mêmes {champs}."""

import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import cache, demo, i18n, pipeline  # noqa: E402
from core.i18n_en import EN  # noqa: E402

FIELD = re.compile(r"\{(\w+)(?::[^}]*)?\}")
ACCENTS = re.compile(r"[àâçéèêëîïôûùüœ]", re.I)


def _sources():
    for base in ("core", "web"):
        for d, _, fs in os.walk(os.path.join(ROOT, base)):
            for f in fs:
                if f.endswith(".py") and not d.endswith(os.path.join("core", "en")) and f != "i18n_en.py":
                    yield os.path.join(d, f)
    yield os.path.join(ROOT, "main.py")


def _msgids():
    found = {}
    for p in _sources():
        with open(p, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "ng"):
                args = n.args[:2] if n.func.id == "ng" else n.args[:1]
                for a in args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        found[a.value] = (p, n.lineno)
    return found


class Catalog(unittest.TestCase):
    def test_every_msgid_is_translated(self):
        missing = [f"{os.path.relpath(p, ROOT)}:{ln} {m[:70]!r}" for m, (p, ln) in _msgids().items() if m not in EN]
        self.assertEqual(missing, [], "textes sans traduction anglaise")

    def test_fields_match(self):
        bad = [m for m, e in EN.items() if set(FIELD.findall(m)) != set(FIELD.findall(e))]
        self.assertEqual(bad, [])

    def test_no_empty_or_french_looking_value(self):
        self.assertEqual([m for m, e in EN.items() if not e.strip()], [])
        # une « traduction » identique à une phrase française accentuée = oubli probable
        same = [m for m, e in EN.items() if m == e and ACCENTS.search(m)]
        self.assertEqual(same, [])

    def test_formats_do_not_crash(self):
        for m, e in EN.items():
            e.format(**{k: 1 for k in FIELD.findall(e)})

    def test_orphans_are_few(self):
        ids = set(_msgids())
        # les clés de données (base de connaissances, règles) passent par tr() et ne sont pas des appels _()
        orphans = [m for m in EN if m not in ids]
        self.assertLess(len(orphans), 80, orphans[:5])

    def test_js_catalog(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "check_i18n_js.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class EnglishOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._home = tempfile.TemporaryDirectory()
        os.environ["MODMAESTRO_HOME"] = cls._home.name
        cache.reset_default()

    @classmethod
    def tearDownClass(cls):
        cache.reset_default()
        os.environ.pop("MODMAESTRO_HOME", None)
        cls._home.cleanup()

    def tearDown(self):
        i18n.set_lang("fr")

    def test_demo_analysis_is_english(self):
        d = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="mm_i18n_"), "pack"))
        i18n.set_lang("en")
        a = pipeline.run_analysis(d)
        res = a.to_dict()
        texts = [i["title"] + " " + i["message"] + " " + i.get("fix", "") for i in res["issues"]]
        texts += res["notes"] + [m["side_reason"] or "" for m in res["mods"]]
        french = [t for t in texts if ACCENTS.search(t)]
        self.assertEqual(french, [])

    def test_language_is_per_context(self):
        i18n.set_lang("en")
        en = i18n._("Rien à signaler") if "Rien à signaler" in EN else None
        i18n.set_lang("fr")
        self.assertEqual(i18n._("Rien à signaler"), "Rien à signaler")
        if en:
            self.assertNotEqual(en, "Rien à signaler")


if __name__ == "__main__":
    unittest.main()
