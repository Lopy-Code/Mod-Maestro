"""Lecture fine d'un crash : relie la pile d'erreur (stack trace) au mod fautif, même sans nom explicite.

Indices utilisés, du plus sûr au moins sûr :
1. la section « Suspected Mods » du rapport de crash (écrite par Forge/NeoForge) ;
2. le nom du `.jar` indiqué à la fin d'une ligne de pile (`~[monmod-1.0.jar%23123!/:1.0]`) ou le module `monmod@1.0/` ;
3. le nom du paquet de la classe, retrouvé dans les `.jar` installés (index des classes de chaque jar) ;
4. le nom d'une méthode injectée par un mixin (`handler$zzz$monmod$…`, `monmod$…`) ;
5. à défaut d'index, un segment de paquet égal à l'identifiant d'un mod installé.
Les classes du jeu, de Java et des chargeurs sont écartées. Rien n'est modifié : c'est une aide au diagnostic.
"""

from __future__ import annotations

import re
import zipfile
from collections import defaultdict

from . import knowledge
from .i18n import _

CORE_PREFIXES = (
    "java.", "javax.", "jdk.", "sun.", "com.sun.", "net.minecraft.", "com.mojang.", "net.minecraftforge.", "net.neoforged.",
    "cpw.mods.", "net.fabricmc.", "org.quiltmc.", "org.spongepowered.", "org.objectweb.", "io.netty.", "it.unimi.",
    "com.google.", "org.apache.", "org.lwjgl.", "org.slf4j.", "org.apache.logging.", "com.electronwill.", "joptsimple.",
    "oshi.", "org.jetbrains.", "kotlin.", "kotlinx.", "org.openjdk.", "org.joml.", "org.lwjgl3.", "net.fabricmc.loader.",
)
MAX_INDEX_JARS = 1500
MAX_ENTRIES_PER_JAR = 60000
MAX_CHAINS = 12
MAX_FRAMES = 400

_EXC_LINE = re.compile(r"^(?:Caused by: |Exception in thread \"[^\"]*\" )?([A-Za-z_][\w.$]*(?:Exception|Error|Throwable))(?::\s?(.*))?$")
_AT = re.compile(r"^\s*at\s+(\S+?)\(([^)]*)\)(?:\s*~?\[([^\]]*)\])?")
_JAR_HINT = re.compile(r"([^\s\[\]%!:/\\,]+\.jar)", re.I)
_SUSPECT_SECTION = re.compile(r"Suspected Mods?:[ \t]*\r?\n((?:[ \t]+[^\r\n]*\r?\n?)+)")
_SUSPECT_LINE = re.compile(r"\(([a-z][a-z0-9_.\-]*)\),\s*Version:\s*(\S+)")
_MIXIN_NAME = re.compile(r"^(?:handler\$[a-z0-9]+\$([a-z][a-z0-9_]*)\$|([a-z][a-z0-9_]*)\$)[\w$]+$")


def is_core(cls: str) -> bool:
    return cls.startswith(CORE_PREFIXES)


def build_index(mods_dir: str, files: list[str]) -> dict[str, set[str]]:
    """Dossier de classes -> {fichiers jar} qui le contiennent (noms seulement, aucune extraction)."""
    owners: dict[str, set[str]] = defaultdict(set)
    import os
    for name in files[:MAX_INDEX_JARS]:
        try:
            with zipfile.ZipFile(os.path.join(mods_dir, name)) as zf:
                for i, entry in enumerate(zf.namelist()):
                    if i > MAX_ENTRIES_PER_JAR:
                        break
                    if entry.endswith(".class") and entry.count("/") >= 2 and not entry.startswith("META-INF/"):
                        owners[entry.rsplit("/", 1)[0].replace("/", ".")].add(name)
        except (OSError, zipfile.BadZipFile):
            continue
    return owners


def _blocks(text: str) -> list[list[dict]]:
    """Découpe en chaînes d'exceptions (exception + « Caused by »), chacune = liste de blocs {title, frames}."""
    chains: list[list[dict]] = []
    cur: dict | None = None
    seen_chain: set[int] = set()
    frames_total = 0
    for line in text.splitlines():
        s = line.rstrip()
        m = _AT.match(s)
        if m and cur is not None:
            if frames_total < MAX_FRAMES * MAX_CHAINS:
                cur["frames"].append({"raw": m.group(1), "hint": m.group(3) or ""})
                frames_total += 1
            continue
        e = _EXC_LINE.match(s.strip()) if not s.startswith((" ", "\t")) else None
        if e:
            cur = {"title": s.strip()[:300], "exc": e.group(1), "frames": []}
            if s.startswith("Caused by:") and chains:
                chains[-1].append(cur)
            else:
                chains.append([cur])
        elif not s.strip().startswith("..."):
            if not s.startswith(("\t", " ")):
                cur = None
    out = []
    for ch in chains:
        ch = [b for b in ch if b["frames"]]
        key = hash(tuple((b["exc"], tuple(f["raw"] for f in b["frames"][:6])) for b in ch))
        if ch and key not in seen_chain:        # une même erreur répétée 1000 fois dans un log ne compte qu'une fois
            seen_chain.add(key)
            out.append(ch)
    return out[:MAX_CHAINS]


