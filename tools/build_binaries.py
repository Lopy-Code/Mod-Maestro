"""Compile ModMaestro en exécutable autonome (aucune installation de Python nécessaire pour l'utiliser).

    python tools/build_binaries.py

Produit dist/ModMaestro (Linux, macOS) ou dist/ModMaestro.exe (Windows) pour le système sur lequel tu lances la commande :
PyInstaller ne sait pas compiler pour un autre système. Les trois versions sont produites par GitHub Actions (voir
.github/workflows/build.yml).
"""

import os
import platform
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller n'est pas installé : pip install pyinstaller (et, facultatif, rich)", file=sys.stderr)
        return 1
    spec = os.path.join(ROOT, "ModMaestro.spec")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           f"--distpath={os.path.join(ROOT, 'dist')}", f"--workpath={os.path.join(ROOT, 'build')}", spec]
    print(f"Système : {platform.system()} {platform.machine()}\n$ {' '.join(cmd)}\n")
    code = subprocess.call(cmd, cwd=ROOT)
    if code:
        print(f"La compilation a échoué (code {code}).", file=sys.stderr)
        return code
    name = "ModMaestro.exe" if platform.system() == "Windows" else "ModMaestro"
    print(f"\nTerminé : {os.path.join(ROOT, 'dist', name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
