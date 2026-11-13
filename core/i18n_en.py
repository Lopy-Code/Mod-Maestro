"""Catalogue anglais : fusion des fichiers de `core/en/` (un par thème, pour garder des fichiers lisibles)."""

from .en import analysis, cli, engine, misc

EN: dict[str, str] = {}
for _part in (analysis, engine, cli, misc):
    EN.update(_part.EN)
