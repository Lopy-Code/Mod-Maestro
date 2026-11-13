"""Base de connaissances : socle (knowledge.json) + base communautaire + ta base personnelle.

Sources fusionnées, de la plus générale à la plus personnelle :
  1. core/data/knowledge.json            socle livré avec l'outil
  2. core/data/community/                base communautaire (un fichier JSON par entrée, pensé pour les pull requests)
  3. <dossier utilisateur>/community/    tes propres fichiers, au même format
  4. table `learned` du cache SQLite     ce que tu as appris depuis tes journaux de crash

Format d'une entrée « côté » (sides/<modid>.json) :
  {"modid": "sodium", "side": "client", "reason": "…", "source": "https://…"}
  side = "client" (inutile sur un serveur) ou "both" (à garder : corrige une fausse alerte)

Format d'une entrée « conflit » (conflicts/<nom>.json) — soit un groupe, soit deux listes :
  {"group": ["a", "b", "c"], "severity": "error|warning|info", "title": "…", "message": "…", "fix": "…", "source": "…"}
  {"a": ["x"], "b": ["y", "z"], "severity": "…", "title": "…", "message": "…", "fix": "…", "source": "…"}
"""

from __future__ import annotations

import copy
import json
import os
import re

from .analyzer import load_knowledge
from .i18n import _
from .cache import user_data_dir

ID_RE = re.compile(r"^[a-z0-9_.\-]{1,64}$")
SIDES = {"client", "both"}
SEVERITIES = {"error", "warning", "info"}
MAX_PAIRS = 50


def builtin_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "community")


def user_community_dir() -> str:
    return os.path.join(user_data_dir(), "community")


def normalize_id(modid) -> str:
    return str(modid or "").strip().lower()


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def _id_list(value, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        errors.append(_("« {label} » doit être une liste non vide d'identifiants.", label=label))
        return []
    out = []
    for v in value:
        n = normalize_id(v)
        if not ID_RE.match(n):
            errors.append(_("Identifiant invalide dans « {label} » : {value} (a-z, 0-9, _ . - uniquement).", label=label, value=repr(v)))
        else:
            out.append(n)
    return out


def validate_side(d) -> list[str]:
    errors: list[str] = []
    if not isinstance(d, dict):
        return [_("L'entrée doit être un objet JSON.")]
    if not ID_RE.match(normalize_id(d.get("modid"))):
        errors.append(_("« modid » manquant ou invalide."))
    if d.get("side") not in SIDES:
        errors.append(_("« side » doit valoir « client » ou « both »."))
    if not str(d.get("reason") or "").strip():
        errors.append(_("« reason » est obligatoire : explique pourquoi."))
    return errors


def validate_conflict(d) -> list[str]:
    errors: list[str] = []
    if not isinstance(d, dict):
        return [_("L'entrée doit être un objet JSON.")]
    if "group" in d:
        if len(_id_list(d["group"], "group", errors)) < 2 and not errors:
            errors.append(_("« group » doit contenir au moins deux mods."))
    elif "a" in d and "b" in d:
        _id_list(d["a"], "a", errors)
        _id_list(d["b"], "b", errors)
    else:
        errors.append(_("Il faut soit « group », soit « a » et « b »."))
    if d.get("severity") not in SEVERITIES:
        errors.append(_("« severity » doit valoir error, warning ou info."))
    for key in ("title", "message"):
        if not str(d.get(key) or "").strip():
            errors.append(_("« {key} » est obligatoire.", key=key))
    return errors


# --------------------------------------------------------------------------
# Chargement
# --------------------------------------------------------------------------

def _read_entries(folder: str, validate) -> tuple[list[dict], list[str]]:
    entries, errors = [], []
    if not os.path.isdir(folder):
        return entries, errors
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            errors.append(_("{name} : fichier illisible ({exc}).", name=name, exc=exc))
            continue
        for item in raw if isinstance(raw, list) else [raw]:
            problems = validate(item)
            if problems:
                errors.append(f"{name} : " + " ".join(problems))
            else:
                entries.append(item)
    return entries, errors


def load_dir(base: str) -> dict:
    sides, e1 = _read_entries(os.path.join(base, "sides"), validate_side)
    conflicts, e2 = _read_entries(os.path.join(base, "conflicts"), validate_conflict)
    return {"sides": sides, "conflicts": conflicts, "errors": e1 + e2}


def _rule(entry: dict, default_source: str) -> dict:
    rule = {k: entry[k] for k in ("severity", "title", "message") if k in entry}
    rule["fix"] = entry.get("fix", "")
    rule["source"] = str(entry.get("source") or default_source)
    if "group" in entry:
        rule["group"] = [normalize_id(x) for x in entry["group"]]
    else:
        rule["a"] = [normalize_id(x) for x in entry["a"]]
        rule["b"] = [normalize_id(x) for x in entry["b"]]
    return rule


def load_all(cache=None, community_dirs: list[str] | None = None) -> dict:
    """Retourne le dictionnaire de connaissances fusionné, prêt à être donné à `analyze`."""
    kb = copy.deepcopy(load_knowledge())
    kb.setdefault("client_only", {}).setdefault("ids", [])
    kb.setdefault("conflict_rules", [])
    kb["force_both"] = []
    kb["_ignored"] = []
    errors: list[str] = []
    n_sides = n_conflicts = 0

    for folder, label in ([(d, _("communauté")) for d in community_dirs] if community_dirs is not None
                          else [(builtin_dir(), _("communauté")), (user_community_dir(), _("tes fichiers"))]):
        loaded = load_dir(folder)
        errors += loaded["errors"]
        for s in loaded["sides"]:
            (kb["client_only"]["ids"] if s["side"] == "client" else kb["force_both"]).append(normalize_id(s["modid"]))
            n_sides += 1
        for c in loaded["conflicts"]:
            kb["conflict_rules"].append(_rule(c, label))
            n_conflicts += 1

    n_learned = 0
    if cache is not None:
        for row in cache.list_learned():
            n_learned += 1
            if row["kind"] == "ignore":
                kb["_ignored"].append(row["a"])
            elif row["kind"] == "side":
                (kb["client_only"]["ids"] if row["side"] == "client" else kb["force_both"]).append(row["a"])
            elif row["kind"] == "conflict":
                kb["conflict_rules"].append({
                    "a": [row["a"]], "b": [row["b"]], "severity": row["severity"] or "error",
                    "title": f"{row['a']} ↔ {row['b']}",
                    "message": row["note"] or _("Tu as signalé ces deux mods comme incompatibles."),
                    "fix": _("Retire l'un des deux mods."), "source": _("ta base personnelle")})
    kb["_stats"] = {"community_sides": n_sides, "community_conflicts": n_conflicts,
                    "learned": n_learned, "errors": errors}
    return kb
