"""Génération du dossier `mods` pour un serveur dédié."""

from __future__ import annotations

import os
import shutil
import zipfile

from .analyzer import Analysis, compute_plan


def suggest_output_dir(mods_dir: str, name: str = "server_mods") -> str:
    """Un chemin qui n'existe pas encore, à côté du dossier mods."""
    parent = os.path.dirname(os.path.abspath(mods_dir))
    candidate = os.path.join(parent, name)
    n = 2
    while os.path.exists(candidate) or os.path.exists(candidate + ".zip"):
        candidate = os.path.join(parent, f"{name}_{n}")
        n += 1
    return candidate


def _inside(child: str, parent: str) -> bool:
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def build_server(
    a: Analysis,
    output: str,
    exclude=(),
    include=(),
    make_zip: bool = False,
    dry_run: bool = False,
) -> dict:
    """Copie les mods retenus dans `output`. Ne modifie jamais le dossier source."""
    plan = compute_plan(a, exclude, include)
    size = sum(a.entries[f]["size"] for f in plan["keep"])
    result = {
        "output": None, "zip": None, "copied": len(plan["keep"]), "bytes": size,
        "removed": len(plan["remove"]), "plan": plan, "dry_run": dry_run,
    }
    if dry_run:
        return result

    output = os.path.abspath(os.path.expanduser(output.strip().strip('"')))
    if _inside(output, a.mods_dir) or _inside(a.mods_dir, output):
        raise ValueError("Le dossier de sortie ne doit pas être le dossier de mods (ni dedans, ni le contenir).")
    if os.path.exists(output) and (not os.path.isdir(output) or os.listdir(output)):
        raise FileExistsError(
            f"« {output} » existe déjà et n'est pas vide. Choisis un autre nom : je ne mélange jamais mes fichiers avec les tiens."
        )
    zip_path = output.rstrip(os.sep) + ".zip"
    if make_zip and os.path.exists(zip_path):
        raise FileExistsError(f"« {zip_path} » existe déjà.")

    os.makedirs(output, exist_ok=True)
    for f in plan["keep"]:
        shutil.copy2(a.entries[f]["path"], os.path.join(output, f))
    result["output"] = output

    if make_zip:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:  # les jars sont déjà compressés
            for f in plan["keep"]:
                zf.write(a.entries[f]["path"], arcname=f"mods/{f}")
        result["zip"] = zip_path
    return result
