"""Export d'un modpack : .mrpack (Modrinth) ou simple .zip.

Le .mrpack suit la spécification officielle (modrinth.index.json) : les mods reconnus sur Modrinth sont
référencés par leur adresse de téléchargement et leurs empreintes (rien n'est embarqué), les autres sont copiés
dans `overrides/mods/` si tu le demandes. Il s'importe dans l'application Modrinth, Prism Launcher, etc.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from urllib.parse import urlparse

from .analyzer import Analysis
from .i18n import _

LOADER_KEY = {"neoforge": "neoforge", "forge": "forge", "fabric": "fabric-loader", "quilt": "quilt-loader"}
# Hôtes de téléchargement autorisés par la spécification .mrpack
ALLOWED_HOSTS = ("cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com")
_PRISM_UIDS = {"net.neoforged": "neoforge", "net.minecraftforge": "forge",
               "net.fabricmc.fabric-loader": "fabric", "org.quiltmc.quilt-loader": "quilt"}


def detect_instance(mods_dir: str) -> dict:
    """Version de Minecraft et du loader, si le dossier appartient à une instance Prism / MultiMC (mmc-pack.json)."""
    here = os.path.abspath(mods_dir)
    for up in (os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        p = os.path.join(up, "mmc-pack.json")
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    comps = json.load(fh).get("components", [])
            except (OSError, ValueError):
                return {}
            out = {}
            for c in comps:
                if c.get("uid") == "net.minecraft":
                    out["mc"] = c.get("version")
                elif c.get("uid") in _PRISM_UIDS:
                    out["loader"], out["loader_version"] = _PRISM_UIDS[c["uid"]], c.get("version")
            return out
    return {}


def _hashes(path: str) -> tuple[str, str]:
    s1, s512 = hashlib.sha1(), hashlib.sha512()  # noqa: S324 — empreintes exigées par le format .mrpack
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            s1.update(block)
            s512.update(block)
    return s1.hexdigest(), s512.hexdigest()


def _safe_name(s: str, default: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s or "").strip()
    return s[:100] or default


def _check_output(a: Analysis, out: str, ext: str) -> str:
    out = os.path.abspath(os.path.expanduser(out.strip().strip('"')))
    if not out.lower().endswith(ext):
        out += ext
    src = os.path.realpath(a.mods_dir)
    real = os.path.realpath(out)
    if real.startswith(src + os.sep):
        raise ValueError(_("Le fichier exporté ne doit pas être écrit dans le dossier de mods."))
    if os.path.exists(out):
        raise FileExistsError(_("« {path} » existe déjà : choisis un autre nom.", path=out))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return out


def export_mrpack(a: Analysis, out: str, *, name: str, version: str = "1.0.0", mc: str = "", loader: str = "",
                  loader_version: str = "", include_unknown: bool = True, exclude=()) -> dict:
    mc = (mc or a.mc_version or "").strip()
    loader = (loader or a.loader or "").strip()
    if not mc:
        raise ValueError(_("La version de Minecraft est nécessaire pour un .mrpack."))
    if loader not in LOADER_KEY:
        raise ValueError(_("Le loader du pack est inconnu : indique NeoForge, Forge, Fabric ou Quilt."))
    if not (loader_version or "").strip():
        raise ValueError(_("La version du loader est nécessaire (par exemple 21.1.172 pour NeoForge)."))
    out = _check_output(a, out, ".mrpack")

    files, overrides, skipped = [], [], []
    for f, e in sorted(a.entries.items()):
        if f in set(exclude) or e["status"] not in ("ok", "no-metadata"):
            continue
        on = e.get("online") or {}
        dl = on.get("download")
        if dl and urlparse(dl["url"]).hostname in ALLOWED_HOSTS and urlparse(dl["url"]).scheme == "https":
            sha1, sha512 = _hashes(e["path"])
            env = {k: (on.get(f"{k}_side") if on.get(f"{k}_side") in ("required", "optional", "unsupported") else "required")
                   for k in ("client", "server")}
            files.append({"path": f"mods/{f}", "hashes": {"sha1": sha1, "sha512": sha512}, "env": env,
                          "downloads": [dl["url"]], "fileSize": os.path.getsize(e["path"])})
        elif include_unknown:
            overrides.append(f)
        else:
            skipped.append(f)

    index = {"formatVersion": 1, "game": "minecraft", "versionId": version or "1.0.0",
             "name": _safe_name(name, "Modpack"), "summary": _("Exporté avec ModMaestro"),
             "files": files, "dependencies": {"minecraft": mc, LOADER_KEY[loader]: loader_version.strip()}}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2, ensure_ascii=False))
        for f in overrides:
            zf.write(a.entries[f]["path"], arcname=f"overrides/mods/{f}")
    warnings = []
    if overrides:
        warnings.append(_("{n} mod(s) inconnu(s) de Modrinth ont été copiés dans le fichier. Ne publie pas ce pack tel "
                          "quel : tu n'as peut-être pas le droit de redistribuer ces mods.", n=len(overrides)))
    if skipped:
        warnings.append(_("{n} mod(s) inconnu(s) de Modrinth ont été laissés de côté : le pack sera incomplet.", n=len(skipped)))
    if not a.online.get("enabled"):
        warnings.append(_("L'analyse a été faite hors ligne : aucun mod n'a pu être référencé, tout est copié dans le fichier. "
                          "Relance l'analyse avec Modrinth pour obtenir un .mrpack léger."))
    return {"path": out, "referenced": len(files), "embedded": len(overrides), "skipped": skipped,
            "warnings": warnings, "bytes": os.path.getsize(out)}


def export_zip(a: Analysis, out: str, files) -> dict:
    """Archive simple : `mods/<fichiers>` (par exemple pour envoyer le pack à un ami)."""
    out = _check_output(a, out, ".zip")
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:  # les jars sont déjà compressés
        for f in sorted(files):
            if f in a.entries:
                zf.write(a.entries[f]["path"], arcname=f"mods/{f}")
                n += 1
    return {"path": out, "files": n, "bytes": os.path.getsize(out)}
