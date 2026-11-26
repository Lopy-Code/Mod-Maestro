"""Mise à jour des mods depuis Modrinth, **dans un nouveau dossier** — jamais en écrasant l'ancien.

1. `candidates` : les mises à jour trouvées par l'analyse en ligne (même loader, mêmes versions de Minecraft).
2. `test` : télécharge les versions choisies (adresses officielles, empreinte vérifiée), assemble un pack de test
   dans un dossier temporaire et le **ré-analyse** : on compare avec le pack d'origine pour voir quels problèmes
   les mises à jour créent ou résolvent (dépendance manquante, version exigée, incompatibilité, doublon…).
3. `apply` : seulement après un test de la même sélection, copie le pack mis à jour dans un dossier neuf.
Le dossier de mods d'origine n'est jamais modifié.
"""

from __future__ import annotations

import os
import shutil
from typing import Callable

from . import packimport, parser
from .analyzer import Analysis
from .builder import _inside, suggest_output_dir
from .i18n import _

Progress = Callable[[str, int, int], None]
IGNORED_CATEGORIES = ("updates",)


def candidates(a: Analysis) -> list[dict]:
    """Mises à jour téléchargeables : {file, name, current, latest, new:{filename,url,size,sha1,…}}."""
    issue = next((i for i in a.issues if i["id"] == "updates"), None)
    ups = (issue or {}).get("data", {}).get("updates") or []
    out = []
    for u in ups:
        new = u.get("new")
        if new and u["file"] in a.entries and packimport._allowed(new.get("url", "")) and os.path.basename(new["filename"]) == new["filename"]:
            out.append(u)
    return out


def _link(src: str, dst: str) -> None:
    """Lien symbolique, sinon lien dur, sinon copie : le pack de test ne duplique pas les jars quand c'est possible."""
    for fn in (os.symlink, os.link):
        try:
            fn(src, dst)
            return
        except OSError:
            continue
    shutil.copy2(src, dst)


def _selected(a: Analysis, files) -> list[dict]:
    wanted, known = set(files), {u["file"]: u for u in candidates(a)}
    unknown = wanted - set(known)
    if unknown or not wanted:
        raise ValueError(_("Choisis au moins une mise à jour disponible."))
    return [known[f] for f in sorted(wanted)]


def download(a: Analysis, files, dl_dir: str, progress: Progress | None = None) -> dict[str, str]:
    """Télécharge (ou retrouve) les nouveaux jars dans `dl_dir`. Renvoie {ancien fichier: chemin du nouveau}."""
    prog = progress or (lambda s, d, t: None)
    ups = _selected(a, files)
    os.makedirs(dl_dir, exist_ok=True)
    budget, got = [0], {}
    for i, u in enumerate(ups):
        prog("download", i, len(ups))
        new = u["new"]
        dest = os.path.join(dl_dir, f"{new['sha1'][:12]}_{new['filename']}")
        if not os.path.isfile(dest):
            ok = packimport._download(new["url"], dest, {"sha1": new["sha1"], "sha512": new.get("sha512")}, int(new.get("size") or 0), budget)
            if not ok:
                raise ValueError(_("Le téléchargement de « {name} » a échoué ou son empreinte ne correspond pas : mise à jour annulée.", name=u["name"]))
        got[u["file"]] = dest
    prog("download", len(ups), len(ups))
    return got


def build_pack(a: Analysis, downloaded: dict[str, str], out: str, copy: bool) -> list[str]:
    """Remplit `out` avec les mods d'origine, sauf ceux remplacés, plus les nouveaux jars. Renvoie les fichiers ajoutés."""
    os.makedirs(out, exist_ok=True)
    added = []
    for fname, e in a.entries.items():
        if fname in downloaded:
            continue
        (shutil.copy2 if copy else _link)(e["path"], os.path.join(out, fname))
    for old, path in downloaded.items():
        name = os.path.basename(path).split("_", 1)[1]
        dest = os.path.join(out, name)
        if os.path.exists(dest):
            raise ValueError(_("Le fichier « {name} » existe déjà dans le pack : mise à jour annulée pour éviter un doublon.", name=name))
        (shutil.copy2 if copy else _link)(path, dest)
        added.append(name)
    return added


def test(a: Analysis, files, dl_dir: str, progress: Progress | None = None) -> dict:
    """Télécharge, assemble un pack de test et le compare à l'original."""
    from . import pipeline
    prog = progress or (lambda s, d, t: None)
    downloaded = download(a, files, dl_dir, prog)
    pack = parser._temp_dir("modmaestro_upd_")
    try:
        added = build_pack(a, downloaded, pack, copy=False)
        prog("scan", 0, 0)
        b = pipeline.run_analysis(pack, online=False)
        old_ids = {i["id"] for i in a.active_issues()}
        new_issues = [i for i in b.active_issues() if i["id"] not in old_ids and i["category"] not in IGNORED_CATEGORIES]
        gone = [i for i in a.active_issues() if i["id"] not in {j["id"] for j in b.active_issues()} and i["category"] not in IGNORED_CATEGORIES]
        results = []
        for u in _selected(a, files):
            name = os.path.basename(downloaded[u["file"]]).split("_", 1)[1]
            mids = {m["modid"] for e in (a.entries.get(u["file"]), b.entries.get(name)) if e for m in e["mods"] if m.get("modid")}
            mine = [i for i in new_issues if set(i.get("modids", [])) & mids or name in i.get("files", [])]
            results.append({"file": u["file"], "name": u["name"], "current": u["current"], "latest": u["latest"], "new_file": name,
                            "verdict": "risky" if mine else "ok",
                            "problems": [{"severity": i["severity"], "title": i["title"], "message": i["message"]} for i in mine]})
        other = [i for i in new_issues if not any(i["title"] == p["title"] for r in results for p in r["problems"])]
        return {"results": results, "added": added,
                "new_issues": [{"severity": i["severity"], "title": i["title"], "message": i["message"]} for i in other],
                "resolved": [{"title": i["title"]} for i in gone], "tested": sorted(files)}
    finally:
        shutil.rmtree(pack, ignore_errors=True)


def apply(a: Analysis, files, dl_dir: str, output: str = "") -> dict:
    """Crée le dossier mis à jour (copie réelle). Refuse tout dossier existant non vide ou lié au dossier source."""
    downloaded = download(a, files, dl_dir)          # déjà en cache : aucun téléchargement
    out = os.path.abspath(os.path.expanduser(output.strip().strip('"'))) if output.strip() else suggest_output_dir(a.mods_dir, "mods_updated")
    if _inside(out, a.mods_dir) or _inside(a.mods_dir, out):
        raise ValueError(_("Le dossier de sortie ne doit pas être le dossier de mods (ni dedans, ni le contenir)."))
    if os.path.exists(out) and (not os.path.isdir(out) or os.listdir(out)):
        raise FileExistsError(_("« {path} » existe déjà et n'est pas vide. Choisis un autre nom : je ne mélange jamais mes fichiers avec les tiens.", path=out))
    try:
        added = build_pack(a, downloaded, out, copy=True)
    except Exception:
        if os.path.isdir(out):
            shutil.rmtree(out, ignore_errors=True)
        raise
    return {"output": out, "replaced": len(downloaded), "kept": len(a.entries) - len(downloaded), "added": added}
