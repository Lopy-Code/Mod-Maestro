#!/usr/bin/env python3
"""ModMaestro — point d'entrée.

    python main.py                       interface web (s'ouvre dans ton navigateur)
    python main.py DOSSIER               interface web, analyse lancée tout de suite
    python main.py --cli [DOSSIER]       menu interactif dans le terminal
    python main.py --demo                crée un faux modpack pour essayer
    python main.py --audit DOSSIER       audit rapide, sans interface (code retour 1 si erreurs)
    python main.py --compare A B         compare deux modpacks (mods ajoutés / retirés / mis à jour, problèmes)
    python main.py DOSSIER --html F      rapport HTML à envoyer à un ami pour demander de l'aide
    python main.py DOSSIER --export-mrpack F   exporte un modpack Modrinth (.mrpack)
    python main.py DOSSIER --server-kit D      crée les fichiers de lancement d'un serveur optimisé
    python main.py DOSSIER --find-crash  cherche le mod fautif par essais successifs
    python main.py DOSSIER --recommend   mods conseillés pour que les autres fonctionnent mieux
    ajoute --online pour interroger Modrinth (facultatif : seules les empreintes SHA-1 sont envoyées)
    ajoute --lang fr|en pour choisir la langue (par défaut : celle du système)
    python main.py --kb                  affiche ta base personnelle ; --export-kb FICHIER / --import-kb FICHIER

Aucune de ces commandes n'écrit dans ton dossier de mods : les résultats vont dans de nouveaux fichiers/dossiers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

if sys.version_info < (3, 11):
    sys.exit("ModMaestro demande Python 3.11 ou plus récent (vous avez %d.%d).\n"
             "ModMaestro needs Python 3.11 or newer (you have %d.%d).\n"
             "https://www.python.org/downloads/" % (sys.version_info[:2] * 2))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (__version__, builder, compare, crashfinder, demo, export, htmlreport, i18n, learn, logscan,  # noqa: E402
                  parser, pipeline, recommend, report, serverkit)
from core.cache import get_cache  # noqa: E402
from core.i18n import _  # noqa: E402

try:  # `rich` est facultatif : sans lui, on garde un affichage simple
    from rich.console import Console
    from rich.progress import BarColumn, Progress, TextColumn, TaskProgressColumn
    from rich.markup import escape
    from rich.prompt import Prompt
    from rich.table import Table
    HAS_RICH = True
except ImportError:  # pragma: no cover
    HAS_RICH = False

LOGO = r"""
  __  __           _ __  __                 _
 |  \/  | ___   __| |  \/  | __ _  ___  ___| |_ _ __ ___
 | |\/| |/ _ \ / _` | |\/| |/ _` |/ _ \/ __| __| '__/ _ \
 | |  | | (_) | (_| | |  | | (_| |  __/\__ \ |_| | | (_) |
 |_|  |_|\___/ \__,_|_|  |_|\__,_|\___||___/\__|_|  \___/
"""


def sev(severity: str) -> tuple[str, str]:
    """Étiquette et couleur d'une gravité."""
    return {"error": (_("ERREUR"), "red"), "warning": (_("ATTENTION"), "yellow"), "info": (_("INFO"), "blue")}[severity]


def pick_lang(argv: list[str]) -> str:
    """Langue choisie AVANT de construire le parser (l'aide doit déjà être traduite) :
    --lang, puis MODMAESTRO_LANG, puis la langue du système ; français par défaut."""
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1] if argv[i + 1] in i18n.LANGS else "fr"
        if a.startswith("--lang="):
            v = a.split("=", 1)[1]
            return v if v in i18n.LANGS else "fr"
    env = os.environ.get("MODMAESTRO_LANG", "").lower()
    if env in i18n.LANGS:
        return env
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(key, "")
        if v:
            return "en" if v.lower().startswith("en") else "fr"
    return "fr"


# --------------------------------------------------------------------------
# Affichage (rich si disponible, sinon texte brut)
# --------------------------------------------------------------------------

