#!/usr/bin/env python3
"""Valide les fichiers de la base communautaire. Code retour 1 si une entrée est invalide (utile en CI / PR).

    python tools/check_community.py [dossier]      (défaut : core/data/community)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import knowledge  # noqa: E402


def main(argv) -> int:
    folder = argv[1] if len(argv) > 1 else knowledge.builtin_dir()
    loaded = knowledge.load_dir(folder)
    print(f"{folder}\n  {len(loaded['sides'])} entrées « côté », {len(loaded['conflicts'])} conflits")
    for e in loaded["errors"]:
        print(f"  ✗ {e}")
    print("  ✓ Tout est valide." if not loaded["errors"] else f"  {len(loaded['errors'])} problème(s).")
    return 1 if loaded["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
