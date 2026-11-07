#!/usr/bin/env python3
"""ModMaestro — point d'entrée.

    python main.py                    interface web (s'ouvre dans ton navigateur)
    python main.py DOSSIER            interface web, analyse lancée tout de suite
    python main.py --cli [DOSSIER]    menu interactif dans le terminal
    python main.py --demo             crée un faux modpack pour essayer
    python main.py --audit DOSSIER    audit rapide, sans interface (code retour 1 si erreurs)
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

if sys.version_info < (3, 11):
    sys.exit("ModMaestro demande Python 3.11 ou plus récent (vous avez %d.%d).\n"
             "Téléchargement : https://www.python.org/downloads/" % sys.version_info[:2])

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import __version__, builder, demo, logscan, parser, report  # noqa: E402
from core.analyzer import analyze  # noqa: E402

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

    def scan(self, folder):
        if not self.c:
            result = parser.scan_folder(folder, progress=lambda d, t: print(f"\r  Lecture {d}/{t}", end="", flush=True))
            print()
            return result
        with Progress(TextColumn("[#D97757]Lecture des mods"), BarColumn(complete_style="#D97757"),
                      TaskProgressColumn(), console=self.c, transient=True) as pr:
            task = pr.add_task("", total=None)
            return parser.scan_folder(folder, progress=lambda d, t: pr.update(task, total=t, completed=d))


def _plain(msg: str) -> str:
    import re
    return re.sub(r"\[/?[^\]]*\]", "", str(msg))


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

def load(ui: UI, path: str):
    folder, notes = parser.resolve_source(path)
    jars, extras = ui.scan(folder)
    a = analyze(jars, extras, source=path, mods_dir=folder, notes=notes)
    for n in notes:
        ui.say(f"[dim]{n}[/]")
    return a


def show_summary(ui: UI, a):
    d = a.to_dict()
    c = d["counts"]
    ui.say(f"\n[bold]{d['loader_label']}[/]" + (f" · Minecraft {d['mc_version']}" if d["mc_version"] else "")
           + f" · {c['mods']} mods dans {c['jars']} fichiers · santé [bold]{d['score']}/100[/]")
    ui.say(f"[red]{c['errors']} erreur(s)[/] · [yellow]{c['warnings']} avertissement(s)[/] · [blue]{c['infos']} info(s)[/]\n")
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

def cli_menu(path: str | None):
    ui = UI()
    ui.banner()
    a = None
    while a is None:
        path = path or ui.ask("Dossier mods du modpack (ou « demo » pour essayer)")
        if path.strip().lower() == "demo":
            path = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
            ui.say(f"[dim]Modpack de démo créé : {path}[/]")
        try:
            a = load(ui, path)
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
            return cli_menu(None)
        elif choice == "0":
            ui.say("À bientôt !")
            return 0
        else:
            ui.say("[yellow]Choix inconnu.[/]\n")


def quick_audit(path: str) -> int:
    ui = UI()
    try:
        a = load(ui, path)
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
    ap.add_argument("--port", type=int, default=8765, help="port de l'interface web (défaut : 8765)")
    ap.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur automatiquement")
    ap.add_argument("--version", action="version", version=f"ModMaestro {__version__}")
    args = ap.parse_args(argv)

    path = args.path
    if args.demo:
        path = demo.build_demo(os.path.join(tempfile.mkdtemp(prefix="modmaestro_demo_"), "modpack_demo"))
        print(f"Modpack de démo : {path}")

    if args.audit:
        if not path:
            ap.error("--audit demande un dossier")
        return quick_audit(path)
    if args.cli:
        return cli_menu(path) or 0

    from web.server import serve
    serve(initial_path=path, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nÀ bientôt !")
        sys.exit(0)
