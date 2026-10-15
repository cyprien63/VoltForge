"""VoltForge — Programme de simulation séquentiel (scénario textuel).

DSL simple, en ligne, pour piloter la simulation dans le temps :

.. code-block:: text

   # Allumage progressif
   loop 0s 6s          # plage d'animation (pour le GIF)
   fps 15              # images par seconde de l'export

   t=0: gen1.voltage = 0 ; switch1.closed = false
   +1s: gen1.voltage = 12V
   +0.5: switch1.closed = true
   t=3: gen1.voltage = 12 ; switch1.closed = false

* Les temps absolus (``t=…``) et relatifs (``+…``) sont acceptés,
  unités ``s`` / ``ms`` / ``us`` / ``min`` (défaut : secondes).
* Plusieurs actions sont séparées par ``;`` sur une même ligne.
* Commentaires : lignes débutant par ``#``.
* Propriétés : ``voltage``, ``current``, ``ri``, ``resistance``,
  ``closed``, ``r_on``, ``r_off``, ``capacitance``, ``v0``,
  ``inductance``, ``r_w``, ``p_max``, ``label``…
* Valeurs booléennes : ``true/false``, ``vrai/faux``, ``on/off``,
  ``open/closed``, ``ouvert/fermé``, ``1/0``.

Indépendant de Qt.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .formatting import parse_time, parse_value

# Aliases de propriétés acceptés à la saisie
PROP_ALIASES: Dict[str, str] = {
    "voltage": "voltage", "v": "voltage", "u": "voltage", "emf": "voltage",
    "tension": "voltage", "courant": "current", "current": "current",
    "i": "current", "ri": "ri", "r_int": "ri",
    "resistance": "resistance", "r": "resistance",
    "closed": "closed", "state": "state", "etat": "state",
    "switch": "closed", "r_on": "r_on", "ron": "r_on",
    "r_off": "r_off", "roff": "r_off",
    "capacitance": "capacitance", "c": "capacitance",
    "v0": "v0", "inductance": "inductance", "l": "inductance",
    "r_w": "r_w", "rw": "r_w", "p_max": "p_max", "pmax": "p_max",
    "label": "label", "name": "label",
}

_EVENT_RE = re.compile(
    r"^\s*([A-Za-z_][\w]*)\s*[.:]\s*(.+)$",          # ident.prop = valeur
)
_TIME_RE = re.compile(r"^([tT])\s*=")


@dataclass
class ScenarioEvent:
    """Une mutation de propriété planifiée à un instant donné."""
    time: float
    target: str            # label du composant (casse insensible)
    prop: str              # propriété normalisée
    value: Any             # valeur déjà convertie
    raw: str = ""          # texte source (affichage d'erreur)
    line: int = 0

    def describe(self) -> str:
        v = self.value
        if isinstance(v, bool):
            v = "true" if v else "false"
        return f"t={self.time:g}s : {self.target}.{self.prop} = {v}"


@dataclass
class ScenarioError:
    line: int
    message: str
    text: str = ""

    def __str__(self) -> str:
        return f"Ligne {self.line} : {self.message}"


@dataclass
class ScenarioProgram:
    """Programme séquentiel entièrement analysé et exécutable."""
    events: List[ScenarioEvent] = field(default_factory=list)
    loop: Optional[Tuple[float, float]] = None
    fps: float = 15.0
    dt: float = 0.005          # pas de temps du solveur transitoire (s)
    tail: float = 0.5          # marge après le dernier événement

    @property
    def duration(self) -> float:
        """Durée totale : plage loop, sinon dernier événement + marge."""
        if self.loop is not None:
            return max(0.0, self.loop[1] - self.loop[0])
        if not self.events:
            return 0.0
        return max(e.time for e in self.events) + self.tail

    @property
    def start(self) -> float:
        return self.loop[0] if self.loop is not None else (
            min((e.time for e in self.events), default=0.0)
        )

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def frame_count(self) -> int:
        if self.fps <= 0 or self.duration <= 0:
            return 0
        return max(2, math.ceil(self.duration * self.fps - 1e-12))

    def events_between(self, t0: float, t1: float, cursor: int) -> int:
        """Nouvel indice curseur après application de tous les événements ≤ t1."""
        while cursor < len(self.events) and self.events[cursor].time <= t1 + 1e-9:
            cursor += 1
        return cursor

    def apply_upto(self, components_by_label: Dict[str, Any], t: float,
                   cursor: int, errors: Optional[List[str]] = None) -> int:
        """Applique tous les événements ≤ ``t`` ; retourne le curseur."""
        while cursor < len(self.events) and self.events[cursor].time <= t + 1e-9:
            ev = self.events[cursor]
            comp = components_by_label.get(ev.target.lower())
            if comp is None:
                msg = f"composant introuvable : {ev.target}"
                if errors is not None and msg not in errors:
                    errors.append(msg)
            else:
                try:
                    comp.set_prop(ev.prop, ev.value)
                except (ValueError, KeyError) as exc:
                    if errors is not None:
                        msg = f"{ev.target}.{ev.prop}: {exc}"
                        if msg not in errors:
                            errors.append(msg)
            cursor += 1
        return cursor


# ---------------------------------------------------------------------------
# Analyse syntaxique
# ---------------------------------------------------------------------------

def _parse_scalar(text: str) -> Any:
    """Convertit un littéral : mot-clé booléen, puis nombre avec unité.

    « 0 » et « 1 » restent **numériques** (les propriétés booléennes
    les convertissent de toute façon) ; les booléens s'écrivent en
    lettres (true/false, ouvert/fermé…).
    """
    s = text.strip()
    low = s.lower()
    if low in ("true", "vrai", "yes", "on", "closed", "fermé", "ferme", "fermée"):
        return True
    if low in ("false", "faux", "no", "off", "open", "ouvert"):
        return False
    return parse_value(s)


def _parse_time_token(token: str, prev_time: float) -> float:
    s = token.strip()
    if s.startswith("+"):
        return prev_time + parse_time(s[1:])
    if _TIME_RE.match(s):
        return parse_time(_TIME_RE.sub("", s))
    return parse_time(s)


def parse_scenario(text: str) -> Tuple[ScenarioProgram, List[ScenarioError]]:
    """Analyse un scénario ; retourne ``(programme, erreurs)``.

    Les erreurs n'interrompent pas l'analyse : les lignes valides sont
    conservées pour permettre l'édition progressive.
    """
    program = ScenarioProgram()
    errors: List[ScenarioError] = []
    prev_time = 0.0
    last_line_time: Optional[float] = None

    for lineno, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue

        # --- directives ---------------------------------------------------
        low = line.lower()
        if low.startswith("loop"):
            parts = line.split()[1:]
            if len(parts) != 2:
                errors.append(ScenarioError(lineno, "syntaxe : loop <t0> <t1>", line))
                continue
            try:
                t0, t1 = parse_time(parts[0]), parse_time(parts[1])
                if t1 <= t0:
                    raise ValueError("t1 doit être > t0")
                program.loop = (t0, t1)
            except ValueError as exc:
                errors.append(ScenarioError(lineno, f"loop invalide : {exc}", line))
            continue
        if low.startswith("fps"):
            try:
                val = float(line.split()[1].replace(",", "."))
                if val <= 0 or val > 120:
                    raise ValueError("fps attendu entre 1 et 120")
                program.fps = val
            except (IndexError, ValueError) as exc:
                errors.append(ScenarioError(lineno, f"fps invalide : {exc}", line))
            continue
        if low.startswith("dt"):
            try:
                program.dt = max(1e-4, parse_time(line.split()[1]))
            except (IndexError, ValueError) as exc:
                errors.append(ScenarioError(lineno, f"dt invalide : {exc}", line))
            continue
        if low.startswith("tail"):
            try:
                program.tail = max(0.0, parse_time(line.split()[1]))
            except (IndexError, ValueError) as exc:
                errors.append(ScenarioError(lineno, f"tail invalide : {exc}", line))
            continue

        # --- horodatage facultatif ----------------------------------------
        cursor = 0
        time_part = line
        if _TIME_RE.match(line) or line.lstrip().startswith("+"):
            head, sep, rest = line.partition(":")
            if not sep:
                errors.append(ScenarioError(lineno, "« : » manquant après le temps", line))
                continue
            try:
                t = _parse_time_token(head, prev_time)
            except ValueError as exc:
                errors.append(ScenarioError(lineno, f"temps invalide : {exc}", line))
                continue
            prev_time = t
            last_line_time = t
            time_part = rest
        elif last_line_time is None:
            prev_time = 0.0

        # --- actions -------------------------------------------------------
        base_time = last_line_time if last_line_time is not None else prev_time
        actions = [a.strip() for a in time_part.split(";") if a.strip()]
        if not actions:
            errors.append(ScenarioError(lineno, "action attendue", line))
            continue
        for action in actions:
            m = _EVENT_RE.match(action)
            if not m:
                errors.append(ScenarioError(lineno, f"action illisible : {action!r}", line))
                continue
            target, rhs = m.group(1), m.group(2)
            if "=" not in rhs:
                errors.append(ScenarioError(lineno, f"« = » manquant dans {action!r}", line))
                continue
            prop_raw, value_raw = rhs.split("=", 1)
            prop_key = prop_raw.strip().lower()
            prop = PROP_ALIASES.get(prop_key)
            if prop is None:
                errors.append(ScenarioError(
                    lineno, f"propriété inconnue {prop_raw.strip()!r}", line))
                continue
            try:
                value = _parse_scalar(value_raw)
            except ValueError as exc:
                errors.append(ScenarioError(lineno, f"valeur invalide : {exc}", line))
                continue
            program.events.append(ScenarioEvent(
                time=base_time, target=target.strip(), prop=prop,
                value=value, raw=action, line=lineno,
            ))

    program.events.sort(key=lambda e: e.time)
    return program, errors
