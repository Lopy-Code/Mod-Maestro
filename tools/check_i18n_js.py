#!/usr/bin/env python3
"""Vérifie la traduction de l'interface web (stdlib seule).

Extrait tous les textes français de web/static/js/*.js (appels t("…") / tn("…", "…") et feat(svg, "titre", "texte")
de l'accueil) et de web/static/index.html (data-t / data-t-title), puis contrôle web/static/i18n/en.json :
chaque texte doit avoir sa traduction, avec exactement les mêmes {champs}.

    python3 tools/check_i18n_js.py          # code retour 1 s'il manque quelque chose
    python3 tools/check_i18n_js.py --keys   # affiche les clés extraites (une par ligne, en JSON)
"""

from __future__ import annotations

import glob
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "web", "static")
FIELD = re.compile(r"\{(\w+)\}")
CALL = re.compile(r"(?<![\w$.])(t|tn|feat)\(")
ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "`": "`", "$": "$"}


def read_literal(src: str, i: int):
    """Lit un littéral JS ('…', "…" ou `…` sans ${}) à partir de src[i] ; renvoie (texte, indice suivant) ou None."""
    while i < len(src) and src[i] in " \t\r\n":
        i += 1
    if i >= len(src) or src[i] not in "'\"`":
        return None
    q, i, out = src[i], i + 1, []
    while i < len(src):
        c = src[i]
        if c == "\\":
            nxt = src[i + 1]
            if nxt == "u":
                out.append(chr(int(src[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(ESC.get(nxt, nxt))
            i += 2
            continue
        if c == q:
            return "".join(out), i + 1
        if q == "`" and c == "$" and src[i + 1:i + 2] == "{":
            return None  # gabarit dynamique : pas un texte fixe
        out.append(c)
        i += 1
    return None


def skip_comma(src: str, i: int):
    while i < len(src) and src[i] in " \t\r\n":
        i += 1
    return i + 1 if src[i:i + 1] == "," else None


def skip_arg(src: str, i: int):
    """Saute un argument quelconque (n, c.mods, rows.length…) jusqu'à la virgule de niveau 0 ; renvoie l'indice après elle."""
    depth = 0
    while i < len(src):
        c = src[i]
        if c in "'\"`":
            lit = read_literal(src, i)
            if lit is None:
                return None
            i = lit[1]
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return None
            depth -= 1
        elif c == "," and depth == 0:
            return i + 1
        i += 1
    return None


def extract_js(src: str, name: str = "") -> tuple[set[str], list[str]]:
    keys: set[str] = set()
    dynamic: list[str] = []
    for m in CALL.finditer(src):
        fn, start = m.group(1), m.end()
        line = src.count("\n", 0, m.start()) + 1
        if fn == "feat":  # feat(svg, titre, texte) : l'accueil construit ses cartes par une fonction locale
            i = start
            lit = read_literal(src, i)
            if lit is None:
                continue  # c'est la définition `const feat = (svg, h, p)` ou un autre usage : ignoré
            i = skip_comma(src, lit[1])
            if i is None:
                continue
            for _ in range(2):
                lit = read_literal(src, i)
                if lit is None:
                    break
                keys.add(lit[0])
                i = skip_comma(src, lit[1])
                if i is None:
                    break
            continue
        if fn == "tn":  # tn(n, singulier, pluriel[, params]) : le nombre est ignoré
            i = skip_arg(src, start)
            lit = read_literal(src, i) if i is not None else None
            lit2 = None
            if lit:
                j = skip_comma(src, lit[1])
                lit2 = read_literal(src, j) if j is not None else None
            if not lit or not lit2:
                dynamic.append(f"{name}:{line}")
                continue
            keys.update((lit[0], lit2[0]))
            continue
        lit = read_literal(src, start)
        if lit is None:
            dynamic.append(f"{name}:{line}")
            continue
        keys.add(lit[0])
    return keys, dynamic


def extract_html(src: str) -> set[str]:
    keys = set()
    for m in re.finditer(r'data-t(?:-title)?="([^"]*)"', src):
        keys.add(html.unescape(m.group(1)))
    return keys


def collect() -> tuple[set[str], list[str]]:
    keys, dynamic = set(), []
    for p in sorted(glob.glob(os.path.join(STATIC, "js", "*.js"))):
        with open(p, encoding="utf-8") as fh:
            k, d = extract_js(fh.read(), os.path.basename(p))
        keys |= k
        dynamic += d
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        keys |= extract_html(fh.read())
    return keys, dynamic


def main() -> int:
    keys, dynamic = collect()
    if "--keys" in sys.argv:
        print(json.dumps(sorted(keys), ensure_ascii=False, indent=0))
        return 0
    with open(os.path.join(STATIC, "i18n", "en.json"), encoding="utf-8") as fh:
        en = json.load(fh)
    missing = sorted(k for k in keys if k not in en)
    bad = sorted(k for k in keys if k in en and set(FIELD.findall(k)) != set(FIELD.findall(en[k])))
    unused = sorted(k for k in en if k not in keys)
    for k in missing:
        print("MANQUE   :", k)
    for k in bad:
        print("CHAMPS   :", k, "->", en[k])
    for k in unused:
        print("INUTILISÉ:", k)
    print(f"{len(keys)} textes, {len(en)} traductions, {len(dynamic)} appel(s) dynamique(s) ignoré(s)")
    return 1 if missing or bad or unused else 0


if __name__ == "__main__":
    sys.exit(main())
