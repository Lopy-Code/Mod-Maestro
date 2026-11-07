<p align="center"><img src="assets/banner.png" alt="ModMaestro" width="720"></p>

# ModMaestro

Audit your Minecraft modpack, spot duplicates and missing dependencies, and build a clean server `mods` folder — with a local web interface, a terminal menu, or a one-line command.
*Audite ton modpack Minecraft, repère doublons et dépendances manquantes, et génère un dossier `mods` serveur propre — avec une interface web locale, un menu terminal ou une simple commande.*

[🇫🇷 Français](#-français) · [🇬🇧 English](#-english)

![Audit](docs/screenshot-audit.png)

---

## 🇫🇷 Français

### À propos

ModMaestro est un outil Python **100 % local** qui lit chaque `.jar` d'un dossier `mods` et explique, en clair, ce qui cloche et comment le réparer. Il prépare aussi le dossier `mods` d'un serveur dédié en retirant ce qui ne sert qu'au joueur.

Compatible **NeoForge, Forge, Fabric et Quilt**, y compris les mods embarqués (jar-in-jar), pour ne pas signaler « manquante » une bibliothèque déjà fournie par un autre mod.

### Stack technique

* **Python 3.11+** — logique principale. Le moteur et l'interface web n'ont **aucune dépendance externe**.
* **`zipfile` / `tomllib` / `json`** — lecture directe des archives `.jar` en mémoire, sans extraction sur le disque, et des fichiers `neoforge.mods.toml`, `mods.toml`, `fabric.mod.json` et `quilt.mod.json`.
* **`http.server`** — petit serveur local pour l'interface web.
* **HTML / CSS / JavaScript** — interface sans framework ni téléchargement de police, thème clair et sombre.
* **Rich** *(facultatif)* — couleurs, tableaux et barre de progression pour le menu terminal. Sans lui, le menu fonctionne en texte simple.

### Fonctionnalités

* **Extraction de métadonnées** : `modid`, nom, version, loader et dépendances de chaque mod, y compris les mods embarqués.
* **Détection de doublons** : plusieurs versions du même mod, avec la version à garder (la plus récente).
* **Dépendances** : mods requis manquants, et versions installées qui ne respectent pas la plage demandée (plages Maven `[1.0,2.0)` et Fabric `>=1.0 <2`, `~`, `^`, `1.21.x`).
* **Incompatibilités** : conflits déclarés par les auteurs, et pièges connus (Sodium + OptiFine, deux moteurs de shaders…).
* **Compatibilité loader et Minecraft** : mod Fabric dans un pack NeoForge, mod Forge dans un pack NeoForge, fichier corrompu ou sans métadonnées, mod visant une autre version de Minecraft.
* **Séparation client / serveur** : mods strictement clients (rendu, mini-cartes, interface), retirés automatiquement. Un mod client dont dépend un mod serveur est **conservé**.
* **Export serveur** : copie des mods retenus vers un dossier **neuf** (jamais dans ton dossier d'origine), avec une archive `.zip` en option. Chaque choix est modifiable.
* **Diagnostic de journal de crash** : `latest.log` ou crash-report → dépendance manquante, doublon, mod client sur serveur, mauvaise version de Java, mémoire insuffisante, mixin en échec…
* **Rapport** : export Markdown de l'audit complet.

### Installation et lancement

Il faut **Python 3.11 ou plus récent** ([python.org](https://www.python.org/downloads/)).

| Système | Interface web |
|---|---|
| Windows | double-clic sur `lancer.bat` |
| Linux / macOS | `./lancer.sh` |
| Partout | `python main.py` |

```bash
python main.py "/chemin/vers/mods"          # interface web, analyse lancée tout de suite
python main.py --demo                       # essayer avec un modpack fictif
python main.py --cli                        # menu interactif dans le terminal
python main.py --audit "/chemin/vers/mods"  # audit rapide ; code retour 1 s'il y a des erreurs
pip install -r requirements.txt             # facultatif : installe Rich pour le menu terminal
```

Le dossier peut être le dossier `mods`, la racine d'une instance (le dossier `mods/` est trouvé tout seul, y compris `minecraft/mods` et `.minecraft/mods` pour Prism ou MultiMC), ou une archive `.zip` qui contient un dossier `mods/`.

### Limites

* Le tri client / serveur est une **estimation** : il s'appuie sur ce que le mod déclare, puis sur une liste de mods connus modifiable (`core/data/knowledge.json`). En cas de doute, le mod est marqué « à vérifier » et gardé.
* Les conflits de code que personne ne déclare ne se détectent qu'en lançant le jeu : c'est le rôle du diagnostic de journal.
* ModMaestro n'interroge pas Internet : il ne sait pas dire qu'une version plus récente existe.

### Confidentialité et sécurité

Rien ne quitte ton ordinateur. Le serveur de l'interface n'écoute que sur `127.0.0.1`, vérifie l'en-tête `Host` et l'origine des requêtes, et exige un jeton aléatoire régénéré à chaque lancement.

### Structure

```
modmaestro/
├── main.py                 point d'entrée : web, --cli, --audit, --demo
├── lancer.bat / lancer.sh  lancement en un clic
├── core/                   parser, versions, analyzer, builder, logscan, report, demo
│   └── data/knowledge.json mods clients et conflits connus (à enrichir)
├── web/                    serveur local + interface
├── assets/                 logo, bannière, illustrations (SVG + PNG)
├── tools/make_assets.py    régénère toute l'identité visuelle
├── tests/                  41 tests : python -m unittest discover -s tests
├── BRAND.md                charte graphique
└── docs/                   captures d'écran
```

### Contribuer

Ajouter un mod client ou un conflit connu ne demande **aucun code** : édite `core/data/knowledge.json`. Les pull requests sont les bienvenues.

### Licence

Cet outil est public : tout le monde peut l'utiliser, le modifier et le partager, sous licence **MIT** (voir `LICENSE`).

---

## 🇬🇧 English

### Overview

ModMaestro is a **fully local** Python tool that reads every `.jar` in a `mods` folder, explains what is wrong in plain language and how to fix it. It also prepares a dedicated-server `mods` folder by removing everything that only matters to the player.

It supports **NeoForge, Forge, Fabric and Quilt**, including bundled mods (jar-in-jar), so a library already provided by another mod is never reported as missing.

### Technical Stack

* **Python 3.11+** — core logic. The engine and the web interface have **no external dependency**.
* **`zipfile` / `tomllib` / `json`** — in-memory inspection of `.jar` archives (nothing is extracted to disk) and parsing of `neoforge.mods.toml`, `mods.toml`, `fabric.mod.json` and `quilt.mod.json`.
* **`http.server`** — small local server for the web interface.
* **HTML / CSS / JavaScript** — framework-free interface, no font downloads, light and dark themes.
* **Rich** *(optional)* — colours, tables and a progress bar for the terminal menu. Without it, the menu falls back to plain text.

### Core Features

* **Metadata extraction**: `modid`, name, version, loader and dependencies for every mod, bundled ones included.
* **Duplicate detection**: several versions of the same mod, with the version to keep (the newest).
* **Dependency audit**: missing required mods, and installed versions that fall outside the requested range (Maven `[1.0,2.0)` and Fabric `>=1.0 <2`, `~`, `^`, `1.21.x` ranges).
* **Incompatibilities**: conflicts declared by authors, plus known pitfalls (Sodium + OptiFine, two shader engines…).
* **Loader and Minecraft compatibility**: Fabric mod in a NeoForge pack, Forge mod in a NeoForge pack, corrupt or metadata-less files, mods targeting another Minecraft version.
* **Environment separation**: strictly client-side mods (renderers, mini-maps, HUDs) are removed automatically. A client mod required by a kept mod is **kept**.
* **Server build**: copies the selected mods into a **new** folder (never into your original one), with an optional `.zip`. Every choice can be overridden.
* **Crash-log diagnosis**: `latest.log` or crash report → missing dependency, duplicate, client mod on server, wrong Java version, out of memory, failed mixin…
* **Report**: Markdown export of the full audit.

### Install and Run

You need **Python 3.11 or newer** ([python.org](https://www.python.org/downloads/)).

| System | Web interface |
|---|---|
| Windows | double-click `lancer.bat` |
| Linux / macOS | `./lancer.sh` |
| Anywhere | `python main.py` |

```bash
python main.py "/path/to/mods"          # web interface, analysis starts immediately
python main.py --demo                   # try it with a fake modpack
python main.py --cli                    # interactive terminal menu
python main.py --audit "/path/to/mods"  # quick audit; exit code 1 if errors are found
pip install -r requirements.txt         # optional: installs Rich for the terminal menu
```

The path can be the `mods` folder, an instance root (the `mods/` folder is found automatically, including `minecraft/mods` and `.minecraft/mods` for Prism or MultiMC), or a `.zip` archive containing a `mods/` folder.

### Limitations

* Client/server sorting is an **estimate**: it relies on what each mod declares, then on an editable list of known mods (`core/data/knowledge.json`). When unsure, a mod is flagged "to check" and kept.
* Code conflicts that nobody declares can only be found by launching the game — that is what the log diagnosis is for.
* ModMaestro does not query the Internet: it cannot tell you that a newer version exists.

### Privacy and Security

Nothing leaves your computer. The interface server only listens on `127.0.0.1`, checks the `Host` header and request origin, and requires a random token regenerated at every launch.

### Contributing

Adding a known client mod or conflict needs **no code**: edit `core/data/knowledge.json`. Pull requests are welcome.

### License

This tool is public: anyone can use, modify and share it under the **MIT** license (see `LICENSE`).