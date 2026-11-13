"""Fichiers de lancement d'un serveur modé : scripts de démarrage, arguments Java optimisés, eula, propriétés.

Ce que ça ne fait pas : télécharger ni installer le serveur du loader (NeoForge, Forge, Fabric…). Ces
installateurs viennent des sites officiels, et leur licence demande de les récupérer là-bas. Le README généré
explique l'étape en une minute ; ensuite `start.sh` / `start.bat` s'occupent du reste.

Le fichier eula.txt n'est mis à `true` que si tu coches explicitement l'acceptation du CLUF de Mojang.
"""

from __future__ import annotations

import math
import os

from .analyzer import Analysis, compute_plan
from .i18n import _

# Aikar's flags (https://mcflags.emc.gs) : la référence communautaire pour G1GC sur un serveur Minecraft
_AIKAR_COMMON = [
    "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled", "-XX:MaxGCPauseMillis=200", "-XX:+UnlockExperimentalVMOptions",
    "-XX:+DisableExplicitGC", "-XX:+AlwaysPreTouch", "-XX:G1HeapWastePercent=5", "-XX:G1MixedGCCountTarget=4",
    "-XX:G1MixedGCLiveThresholdPercent=90", "-XX:G1RSetUpdatingPauseTimePercent=5", "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem", "-XX:MaxTenuringThreshold=1", "-Dusing.aikars.flags=https://mcflags.emc.gs",
    "-Daikars.new.flags=true",
]
_AIKAR_SMALL = ["-XX:G1NewSizePercent=30", "-XX:G1MaxNewSizePercent=40", "-XX:G1HeapRegionSize=8M",
                "-XX:G1ReservePercent=20", "-XX:InitiatingHeapOccupancyPercent=15"]
_AIKAR_BIG = ["-XX:G1NewSizePercent=40", "-XX:G1MaxNewSizePercent=50", "-XX:G1HeapRegionSize=16M",
              "-XX:G1ReservePercent=15", "-XX:InitiatingHeapOccupancyPercent=20"]


def java_for_mc(mc: str | None) -> int:
    """Version de Java minimale pour un serveur de cette version de Minecraft."""
    if not mc:
        return 21
    nums = [int(x) for x in mc.split(".") if x.isdigit()]
    major, minor, patch = (nums + [0, 0, 0])[:3]
    if (major, minor, patch) >= (1, 20, 5) or major >= 2:
        return 21
    if (major, minor) >= (1, 18):
        return 17
    if (major, minor) == (1, 17):
        return 16
    return 8


def estimate_ram_gb(server_mods: int) -> int:
    """Estimation prudente de la mémoire (Go) : 2 Go de base + ~35 Mo par mod, entre 3 et 16 Go."""
    return max(3, min(16, math.ceil(2 + 0.035 * server_mods)))


def jvm_flags(ram_gb: int) -> list[str]:
    return [f"-Xms{ram_gb}G", f"-Xmx{ram_gb}G"] + _AIKAR_COMMON + (_AIKAR_BIG if ram_gb >= 12 else _AIKAR_SMALL)


def _mode(loader: str | None, mc: str | None) -> str:
    """modern (run.sh généré par l'installateur) | fabric | quilt | legacy (forge-*.jar)."""
    if loader in ("fabric", "quilt"):
        return loader
    nums = [int(x) for x in (mc or "1.21").split(".") if x.isdigit()] + [0, 0]
    if loader == "forge" and (nums[0], nums[1]) < (1, 17):
        return "legacy"
    return "modern"


def _NO_LOADER() -> str:
    return _("Le serveur du loader n'est pas installé : lis README-SERVER.txt.")


