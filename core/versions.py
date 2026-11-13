"""Comparaison de versions et plages de versions (Maven / Fabric).

Tout est volontairement tolérant : quand une version ou une plage est
incompréhensible, on considère qu'elle est satisfaite plutôt que de lever
une fausse alerte.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\d+|[A-Za-z]+")

# Ordre des qualificatifs : < 0 = pré-version, 0 = release, > 0 = post-release.
_QUALIFIERS = {
    "alpha": -5, "a": -5,
    "beta": -4, "b": -4,
    "milestone": -3, "m": -3,
    "pre": -2,
    "rc": -1, "cr": -1, "snapshot": -1,
    "": 0, "final": 0, "ga": 0, "release": 0,
    "sp": 1,
}


def has_digits(version: str | None) -> bool:
    return bool(version and re.search(r"\d", str(version)))


def parse(version: str) -> list:
    v = str(version).strip()
    if len(v) > 1 and v[0] in "vV" and v[1].isdigit():
        v = v[1:]
    v = v.split("+", 1)[0]  # métadonnées de build ignorées
    return [int(t) if t.isdigit() else t.lower() for t in _TOKEN.findall(v)]


def _rank(token: str) -> float:
    return _QUALIFIERS.get(token, 0.5)


def _cmp_tok(x, y) -> int:
    if x is None and y is None:
        return 0
    if x is None:
        return -_cmp_tok(y, None)
    if y is None:
        if isinstance(x, int):
            return 1 if x > 0 else 0
        r = _rank(x)
        return -1 if r < 0 else (0 if r == 0 else 1)
    if isinstance(x, int) and isinstance(y, int):
        return (x > y) - (x < y)
    if isinstance(x, int):
        return 1
    if isinstance(y, int):
        return -1
    rx, ry = _rank(x), _rank(y)
    if rx != ry:
        return (rx > ry) - (rx < ry)
    return (x > y) - (x < y)


def compare(a: str, b: str) -> int:
    ta, tb = parse(a), parse(b)
    for i in range(max(len(ta), len(tb))):
        x = ta[i] if i < len(ta) else None
        y = tb[i] if i < len(tb) else None
        if x == y:
            continue
        c = _cmp_tok(x, y)
        if c:
            return c
    return 0


def newest(versions: list[str | None]) -> int:
    """Indice de la plus haute version (les versions inconnues perdent)."""
    best = 0
    for i, v in enumerate(versions):
        if i == 0:
            continue
        cur, cand = versions[best], v
        if not has_digits(cand):
            continue
        if not has_digits(cur) or compare(cand, cur) > 0:
            best = i
    return best


# --------------------------------------------------------------------------
# Plages Maven : [1.0,2.0)  (,2.0]  [1.0]  [1.0,)  puis listes "[1,2),[3,4)"
# --------------------------------------------------------------------------

_MAVEN_RESTRICTION = re.compile(
    r"([\[\(])\s*([^,\[\]\(\)]*?)\s*(?:(,)\s*([^,\[\]\(\)]*?))?\s*([\]\)])"
)


def maven_contains(spec: str | None, version: str | None) -> bool:
    if spec is None:
        return True
    spec = str(spec).strip()
    if spec in ("", "*") or spec[0] not in "[(":
        return True  # absent, joker, ou version « souple » : on ne bloque pas
    if not has_digits(version):
        return True
    restrictions = _MAVEN_RESTRICTION.findall(spec)
    if not restrictions:
        return True
    for lo_br, lo, comma, hi, hi_br in restrictions:
        if not comma:  # [1.0]
            if lo and compare(version, lo) == 0:
                return True
            continue
        ok = True
        if lo:
            c = compare(version, lo)
            ok = c > 0 or (c == 0 and lo_br == "[")
        if ok and hi:
            c = compare(version, hi)
            ok = c < 0 or (c == 0 and hi_br == "]")
        if ok:
            return True
    return False


# --------------------------------------------------------------------------
# Prédicats Fabric / Quilt : ">=1.0 <2.0", "~1.21", "^1.2.3", "1.21.x", "*"
# --------------------------------------------------------------------------

_FABRIC_TERM = re.compile(r"^(>=|<=|>|<|=|\^|~)?\s*(.+)$")


def _int_prefix(tokens: list) -> list[int]:
    out = []
    for t in tokens:
        if isinstance(t, int):
            out.append(t)
        else:
            break
    return out


def _fmt(nums: list[int]) -> str:
    return ".".join(str(n) for n in nums) or "0"


def _fabric_term(version: str, term: str) -> bool:
    term = term.strip()
    if term in ("", "*", "x", "X"):
        return True
    m = _FABRIC_TERM.match(term)
    if not m:
        return True
    op, ver = m.group(1) or "=", m.group(2).strip()
    if re.search(r"(^|\.)[xX*](\.|$)", ver):
        prefix = []
        for part in ver.split("."):
            if part in ("x", "X", "*"):
                break
            prefix.append(part)
        if op == "=":
            have = parse(version)
            want = parse(".".join(prefix))
            return have[: len(want)] == want
        ver = ".".join(p if p not in ("x", "X", "*") else "0" for p in ver.split("."))
    c = compare(version, ver)
    if op == "=":
        return c == 0
    if op == ">=":
        return c >= 0
    if op == "<=":
        return c <= 0
    if op == ">":
        return c > 0
    if op == "<":
        return c < 0
    nums = _int_prefix(parse(ver))
    if not nums:
        return True
    if op == "~":
        upper = nums[:2] if len(nums) >= 2 else nums[:1]
        upper[-1] += 1
        return c >= 0 and compare(version, _fmt(upper)) < 0
    if op == "^":
        idx = next((i for i, n in enumerate(nums) if n != 0), len(nums) - 1)
        upper = nums[: idx + 1]
        upper[-1] += 1
        return c >= 0 and compare(version, _fmt(upper)) < 0
    return True


def fabric_satisfies(spec, version: str | None) -> bool:
    if spec is None or not has_digits(version):
        return True
    alternatives = spec if isinstance(spec, list) else [spec]
    for alt in alternatives:
        for branch in str(alt).split("||"):
            terms = branch.split()
            if all(_fabric_term(version, t) for t in terms or ["*"]):
                return True
    return False


def _strict(syntax: str, spec, version: str | None) -> bool:
    if syntax == "maven":
        return maven_contains(spec if isinstance(spec, str) or spec is None else str(spec), version)
    return fabric_satisfies(spec, version)


_MC_PREFIX = re.compile(r"^(?:mc)?1\.\d{1,2}(?:\.\d+)?[-_+](.+)$", re.IGNORECASE)
_MC_SUFFIX = re.compile(r"^(.+?)[-_+](?:mc)?1\.\d{1,2}(?:\.\d+)?$", re.IGNORECASE)


def satisfies(syntax: str, spec, version: str | None) -> bool:
    """Vrai si `version` respecte `spec`.

    Beaucoup de mods écrivent leur version avec la version de Minecraft devant ou derrière
    (« 1.20.1-47.1.3 », « mc1.20.1-0.5.2 », « 2.0+1.20.1 ») alors que les plages visent le numéro du mod seul :
    on réessaie donc sans ce préfixe / suffixe, pour ne pas signaler un faux problème.
    """
    if _strict(syntax, spec, version):
        return True
    v = str(version or "")
    for rx in (_MC_PREFIX, _MC_SUFFIX):
        m = rx.match(v)
        if m and _strict(syntax, spec, m.group(1)):
            return True
    return False


def candidate_versions(spec) -> set[str]:
    """Versions « X.Y(.Z) » citées dans une plage (utile pour deviner la version de MC)."""
    text = " ".join(spec) if isinstance(spec, list) else str(spec or "")
    return set(re.findall(r"\d+\.\d+(?:\.\d+)?", text))


def mc_minor(version: str) -> tuple[int, int] | None:
    nums = _int_prefix(parse(version))
    return (nums[0], nums[1]) if len(nums) >= 2 else None
