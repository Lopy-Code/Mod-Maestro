"""Apprentissage : enregistrer un conflit ou un mod « client » découvert, l'exporter pour la communauté.

Tout est stocké localement (table `learned` du cache). Rien n'est envoyé nulle part : pour partager,
tu exportes un fichier (ou des fichiers prêts pour une pull request) et c'est toi qui décides quoi en faire.
"""

from __future__ import annotations

import json
import os
import time
from itertools import combinations, product

from .knowledge import (ID_RE, MAX_PAIRS, SEVERITIES, SIDES, normalize_id, validate_conflict, validate_side)

BUNDLE_FORMAT = "modmaestro-community"
BUNDLE_VERSION = 1


def _check_id(modid: str, label: str = "mod") -> str:
    n = normalize_id(modid)
    if not ID_RE.match(n):
        raise ValueError(f"Identifiant de {label} invalide : « {modid} » (lettres, chiffres, _ . - uniquement).")
    return n


def add_conflict(cache, a: str, b: str, note: str = "", severity: str = "error", source: str = "manual") -> dict:
    a, b = sorted([_check_id(a, "premier mod"), _check_id(b, "second mod")])
    if a == b:
        raise ValueError("Choisis deux mods différents.")
    if severity not in SEVERITIES:
        raise ValueError("Sévérité inconnue : error, warning ou info.")
    return cache.add_learned("conflict", a, b, severity=severity, note=str(note or "").strip()[:500], source=source)


def add_side(cache, modid: str, side: str = "client", note: str = "", source: str = "manual") -> dict:
    if side not in SIDES:
        raise ValueError("« side » doit valoir « client » ou « both ».")
    return cache.add_learned("side", _check_id(modid), side=side, note=str(note or "").strip()[:500], source=source)


def list_learned(cache) -> list[dict]:
    return cache.list_learned()


def remove(cache, learned_id: int) -> bool:
    return cache.remove_learned(learned_id)


# --------------------------------------------------------------------------
# Export / import
# --------------------------------------------------------------------------

def _side_entry(row: dict) -> dict:
    return {"modid": row["a"], "side": row["side"],
            "reason": row["note"] or ("Inutile sur un serveur dédié." if row["side"] == "client" else "À garder sur le serveur."),
            "source": "signalé par un utilisateur de ModMaestro"}


def _conflict_entry(row: dict) -> dict:
    return {"a": [row["a"]], "b": [row["b"]], "severity": row["severity"] or "error",
            "title": f"{row['a']} ↔ {row['b']}",
            "message": row["note"] or "Ces deux mods ont été signalés comme incompatibles.",
            "fix": "Retire l'un des deux mods.", "source": "signalé par un utilisateur de ModMaestro"}


def to_bundle(cache, ids=None) -> dict:
    rows = [r for r in cache.list_learned() if ids is None or r["id"] in set(ids)]
    return {
        "format": BUNDLE_FORMAT, "version": BUNDLE_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sides": [_side_entry(r) for r in rows if r["kind"] == "side"],
        "conflicts": [_conflict_entry(r) for r in rows if r["kind"] == "conflict"],
    }


def import_bundle(cache, bundle) -> dict:
    """Importe un export (le tien ou celui de quelqu'un d'autre). Chaque entrée est validée."""
    if not isinstance(bundle, dict) or bundle.get("format") != BUNDLE_FORMAT:
        raise ValueError("Ce fichier n'est pas un export ModMaestro.")
    added, errors = 0, []
    for s in bundle.get("sides") or []:
        problems = validate_side(s)
        if problems:
            errors.append(f"Mod « {s.get('modid') if isinstance(s, dict) else '?'} » : " + " ".join(problems))
            continue
        add_side(cache, s["modid"], s["side"], s.get("reason", ""), source="import")
        added += 1
    for c in bundle.get("conflicts") or []:
        problems = validate_conflict(c)
        if problems:
            errors.append("Conflit : " + " ".join(problems))
            continue
        if "group" in c:
            pairs = list(combinations([normalize_id(x) for x in c["group"]], 2))
        else:
            pairs = [(normalize_id(x), normalize_id(y)) for x, y in product(c["a"], c["b"])]
        for x, y in pairs[:MAX_PAIRS]:
            if x != y:
                add_conflict(cache, x, y, c.get("message", ""), c["severity"], source="import")
                added += 1
    return {"added": added, "errors": errors}


def export_files(cache, outdir: str, ids=None) -> list[str]:
    """Écrit un fichier JSON par entrée, dans l'arborescence de core/data/community (prêt pour une PR)."""
    bundle = to_bundle(cache, ids)
    written = []
    for s in bundle["sides"]:
        path = os.path.join(outdir, "sides", f"{s['modid']}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        written.append(path)
    for c in bundle["conflicts"]:
        path = os.path.join(outdir, "conflicts", f"{c['a'][0]}__{c['b'][0]}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(c, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        written.append(path)
    return written


# --------------------------------------------------------------------------
# Suggestions à partir d'un journal de crash
# --------------------------------------------------------------------------

def suggest(findings: list[dict], installed: list[dict]) -> list[dict]:
    """Propose d'enregistrer ce que le journal laisse entrevoir. L'utilisateur confirme toujours.

    installed : liste de {"modid", "side"} des mods du pack (peut être vide sans analyse).
    """
    ids = {normalize_id(m["modid"]) for m in installed if m.get("modid")}
    not_client = sorted({normalize_id(m["modid"]) for m in installed if m.get("modid") and m.get("side") != "client"})
    out = []
    for i, f in enumerate(findings):
        cited = [normalize_id(x) for x in f.get("mods", []) if normalize_id(x) in ids]
        if f["code"] in ("mixin", "binary"):
            out.append({"finding": i, "kind": "conflict", "a": cited[0] if cited else "", "b": "",
                        "note": f["title"], "hint": "Indique avec quel autre mod celui-ci se bat, si tu l'as identifié."})
        elif f["code"] == "client-on-server":
            out.append({"finding": i, "kind": "side", "a": "", "candidates": not_client,
                        "note": "Chargé côté serveur alors qu'il ne devrait pas : mod client.",
                        "hint": "Choisis le mod qui n'a pas sa place sur le serveur."})
    return out