def _sh(mode: str, java: int, flags: list[str]) -> str:
    jv = " ".join(flags)
    gen, no_java, no_loader = _("Généré par ModMaestro"), _("Java {n} ou plus récent est nécessaire (trouvé : ${{JV:-aucun}}).", n=java), _NO_LOADER()
    head = ["#!/usr/bin/env bash", "# " + gen, 'cd "$(dirname "$0")"', "",
            f'JAVA_ARGS="{jv}"', "",
            "JV=$(java -version 2>&1 | awk -F'[\".]' '/version/ {print ($2==\"1\") ? $3 : $2; exit}')",
            f'if [ -z "$JV" ] || [ "$JV" -lt {java} ]; then',
            f'  echo "{no_java}"', "  exit 1", "fi", ""]
    body = {
        "modern": ['if [ -f run.sh ]; then', "  exec bash run.sh nogui   # lit user_jvm_args.txt", "fi"],
        "fabric": ['if [ -f fabric-server-launch.jar ]; then', '  exec java $JAVA_ARGS -jar fabric-server-launch.jar nogui', "fi"],
        "quilt": ['if [ -f quilt-server-launch.jar ]; then', '  exec java $JAVA_ARGS -jar quilt-server-launch.jar nogui', "fi"],
        "legacy": ['F=$(ls forge-*.jar 2>/dev/null | grep -v installer | head -n1)',
                   'if [ -n "$F" ]; then', '  exec java $JAVA_ARGS -jar "$F" nogui', "fi"],
    }[mode]
    tail = ["", f'echo "{no_loader}"', "exit 1", ""]
    return "\n".join(head + body + tail)


def _bat(mode: str, java: int, flags: list[str]) -> str:
    jv = " ".join(flags)
    body = {
        "modern": ["if exist run.bat (", "  call run.bat nogui", "  goto :end", ")"],
        "fabric": ["if exist fabric-server-launch.jar (", f"  java {jv} -jar fabric-server-launch.jar nogui", "  goto :end", ")"],
        "quilt": ["if exist quilt-server-launch.jar (", f"  java {jv} -jar quilt-server-launch.jar nogui", "  goto :end", ")"],
        "legacy": ["for %%F in (forge-*.jar) do (", f"  java {jv} -jar %%F nogui", "  goto :end", ")"],
    }[mode]
    gen, no_java = _("Généré par ModMaestro"), _("Java {n} ou plus récent est nécessaire.", n=java)
    lines = ["@echo off", "rem " + gen, 'cd /d "%~dp0"',
             "where java >nul 2>nul", f"if errorlevel 1 (echo {no_java} & pause & exit /b 1)", ""]
    lines += body
    lines += ["echo " + _NO_LOADER(), ":end", "pause", ""]
    return "\r\n".join(lines)


_LOADER_HELP = {
    "neoforge": ("NeoForge", "https://neoforged.net/", "java -jar neoforge-<version>-installer.jar --installServer"),
    "forge": ("Forge", "https://files.minecraftforge.net/", "java -jar forge-<version>-installer.jar --installServer"),
    "fabric": ("Fabric", "https://fabricmc.net/use/server/", "java -jar fabric-server-launch.jar"),
    "quilt": ("Quilt", "https://quiltmc.org/en/install/server/", "java -jar quilt-installer.jar install server <mc> --download-server"),
}


def _readme(loader, mc, java, ram, mode, eula) -> str:
    name, url, cmd = _LOADER_HELP.get(loader or "neoforge", _LOADER_HELP["neoforge"])
    return "\n".join([
        _("SERVEUR {loader} — Minecraft {mc}", loader=name, mc=mc or "?"), "=" * 50, "",
        _("1. Installe Java {n} (ou plus récent).", n=java),
        _("2. Télécharge l'installateur de {loader} sur le site officiel : {url}", loader=name, url=url),
        _("   puis, dans ce dossier : {cmd}", cmd=cmd), "",
        _("3. Les mods sont déjà dans le dossier « mods »."),
        (_("4. eula.txt : tu as accepté le CLUF de Mojang.") if eula else
         _("4. Ouvre eula.txt et remplace eula=false par eula=true si tu acceptes le CLUF de Mojang "
           "(https://aka.ms/MinecraftEULA).")),
        _("5. Lance start.sh (Linux / macOS) ou start.bat (Windows)."), "",
        _("Mémoire allouée : {ram} Go (estimation d'après le nombre de mods : ajuste-la dans {where}).", ram=ram,
          where="user_jvm_args.txt" if mode == "modern" else "start.sh / start.bat"),
        _("Les arguments Java sont ceux d'Aikar (G1GC), la référence pour les serveurs Minecraft."), "",
    ])


