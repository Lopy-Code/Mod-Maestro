"""Traduction FR/EN des textes produits par le moteur (alertes, rapports, menu terminal).

Principe « gettext » : le texte **français** sert d'identifiant. En anglais on cherche sa traduction dans
`i18n_en.EN` ; sans traduction, le français est conservé. `tests/test_i18n.py` vérifie que chaque texte
passé à `_()` / `ng()` a bien sa traduction : impossible d'oublier une phrase.

La langue courante est propre à chaque requête / tâche (contextvars), donc deux onglets peuvent différer.
"""

from __future__ import annotations

import contextvars

LANGS = ("fr", "en")
_lang: contextvars.ContextVar[str] = contextvars.ContextVar("modmaestro_lang", default="fr")


def set_lang(lang: str | None) -> str:
    lang = lang if lang in LANGS else "fr"
    _lang.set(lang)
    return lang


def get_lang() -> str:
    return _lang.get()


def _catalog() -> dict:
    from .i18n_en import EN  # import tardif : le catalogue est volumineux
    return EN


def _(msgid: str, **kw) -> str:
    """Traduit `msgid` (français) dans la langue courante, puis remplace les {champs}."""
    text = _catalog().get(msgid, msgid) if _lang.get() == "en" else msgid
    return text.format(**kw) if kw else text


def tr(text: str) -> str:
    """Traduit un texte qui vient de *données* (base de connaissances) : pas de {champs}, repli sur l'original."""
    return _catalog().get(text, text) if text and _lang.get() == "en" else text


def ng(one: str, many: str, n: int, **kw) -> str:
    """Singulier / pluriel : `ng("{n} mod", "{n} mods", 3)`. Les deux formes sont des identifiants de traduction."""
    return _(one if n == 1 else many, n=n, **kw)