class UI:
    def __init__(self):
        self.c = Console() if HAS_RICH else None

    def say(self, msg="", style=""):
        if self.c:
            self.c.print(msg, style=style or None, highlight=False)
        else:
            print(_plain(msg))

    def ask(self, label, default=None):
        if self.c:
            return Prompt.ask(f"[bold #D97757]›[/] {label}", default=default) if default else Prompt.ask(f"[bold #D97757]›[/] {label}")
        raw = input(f"› {label}" + (f" [{default}]" if default else "") + " : ").strip()
        return raw or (default or "")

    def confirm(self, label, default=True):
        hint = f"[{_('O/n') if default else _('o/N')}]"
        if self.c:  # pas de Confirm de rich : il n'accepte que « y / n », or « o » (oui) doit marcher aussi
            self.c.print(f"[bold #D97757]›[/] {label} {escape(hint)} :", end=" ", highlight=False)
            raw = input().strip().lower()
        else:
            raw = input(f"› {label} {hint} : ").strip().lower()
        return default if not raw else raw in ("o", "oui", "y", "yes")

    def banner(self):
        if self.c:
            self.c.print(f"[#D97757]{LOGO}[/]")
            self.c.print("  " + _("[bold]Le chef d'orchestre de ton modpack Minecraft[/]  [dim]v{version}[/]", version=__version__) + "\n")
        else:
            print(LOGO + "\n  " + _("Le chef d'orchestre de ton modpack Minecraft — v{version}", version=__version__) + "\n")

    def run(self, path, online=False):
        """Lance l'analyse (pipeline commun avec l'interface web) avec une barre de progression."""
        labels = {"scan": _("Lecture des mods"), "hash": _("Calcul des empreintes"), "query": _("Interrogation de Modrinth"),
                  "projects": _("Fiches Modrinth"), "updates": _("Mises à jour")}
        if not self.c:
            last = {"stage": None}

            def plain(stage, done, total):
                if stage != last["stage"] and last["stage"]:
                    print()
                last["stage"] = stage
                print(f"\r  {labels.get(stage, stage)} {done}/{total}", end="", flush=True)
            try:
                return pipeline.run_analysis(path, online=online, progress=plain)
            finally:
                print()
        with Progress(TextColumn("[#D97757]{task.description}"), BarColumn(complete_style="#D97757"),
                      TaskProgressColumn(), console=self.c, transient=True) as pr:
            task = pr.add_task(_("Lecture des mods"), total=None)

            def fancy(stage, done, total):
                pr.update(task, description=labels.get(stage, stage), total=total, completed=done)
            return pipeline.run_analysis(path, online=online, progress=fancy)


def _plain(msg: str) -> str:
    import re
    return re.sub(r"\[/?[^\]]*\]", "", str(msg))


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

def load(ui: UI, path: str, online: bool = False):
    a = ui.run(path, online)
    for n in a.notes:
        ui.say(f"[dim]{n}[/]")
    return a


def show_summary(ui: UI, a):
    d = a.to_dict()
    c = d["counts"]
    ui.say(f"\n[bold]{d['loader_label']}[/]" + (f" · Minecraft {d['mc_version']}" if d["mc_version"] else "") + " · "
           + _("{mods} mods dans {jars} fichiers · santé [bold]{score}/100[/]", mods=c["mods"], jars=c["jars"], score=d["score"]))
    ui.say(_("[red]{e} erreur(s)[/] · [yellow]{w} avertissement(s)[/] · [blue]{i} info(s)[/]",
             e=c["errors"], w=c["warnings"], i=c["infos"]))
    o = d.get("online") or {}
    if o.get("enabled"):
        line = _("Modrinth : {a}/{b} mods reconnus", a=o.get("identified", 0), b=o.get("total", 0))
        if o.get("updates"):
            line += " · " + _("{n} mise(s) à jour", n=o["updates"])
        ui.say(f"[dim]{line}[/]")
    if d.get("boot") and d["boot"].get("fresh") and d["boot"]["status"] != "unknown":
        ui.say("[green]" + _("✓ Le dernier lancement du jeu a réussi.") + "[/]" if d["boot"]["status"] == "ok"
               else "[red]" + _("✗ Le dernier lancement du jeu a échoué.") + "[/]")
    ui.say()
    return d


def show_issues(ui: UI, d: dict, category: str | None = None):
    issues = [i for i in d["issues"] if category in (None, i["category"]) and not i.get("ignored")]
    if not issues:
        ui.say("[green]" + _("✓ Rien à signaler.") + "[/]\n")
        return
    for i in issues:
        label, color = sev(i["severity"])
        ui.say(f"[bold {color}]{label}[/]  [bold]{i['title']}[/]")
        ui.say(f"   {i['message']}")
        if i["fix"]:
            ui.say(f"   [green]→ {i['fix']}[/]")
        ui.say()


