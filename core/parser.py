"""Lecture des métadonnées des .jar (NeoForge, Forge, Fabric, Quilt).

Un .jar est une archive zip. On y lit :
  - META-INF/neoforge.mods.toml   (NeoForge)
  - META-INF/mods.toml            (Forge)
  - fabric.mod.json               (Fabric)
  - quilt.mod.json                (Quilt)
et on descend dans les jars imbriqués (jar-in-jar) pour savoir quels mods
sont déjà fournis par d'autres.
"""

from __future__ import annotations

import contextvars
import io
import json
import os
import re
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .i18n import _

try:  # Python ≥ 3.11
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

MAX_NESTED_DEPTH = 2
MAX_NESTED_BYTES = 256 * 1024 * 1024

# Identifiants fournis par la plateforme elle-même : jamais « manquants ».
PLATFORM_IDS = {
    "minecraft", "java", "neoforge", "forge", "fml",
    "fabricloader", "fabric-loader", "fabric_loader",
    "quilt_loader", "quilt-loader",
}


@dataclass
class Dep:
    modid: str
    kind: str  # required | optional | incompatible | discouraged
    range: object = None  # str (Maven) ou str/list (Fabric)
    syntax: str = "maven"  # maven | fabric
    side: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"modid": self.modid, "kind": self.kind, "range": self.range, "side": self.side}


@dataclass
class ModInfo:
    modid: str
    name: str
    version: str | None
    loader: str  # neoforge | forge | fabric | quilt
    deps: list[Dep] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    env: str = "both"  # both | client | server
    env_reason: str | None = None
    description: str = ""
    entrypoints: list[str] = field(default_factory=list)
    bundled_in: str | None = None


@dataclass
class JarInfo:
    file: str
    path: str
    size: int
    mtime: float = 0.0
    status: str = "ok"  # ok | no-metadata | corrupt | unreadable
    error: str | None = None
    mods: list[ModInfo] = field(default_factory=list)  # tous loaders confondus
    bundled: list[ModInfo] = field(default_factory=list)  # jar-in-jar
    library: bool = False  # bibliothèque déclarée (FMLModType: LIBRARY) : sans métadonnées, mais volontaire

    @property
    def loaders(self) -> list[str]:
        seen: list[str] = []
        for m in self.mods:
            if m.loader not in seen:
                seen.append(m.loader)
        return seen


# --------------------------------------------------------------------------
# Découverte des fichiers
# --------------------------------------------------------------------------

def count_jars(folder: str, cap: int = 9999) -> int:
    n = 0
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.is_file() and e.name.lower().endswith(".jar"):
                    n += 1
                    if n >= cap:
                        break
    except OSError:
        pass
    return n


def resolve_source(path: str) -> tuple[str, list[str]]:
    """Retourne (dossier contenant les .jar, notes).

    Accepte : un dossier `mods`, la racine d'une instance (qui contient `mods/`),
    une instance Prism/MultiMC (`minecraft/mods`, `.minecraft/mods`) ou un .zip.
    """
    notes: list[str] = []
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    if not os.path.exists(path):
        raise ValueError(f"Chemin introuvable : {path}")

    if os.path.isfile(path):
        if path.lower().endswith((".zip", ".mrpack")):
            return _extract_zip(path)
        if path.lower().endswith(".jar"):
            return os.path.dirname(path), [_("Un seul fichier .jar a été donné : analyse du dossier qui le contient.")]
        raise ValueError(_("Choisis un dossier de mods ou une archive .zip."))

    if count_jars(path):
        return path, notes
    for rel in ("mods", "minecraft/mods", ".minecraft/mods", "overrides/mods"):
        cand = os.path.join(path, rel)
        if os.path.isdir(cand) and count_jars(cand):
            notes.append(_("Dossier de mods détecté automatiquement : {rel}/", rel=rel))
            return cand, notes
    raise ValueError(_(
        "Aucun fichier .jar trouvé ici. Choisis le dossier `mods` de ton modpack "
        "(ou la racine de l'instance qui le contient)."
    ))


