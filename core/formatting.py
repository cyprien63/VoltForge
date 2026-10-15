"""VoltForge — Formatage et analyse de grandeurs physiques (SI).

Petites utilitaires utilisées par le modèle de composants, le solveur MNA
et le parseur de scénarios : conversion « 4.7k » -> 4700.0, affichage
élégant « 4.7 kΩ », gestion des préfixes SI et des unités usuelles.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# (facteur, préfixe) — du plus grand au plus petit
_PREFIXES = (
    (1e12, "T"),
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "µ"),
    (1e-9, "n"),
    (1e-12, "p"),
    (1e-15, "f"),
)

# Suffixes d'unités acceptés à la saisie (ignorés après la valeur)
_UNIT_ALIASES = {
    "": 1.0,
    "v": 1.0,
    "volt": 1.0,
    "volts": 1.0,
    "a": 1.0,
    "amp": 1.0,
    "ampere": 1.0,
    "ampères": 1.0,
    "ohm": 1.0,
    "ohms": 1.0,
    "Ω": 1.0,
    "r": 1.0,
    "f": 1.0,
    "farad": 1.0,
    "h": 1.0,
    "henry": 1.0,
    "s": 1.0,
    "sec": 1.0,
    "ms": 1.0e-3,   # géré par la 1re lettre : 'm' -> milli
    "w": 1.0,
    "watt": 1.0,
    "hz": 1.0,
    "%": 0.01,
}

_PREFIX_MULT = {
    "T": 1e12, "G": 1e9, "M": 1e6, "K": 1e3, "k": 1e3,
    "": 1.0, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "n": 1e-9, "p": 1e-12, "f": 1e-15,
}
# Note : casse significative — 'M' = méga, 'm' = milli, 'K'/'k' = kilo.

_NUMBER_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$"
)


def parse_value(text: str, default: Optional[float] = None) -> float:
    """Analyse une valeur physique textuelle.

    Accepte : « 12 », « 4,7 », « 4.7k », « 12V », « 1mA », « 0.5s »,
    « 1 kOhm », « 1e3 ». Le suffixe d'unité est ignoré, seul le préfixe
    SI compte. Lève ``ValueError`` en cas d'analyse ratée.
    """
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s:
        if default is not None:
            return default
        raise ValueError("valeur vide")
    m = _NUMBER_RE.match(s)
    if not m:
        raise ValueError(f"valeur illisible : {text!r}")
    num = float(m.group(1).replace(",", "."))
    suffix = m.group(2)
    if not suffix:
        return num
    # Unité littérale complète ? (V, Ohm, F, H, s, W, % …)
    low = suffix.lower().strip()
    if low in _UNIT_ALIASES:
        return num * _UNIT_ALIASES[low]
    # Sinon : préfixe + unité éventuelle ('k', '1kΩ', '2mA'…)
    first = suffix[0]
    mult = _PREFIX_MULT.get(first)
    if mult is None:
        # unité inconnue mais cohérente ? on tolère l'unité seule
        raise ValueError(f"préfixe inconnu dans {text!r}")
    return num * mult


def parse_time(text: str) -> float:
    """Analyse une durée : « 2 », « 500ms », « 1.5s », « 250us », « 1min ». Returns seconds."""
    s = str(text).strip().lower()
    m = re.match(r"^([+-]?[\d.,]+(?:e[+-]?\d+)?)\s*([a-zµμ]*)$", s)
    if not m:
        raise ValueError(f"temps illisible : {text!r}")
    num = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    if unit in ("", "s", "sec", "secs"):
        return num
    if unit in ("ms", "msec"):
        return num * 1e-3
    if unit in ("us", "µs", "μs", "usec"):
        return num * 1e-6
    if unit in ("min", "mins"):
        return num * 60.0
    if unit == "h":
        return num * 3600.0
    raise ValueError(f"unité de temps inconnue : {unit!r}")


def si_format(value: float, unit: str = "", precision: int = 4) -> str:
    """Formatte une valeur en notation SI lisible : 4700 Ω -> « 4.7 kΩ »."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v != v:  # NaN
        return "—"
    if v == 0:
        return f"0 {unit}".strip()
    av = abs(v)
    factor, prefix = _PREFIXES[-1], "f"
    for f, p in _PREFIXES:
        if av >= f:
            factor, prefix = f, p
            break
    scaled = v / factor
    # Jusqu'à 4 chiffres significatifs, décimales inutiles supprimées
    txt = f"{scaled:.{precision}g}"
    if "." in txt:
        txt = txt.rstrip("0").rstrip(".")
    return f"{txt} {prefix}{unit}".strip()


def format_seconds(t: float) -> str:
    """Formatte un temps d'animation : « 1.50 s » (ou « 250 ms » si court)."""
    if abs(t) < 1:
        return f"{t * 1000:.0f} ms"
    return f"{t:.2f} s"


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)