def show_mods(ui: UI, d: dict):
    if not ui.c:
        for m in d["mods"]:
            print(f"{m['name']:<36} {str(m['version'] or '?'):<14} {m['side']:<8} {m['file']}")
        return
    t = Table(show_lines=False, header_style="bold #D97757", border_style="dim")
    for col in (_("Mod"), _("Version"), _("Loader"), _("Côté"), _("Fichier")):
        t.add_column(col)
    colors = {"client": "blue", "server": "green", "both": "white", "unsure": "yellow"}
    for m in sorted(d["mods"], key=lambda x: x["name"].lower()):
        t.add_row(m["name"], str(m["version"] or "?"), m["loader"] or "—",
                  f"[{colors[m['side']]}]{m['side']}[/]", m["file"])
    ui.c.print(t)


def _guard(a, dest: str) -> str:
    """Chemin absolu de `dest`, à condition qu'il ne soit pas dans (ni ne contienne) le dossier de mods analysé."""
    out = os.path.abspath(os.path.expanduser(str(dest).strip().strip('"')))
    src = os.path.realpath(a.mods_dir)
    real = os.path.realpath(out)
    if real == src or real.startswith(src + os.sep) or src.startswith(real + os.sep):
        raise ValueError(_("La destination ne doit pas être le dossier de mods (ni dedans, ni le contenir)."))
    return out