def _props(port, motd, players, view, sim) -> str:
    return "\n".join([
        "#Minecraft server properties (ModMaestro)", f"server-port={port}", f"motd={motd}", f"max-players={players}",
        f"view-distance={view}", f"simulation-distance={sim}", "online-mode=true", ""])


def _clean_motd(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isprintable() and ch not in "\\=#!:")[:59] or "A Minecraft Server"


def generate(a: Analysis, outdir: str, *, ram_gb: int | None = None, eula: bool = False, port: int = 25565,
             max_players: int = 20, motd: str = "", view_distance: int = 10, simulation_distance: int = 8,
             with_mods: bool = False, exclude=(), include=()) -> dict:
    """Écrit le kit dans `outdir` (jamais par-dessus un fichier existant). `with_mods` copie aussi les mods serveur."""
    from .builder import build_server  # import tardif : évite un cycle

    if not (1 <= int(port) <= 65535):
        raise ValueError(_("Port invalide (1 à 65535)."))
    if not (1 <= int(max_players) <= 1000):
        raise ValueError(_("Nombre de joueurs invalide (1 à 1000)."))
    if not (2 <= int(view_distance) <= 32 and 2 <= int(simulation_distance) <= 32):
        raise ValueError(_("Les distances doivent être comprises entre 2 et 32."))
    plan = compute_plan(a, exclude, include)
    ram = int(ram_gb) if ram_gb else estimate_ram_gb(len(plan["keep"]))
    if not (1 <= ram <= 64):
        raise ValueError(_("Mémoire invalide (1 à 64 Go)."))
    mode, java = _mode(a.loader, a.mc_version), java_for_mc(a.mc_version)
    flags = jvm_flags(ram)

    outdir = os.path.abspath(os.path.expanduser(outdir.strip().strip('"')))
    mods_result = None
    if with_mods:
        mods_result = build_server(a, os.path.join(outdir, "mods"), exclude, include)
    elif os.path.realpath(outdir).startswith(os.path.realpath(a.mods_dir) + os.sep) or os.path.realpath(outdir) == os.path.realpath(a.mods_dir):
        raise ValueError(_("Le dossier de sortie ne doit pas être le dossier de mods."))
    os.makedirs(outdir, exist_ok=True)

    files = {
        "start.sh": _sh(mode, java, flags), "start.bat": _bat(mode, java, flags),
        "eula.txt": "#By changing the setting below to TRUE you are indicating your agreement to the Minecraft EULA "
                    "(https://aka.ms/MinecraftEULA).\n" + f"eula={'true' if eula else 'false'}\n",
        "server.properties": _props(int(port), _clean_motd(motd), int(max_players), int(view_distance), int(simulation_distance)),
        "README-SERVER.txt": _readme(a.loader, a.mc_version, java, ram, mode, eula),
    }
    if mode == "modern":
        files["user_jvm_args.txt"] = "\n".join(flags) + "\n"
    written, skipped = [], []
    for name, text in files.items():
        path = os.path.join(outdir, name)
        if os.path.exists(path):
            skipped.append(name)
            continue
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if name.endswith(".sh"):
            os.chmod(path, 0o755)
        written.append(name)
    notes = []
    if not eula:
        notes.append(_("eula.txt est à « false » : tu devras l'accepter toi-même avant le premier lancement."))
    if skipped:
        notes.append(_("Fichiers déjà présents, laissés intacts : {names}.", names=", ".join(skipped)))
    return {"output": outdir, "written": written, "skipped": skipped, "java": java, "ram": ram, "mode": mode,
            "mods": mods_result, "notes": notes}