def _split_frame(raw: str) -> tuple[str, str, list[str]]:
    """'TRANSFORMER/mymod@1.0/com.x.Foo.tick' -> (classe, méthode, modules)."""
    parts = raw.split("/")
    mods = [p.split("@", 1)[0] for p in parts[:-1] if "@" in p]
    cm = parts[-1]
    cls, _dot, meth = cm.rpartition(".")
    return cls, meth, mods


def attribute(text: str, index: dict[str, set[str]] | None = None, jars: dict[str, dict] | None = None,
              modids: set[str] | None = None) -> dict:
    """Renvoie {"root": exception racine, "suspects": [{modid, name, file, score, confidence, evidence}]}.

    jars : {nom de fichier: {"modids": [...], "name": str}} des mods installés ; index : voir build_index."""
    jars = jars or {}
    installed = {knowledge.normalize_id(m) for m in (modids or set())} | {knowledge.normalize_id(m) for j in jars.values() for m in j.get("modids", [])}
    by_modid: dict[str, str] = {}
    for fname, j in jars.items():
        for m in j.get("modids", []):
            by_modid.setdefault(knowledge.normalize_id(m), fname)
    names = {knowledge.normalize_id(m): j.get("name") or m for j in jars.values() for m in j.get("modids", [])}
    lower_files = {f.lower(): f for f in jars}

    score: dict[str, float] = defaultdict(float)
    best: dict[str, int] = {}
    why: dict[str, list[str]] = defaultdict(list)
    certain: set[str] = set()

    def credit(modid: str, pts: float, note: str, rank: int) -> None:
        score[modid] += pts
        best[modid] = min(best.get(modid, 99), rank)
        if note not in why[modid] and len(why[modid]) < 3:
            why[modid].append(note)

    for sect in _SUSPECT_SECTION.findall(text):
        for modid, _ver in _SUSPECT_LINE.findall(sect):
            mid = knowledge.normalize_id(modid)
            if mid in ("minecraft", "forge", "neoforge", "fml", "fabricloader", "java"):
                continue
            certain.add(mid)
            credit(mid, 10, _("Désigné par le rapport de crash (Suspected Mods)"), 0)

    root = ""
    chains = _blocks(text)
    for chain in chains:
        for depth, block in enumerate(chain):
            is_root = depth == len(chain) - 1
            if is_root and not root:
                root = block["title"]
            rank = 0
            for fr in block["frames"][:80]:
                cls, meth, modules = _split_frame(fr["raw"])
                found: list[tuple[str, str]] = []                 # (modid, preuve)
                for m in modules:
                    mid = knowledge.normalize_id(m)
                    if mid in installed:
                        found.append((mid, _("module « {m} » dans la pile", m=m)))
                hint = _JAR_HINT.search(fr["hint"])
                if hint and hint.group(1).lower() in lower_files:
                    f = lower_files[hint.group(1).lower()]
                    for m in jars[f].get("modids", [])[:1]:
                        found.append((knowledge.normalize_id(m), _("fichier {f} cité dans la pile", f=f)))
                if not found and cls and not is_core(cls) and index is not None:
                    files = index.get(cls.rsplit("$", 1)[0].rpartition(".")[0] if "." in cls else "", set())
                    if len(files) == 1:
                        f = next(iter(files))
                        for m in jars.get(f, {}).get("modids", [])[:1]:
                            found.append((knowledge.normalize_id(m), _("classe {c} trouvée dans {f}", c=cls.rpartition(".")[2], f=f)))
                if not found and cls and not is_core(cls) and index is None and modids:
                    seg = {p.lower().replace("-", "_") for p in cls.split(".")[:-1]}
                    for mid in installed:
                        if len(mid) >= 4 and mid.replace("-", "_") in seg:
                            found.append((mid, _("paquet {c}", c=cls.rpartition(".")[0])))
                mm = _MIXIN_NAME.match(meth)
                if mm and is_core(cls):
                    mid = knowledge.normalize_id(mm.group(1) or mm.group(2))
                    if mid in installed:
                        found.append((mid, _("code injecté par un mixin dans {c}", c=cls.rpartition(".")[2])))
                for mid, note in found:
                    # Les premières lignes de la pile (là où l'erreur s'est produite) pèsent le plus ; la cause racine double le poids.
                    pts = (3 if rank < 3 else 1.5 if rank < 12 else 0.5) * (2 if is_root else 1)
                    credit(mid, pts, note, rank)
                if found:
                    rank += 1

    suspects = []
    for mid, pts in sorted(score.items(), key=lambda kv: (-kv[1], best.get(kv[0], 99))):
        conf = "certain" if mid in certain else "likely" if pts >= 3 else "heuristic"
        suspects.append({"modid": mid, "name": names.get(mid, mid), "file": by_modid.get(mid), "score": round(pts, 1),
                         "confidence": conf, "evidence": why[mid]})
    return {"root": root, "suspects": suspects[:6]}


def context(a) -> tuple[dict, dict]:
    """(jars, index) d'un pack analysé ; l'index des classes est calculé une fois puis gardé."""
    jars = {f: {"modids": [m["modid"] for m in e["mods"] if m.get("modid")], "name": (e["mods"][0]["name"] if e["mods"] else f)}
            for f, e in a.entries.items()}
    index = getattr(a, "_class_index", None)
    if index is None:
        index = a._class_index = build_index(a.mods_dir, list(a.entries))
    return jars, index


def from_analysis(a, text: str) -> dict:
    """Attribution pour un pack déjà analysé."""
    jars, index = context(a)
    return attribute(text, index, jars)
