# ModMaestro

A fast and modular Python CLI tool designed to audit Minecraft modpacks, identify duplicate files, detect missing dependencies, isolate client-only mods, and construct a clean server-side `mods` folder.

---

## 🇫🇷 Français

### À propos

ModMaestro est un utilitaire en ligne de commande développé en Python. Il simplifie la préparation des modpacks Minecraft (compatibilité NeoForge, Fabric et versions récentes) en automatisant les vérifications de structure et le filtrage des fichiers pour le déploiement sur serveur dédié.

### Stack technique

* **Python 3.10+** — Logique principale et traitement de données.
* **Rich** — Formatage des sorties terminal (tableaux, statuts, affichages dynamiques).
* **Zipfile** — Inspection directe des archives `.jar` sans extraction préalable sur le disque.
* **Tomllib / Tomli** — Parsing des fichiers de configuration internes (`neoforge.mods.toml`, `fabric.mod.json`).

### Fonctionnalités

* **Extraction de métadonnées** : Lecture directe du `modid`, du nom, de la version et des dépendances de chaque fichier `.jar`.
* **Détection de doublons** : Identification automatique des conflits de versions pour un même mod.
* **Vérification des dépendances** : Validation de la présence de toutes les bibliothèques requises.
* **Séparation Client / Serveur** : Identification des mods strictement clients (mini-cartes, shaders, optimisations d'affichage).
* **Export serveur** : Copie sélective des mods nécessaires vers un répertoire cible `server_mods`.

Cette outils est publiques et peux être utiliser par tout le monde.

## 🇬🇧 English

### Overview

ModMaestro is a Python-based command-line tool built to streamline Minecraft modpack maintenance for NeoForge and Fabric setups. It automates package validation, dependency checking, and client-side mod exclusion before deploying to a dedicated server.

### Technical Stack

* **Python 3.10+** — Core processing logic.
* **Rich** — Terminal UI layout and tabular data rendering.
* **Zipfile** — In-memory inspection of `.jar` archives.
* **Tomllib / Tomli** — Parsing internal metadata manifests (`neoforge.mods.toml`, `fabric.mod.json`).

### Core Features

* **Metadata Extraction**: Reads `modid`, versioning, and dependency lists directly from archive files.
* **Duplicate Detection**: Flags duplicate mod IDs across multiple files.
* **Dependency Audit**: Validates required libraries against installed mods.
* **Environment Separation**: Filters out client-only dependencies (HUDs, renderers, mini-maps).
* **Build Automation**: Compiles a clean `server_mods` output directory.

This tool is public and open for anyone to use.