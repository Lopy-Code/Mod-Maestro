# Règles de configuration

`configrules.json` contient des règles pour les fichiers de `config/` (liste vide par défaut : on n'ajoute que des
réglages vérifiés). Exemple de règle :

```json
{"id": "mymod-radius", "path": "config/mymod.toml", "key": "general.radius", "op": "gt", "value": 8,
 "severity": "warning", "requires_mod": "mymod",
 "title": "Rayon trop grand", "message": "Un rayon > 8 fait chuter les TPS.", "fix": "Mets 8 ou moins.",
 "en": {"title": "Radius too large", "message": "A radius > 8 drops TPS.", "fix": "Set 8 or lower."}}
```
