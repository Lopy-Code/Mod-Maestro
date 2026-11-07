"""Génère un faux modpack NeoForge 1.21.1 pour essayer ModMaestro sans vrai modpack.

Les jars sont fictifs (quelques octets de métadonnées) : ils servent uniquement à
déclencher chaque type de détection (doublon, dépendance manquante, mauvais loader…).
"""

from __future__ import annotations

import io
import json
import os
import zipfile

MC_OK = "[1.21,1.22)"


def _toml(modid, name, version, deps=(), side="BOTH", mc=MC_OK, nested_note=""):
    lines = [
        'modLoader="javafml"', 'loaderVersion="[4,)"', 'license="MIT"', "",
        "[[mods]]", f'modId="{modid}"', f'version="{version}"', f'displayName="{name}"',
        f'description="Mod fictif — démo ModMaestro{nested_note}"', "",
        f"[[dependencies.{modid}]]", 'modId="neoforge"', 'type="required"',
        'versionRange="[21.1.0,)"', 'ordering="NONE"', f'side="{side}"', "",
        f"[[dependencies.{modid}]]", 'modId="minecraft"', 'type="required"',
        f'versionRange="{mc}"', 'ordering="NONE"', 'side="BOTH"', "",
    ]
    for dep_id, kind, rng in deps:
        lines += [f"[[dependencies.{modid}]]", f'modId="{dep_id}"', f'type="{kind}"',
                  f'versionRange="{rng}"', 'ordering="NONE"', 'side="BOTH"', ""]
    return "\n".join(lines)


def _forge_toml(modid, name, version):
    return "\n".join([
        'modLoader="javafml"', 'loaderVersion="[47,)"', 'license="MIT"', "",
        "[[mods]]", f'modId="{modid}"', f'version="{version}"', f'displayName="{name}"', "",
    ])


def _fabric(modid, name, version, depends=None, environment="*"):
    return json.dumps({
        "schemaVersion": 1, "id": modid, "version": version, "name": name,
        "environment": environment,
        "depends": depends or {"fabricloader": ">=0.15", "minecraft": "~1.21"},
    }, indent=2)


