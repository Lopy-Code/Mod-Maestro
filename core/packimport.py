"""Import direct d'un modpack `.mrpack` (Modrinth) ou d'un zip CurseForge, sans le décompresser à la main.

* Les `.jar` embarqués dans l'archive (`overrides/mods/…`) sont lus directement, avec des limites de taille.
* `.mrpack` : la liste `modrinth.index.json` donne l'adresse et l'empreinte de chaque mod. Ils ne sont téléchargés
  **que si tu actives Modrinth** (option « en ligne ») ; chaque fichier est vérifié (SHA-1 / SHA-512) et seuls les
  hébergeurs autorisés par la spécification officielle sont acceptés.
* Zip CurseForge : la liste ne contient que des numéros de projet, impossibles à télécharger sans clé d'API :
  seuls les `.jar` embarqués sont analysés, et on te le dit.
Tout est rangé dans un dossier temporaire supprimé à la fermeture ; l'archive d'origine n'est jamais modifiée.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Callable

from . import __version__
from .i18n import _, ng

# Hébergeurs autorisés par la spécification .mrpack.
ALLOWED_HOSTS = ("cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com")
MAX_JAR = 512 * 1024**2       # un seul mod
MAX_TOTAL = 4 * 1024**3       # tout le pack
MAX_FILES = 2500
TIMEOUT = 30
_LOADER_KEYS = {"fabric-loader": "Fabric", "quilt-loader": "Quilt", "forge": "Forge", "neoforge": "NeoForge"}
_JAR_IN_MODS = re.compile(r"^(?:(?:overrides|client-overrides|server-overrides)/)?mods/([^/]+\.jar)$", re.I)

Progress = Callable[[str, int, int], None]


def kind_of(zf: zipfile.ZipFile) -> str:
    names = set(zf.namelist())
    if "modrinth.index.json" in names:
        return "mrpack"
    if "manifest.json" in names:
        try:
            m = json.loads(zf.read("manifest.json"))
        except (ValueError, KeyError, zipfile.BadZipFile):
            return "plain"
        if isinstance(m, dict) and ("minecraft" in m or m.get("manifestType") == "minecraftModpack"):
            return "curseforge"
    return "plain"


def _read_json(zf: zipfile.ZipFile, name: str, limit: int = 20 * 1024 * 1024) -> dict:
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise ValueError(_("Cette archive est corrompue ou n'est pas un zip valide."))
    data = json.loads(zf.read(name).decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(_("Cette archive est corrompue ou n'est pas un zip valide."))
    return data


def _unique(folder: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base}-{i}{ext}")
        i += 1
    return path


def _extract_embedded(zf: zipfile.ZipFile, out: str, budget: list[int]) -> int:
    """Copie les .jar embarqués, en flux, avec plafond de taille (protège contre les « zip bombs »)."""
    n = 0
    for info in zf.infolist():
        m = _JAR_IN_MODS.match(info.filename)
        if not m or info.is_dir():
            continue
        if info.file_size > MAX_JAR or budget[0] + info.file_size > MAX_TOTAL or n >= MAX_FILES:
            raise ValueError(_("Cette archive contient des fichiers trop volumineux : analyse annulée."))
        dest = _unique(out, os.path.basename(m.group(1)))
        written = 0
        with zf.open(info) as src, open(dest, "wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if written > info.file_size or written > MAX_JAR:   # taille déclarée mensongère
                    raise ValueError(_("Cette archive est corrompue ou n'est pas un zip valide."))
                dst.write(chunk)
        budget[0] += written
        n += 1
    return n


def _allowed(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    return p.scheme == "https" and (p.hostname or "").lower() in ALLOWED_HOSTS


def _download(url: str, dest: str, expect: dict, size_hint: int, budget: list[int]) -> bool:
    """Télécharge un mod ; garde le fichier seulement si son empreinte correspond. True si réussi."""
    sha1, sha512 = hashlib.sha1(), hashlib.sha512()   # noqa: S324 — empreinte fournie par le pack, pas un usage de sécurité
    req = urllib.request.Request(url, headers={"User-Agent": f"ModMaestro/{__version__}"})
    limit = min(MAX_JAR, max(size_hint, 0) * 2 or MAX_JAR)
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, open(dest, "wb") as fh:
            if not _allowed(resp.geturl()):             # redirection vers un autre hébergeur : refusée
                raise ValueError("host")
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                got += len(chunk)
                if got > limit or budget[0] + got > MAX_TOTAL:
                    raise ValueError("size")
                sha1.update(chunk)
                sha512.update(chunk)
                fh.write(chunk)
        ok = ((not expect.get("sha1") or sha1.hexdigest() == str(expect["sha1"]).lower())
              and (not expect.get("sha512") or sha512.hexdigest() == str(expect["sha512"]).lower())
              and bool(expect.get("sha1") or expect.get("sha512")))
    except (urllib.error.URLError, OSError, ValueError):
        ok = False
    if ok:
        budget[0] += got
    else:
        try:
            os.remove(dest)
        except OSError:
            pass
    return ok


def _describe(name, mc, loaders) -> str:
    bits = [f"Minecraft {mc}" if mc else "", ", ".join(loaders)]
    return _("Modpack « {name} » — {info}", name=str(name or "?")[:80], info=" · ".join(b for b in bits if b) or "?")


def extract_pack(path: str, out: str, online: bool = False, progress: Progress | None = None) -> tuple[str, list[str]]:
    """Prépare `out` (dossier vide) avec les .jar du pack ; renvoie (kind, notes). Lève ValueError si rien à analyser."""
    prog = progress or (lambda s, d, t: None)
    notes: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(_("Cette archive est corrompue ou n'est pas un zip valide.")) from exc
    with zf:
        kind = kind_of(zf)
        budget = [0]
        listed: list[dict] = []
        try:
            if kind == "mrpack":
                idx = _read_json(zf, "modrinth.index.json")
                deps = idx.get("dependencies") if isinstance(idx.get("dependencies"), dict) else {}
                loaders = [lbl for k, lbl in _LOADER_KEYS.items() if k in deps]
                notes.append(_describe(idx.get("name"), deps.get("minecraft"), loaders))
                for f in idx.get("files") or []:
                    if isinstance(f, dict) and re.match(r"^mods/[^/]+\.jar$", str(f.get("path", "")), re.I):
                        listed.append(f)
            elif kind == "curseforge":
                man = _read_json(zf, "manifest.json")
                mc = (man.get("minecraft") or {}) if isinstance(man.get("minecraft"), dict) else {}
                loaders = [str(l.get("id", "")).split("-")[0].capitalize() for l in (mc.get("modLoaders") or []) if isinstance(l, dict)]
                notes.append(_describe(man.get("name"), mc.get("version"), loaders))
        except (ValueError, KeyError) as exc:
            raise ValueError(_("Cette archive est corrompue ou n'est pas un zip valide.")) from exc

        embedded = _extract_embedded(zf, out, budget)
        if embedded:
            notes.append(_("{n} jar extraits de l'archive vers un dossier temporaire.", n=embedded))

        if kind == "curseforge":
            count = len(((_read_json(zf, "manifest.json")).get("files") or []))
            if count:
                notes.append(ng("{n} mod listé par CurseForge n'est pas analysé : il n'est téléchargeable qu'avec une clé d'API CurseForge. "
                                "Installe le pack avec ton launcher pour l'analyser en entier.",
                                "{n} mods listés par CurseForge ne sont pas analysés : ils ne sont téléchargeables qu'avec une clé d'API CurseForge. "
                                "Installe le pack avec ton launcher pour l'analyser en entier.", count))
        if kind == "mrpack" and listed:
            if not online:
                raise ValueError(_(
                    "Ce .mrpack liste {n} mods à télécharger. Active l'option Modrinth pour que ModMaestro les récupère "
                    "(chacun est vérifié par son empreinte), ou installe le pack avec ton launcher puis choisis son dossier `mods`.",
                    n=len(listed)))
            if len(listed) + embedded > MAX_FILES:
                raise ValueError(_("Cette archive contient trop de fichiers : analyse annulée."))
            failed = 0
            for i, f in enumerate(listed, 1):
                prog("download", i - 1, len(listed))
                urls = [u for u in (f.get("downloads") or []) if isinstance(u, str) and _allowed(u)]
                hashes = f.get("hashes") if isinstance(f.get("hashes"), dict) else {}
                size = int(f["fileSize"]) if isinstance(f.get("fileSize"), int) else 0
                dest = _unique(out, os.path.basename(str(f["path"])))
                if not any(_download(u, dest, hashes, size, budget) for u in urls):
                    failed += 1
            prog("download", len(listed), len(listed))
            notes.append(ng("{n} mod téléchargé depuis le pack et vérifié.", "{n} mods téléchargés depuis le pack et vérifiés.", len(listed) - failed))
            if failed:
                notes.append(ng("{n} mod n'a pas pu être téléchargé ou son empreinte ne correspond pas : il est ignoré.",
                                "{n} mods n'ont pas pu être téléchargés ou leur empreinte ne correspond pas : ils sont ignorés.", failed))
        if not any(n.lower().endswith(".jar") for n in os.listdir(out)):
            if kind in ("mrpack", "curseforge") or "manifest.json" in zf.namelist():
                raise ValueError(_(
                    "Ce zip ne contient que la liste des mods (manifest), pas les .jar eux-mêmes. "
                    "Installe le modpack avec ton launcher, puis choisis le dossier `mods` de l'instance."))
            raise ValueError(_("Aucun dossier `mods/` contenant des .jar dans cette archive."))
    return kind, notes
