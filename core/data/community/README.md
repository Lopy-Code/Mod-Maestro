# Base communautaire ModMaestro

Un fichier JSON par entrée : facile à relire, facile à proposer par pull request.
ModMaestro charge automatiquement tout ce dossier au lancement (et ton dossier personnel, au même format).

## `sides/<modid>.json` — côté client / serveur

```json
{
  "modid": "betterthirdperson",
  "side": "client",
  "reason": "Mod de caméra : n'agit que sur la vue du joueur.",
  "source": "https://…  (page du mod, ou une phrase)"
}
```

- `side: "client"` → inutile sur un serveur : retiré automatiquement du dossier serveur.
- `side: "both"` → à **garder** : corrige une fausse alerte (un mod pris à tort pour un mod client).

## `conflicts/<a>__<b>.json` — incompatibilités

Soit un groupe (au moins deux mods qui se gênent entre eux) :

```json
{ "group": ["starlight", "phosphor"], "severity": "warning",
  "title": "Deux moteurs d'éclairage", "message": "Pourquoi c'est un problème.",
  "fix": "Que faire.", "source": "https://…" }
```

Soit deux listes (chaque mod de `a` contre chaque mod de `b`) :

```json
{ "a": ["optifine"], "b": ["sodium", "iris"], "severity": "error",
  "title": "…", "message": "…", "fix": "…", "source": "…" }
```

## Règles

- Identifiants (`modid`) : ceux **du mod lui-même** (dans `neoforge.mods.toml` / `fabric.mod.json`), en minuscules.
- `severity` : `error` (le jeu plante ou le mod ne marche pas), `warning` (problèmes probables), `info` (redondance).
- Une `source` est vivement demandée : une page du mod, une issue GitHub, un rapport de crash.
- N'ajoute que ce dont tu es sûr. Un faux conflit fait perdre du temps à tout le monde : en cas de doute, mets `info`.
- Vérifie ton fichier : `python tools/check_community.py`.

Tu peux aussi enregistrer un conflit dans l'interface (onglet « Ma base »), puis **exporter** : les fichiers sont générés
dans ce format, prêts à être copiés ici.