def _jar(path: str, files: dict[str, str | bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        for name, content in files.items():
            zf.writestr(name, content)


def _inner_jar(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def build_demo(dest: str) -> str:
    """Crée dest/mods + dest/logs ; retourne le chemin de dest (racine d'instance)."""
    mods = os.path.join(dest, "mods")
    os.makedirs(mods, exist_ok=True)
    os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
    M = "META-INF/neoforge.mods.toml"

    def neo(fname, *args, **kw):
        _jar(os.path.join(mods, fname), {M: _toml(*args, **kw)})

    # — mods corrects ————————————————————————————————————————————————
    neo("geckolib-neoforge-1.21.1-4.6.jar", "geckolib", "GeckoLib", "4.6.0")
    neo("curios-neoforge-9.0.0+1.21.1.jar", "curios", "Curios API", "9.0.0")
    neo("mysticbags-1.4.2.jar", "mysticbags", "Mystic Bags", "1.4.2",
        deps=[("curios", "required", "[9.0,)"), ("architectury", "required", "[13.0,)")])
    neo("wandcraft-2.1.0.jar", "wandcraft", "Wandcraft", "2.1.0",
        deps=[("geckolib", "required", "[4.4,)"), ("jei", "optional", "[19,)")])
    neo("ironstorage-3.0.jar", "ironstorage", "Iron Storage", "3.0.0")

    # — doublon ————————————————————————————————————————————————————
    neo("geckolib-neoforge-1.21.1-4.4.jar", "geckolib", "GeckoLib", "4.4.0")

    # — jar-in-jar : « gearlib » est embarqué dans dragonforge ——————————————
    inner = _inner_jar({M: _toml("gearlib", "Gear Lib", "1.2.0")})
    _jar(os.path.join(mods, "dragonforge-0.9.3.jar"), {
        M: _toml("dragonforge", "Dragon Forge", "0.9.3",
                 deps=[("architectury", "required", "[13.0,)"), ("geckolib", "required", "[4.0,)")]),
        "META-INF/jarjar/gearlib-1.2.0.jar": inner,
    })
    neo("steamgears-5.2.jar", "steamgears", "Steampunk Gears", "5.2.0",
        deps=[("gearlib", "required", "[1.0,)"), ("cloth_config", "required", "[15.0,)"),
              ("curios", "required", "[10.0,)")])

    # — incompatibilité déclarée ———————————————————————————————————————————
    neo("biomebloom-1.0.8.jar", "biomebloom", "Biome Bloom", "1.0.8",
        deps=[("steamgears", "incompatible", "[5.0,)")])

    # — mauvaise version de Minecraft ——————————————————————————————————————
    neo("oldcharm-0.3.jar", "oldcharm", "Old Charm", "0.3.0", mc="[1.20.1,1.20.2)")

    # — côté client / serveur ——————————————————————————————————————————————————
    neo("sodium-neoforge-0.6.2.jar", "sodium", "Sodium", "0.6.2", side="CLIENT")
    neo("embeddium-1.0.9.jar", "embeddium", "Embeddium", "1.0.9", side="CLIENT")
    neo("tooltipper-2.0.jar", "tooltipper", "Tooltipper", "2.0.0", side="CLIENT")
    neo("jei-1.21.1-neoforge-19.8.jar", "jei", "Just Enough Items", "19.8.0")
    neo("shadertweaks-1.1.jar", "shadertweaks", "Shader Tweaks", "1.1.0")

    # — mauvais loader ———————————————————————————————————————————————————————
    _jar(os.path.join(mods, "fabric-only-charm-1.5.jar"),
         {"fabric.mod.json": _fabric("fabriccharm", "Fabric Charm", "1.5.0")})
    _jar(os.path.join(mods, "legacy-forge-mod-1.0.jar"),
         {"META-INF/mods.toml": _forge_toml("legacyforge", "Legacy Forge Mod", "1.0.0")})

    # — fichiers cassés ———————————————————————————————————————————————————————————
    with open(os.path.join(mods, "broken-download.jar"), "wb") as fh:
        fh.write(b"PK\x03\x04 ce fichier est tronque")
    _jar(os.path.join(mods, "kotlin-stdlib-1.9.jar"), {"kotlin/Unit.class": b"\xca\xfe\xba\xbe"})
    with open(os.path.join(mods, "oldmod-1.0.jar.disabled"), "wb") as fh:
        fh.write(b"")

    with open(os.path.join(dest, "logs", "latest.log"), "w", encoding="utf-8") as fh:
        fh.write(
            "[06Nov2026 21:02:09.411] [main/INFO] [net.neoforged.fml.loading.FMLLoader/]: Loading Minecraft 1.21.1\n"
            "[06Nov2026 21:02:11.123] [main/ERROR] [net.neoforged.fml.loading.ModSorter/LOADING]: "
            "Missing or unsupported mandatory dependencies:\n"
            "\tMod ID: 'architectury', Requested by: 'dragonforge', Expected range: '[13.0,)', Actual version: '[MISSING]'\n"
            "\tMod ID: 'architectury', Requested by: 'mysticbags', Expected range: '[13.0,)', Actual version: '[MISSING]'\n"
            "\tMod ID: 'curios', Requested by: 'steamgears', Expected range: '[10.0,)', Actual version: '9.0.0'\n"
            "[06Nov2026 21:02:11.130] [main/ERROR] [net.neoforged.fml.loading.ModSorter/LOADING]: Found duplicate mods:\n"
            "\tMod ID: 'geckolib' from mod files: geckolib-neoforge-1.21.1-4.6.jar, geckolib-neoforge-1.21.1-4.4.jar\n"
        )
    return dest