def _extract_zip(path: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(_("Cette archive est corrompue ou n'est pas un zip valide.")) from exc
    with zf:
        members = [
            n for n in zf.namelist()
            if re.search(r"(^|/)mods/[^/]+\.jar$", n, re.IGNORECASE)
        ]
        if not members:
            names = set(zf.namelist())
            if "manifest.json" in names or "modrinth.index.json" in names:
                raise ValueError(_(
                    "Ce zip ne contient que la liste des mods (manifest), pas les .jar eux-mêmes. "
                    "Installe le modpack avec ton launcher, puis choisis le dossier `mods` de l'instance."
                ))
            raise ValueError(_("Aucun dossier `mods/` contenant des .jar dans cette archive."))
        out = tempfile.mkdtemp(prefix="modmaestro_zip_")
        for name in members:
            target = os.path.join(out, os.path.basename(name))
            with zf.open(name) as src, open(target, "wb") as dst:
                dst.write(src.read())
        notes.append(_("{n} jar extraits de l'archive vers un dossier temporaire.", n=len(members)))
    return out, notes


def list_jar_files(folder: str) -> tuple[list[str], dict]:
    jars: list[str] = []
    extras = {"disabled": 0, "subfolder_jars": 0}
    with os.scandir(folder) as it:
        for e in it:
            low = e.name.lower()
            if e.is_file():
                if low.endswith(".jar"):
                    jars.append(e.path)
                elif low.endswith(".jar.disabled") or low.endswith(".jar.old"):
                    extras["disabled"] += 1
            elif e.is_dir() and not e.name.startswith("."):
                extras["subfolder_jars"] += count_jars(e.path, cap=999)
    jars.sort(key=lambda p: os.path.basename(p).lower())
    return jars, extras


# --------------------------------------------------------------------------
# Lecture d'un jar
# --------------------------------------------------------------------------

def read_jar(path: str) -> JarInfo:
    st = os.stat(path)
    info = JarInfo(file=os.path.basename(path), path=path, size=st.st_size, mtime=st.st_mtime)
    if st.st_size == 0:
        info.status, info.error = "corrupt", "Fichier vide (0 octet)."
        return info
    try:
        with zipfile.ZipFile(path) as zf:
            mods, bundled = _read_archive(zf, info.file, 0)
    except zipfile.BadZipFile:
        info.status, info.error = "corrupt", _("Archive zip invalide (téléchargement interrompu ou fichier abîmé).")
        return info
    except Exception as exc:  # noqa: BLE001 — on ne veut jamais planter l'audit complet
        info.status, info.error = "unreadable", _("Lecture impossible : {exc}", exc=exc)
        return info
    info.mods, info.bundled = mods, bundled
    if not mods:
        info.library = _is_declared_library(path)
        info.status = "no-metadata"
        info.error = _("Aucune métadonnée de mod (bibliothèque, coremod ou format trop ancien).")
    return info


def _is_declared_library(path: str) -> bool:
    """Bibliothèque volontaire : le manifeste porte `FMLModType: LIBRARY` / `GAMELIBRARY`."""
    try:
        with zipfile.ZipFile(path) as zf:
            text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return False
    return bool(re.search(r"^FMLModType:\s*(GAME)?LIBRARY\s*$", text, re.MULTILINE | re.IGNORECASE))


def _manifest_version(zf: zipfile.ZipFile) -> str | None:
    try:
        text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except KeyError:
        return None
    m = re.search(r"^Implementation-Version:\s*(\S+)", text, re.MULTILINE)
    return m.group(1) if m else None


def _read_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8-sig", "replace")


def _read_archive(zf: zipfile.ZipFile, label: str, depth: int) -> tuple[list[ModInfo], list[ModInfo]]:
    names = set(zf.namelist())
    mods: list[ModInfo] = []
    manifest_v = _manifest_version(zf)

    for loader, meta in (("neoforge", "META-INF/neoforge.mods.toml"), ("forge", "META-INF/mods.toml")):
        if meta in names:
            mods += _parse_forge_toml(_read_text(zf, meta), loader, manifest_v)
    if "fabric.mod.json" in names:
        mods += _parse_fabric(_read_text(zf, "fabric.mod.json"))
    if "quilt.mod.json" in names:
        mods += _parse_quilt(_read_text(zf, "quilt.mod.json"))

    bundled: list[ModInfo] = []
    if depth < MAX_NESTED_DEPTH:
        nested = [n for n in names if re.match(r"META-INF/(jarjar|jars)/[^/]+\.jar$", n, re.IGNORECASE)]
        nested += _fabric_declared_jars(zf, names)
        for n in sorted(set(nested)):
            if n not in names:
                continue
            try:
                if zf.getinfo(n).file_size > MAX_NESTED_BYTES:
                    continue
                with zipfile.ZipFile(io.BytesIO(zf.read(n))) as inner:
                    sub_mods, sub_bundled = _read_archive(inner, os.path.basename(n), depth + 1)
            except Exception:  # noqa: BLE001
                continue
            for m in sub_mods + sub_bundled:
                m.bundled_in = label
                bundled.append(m)
    return mods, bundled


def _fabric_declared_jars(zf: zipfile.ZipFile, names: set[str]) -> list[str]:
    if "fabric.mod.json" not in names:
        return []
    try:
        data = json.loads(_read_text(zf, "fabric.mod.json"), strict=False)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for j in data.get("jars", []) or []:
        if isinstance(j, dict) and isinstance(j.get("file"), str):
            out.append(j["file"])
    return out


# --------------------------------------------------------------------------
# NeoForge / Forge — TOML
# --------------------------------------------------------------------------

def _clean_version(v, manifest_v: str | None) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    if v == "${file.jarVersion}":
        return manifest_v
    if v.startswith("${"):
        return None
    return v or None


def _parse_forge_toml(text: str, loader: str, manifest_v: str | None) -> list[ModInfo]:
    try:
        data = tomllib.loads(text)
    except Exception:  # TOML invalide : on récupère au moins l'identifiant
        return _toml_fallback(text, loader, manifest_v)

    all_deps = data.get("dependencies") or {}
    mods: list[ModInfo] = []
    for entry in data.get("mods") or []:
        modid = str(entry.get("modId", "")).strip()
        if not modid:
            continue
        deps_raw = all_deps.get(modid, []) if isinstance(all_deps, dict) else []
        deps: list[Dep] = []
        env = "both"
        env_reason = None
        for d in deps_raw if isinstance(deps_raw, list) else []:
            if not isinstance(d, dict) or not d.get("modId"):
                continue
            dep_id = str(d["modId"]).strip()
            if "type" in d:
                kind = str(d["type"]).lower()
            else:
                kind = "required" if d.get("mandatory", True) else "optional"
            if kind not in ("required", "optional", "incompatible", "discouraged"):
                kind = "required"
            side = str(d.get("side", "BOTH")).upper()
            deps.append(Dep(dep_id, kind, d.get("versionRange"), "maven", side, d.get("reason")))
            if dep_id in ("neoforge", "forge", "minecraft") and kind == "required":
                if side == "CLIENT":
                    env, env_reason = "client", _("Déclaré côté client uniquement dans ses métadonnées")
                elif side == "SERVER" and env == "both":
                    env, env_reason = "server", _("Déclaré côté serveur uniquement dans ses métadonnées")
        mods.append(ModInfo(
            modid=modid,
            name=str(entry.get("displayName") or modid),
            version=_clean_version(entry.get("version"), manifest_v),
            loader=loader,
            deps=deps,
            env=env,
            env_reason=env_reason,
            description=str(entry.get("description") or "").strip()[:300],
        ))
    return mods


def _toml_fallback(text: str, loader: str, manifest_v: str | None) -> list[ModInfo]:
    mods = []
    for m in re.finditer(r'modId\s*=\s*"([^"]+)"', text):
        mods.append(ModInfo(modid=m.group(1), name=m.group(1), version=manifest_v, loader=loader))
        break  # au mieux le premier : les dépendances ont aussi une clé modId
    return mods


# --------------------------------------------------------------------------
# Fabric
# --------------------------------------------------------------------------

def _fabric_deps(block, kind: str) -> list[Dep]:
    out = []
    if isinstance(block, dict):
        for dep_id, rng in block.items():
            out.append(Dep(str(dep_id), kind, rng, "fabric"))
    return out


def _parse_fabric(text: str) -> list[ModInfo]:
    try:
        data = json.loads(text, strict=False)
    except Exception:  # noqa: BLE001
        return []
    modid = str(data.get("id", "")).strip()
    if not modid:
        return []
    deps = (
        _fabric_deps(data.get("depends"), "required")
        + _fabric_deps(data.get("recommends"), "optional")
        + _fabric_deps(data.get("suggests"), "optional")
        + _fabric_deps(data.get("conflicts"), "discouraged")
        + _fabric_deps(data.get("breaks"), "incompatible")
    )
    provides = []
    for p in data.get("provides") or []:
        provides.append(str(p.get("id") if isinstance(p, dict) else p))
    env_raw = str(data.get("environment", "*")).lower()
    env = {"client": "client", "server": "server"}.get(env_raw, "both")
    env_reason = _("environment = « {env} » dans fabric.mod.json", env=env_raw) if env != "both" else None

    eps = data.get("entrypoints")
    ep_keys = sorted(eps.keys()) if isinstance(eps, dict) else []
    if env == "both" and ep_keys and "client" in ep_keys and not {"main", "server"} & set(ep_keys):
        env, env_reason = "client", _("Seul un point d'entrée « client » est déclaré")

    return [ModInfo(
        modid=modid,
        name=str(data.get("name") or modid),
        version=_clean_version(data.get("version"), None),
        loader="fabric",
        deps=deps,
        provides=provides,
        env=env,
        env_reason=env_reason,
        description=str(data.get("description") or "").strip()[:300],
        entrypoints=ep_keys,
    )]


# --------------------------------------------------------------------------
# Quilt
# --------------------------------------------------------------------------

def _quilt_deps(items, kind: str) -> list[Dep]:
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append(Dep(it, kind, None, "fabric"))
        elif isinstance(it, dict):
            dep_id = it.get("id")
            if not dep_id:
                continue
            k = "optional" if (kind == "required" and it.get("optional")) else kind
            out.append(Dep(str(dep_id), k, it.get("versions"), "fabric", reason=it.get("reason")))
    return out


def _parse_quilt(text: str) -> list[ModInfo]:
    try:
        data = json.loads(text, strict=False)
    except Exception:  # noqa: BLE001
        return []
    q = data.get("quilt_loader") or {}
    modid = str(q.get("id", "")).strip()
    if not modid:
        return []
    meta = q.get("metadata") or {}
    provides = [str(p.get("id") if isinstance(p, dict) else p) for p in (q.get("provides") or [])]
    env_raw = str((data.get("minecraft") or {}).get("environment", "*")).lower()
    env = {"client": "client", "dedicated_server": "server"}.get(env_raw, "both")
    return [ModInfo(
        modid=modid,
        name=str(meta.get("name") or modid),
        version=_clean_version(q.get("version"), None),
        loader="quilt",
        deps=_quilt_deps(q.get("depends"), "required") + _quilt_deps(q.get("breaks"), "incompatible"),
        provides=provides,
        env=env,
        env_reason=_("minecraft.environment = « {env} » dans quilt.mod.json", env=env_raw) if env != "both" else None,
        description=str(meta.get("description") or "").strip()[:300],
    )]


# --------------------------------------------------------------------------
# Scan d'un dossier complet
# --------------------------------------------------------------------------

def scan_folder(
    folder: str,
    progress: Callable[[int, int], None] | None = None,
    workers: int = 8,
) -> tuple[list[JarInfo], dict]:
    paths, extras = list_jar_files(folder)
    total = len(paths)
    results: list[JarInfo | None] = [None] * total
    done = 0
    if progress:
        progress(0, total)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # chaque tâche hérite de la langue courante (contextvars) : les messages d'erreur sortent dans la bonne langue
        futures = {pool.submit(contextvars.copy_context().run, read_jar, p): i for i, p in enumerate(paths)}
        for fut, i in futures.items():
            results[i] = fut.result()
            done += 1
            if progress:
                progress(done, total)
    return [r for r in results if r is not None], extras
