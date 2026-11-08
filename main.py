#!/usr/bin/env python3
"""ModMaestro — point d'entrée.

    python main.py                    interface web (s'ouvre dans ton navigateur)
    python main.py DOSSIER            interface web, analyse lancée tout de suite
    python main.py --cli [DOSSIER]    menu interactif dans le terminal
    python main.py --demo             crée un faux modpack pour essayer
    python main.py --audit DOSSIER    audit rapide, sans interface (code retour 1 si erreurs)
    ajoute --online pour interroger Modrinth (facultatif : seules les empreintes SHA-1 sont envoyées)
    python main.py --kb               affiche ta base personnelle ; --export-kb FICHIER / --import-kb FICHIER
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

if sys.version_info < (3, 11):
    sys.exit("ModMaestro demande Python 3.11 ou plus récent (vous avez %d.%d).\n"
             "Téléchargement : https://www.python.org/downloads/" % sys.version_info[:2])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import __version__, builder, demo, learn, logscan, parser, pipeline, report  # noqa: E402
from core.cache import get_cache  # noqa: E402

try:  # `rich` est facultatif : sans lui, on garde un affichage simple
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn, TaskProgressColumn
    from rich.prompt import Confirm, IntPrompt, Prompt
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
SEV = {"error": ("ERREUR", "red"), "warning": ("ATTENTION", "yellow"), "info": ("INFO", "blue")}


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
        if self.c:
            return Confirm.ask(f"[bold #D97757]›[/] {label}", default=default)
        raw = input(f"› {label} [{'O/n' if default else 'o/N'}] : ").strip().lower()
        return default if not raw else raw in ("o", "oui", "y", "yes")

    def banner(self):
        if self.c:
            self.c.print(f"[#D97757]{LOGO}[/]")
            self.c.print(f"  [bold]Le chef d'orchestre de ton modpack Minecraft[/]  [dim]v{__version__}[/]\n")
        else:
            print(LOGO + f"\n  Le chef d'orchestre de ton modpack Minecraft — v{__version__}\n")

    def run(self, path, online=False):
        """Lance l'analyse (pipeline commun avec l'interface web) avec une barre de progression."""
        labels = {"scan": "Lecture des mods", "hash": "Calcul des empreintes", "query": "Interrogation de Modrinth",
                  "projects": "Fiches Modrinth", "updates": "Mises à jour"}
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
            task = pr.add_task("Lecture des mods", total=None)

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
    ui.say(f"\n[bold]{d['loader_label']}[/]" + (f" · Minecraft {d['mc_version']}" if d["mc_version"] else "")
           + f" · {c['mods']} mods dans {c['jars']} fichiers · santé [bold]{d['score']}/100[/]")
    ui.say(f"[red]{c['errors']} erreur(s)[/] · [yellow]{c['warnings']} avertissement(s)[/] · [blue]{c['infos']} info(s)[/]")
    o = d.get("online") or {}
    if o.get("enabled"):
        ui.say(f"[dim]Modrinth : {o.get('identified', 0)}/{o.get('total', 0)} mods reconnus"
               + (f" · {o['updates']} mise(s) à jour" if o.get("updates") else "") + "[/]")
    ui.say()
    return d


def show_issues(ui: UI, d: dict, category: str | None = None):
    issues = [i for i in d["issues"] if category in (None, i["category"])]
    if not issues:
        ui.say("[green]✓ Rien à signaler.[/]\n")
        return
    for i in issues:
        label, color = SEV[i["severity"]]
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
    for col in ("Mod", "Version", "Loader", "Côté", "Fichier"):
        t.add_column(col)
    colors = {"client": "blue", "server": "green", "both": "white", "unsure": "yellow"}
    for m in sorted(d["mods"], key=lambda x: x["name"].lower()):
        t.add_row(m["name"], str(m["version"] or "?"), m["loader"] or "—",
                  f"[{colors[m['side']]}]{m['side']}[/]", m["file"])
    ui.c.print(t)


def do_server(ui: UI, a):
    d = a.to_dict()
    p = d["plan"]
    ui.say(f"\n[bold]{len(p['keep'])}[/] mods gardés · [bold]{len(p['remove'])}[/] retirés · [bold]{len(p['unsure'])}[/] à vérifier\n")
    for r in p["remove"]:
        ui.say(f"  [red]✗[/] {r['file']}  [dim]{r['reason']}[/]")
    for u in p["unsure"]:
        ui.say(f"  [yellow]?[/] {u['file']}  [dim]gardé — {u['reason']}[/]")
    ui.say()
    exclude = []
    if p["unsure"] and ui.confirm("Retirer aussi les mods « à vérifier » ?", default=False):
        exclude = [u["file"] for u in p["unsure"]]
    out = ui.ask("Dossier de destination", builder.suggest_output_dir(a.mods_dir))
    make_zip = ui.confirm("Créer aussi une archive .zip ?", default=False)
    try:
        r = builder.build_server(a, out, exclude=exclude, make_zip=make_zip)
    except (ValueError, FileExistsError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return
    ui.say(f"\n[green]✓ {r['copied']} mods copiés[/] dans {r['output']}" + (f"\n[green]✓ Archive :[/] {r['zip']}" if r["zip"] else "") + "\n")


def do_logs(ui: UI, a=None):
    default = None
    if a:
        found = logscan.find_logs(a.mods_dir)
        if found:
            default = found[0]["path"]
            ui.say(f"[dim]Journal le plus récent trouvé : {found[0]['name']}[/]")
    path = ui.ask("Chemin du journal (latest.log, crash-report…)", default)
    try:
        findings = logscan.scan_text(logscan.read_log(path))
    except (ValueError, OSError) as exc:
        ui.say(f"[red]{exc}[/]\n")
        return
    if not findings:
        ui.say("[green]✓ Aucune cause connue détectée dans ce journal.[/]\n")
    for f in findings:
        label, color = SEV[f["severity"]]
        ui.say(f"[bold {color}]{label}[/]  [bold]{f['title']}[/]\n   {f['message']}")
        if f["fix"]:
            ui.say(f"   [green]→ {f['fix']}[/]")
        ui.say()


def do_learn(ui: UI, a):
    """Enregistre un conflit ou un mod « client » dans ta base personnelle (stockée sur ton ordinateur)."""
    cache = get_cache()
    ids = sorted({m["modid"] for m in a.to_dict()["mods"] if m["modid"]})
    ui.say("[bold]Ma base[/]  [dim](stockée sur ton ordinateur, appliquée à toutes tes prochaines analyses)[/]")
    for r in cache.list_learned():
        what = f"{r['a']} ↔ {r['b']}" if r["kind"] == "conflict" else f"{r['a']} ({r['side']})"
        ui.say(f"  [dim]#{r['id']}[/] {what}" + (f"  [dim]{r['note']}[/]" if r["note"] else ""))
    ui.say("\n  [bold]1[/] Ajouter un conflit   [bold]2[/] Marquer un mod « client uniquement »   "
           "[bold]3[/] Marquer un mod « à garder sur le serveur »   [bold]4[/] Supprimer une entrée   [bold]0[/] Retour")
    choice = ui.ask("Ton choix", "0")
    try:
        if choice == "1":
            x = ui.ask("Premier mod (identifiant)")
            y = ui.ask("Second mod (identifiant)")
            note = ui.ask("Note (facultative)", "")
            sev = ui.ask("Gravité (error / warning / info)", "error")
            learn.add_conflict(cache, x, y, note, sev)
        elif choice in ("2", "3"):
            ui.say("[dim]Mods du pack : " + ", ".join(ids[:30]) + (" …" if len(ids) > 30 else "") + "[/]")
            learn.add_side(cache, ui.ask("Mod (identifiant)"), "client" if choice == "2" else "both", ui.ask("Note (facultative)", ""))
        elif choice == "4":
            ui.say("[green]✓ Supprimée.[/]" if learn.remove(cache, int(ui.ask("Numéro de l'entrée"))) else "[yellow]Aucune entrée avec ce numéro.[/]")
            return
        else:
            return
    except ValueError as exc:
        ui.say(f"[red]{exc}[/]\n")
        return
    ui.say("[green]✓ Enregistré.[/] Relance l'analyse (choix 9) pour l'appliquer.\n")


def export_report(ui: UI, a):
    dest = ui.ask("Enregistrer le rapport sous", os.path.join(os.path.dirname(a.mods_dir), "rapport-modmaestro.md"))
    try:
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(report.to_markdown(a.to_dict()))
        ui.say(f"[green]✓ Rapport écrit :[/] {dest}\n")
    except OSError as exc:
        ui.say(f"[red]{exc}[/]\n")


# --------------------------------------------------------------------------
# Menu interactif
# --------------------------------------------------------------------------

def cli_menu(path: str | None, online: bool = False):
    ui = UI()
    ui.banner()
    a = None
    while a is None:
        path = path or ui.ask("Dossier mods du modpack (ou « demo » pour essayer)")
        if path.strip().lower() == "demo":
            path = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
            ui.say(f"[dim]Modpack de démo créé : {path}[/]")
        try:
            a = load(ui, path, online)
        except ValueError as exc:
            ui.say(f"[red]{exc}[/]\n")
            path = None
    d = show_summary(ui, a)

    entries = [
        ("1", "Audit complet (doublons, dépendances, incompatibilités)"),
        ("2", "Doublons uniquement"),
        ("3", "Dépendances manquantes uniquement"),
        ("4", "Liste des mods"),
        ("5", "Créer le dossier mods du serveur"),
        ("6", "Analyser un journal de crash"),
        ("7", "Exporter le rapport (.md)"),
        ("8", "Analyser un autre dossier"),
        ("9", "Relancer l'analyse" + (" (Modrinth activé)" if online else "")),
        ("m", "Ma base : conflits et mods client appris"),
        ("o", "Activer / désactiver Modrinth (actuellement : " + ("activé" if online else "désactivé") + ")"),
        ("0", "Quitter"),
    ]
    while True:
        ui.say("[bold #D97757]Que veux-tu faire ?[/]")
        for k, label in entries:
            ui.say(f"  [bold]{k}[/]  {label}")
        choice = ui.ask("Ton choix", "1")
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
        elif choice.lower() == "m":
            do_learn(ui, a)
        elif choice.lower() == "o":
            if online:
                online = False
            else:
                ui.say("Modrinth reçoit [bold]uniquement l'empreinte SHA-1[/] de chaque .jar (jamais les noms de fichiers ni ton dossier).")
                online = ui.confirm("Activer Modrinth pour la prochaine analyse ?", default=False)
            ui.say("Modrinth : " + ("[green]activé[/]" if online else "désactivé") + " — choisis 9 pour relancer l'analyse.\n")
        elif choice == "0":
            ui.say("À bientôt !")
            return 0
        else:
            ui.say("[yellow]Choix inconnu.[/]\n")


def kb_command(args) -> int:
    cache = get_cache()
    if args.import_kb:
        try:
            with open(args.import_kb, encoding="utf-8") as fh:
                res = learn.import_bundle(cache, json.load(fh))
        except (OSError, ValueError) as exc:
            print(f"Import impossible : {exc}", file=sys.stderr)
            return 2
        print(f"{res['added']} entrée(s) importée(s)." + (f" {len(res['errors'])} ignorée(s) : " + " ".join(res["errors"][:3]) if res["errors"] else ""))
    if args.export_kb:
        with open(args.export_kb, "w", encoding="utf-8") as fh:
            json.dump(learn.to_bundle(cache), fh, ensure_ascii=False, indent=2)
        print(f"Base exportée : {args.export_kb}")
    if not (args.import_kb or args.export_kb):
        rows = cache.list_learned()
        for r in rows:
            print(f"#{r['id']:<3} {r['kind']:<8} {r['a']}" + (f" ↔ {r['b']}" if r["b"] else f" ({r['side']})") + (f"  — {r['note']}" if r["note"] else ""))
        if not rows:
            print("Ta base est vide. Ajoute des entrées depuis l'interface (onglet « Ma base ») ou le menu (touche m).")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="modmaestro", description="Audit de modpacks Minecraft.")
    ap.add_argument("path", nargs="?", help="dossier mods (ou instance) à analyser")
    ap.add_argument("--cli", action="store_true", help="menu dans le terminal plutôt que l'interface web")
    ap.add_argument("--audit", action="store_true", help="audit rapide non interactif")
    ap.add_argument("--demo", action="store_true", help="crée un modpack de démonstration et l'ouvre")
    ap.add_argument("--online", action="store_true",
                    help="interroge Modrinth (envoie uniquement les empreintes SHA-1 des .jar) — désactivé par défaut")
    ap.add_argument("--kb", action="store_true", help="affiche ta base personnelle (conflits et mods client appris)")
    ap.add_argument("--export-kb", metavar="FICHIER", help="exporte ta base personnelle dans un fichier .json")
    ap.add_argument("--import-kb", metavar="FICHIER", help="importe une base .json (rien n'est envoyé nulle part)")
    ap.add_argument("--port", type=int, default=8765, help="port de l'interface web (défaut : 8765)")
    ap.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur automatiquement")
    ap.add_argument("--version", action="version", version=f"ModMaestro {__version__}")
    args = ap.parse_args(argv)

    if args.kb or args.export_kb or args.import_kb:
        return kb_command(args)

    path = args.path
    if args.demo:
        path = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
        print(f"Modpack de démo : {path}")

    if args.audit:
        if not path:
            ap.error("--audit demande un dossier")
        return quick_audit(path, args.online)
    if args.cli:
        return cli_menu(path, args.online) or 0

    from web.server import serve
    serve(initial_path=path, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nÀ bientôt !")
        sys.exit(0)