def do_server(ui: UI, a):
    d = a.to_dict()
    p = d["plan"]
    ui.say("\n" + _("[bold]{keep}[/] mods gardés · [bold]{remove}[/] retirés · [bold]{unsure}[/] à vérifier",
                    keep=len(p["keep"]), remove=len(p["remove"]), unsure=len(p["unsure"])) + "\n")
    for r in p["remove"]:
        ui.say(f"  [red]✗[/] {r['file']}  [dim]{r['reason']}[/]")
    for u in p["unsure"]:
        ui.say(f"  [yellow]?[/] {u['file']}  [dim]" + _("gardé — {reason}", reason=u["reason"]) + "[/]")
    ui.say()
    exclude = []
    if p["unsure"] and ui.confirm(_("Retirer aussi les mods « à vérifier » ?"), default=False):
        exclude = [u["file"] for u in p["unsure"]]
    out = ui.ask(_("Dossier de destination"), builder.suggest_output_dir(a.mods_dir))
    make_zip = ui.confirm(_("Créer aussi une archive .zip ?"), default=False)
    try:
        r = builder.build_server(a, out, exclude=exclude, make_zip=make_zip)
    except (ValueError, FileExistsError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return
    ui.say("\n" + _("[green]✓ {copied} mods copiés[/] dans {output}", copied=r["copied"], output=r["output"])
           + ("\n" + _("[green]✓ Archive :[/] {zip}", zip=r["zip"]) if r["zip"] else "") + "\n")


def do_logs(ui: UI, a=None):
    default = None
    if a:
        found = logscan.find_logs(a.mods_dir)
        if found:
            default = found[0]["path"]
            ui.say("[dim]" + _("Journal le plus récent trouvé : {name}", name=found[0]["name"]) + "[/]")
    path = ui.ask(_("Chemin du journal (latest.log, crash-report…)"), default)
    try:
        findings = logscan.scan_text(logscan.read_log(path))
    except (ValueError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return
    if not findings:
        ui.say("[green]" + _("✓ Aucune cause connue détectée dans ce journal.") + "[/]\n")
    for f in findings:
        label, color = sev(f["severity"])
        ui.say(f"[bold {color}]{label}[/]  [bold]{f['title']}[/]\n   {f['message']}")
        if f["fix"]:
            ui.say(f"   [green]→ {f['fix']}[/]")
        ui.say()


def do_learn(ui: UI, a):
    """Enregistre un conflit ou un mod « client » dans ta base personnelle (stockée sur ton ordinateur)."""
    cache = get_cache()
    ids = sorted({m["modid"] for m in a.to_dict()["mods"] if m["modid"]})
    ui.say(_("[bold]Ma base[/]  [dim](stockée sur ton ordinateur, appliquée à toutes tes prochaines analyses)[/]"))
    for r in cache.list_learned():
        what = f"{r['a']} ↔ {r['b']}" if r["kind"] == "conflict" else f"{r['a']} ({r['side']})"
        ui.say(f"  [dim]#{r['id']}[/] {what}" + (f"  [dim]{r['note']}[/]" if r["note"] else ""))
    ui.say("\n  " + _("[bold]1[/] Ajouter un conflit   [bold]2[/] Marquer un mod « client uniquement »   "
                      "[bold]3[/] Marquer un mod « à garder sur le serveur »   [bold]4[/] Supprimer une entrée   [bold]0[/] Retour"))
    choice = ui.ask(_("Ton choix"), "0")
    try:
        if choice == "1":
            x = ui.ask(_("Premier mod (identifiant)"))
            y = ui.ask(_("Second mod (identifiant)"))
            note = ui.ask(_("Note (facultative)"), "")
            sv = ui.ask(_("Gravité (error / warning / info)"), "error")
            learn.add_conflict(cache, x, y, note, sv)
        elif choice in ("2", "3"):
            ui.say("[dim]" + _("Mods du pack : {mods}", mods=", ".join(ids[:30]) + (" …" if len(ids) > 30 else "")) + "[/]")
            learn.add_side(cache, ui.ask(_("Mod (identifiant)")), "client" if choice == "2" else "both", ui.ask(_("Note (facultative)"), ""))
        elif choice == "4":
            ui.say("[green]" + _("✓ Supprimée.") + "[/]" if learn.remove(cache, int(ui.ask(_("Numéro de l'entrée"))))
                   else "[yellow]" + _("Aucune entrée avec ce numéro.") + "[/]")
            return
        else:
            return
    except ValueError as exc:
        ui.say(f"[red]{exc}[/]\n")
        return
    ui.say(_("[green]✓ Enregistré.[/] Relance l'analyse (choix 9) pour l'appliquer.") + "\n")


def export_report(ui: UI, a):
    dest = ui.ask(_("Enregistrer le rapport sous"), os.path.join(os.path.dirname(a.mods_dir), "rapport-modmaestro.md"))
    try:
        with open(_guard(a, dest), "w", encoding="utf-8") as fh:
            fh.write(report.to_markdown(a.to_dict()))
        ui.say(_("[green]✓ Rapport écrit :[/] {path}", path=dest) + "\n")
    except (OSError, ValueError) as exc:
        ui.say(f"[red]{exc}[/]\n")


# --------------------------------------------------------------------------
# Nouvelles fonctions (v1.2) : chaque fonction `run_*` sert à la fois au menu et aux options de la ligne de commande
# --------------------------------------------------------------------------

def run_html(ui: UI, a, dest: str) -> int:
    try:
        out = _guard(a, dest)
        if os.path.exists(out):
            raise FileExistsError(_("« {path} » existe déjà : choisis un autre nom.", path=out))
        html = htmlreport.to_html(a.to_dict(), include_files=True, include_source=False)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
    except (ValueError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return 2
    ui.say(_("[green]✓ Rapport HTML écrit :[/] {path}", path=out))
    ui.say("[dim]" + _("Aucun chemin de ton ordinateur n'y figure : tu peux l'envoyer tel quel.") + "[/]\n")
    return 0


def _pack_name(a) -> str:
    base = os.path.basename(os.path.abspath(a.mods_dir))
    if base.lower() == "mods":
        base = os.path.basename(os.path.dirname(os.path.abspath(a.mods_dir)))
    return base or "modpack"


def run_mrpack(ui: UI, a, dest: str, name: str = "", mc: str = "", loader_version: str = "") -> int:
    try:
        out = _guard(a, dest)
        if os.path.exists(out):
            raise FileExistsError(_("« {path} » existe déjà : choisis un autre nom.", path=out))
        inst = export.detect_instance(a.mods_dir)
        r = export.export_mrpack(a, out, name=name or _pack_name(a), mc=mc or inst.get("mc", ""),
                                 loader_version=loader_version or inst.get("loader_version", ""))
    except (ValueError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return 2
    ui.say(_("[green]✓ Modpack écrit :[/] {path}", path=r["path"]))
    ui.say(_("{a} mods référencés, {b} copiés dans le fichier.", a=r["referenced"], b=r["embedded"]))
    for w in r["warnings"]:
        ui.say(f"[yellow]! {w}[/]")
    ui.say()
    return 0


def run_kit(ui: UI, a, dest: str, ram: int | None = None, eula: bool = False) -> int:
    try:
        out = _guard(a, dest)
        r = serverkit.generate(a, out, ram_gb=ram, eula=eula, with_mods=True)
    except (ValueError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return 2
    ui.say(_("[green]✓ Kit serveur créé :[/] {path}", path=r["output"]))
    ui.say(_("Java {java} · {ram} Go de mémoire · fichiers : {files}", java=r["java"], ram=r["ram"], files=", ".join(r["written"])))
    for n in r["notes"]:
        ui.say(f"[yellow]! {n}[/]")
    ui.say()
    return 0


def run_recommend(ui: UI, a, online: bool = False) -> int:
    r = recommend.run(a, online=online, cache=get_cache())
    if r.get("error"):
        ui.say(f"[yellow]{r['error']}[/]")
    if r.get("note"):
        ui.say(f"[dim]{r['note']}[/]")
    if not r["items"]:
        ui.say("[green]" + _("✓ Rien à ajouter : ton pack a déjà les compagnons habituels.") + "[/]\n")
        return 0
    cats = {"compat": _("Compatibilité"), "performance": _("Performances"), "companion": _("Compagnons utiles"),
            "diagnostic": _("Diagnostic")}
    last = None
    for it in r["items"]:
        if it["category"] != last:
            last = it["category"]
            ui.say(f"\n[bold #D97757]{cats.get(last, last)}[/]")
        status = ""
        if it.get("available") is True:
            status = " [green]" + _("disponible") + "[/]"
        elif it.get("available") is False:
            status = " [red]" + _("pas pour Minecraft {mc}", mc=r["mc_version"] or "?") + "[/]"
        ui.say(f"  [bold]{it['name']}[/]{status}  [dim]{it['url']}[/]")
        ui.say(f"    {it['why']}")
        if it.get("alternatives"):
            ui.say("    [dim]" + _("Alternatives : {names}", names=", ".join(it["alternatives"])) + "[/]")
    ui.say()
    return 0


def run_find_crash(ui: UI, a) -> int:
    """Recherche par essais : ModMaestro prépare des dossiers de test, tu lances le jeu et tu réponds."""
    st = crashfinder.start(a)
    hints = crashfinder.quick_suspects(a)
    if hints:
        ui.say("[bold]" + _("Suspects évidents :") + "[/] " + ", ".join(f"{h['name']} ({h['why']})" for h in hints) + "\n")
    outcomes = {"c": crashfinder.CRASH, "f": crashfinder.FINE, "s": crashfinder.SKIP}
    try:
        for _n in range(80):  # garde-fou : une recherche normale tient en une dizaine d'essais
            if st["done"]:
                break
            v = crashfinder.describe(a, st)
            p = v["pending"]
            ui.say(_("[bold #D97757]Essai {step}[/] — environ {n} essai(s) restant(s)", step=v["step"], n=v["estimate"]))
            if p["kind"] == "confirm":
                ui.say(_("Dernier contrôle : lance le jeu sans le suspect trouvé ({count} mods).", count=p["count"]))
            else:
                ui.say(_("Lance le jeu avec {count} mods ({in_play} suspects en lice, {excluded} mis de côté).",
                         count=p["count"], in_play=p["in_play"], excluded=p["excluded"]))
            if ui.confirm(_("Créer le dossier de test ?"), default=True):
                out = ui.ask(_("Dossier de test (nouveau, vide)"), builder.suggest_output_dir(a.mods_dir, "modmaestro_test"))
                try:
                    r = crashfinder.build_test_folder(a, st, out)
                    ui.say(_("[green]✓ {copied} mods copiés[/] dans {output}", copied=r["copied"], output=r["output"]))
                except (ValueError, OSError) as exc:
                    ui.say(f"[red]{exc}[/]")
            while True:
                ans = ui.ask(_("Résultat : c = ça plante · f = ça marche · s = je n'ai pas pu tester")).strip().lower()[:1]
                if ans in outcomes:
                    break
                ui.say("[yellow]" + _("Choix inconnu.") + "[/]")
            st = crashfinder.answer(a, st, outcomes[ans])
            ui.say()
    except (EOFError, KeyboardInterrupt):
        ui.say("\n" + _("Recherche interrompue."))
        return 2
    if not st["done"]:
        ui.say("[yellow]" + _("Recherche interrompue : trop d'essais sans réponse.") + "[/]")
        return 2
    ui.say("[bold green]" + crashfinder.summary(a, st) + "[/]\n")
    return 0


def run_compare(ui: UI, a, b) -> int:
    r = compare.compare(a.to_dict(), b.to_dict())
    for tag, h in ((_("Avant"), r["a"]), (_("Après"), r["b"])):
        ui.say(f"[bold]{tag}[/] : {h['loader_label']}" + (f" · Minecraft {h['mc_version']}" if h["mc_version"] else "") + " — "
               + _("{mods} mods · santé {score}/100", mods=h["mods"], score=h["score"]))
    ui.say(_("Variation de santé : {delta:+d}", delta=r["score_delta"]) + "\n")
    for n in r["notes"]:
        ui.say(f"[dim]{n}[/]")
    sections = (
        (_("Mods ajoutés ({n})", n=len(r["added"])), r["added"], "[green]+[/]", lambda m: f"{m['name']} {m['version'] or ''}"),
        (_("Mods retirés ({n})", n=len(r["removed"])), r["removed"], "[red]-[/]", lambda m: f"{m['name']} {m['version'] or ''}"),
        (_("Mods mis à jour ({n})", n=len(r["updated"])), r["updated"], "[blue]↑[/]", lambda m: f"{m['name']}  {m['from'] or '?'} → {m['to'] or '?'}"),
        (_("Versions plus anciennes ({n})", n=len(r["downgraded"])), r["downgraded"], "[yellow]↓[/]",
         lambda m: f"{m['name']}  {m['from'] or '?'} → {m['to'] or '?'}"),
        (_("Problèmes apparus ({n})", n=len(r["new_issues"])), r["new_issues"], "[red]![/]", lambda i: i["title"]),
        (_("Problèmes résolus ({n})", n=len(r["fixed_issues"])), r["fixed_issues"], "[green]✓[/]", lambda i: i["title"]),
    )
    for title, rows, mark, fmt in sections:
        if rows:
            ui.say(f"[bold]{title}[/]")
            for row in rows:
                ui.say(f"  {mark} {fmt(row)}")
            ui.say()
    ui.say(_("{n} mods inchangés", n=r["unchanged"]) + "\n")
    return 0


# --------------------------------------------------------------------------
# Menu interactif
# --------------------------------------------------------------------------

def cli_menu(path: str | None, online: bool = False):
    ui = UI()
    ui.banner()
    a = None
    while a is None:
        path = path or ui.ask(_("Dossier mods du modpack (ou « demo » pour essayer)"))
        if path.strip().lower() == "demo":
            path = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
            ui.say("[dim]" + _("Modpack de démo créé : {path}", path=path) + "[/]")
        try:
            a = load(ui, path, online)
        except ValueError as exc:
            ui.say(f"[red]{exc}[/]\n")
            path = None
    d = show_summary(ui, a)

    while True:
        entries = [
            ("1", _("Audit complet (doublons, dépendances, incompatibilités)")),
            ("2", _("Doublons uniquement")),
            ("3", _("Dépendances manquantes uniquement")),
            ("4", _("Liste des mods")),
            ("5", _("Créer le dossier mods du serveur")),
            ("6", _("Analyser un journal de crash")),
            ("7", _("Exporter le rapport (.md)")),
            ("8", _("Analyser un autre dossier")),
            ("9", _("Relancer l'analyse") + (" " + _("(Modrinth activé)") if online else "")),
            ("f", _("Chercher le mod fautif par essais")),
            ("c", _("Comparer avec un autre modpack")),
            ("r", _("Mods conseillés")),
            ("h", _("Rapport HTML à envoyer à un ami")),
            ("x", _("Exporter en modpack .mrpack")),
            ("k", _("Fichiers de lancement du serveur")),
            ("m", _("Ma base : conflits et mods client appris")),
            ("o", _("Activer / désactiver Modrinth (actuellement : {state})", state=_("activé") if online else _("désactivé"))),
            ("l", _("Changer de langue (français / English)")),
            ("0", _("Quitter")),
        ]
        ui.say("[bold #D97757]" + _("Que veux-tu faire ?") + "[/]")
        for k, label in entries:
            ui.say(f"  [bold]{k}[/]  {label}")
        choice = ui.ask(_("Ton choix"), "1").strip().lower()
        ui.say()
        if choice == "1":
            show_issues(ui, d)
        elif choice == "2":
            show_issues(ui, d, "duplicates")
        elif choice == "3":
            show_issues(ui, d, "dependencies")
        elif choice == "4":
            show_mods(ui, d)
        elif choice == "5":
            do_server(ui, a)
        elif choice == "6":
            do_logs(ui, a)
        elif choice == "7":
            export_report(ui, a)
        elif choice == "8":
            return cli_menu(None, online)
        elif choice == "9":
            return cli_menu(a.source, online)
        elif choice == "f":
            run_find_crash(ui, a)
        elif choice == "c":
            other = ui.ask(_("Dossier mods de l'autre modpack"))
            try:
                run_compare(ui, a, load(ui, other, online))
            except ValueError as exc:
                ui.say(f"[red]{exc}[/]\n")
        elif choice == "r":
            run_recommend(ui, a, online)
        elif choice == "h":
            run_html(ui, a, ui.ask(_("Enregistrer le rapport sous"), builder.suggest_file(a.mods_dir, "rapport-modmaestro", ".html")))
        elif choice == "x":
            run_mrpack(ui, a, ui.ask(_("Enregistrer le modpack sous"), builder.suggest_file(a.mods_dir, _pack_name(a), ".mrpack")))
        elif choice == "k":
            eula = ui.confirm(_("Accepter le contrat de licence de Minecraft (EULA) dans eula.txt ?"), default=False)
            run_kit(ui, a, ui.ask(_("Dossier de destination"), builder.suggest_output_dir(a.mods_dir, "server_kit")), eula=eula)
        elif choice == "m":
            do_learn(ui, a)
        elif choice == "l":
            i18n.set_lang("en" if i18n.get_lang() == "fr" else "fr")
            ui.say(_("Langue : français") + "\n")
        elif choice == "o":
            if online:
                online = False
            else:
                ui.say(_("Modrinth reçoit [bold]uniquement l'empreinte SHA-1[/] de chaque .jar (jamais les noms de fichiers ni ton dossier)."))
                online = ui.confirm(_("Activer Modrinth pour la prochaine analyse ?"), default=False)
            ui.say(_("Modrinth : {state} — choisis 9 pour relancer l'analyse.", state=_("[green]activé[/]") if online else _("désactivé")) + "\n")
        elif choice == "0":
            ui.say(_("À bientôt !"))
            return 0
        else:
            ui.say("[yellow]" + _("Choix inconnu.") + "[/]\n")


def kb_command(args) -> int:
    cache = get_cache()
    if args.import_kb:
        try:
            with open(args.import_kb, encoding="utf-8") as fh:
                res = learn.import_bundle(cache, json.load(fh))
        except (OSError, ValueError) as exc:
            print(_("Import impossible : {exc}", exc=exc), file=sys.stderr)
            return 2
        msg = _("{n} entrée(s) importée(s).", n=res["added"])
        if res["errors"]:
            msg += " " + _("{n} ignorée(s) : {errors}", n=len(res["errors"]), errors=" ".join(res["errors"][:3]))
        print(msg)
    if args.export_kb:
        with open(args.export_kb, "w", encoding="utf-8") as fh:
            json.dump(learn.to_bundle(cache), fh, ensure_ascii=False, indent=2)
        print(_("Base exportée : {path}", path=args.export_kb))
    if not (args.import_kb or args.export_kb):
        rows = cache.list_learned()
        for r in rows:
            print(f"#{r['id']:<3} {r['kind']:<8} {r['a']}" + (f" ↔ {r['b']}" if r["b"] else f" ({r['side']})") + (f"  — {r['note']}" if r["note"] else ""))
        if not rows:
            print(_("Ta base est vide. Ajoute des entrées depuis l'interface (onglet « Ma base ») ou le menu (touche m)."))
    return 0


def quick_audit(path: str, online: bool = False) -> int:
    ui = UI()
    try:
        a = load(ui, path, online)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    d = show_summary(ui, a)
    show_issues(ui, d)
    return 1 if d["counts"]["errors"] else 0


def compare_command(pa: str, pb: str, online: bool) -> int:
    ui = UI()
    try:
        a = load(ui, pa, online)
        b = load(ui, pb, online)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    return run_compare(ui, a, b)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="modmaestro", description=_("Audit de modpacks Minecraft."))
    ap.add_argument("path", nargs="?", help=_("dossier mods (ou instance) à analyser"))
    ap.add_argument("--lang", choices=i18n.LANGS, help=_("langue : fr ou en (par défaut : celle du système)"))
    ap.add_argument("--cli", action="store_true", help=_("menu dans le terminal plutôt que l'interface web"))
    ap.add_argument("--audit", action="store_true", help=_("audit rapide non interactif"))
    ap.add_argument("--demo", action="store_true", help=_("crée un modpack de démonstration et l'ouvre"))
    ap.add_argument("--online", action="store_true",
                    help=_("interroge Modrinth (envoie uniquement les empreintes SHA-1 des .jar) — désactivé par défaut"))
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help=_("compare deux modpacks (A = avant, B = après)"))
    ap.add_argument("--html", metavar=_("FICHIER"), help=_("écrit un rapport HTML à envoyer pour demander de l'aide"))
    ap.add_argument("--export-mrpack", metavar=_("FICHIER"), help=_("exporte le modpack au format Modrinth (.mrpack)"))
    ap.add_argument("--mc", default="", help=_("version de Minecraft pour le .mrpack (sinon : détectée)"))
    ap.add_argument("--loader-version", default="", help=_("version du loader pour le .mrpack (par exemple 21.1.172)"))
    ap.add_argument("--server-kit", metavar=_("DOSSIER"), help=_("crée les fichiers de lancement d'un serveur optimisé dans ce nouveau dossier"))
    ap.add_argument("--ram", type=int, help=_("mémoire du serveur en Go (par défaut : estimée d'après le nombre de mods)"))
    ap.add_argument("--accept-eula", action="store_true",
                    help=_("accepte toi-même le contrat de licence de Minecraft dans eula.txt (sinon il reste à « false »)"))
    ap.add_argument("--find-crash", action="store_true", help=_("cherche le mod fautif par essais successifs"))
    ap.add_argument("--recommend", action="store_true", help=_("affiche les mods conseillés pour ce pack"))
    ap.add_argument("--kb", action="store_true", help=_("affiche ta base personnelle (conflits et mods client appris)"))
    ap.add_argument("--export-kb", metavar=_("FICHIER"), help=_("exporte ta base personnelle dans un fichier .json"))
    ap.add_argument("--import-kb", metavar=_("FICHIER"), help=_("importe une base .json (rien n'est envoyé nulle part)"))
    ap.add_argument("--port", type=int, default=8765, help=_("port de l'interface web (défaut : 8765)"))
    ap.add_argument("--no-browser", action="store_true", help=_("ne pas ouvrir le navigateur automatiquement"))
    ap.add_argument("--version", action="version", version=f"ModMaestro {__version__}")
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.set_lang(pick_lang(argv))
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.kb or args.export_kb or args.import_kb:
        return kb_command(args)
    if args.compare:
        return compare_command(args.compare[0], args.compare[1], args.online)

    path = args.path
    if args.demo:
        path = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
        print(_("Modpack de démo : {path}", path=path))

    jobs = [("--audit", args.audit), ("--html", args.html), ("--export-mrpack", args.export_mrpack),
            ("--server-kit", args.server_kit), ("--find-crash", args.find_crash), ("--recommend", args.recommend)]
    active = [name for name, on in jobs if on]
    if active:
        if not path:
            ap.error(_("{opt} demande un dossier", opt=active[0]))
        if args.audit and len(active) == 1:
            return quick_audit(path, args.online)
        ui = UI()
        try:
            a = load(ui, path, args.online)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        code = 0
        if args.audit:
            code = max(code, 1 if show_summary(ui, a)["counts"]["errors"] else 0)
        if args.html:
            code = max(code, run_html(ui, a, args.html))
        if args.export_mrpack:
            code = max(code, run_mrpack(ui, a, args.export_mrpack, mc=args.mc, loader_version=args.loader_version))
        if args.server_kit:
            code = max(code, run_kit(ui, a, args.server_kit, ram=args.ram, eula=args.accept_eula))
        if args.recommend:
            code = max(code, run_recommend(ui, a, args.online))
        if args.find_crash:
            code = max(code, run_find_crash(ui, a))
        return code
    if args.cli:
        return cli_menu(path, args.online) or 0

    from web.server import serve
    serve(initial_path=path, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n" + _("À bientôt !"))
        sys.exit(0)
