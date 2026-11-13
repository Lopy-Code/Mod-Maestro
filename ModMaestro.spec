# -*- mode: python ; coding: utf-8 -*-
# PyInstaller : un seul fichier exécutable, sans Python à installer.
#   python tools/build_binaries.py        (ou : pyinstaller ModMaestro.spec)
import os
import sys

ROOT = os.path.abspath(os.path.dirname(SPEC))

datas = [
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "web", "static"), os.path.join("web", "static")),
    (os.path.join(ROOT, "core", "data"), os.path.join("core", "data")),
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    # `rich` est facultatif : s'il est installé au moment de la compilation, le menu terminal est plus joli.
    hiddenimports=["sqlite3", "tomllib", "core.i18n_en", "core.en.analysis", "core.en.engine", "core.en.cli", "core.en.misc"],
    excludes=["tkinter", "unittest", "pydoc", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ModMaestro",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # la console affiche l'adresse de l'interface et permet d'arrêter avec Ctrl+C
    icon=os.path.join(ROOT, "assets", "favicon.ico") if sys.platform == "win32" else None,
)
