<p align="center"><img src="assets/banner.png" alt="ModMaestro" width="720"></p>

# ModMaestro

Audit your Minecraft modpack, spot duplicates and missing dependencies, and build a clean server `mods` folder — with a local web interface, a terminal menu, or a one-line command.
*Audite ton modpack Minecraft, repère doublons et dépendances manquantes, et génère un dossier `mods` serveur propre — avec une interface web locale, un menu terminal ou une simple commande.*

[🇫🇷 Français](#-français) · [🇬🇧 English](#-english)

![Audit](docs/screenshot-audit.png)

---

## 🇫🇷 Français

### À propos

ModMaestro est un outil Python **local par défaut** qui lit chaque `.jar` d'un dossier `mods` et explique, en clair, ce qui cloche et comment le réparer. Il prépare aussi le dossier `mods` d'un serveur dédié en retirant ce qui ne sert qu'au joueur.

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
* **Modrinth** *(facultatif, désactivé par défaut)* : reconnaît tes mods par empreinte, fiabilise le tri client / serveur, ajoute les incompatibilités et dépendances déclarées sur Modrinth, et signale les mises à jour disponibles.
* **Cache SQLite** : les réponses de Modrinth sont gardées sur ton ordinateur (7 jours pour un mod reconnu, 1 jour pour un mod inconnu, 12 h pour les mises à jour). Une 2ᵉ analyse du même pack ne fait aucune requête.
* **Base de connaissances communautaire** : un fichier JSON par mod ou par conflit dans `core/data/community/`, simple à proposer en pull request, avec une validation automatique.
* **Apprentissage** : un conflit ou un mod « client » découvert, ou repéré dans un journal de crash, s'enregistre dans **ta base personnelle** (onglet « Ma base » ou touche `m` du menu), s'applique à toutes tes analyses suivantes et s'exporte / s'importe pour être partagé.
* **Passerelles de loader** : avec Sinytra Connector, les mods Fabric d'un pack NeoForge sont signalés en simple information, pas en erreur.

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
python main.py --audit "/chemin/vers/mods" --online   # idem, en interrogeant Modrinth
python main.py --kb                         # affiche ta base personnelle
python main.py --export-kb ma-base.json     # exporte ta base (--import-kb pour en importer une)
pip install -r requirements.txt             # facultatif : installe Rich pour le menu terminal
```

Le dossier peut être le dossier `mods`, la racine d'une instance (le dossier `mods/` est trouvé tout seul, y compris `minecraft/mods` et `.minecraft/mods` pour Prism ou MultiMC), ou une archive `.zip` qui contient un dossier `mods/`.

### Limites

* Le tri client / serveur est une **estimation** : il s'appuie sur ce que le mod déclare, puis sur une liste de mods connus modifiable (`core/data/knowledge.json`). En cas de doute, le mod est marqué « à vérifier » et gardé.
* Les conflits de code que personne ne déclare ne se détectent qu'en lançant le jeu : c'est le rôle du diagnostic de journal.
* Modrinth ne connaît que les mods qui y sont publiés (pas CurseForge, ni les mods privés) : un mod inconnu est simplement analysé avec ses métadonnées locales. Une dépendance « manquante » d'après Modrinth n'est qu'un **avertissement** : le mod peut déjà l'embarquer.
* La base communautaire fournie est un **point de départ** (quelques entrées) : elle ne grandit que si tu y contribues.

### Confidentialité et sécurité

**Par défaut, rien ne quitte ton ordinateur.** Si tu actives Modrinth (interrupteur de l'accueil, `--online` ou touche `o` du menu), ModMaestro envoie à `api.modrinth.com` **uniquement l'empreinte SHA-1 de chaque `.jar`**, puis des identifiants de projets Modrinth : jamais les noms de fichiers, ni les chemins, ni ta base personnelle. Le cache et ta base sont stockés dans `%APPDATA%\ModMaestro` (Windows), `~/Library/Application Support/ModMaestro` (macOS) ou `~/.local/share/modmaestro` (Linux), modifiable avec la variable `MODMAESTRO_HOME`. Le bouton « Vider le cache » conserve ta base personnelle.

Modrinth demande aux applications de s'identifier : renseigne ton lien GitHub dans la variable `MODMAESTRO_CONTACT` (ou dans `CONTACT` de `core/modrinth.py`). `MODMAESTRO_MODRINTH_URL` permet de viser un miroir ou un serveur de test.

Le serveur de l'interface n'écoute que sur `127.0.0.1`, vérifie l'en-tête `Host` et l'origine des requêtes, et exige un jeton aléatoire régénéré à chaque lancement.

### Structure

```
modmaestro/
├── main.py                 point d'entrée : web, --cli, --audit, --demo
├── lancer.bat / lancer.sh  lancement en un clic
├── core/                   parser, versions, analyzer, builder, logscan, report, demo
│   ├── pipeline.py         analyse complète (locale ou avec Modrinth)
│   ├── modrinth.py         client de l'API Modrinth (empreintes SHA-1 uniquement)
│   ├── cache.py            cache SQLite + ta base personnelle
│   ├── knowledge.py        fusion : base intégrée + communauté + ta base
│   ├── learn.py            apprentissage, export / import, suggestions depuis un journal
│   ├── enrich.py           transforme les données Modrinth en alertes
│   └── data/
│       ├── knowledge.json  mods clients et conflits connus, passerelles de loader
│       └── community/      un fichier par mod (sides/) ou par conflit (conflicts/)
├── tools/check_community.py  valide la base communautaire (à lancer avant une PR)
├── web/                    serveur local + interface
├── assets/                 logo, bannière, illustrations (SVG + PNG)
├── tools/make_assets.py    régénère toute l'identité visuelle
├── tests/                  74 tests : python -m unittest discover -s tests
├── BRAND.md                charte graphique
└── docs/                   captures d'écran
```

### Contribuer

Ajouter un mod client ou un conflit connu ne demande **aucun code** :

1. crée un fichier dans `core/data/community/sides/<modid>.json` ou `core/data/community/conflicts/<a>__<b>.json` (format et règles dans `core/data/community/README.md`) ;
2. ou exporte ta base depuis l'onglet « Ma base » et copie les fichiers générés ;
3. vérifie avec `python tools/check_community.py`, puis ouvre une pull request avec **la source** (log, page Modrinth, issue…).

Les pull requests sont les bienvenues.

### Licence

Cet outil est public : tout le monde peut l'utiliser, le modifier et le partager, sous licence **MIT** (voir `LICENSE`).

---

## 🇬🇧 English

### Overview

ModMaestro is a Python tool that is **local by default**: that reads every `.jar` in a `mods` folder, explains what is wrong in plain language and how to fix it. It also prepares a dedicated-server `mods` folder by removing everything that only matters to the player.

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
* **Modrinth** *(optional, off by default)*: recognises your mods by hash, makes client/server sorting more reliable, adds incompatibilities and dependencies declared on Modrinth, and reports available updates.
* **SQLite cache**: Modrinth answers are kept on your computer (7 days for a known mod, 1 day for an unknown one, 12 h for updates). A second analysis of the same pack makes no request at all.
* **Community knowledge base**: one JSON file per mod or per conflict in `core/data/community/`, easy to submit as a pull request, with automatic validation.
* **Learning**: a conflict or client-only mod you discover — or that shows up in a crash log — is saved to **your personal base** ("My base" tab, or `m` in the menu), applied to every later analysis, and can be exported / imported to be shared.
* **Loader bridges**: with Sinytra Connector, Fabric mods in a NeoForge pack are reported as information, not errors.

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
python main.py --audit "/path/to/mods" --online   # same, querying Modrinth
python main.py --kb                     # show your personal base
python main.py --export-kb my-base.json # export it (--import-kb to import one)
pip install -r requirements.txt         # optional: installs Rich for the terminal menu
```

The path can be the `mods` folder, an instance root (the `mods/` folder is found automatically, including `minecraft/mods` and `.minecraft/mods` for Prism or MultiMC), or a `.zip` archive containing a `mods/` folder.

### Limitations

* Client/server sorting is an **estimate**: it relies on what each mod declares, then on an editable list of known mods (`core/data/knowledge.json`). When unsure, a mod is flagged "to check" and kept.
* Code conflicts that nobody declares can only be found by launching the game — that is what the log diagnosis is for.
* Modrinth only knows the mods published there (not CurseForge, nor private mods): an unknown mod is simply analysed from its local metadata. A dependency reported "missing" by Modrinth is only a **warning**: the mod may already bundle it.
* The bundled community base is a **starting point** (a handful of entries): it only grows if you contribute.

### Privacy and Security

**By default, nothing leaves your computer.** If you enable Modrinth (the switch on the home screen, `--online`, or `o` in the menu), ModMaestro sends `api.modrinth.com` **only the SHA-1 hash of each `.jar`**, then Modrinth project IDs — never file names, paths or your personal base. The cache and your base live in `%APPDATA%\ModMaestro` (Windows), `~/Library/Application Support/ModMaestro` (macOS) or `~/.local/share/modmaestro` (Linux); override with `MODMAESTRO_HOME`. "Clear cache" keeps your personal base.

Modrinth asks applications to identify themselves: put your GitHub link in the `MODMAESTRO_CONTACT` variable (or in `CONTACT` in `core/modrinth.py`). `MODMAESTRO_MODRINTH_URL` points to a mirror or a test server.

The interface server only listens on `127.0.0.1`, checks the `Host` header and request origin, and requires a random token regenerated at every launch.

### Contributing

Adding a known client mod or conflict needs **no code**:

1. create `core/data/community/sides/<modid>.json` or `core/data/community/conflicts/<a>__<b>.json` (format and rules in `core/data/community/README.md`);
2. or export your base from the "My base" tab and copy the generated files;
3. check with `python tools/check_community.py`, then open a pull request including **the source** (log, Modrinth page, issue…).

Pull requests are welcome.

### License

This tool is public: anyone can use, modify and share it under the **MIT** license (see `LICENSE`).