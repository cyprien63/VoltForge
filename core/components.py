"""VoltForge — Modèle de composants électriques normalisés.

Catalogue complet (17 types) :

=======  ===========================================================
Sources  Générateur (tension / courant), pile
Passifs  Résistance personnalisable, Potentiomètre, Condensateur, Bobine
Semi-    Diode, LED
conduct.
Énergie  Lampe, Moteur, Fusible
Outils   Voltmètre, Ampèremètre, Ohmmètre
Topo.    Masse (référence 0 V), Fil de connexion
=======  ===========================================================

Chaque composant est décrit par sa position centrale (grille de 20 px),
sa rotation (0/90/180/270°, sens horaire comme en Qt), ses bornes et un
dictionnaire de propriétés typées pilotant à la fois l'interface et le
moteur de simulation.

Géométrie : les bornes sont toujours à un multiple du pas de grille
(20 px) pour que les coïncidences de coordinates résolvent exactement
les nœuds électriques.

Ce module est volontairement **indépendant de Qt** (testable via
``python -m core``).
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from .formatting import si_format

# ---------------------------------------------------------------------------
# Géométrie de la grille
# ---------------------------------------------------------------------------

GRID_SIZE = 20                 # px par pas de grille
COMP_LENGTH = 40               # distance entre les deux bornes « principales »
HALF_LENGTH = COMP_LENGTH // 2  # 20 px = exactement 1 maille


def snap(value: float, grid: int = GRID_SIZE) -> int:
    """Aligne une coordonnée sur la grille (snap-to-grid)."""
    return int(round(value / grid)) * grid


def snap_point(x: float, y: float) -> Tuple[int, int]:
    return snap(x), snap(y)


def rotate_offset(dx: float, dy: float, degrees: int) -> Tuple[float, float]:
    """Rotation dans le repère écran (y vers le bas), sens horaire > 0.

    Même convention que ``QGraphicsItem.setRotation``.
    """
    r = math.radians(degrees % 360)
    c, s = math.cos(r), math.sin(r)
    return dx * c - dy * s, dx * s + dy * c


# ---------------------------------------------------------------------------
# Enumérations partagées
# ---------------------------------------------------------------------------

class Kind(str, Enum):
    """Type normalisé d'un composant physique."""

    # Sources
    GENERATOR = "generator"
    BATTERY = "battery"
    # Passifs
    RESISTOR = "resistor"
    CUSTOM = "custom"
    POTENTIOMETER = "potentiometer"
    SWITCH = "switch"
    CAPACITOR = "capacitor"
    INDUCTOR = "inductor"
    # Semi-conducteurs
    DIODE = "diode"
    LED = "led"
    # Énergie / actionneurs
    LAMP = "lamp"
    MOTOR = "motor"
    FUSE = "fuse"
    # Instruments de mesure
    VOLTMETER = "voltmeter"
    AMMETER = "ammeter"
    OHMMETER = "ohmmeter"
    # Topologie
    GROUND = "ground"

    @property
    def label_fr(self) -> str:
        return _KIND_LABELS[self.value]

    @property
    def is_instrument(self) -> bool:
        return self in (Kind.VOLTMETER, Kind.AMMETER, Kind.OHMMETER)


_KIND_LABELS = {
    "generator": "Générateur",
    "battery": "Pile",
    "resistor": "Résistance",
    "custom": "Composant personnalisé",
    "potentiometer": "Potentiomètre",
    "switch": "Interrupteur",
    "capacitor": "Condensateur",
    "inductor": "Bobine",
    "diode": "Diode",
    "led": "LED",
    "lamp": "Lampe",
    "motor": "Moteur",
    "fuse": "Fusible",
    "voltmeter": "Voltmètre",
    "ammeter": "Ampèremètre",
    "ohmmeter": "Ohmmètre",
    "ground": "Masse",
}


class SourceType(str, Enum):
    """Mode de fonctionnement du générateur."""
    VOLTAGE = "voltage"
    CURRENT = "current"


# ---------------------------------------------------------------------------
# Métadonnées de propriétés (pilotent le panneau d'édition)
# ---------------------------------------------------------------------------

@dataclass
class Prop:
    """Description d'une propriété éditable d'un composant."""
    default: Any
    ptype: str = "float"            # "float" | "bool" | "enum" | "str"
    unit: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: float = 1.0
    decimals: int = 5
    choices: Optional[Tuple[str, ...]] = None
    group: str = "Général"
    tip: str = ""

    def coerce(self, value: Any) -> Any:
        """Convertit ``value`` vers le type attendu (lève ValueError)."""
        if self.ptype == "bool":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("1", "true", "vrai", "yes", "on", "closed",
                     "fermé", "ferme", "fermée", "grillé", "grille"):
                return True
            if s in ("0", "false", "faux", "no", "off", "open",
                     "ouvert", "intact", "ok"):
                return False
            raise ValueError(f"booléen attendu, reçu {value!r}")
        if self.ptype == "float":
            if isinstance(value, bool):
                raise ValueError("nombre attendu")
            from .formatting import parse_value
            return float(parse_value(value))
        if self.ptype == "enum":
            s = str(value).strip().lower()
            if self.choices:
                for c in self.choices:
                    if c.lower() == s:
                        return c
            raise ValueError(f"choix parmi {self.choices}, reçu {value!r}")
        return str(value)


# ---------------------------------------------------------------------------
# Terminaux
# ---------------------------------------------------------------------------

@dataclass
class Terminal:
    """Borne électrique d'un composant (position scène absolue)."""
    name: str          # "p" (+), "n" (−) ou "w" (curseur du potentiomètre)
    x: float
    y: float

    @property
    def pos(self) -> Tuple[float, float]:
        return (self.x, self.y)

    @property
    def key(self) -> Tuple[int, int]:
        return snap(self.x), snap(self.y)


# ---------------------------------------------------------------------------
# Gestion des labels (unicité dans une session)
# ---------------------------------------------------------------------------

_LABEL_COUNTERS: Dict[str, int] = {}
_USED_LABELS: set = set()


def _next_label(prefix: str) -> str:
    n = _LABEL_COUNTERS.get(prefix, 0) + 1
    while f"{prefix}{n}" in _USED_LABELS:
        n += 1
    _LABEL_COUNTERS[prefix] = n
    _USED_LABELS.add(f"{prefix}{n}")
    return f"{prefix}{n}"


def reserve_label(label: str) -> None:
    """Réserve un label existant (chargement de projet)."""
    _USED_LABELS.add(label)
    prefix = "".join(ch for ch in label if not ch.isdigit()) or label
    digits = "".join(ch for ch in label if ch.isdigit())
    if digits:
        _LABEL_COUNTERS[prefix] = max(_LABEL_COUNTERS.get(prefix, 0), int(digits))


def reset_labels() -> None:
    """Remet à zéro les compteurs (nouveau projet)."""
    _LABEL_COUNTERS.clear()
    _USED_LABELS.clear()


# ---------------------------------------------------------------------------
# Classe de base
# ---------------------------------------------------------------------------

class Component:
    """Composant électrique à bornes rotatives sur grille."""

    kind: ClassVar[Kind] = Kind.RESISTOR
    prefix: ClassVar[str] = "X"
    is_branch: ClassVar[bool] = True       # False : pas de branche MNA (masse)
    #: Offsets des bornes au repos (composant à rotation 0, centré en 0,0)
    TERMINAL_OFFSETS: ClassVar[Dict[str, Tuple[float, float]]] = {
        "p": (-HALF_LENGTH, 0.0),
        "n": (HALF_LENGTH, 0.0),
    }

    PROPS: ClassVar[Dict[str, Prop]] = OrderedDict(
        label=Prop("", ptype="str", group="Identité", tip="Identifiant affiché"),
        p_max=Prop(1.0, unit="W", minimum=0.0, maximum=1e6, step=0.1,
                   group="Limites", tip="Puissance admissible avant avertissement"),
    )
    COMMON_PROPS: ClassVar[Dict[str, Prop]] = OrderedDict(
        u_max=Prop(250.0, unit="V", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites", tip="Tension maximale avant destruction"),
        blown=Prop(False, ptype="bool", group="État",
                   tip="Composant grillé ; décocher pour le réarmer"),
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Make common ratings and the repair state available in every editor.
        declared = cls.PROPS
        common = OrderedDict(cls.COMMON_PROPS)
        if cls.kind in (Kind.DIODE, Kind.LED):
            common["u_max"] = Prop(
                50.0, unit="V", minimum=0.0, maximum=1e6, step=1.0,
                group="Limites", tip="Tension maximale avant destruction",
            )
        merged = OrderedDict()
        merged["label"] = declared.get(
            "label", Component.PROPS["label"]
        )
        for name, prop in common.items():
            merged[name] = declared.get(name, prop)
        merged.update((name, prop) for name, prop in declared.items()
                      if name not in merged)
        cls.PROPS = merged

    def __init__(self, x: float, y: float, rotation: int = 0,
                 label: Optional[str] = None, **props: Any):
        self.x = float(snap(x))
        self.y = float(snap(y))
        self.rotation = int(rotation) % 360
        self.label = label or _next_label(self.prefix)
        if label:
            reserve_label(label)
        # valeurs par défaut
        self._props: Dict[str, Any] = {}
        for name, p in self.PROPS.items():
            self._props[name] = p.default
        self._props["label"] = self.label
        for k, v in props.items():
            if k in self.PROPS:
                self.set_prop(k, v)
        # Résolution nodale (remplie par Circuit.recompute_nodes)
        self.node_of: Dict[str, Optional[int]] = {
            name: None for name in self.TERMINAL_OFFSETS
        }
        # États transitoires (condensateur, bobine, diode, fusible…)
        self.tstate: Dict[str, Any] = {}

    # -- identité ----------------------------------------------------------
    @property
    def id(self) -> str:
        return self.label

    @property
    def kind_value(self) -> str:
        return self.kind.value

    # -- géométrie ---------------------------------------------------------
    @property
    def position(self) -> Tuple[float, float]:
        return (self.x, self.y)

    @position.setter
    def position(self, value: Tuple[float, float]) -> None:
        self.x, self.y = float(snap(value[0])), float(snap(value[1]))

    def move_to(self, x: float, y: float) -> None:
        self.x, self.y = float(snap(x)), float(snap(y))

    def rotate(self, delta: int = 90) -> None:
        self.rotation = (self.rotation + delta) % 360

    def terminal_positions(self) -> Dict[str, Tuple[float, float]]:
        """Positions scène de toutes les bornes selon rotation."""
        out: Dict[str, Tuple[float, float]] = {}
        for name, (ox, oy) in self.TERMINAL_OFFSETS.items():
            rx, ry = rotate_offset(ox, oy, self.rotation)
            out[name] = (self.x + rx, self.y + ry)
        return out

    def terminals(self) -> List[Terminal]:
        return [Terminal(n, pos[0], pos[1])
                for n, pos in self.terminal_positions().items()]

    def terminal_at(self, x: float, y: float, radius: float = 12.0) -> Optional[str]:
        """Nom de la borne la plus proche de (x, y) si dans ``radius``."""
        best, best_d = None, radius * radius
        for name, (tx, ty) in self.terminal_positions().items():
            d = (tx - x) ** 2 + (ty - y) ** 2
            if d <= best_d:
                best, best_d = name, d
        return best

    # -- résolution nodale -------------------------------------------------
    @property
    def node_p(self) -> Optional[int]:
        return self.node_of.get("p")

    @node_p.setter
    def node_p(self, value: Optional[int]) -> None:
        self.node_of["p"] = value

    @property
    def node_n(self) -> Optional[int]:
        return self.node_of.get("n")

    @node_n.setter
    def node_n(self, value: Optional[int]) -> None:
        self.node_of["n"] = value

    def resolve_nodes(self, root_to_id: Dict[Tuple[int, int], int], uf: Any) -> None:
        """Affecte ``node_of`` à partir de l'Union-Find topologique."""
        for name, pos in self.terminal_positions().items():
            key = (snap(pos[0]), snap(pos[1]))
            self.node_of[name] = root_to_id.get(uf.find(key))

    # -- propriétés --------------------------------------------------------
    @classmethod
    def prop_specs(cls) -> "OrderedDict[str, Prop]":
        return cls.PROPS

    @classmethod
    def default_props(cls) -> Dict[str, Any]:
        """Valeurs par défaut de toutes les propriétés (hors label)."""
        return {name: spec.default for name, spec in cls.PROPS.items()}

    def get_prop(self, name: str) -> Any:
        if name == "label":
            return self.label
        return self._props.get(name)

    def set_prop(self, name: str, value: Any) -> None:
        if name == "label":
            new = str(value).strip() or self.label
            _USED_LABELS.discard(self.label)
            self.label = new
            self._props["label"] = new
            reserve_label(new)
            return
        spec = self.PROPS.get(name)
        if spec is None:
            raise KeyError(f"propriété inconnue : {name!r}")
        self._props[name] = spec.coerce(value)

    def props(self) -> "OrderedDict[str, Any]":
        out: "OrderedDict[str, Any]" = OrderedDict()
        out["label"] = self.label
        for k in self.PROPS:
            if k != "label":
                out[k] = self._props.get(k)
        return out

    # -- affichage ---------------------------------------------------------
    def display_value(self) -> str:
        """Valeur principale affichée sous le symbole."""
        return ""

    def short_description(self) -> str:
        return f"{self.kind.label_fr} {self.label}"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class Generator(Component):
    kind = Kind.GENERATOR
    prefix = "G"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        source_type=Prop(SourceType.VOLTAGE.value, ptype="enum",
                         choices=(SourceType.VOLTAGE.value, SourceType.CURRENT.value),
                         group="Génération", tip="Tension (U) ou courant (I) imposé"),
        voltage=Prop(12.0, unit="V", minimum=-1e4, maximum=1e4, step=0.5,
                     group="Génération", tip="Tension continue imposée"),
        current=Prop(1.0, unit="A", minimum=-1e3, maximum=1e3, step=0.1,
                     group="Génération", tip="Courant imposé (mode courant)"),
        ri=Prop(0.1, unit="Ω", minimum=0.0, maximum=1e4, step=0.01,
                group="Génération", tip="Résistance interne (limite les courts-circuits)"),
        p_max=Prop(50.0, unit="W", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites", tip="Puissance maximale délivrable"),
    )

    @property
    def source_type(self) -> SourceType:
        return SourceType(self._props["source_type"])

    @property
    def voltage(self) -> float:
        return float(self._props["voltage"])

    @property
    def current(self) -> float:
        return float(self._props["current"])

    @property
    def ri(self) -> float:
        return float(self._props["ri"])

    def display_value(self) -> str:
        if self.source_type is SourceType.VOLTAGE:
            return si_format(self.voltage, "V")
        return si_format(self.current, "A")


class Battery(Generator):
    """Pile à tension continue, avec des bornes positive et négative."""

    kind = Kind.BATTERY
    prefix = "BAT"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        source_type=Prop(SourceType.VOLTAGE.value, ptype="enum",
                         choices=(SourceType.VOLTAGE.value,), group="Génération"),
        voltage=Prop(9.0, unit="V", minimum=-1e4, maximum=1e4, step=0.5,
                     group="Génération", tip="Tension continue de la pile"),
        ri=Prop(0.1, unit="Ω", minimum=0.0, maximum=1e4, step=0.01,
                group="Génération", tip="Résistance interne"),
        p_max=Prop(20.0, unit="W", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites"),
    )


# ---------------------------------------------------------------------------
# Passifs
# ---------------------------------------------------------------------------

class Resistor(Component):
    kind = Kind.RESISTOR
    prefix = "R"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        resistance=Prop(100.0, unit="Ω", minimum=1e-6, maximum=1e12, step=10.0,
                        group="Valeur", tip="Résistance ohmique"),
        p_max=Prop(1.0, unit="W", minimum=0.0, maximum=1e6, step=0.25,
                   group="Limites"),
    )

    @property
    def resistance(self) -> float:
        return float(self._props["resistance"])

    def display_value(self) -> str:
        return si_format(self.resistance, "Ω")


class CustomComponent(Resistor):
    """Composant personnalisé défini comme une résistance à deux bornes."""

    kind = Kind.CUSTOM
    prefix = "X"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        custom_name=Prop("Composant perso", ptype="str", group="Identité"),
        symbol=Prop("X", ptype="str", group="Aspect"),
        resistance=Prop(100.0, unit="Ω", minimum=1e-6, maximum=1e12,
                        step=10.0, group="Modèle électrique"),
        p_max=Prop(1.0, unit="W", minimum=0.0, maximum=1e6,
                   group="Limites"),
    )

    @property
    def custom_name(self) -> str:
        return str(self._props["custom_name"])

    @property
    def symbol(self) -> str:
        return str(self._props["symbol"])

    def short_description(self) -> str:
        return f"{self.custom_name} {self.label}"


class Potentiometer(Component):
    """Potentiomètre 3 bornes : p–n (rétotal) et w (curseur).

    Utilisable en rhéostat (relier w à n) ou en pont diviseur
    (sortie sur w). Les deux sections p–w et w–n sont modélisées
    comme deux résistances en série partageant le nœud interne w.
    """

    kind = Kind.POTENTIOMETER
    prefix = "P"
    TERMINAL_OFFSETS = {
        "p": (-HALF_LENGTH, 0.0),
        "n": (HALF_LENGTH, 0.0),
        "w": (0.0, HALF_LENGTH),     # curseur sous le corps
    }
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        resistance=Prop(1000.0, unit="Ω", minimum=1.0, maximum=1e7, step=100.0,
                        group="Valeur", tip="Résistance totale (p ↔ n)"),
        level=Prop(0.5, minimum=0.0, maximum=1.0, step=0.01, decimals=3,
                   group="Curseur", tip="Position du curseur 0 → 1"),
        p_max=Prop(1.0, unit="W", minimum=0.0, maximum=1e6, step=0.25,
                   group="Limites"),
    )

    @property
    def resistance(self) -> float:
        return float(self._props["resistance"])

    @property
    def level(self) -> float:
        return float(self._props["level"])

    @property
    def sections(self) -> Tuple[float, float]:
        """(R_p→w, R_w→n) selon la position du curseur."""
        r_tot = max(self.resistance, 1e-3)
        lvl = min(max(self.level, 0.0), 1.0)
        r_pw = lvl * r_tot
        r_wn = (1.0 - lvl) * r_tot
        return max(r_pw, 1e-3), max(r_wn, 1e-3)

    def display_value(self) -> str:
        return f"{si_format(self.resistance, 'Ω')} @ {self.level * 100:.0f} %"


class Switch(Component):
    kind = Kind.SWITCH
    prefix = "K"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        closed=Prop(True, ptype="bool", group="État",
                    tip="État de l'interrupteur (double-clic pour basculer)"),
        r_on=Prop(0.01, unit="Ω", minimum=1e-6, maximum=1.0, step=0.001,
                  group="Contact", tip="Résistance de contact fermé"),
        r_off=Prop(1e6, unit="Ω", minimum=1e3, maximum=1e12, step=1e5,
                   group="Contact", tip="Résistance d'isolement ouvert"),
        p_max=Prop(10.0, unit="W", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites"),
    )

    @property
    def closed(self) -> bool:
        return bool(self._props["closed"])

    @closed.setter
    def closed(self, value: bool) -> None:
        self._props["closed"] = self.PROPS["closed"].coerce(value)

    @property
    def resistance(self) -> float:
        return float(self._props["r_on"] if self.closed else self._props["r_off"])

    def display_value(self) -> str:
        return "Fermé" if self.closed else "Ouvert"


class Capacitor(Component):
    kind = Kind.CAPACITOR
    prefix = "C"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        capacitance=Prop(1e-3, unit="F", minimum=1e-12, maximum=1e3, step=1e-3,
                         group="Valeur", tip="Capacité"),
        v0=Prop(0.0, unit="V", minimum=-1e4, maximum=1e4, step=0.5,
                group="Valeur", tip="Tension initiale (régime transitoire)"),
        p_max=Prop(100.0, unit="W", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites"),
    )

    @property
    def capacitance(self) -> float:
        return float(self._props["capacitance"])

    @property
    def v0(self) -> float:
        return float(self._props["v0"])

    def display_value(self) -> str:
        return si_format(self.capacitance, "F")


class Inductor(Component):
    kind = Kind.INDUCTOR
    prefix = "L"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        inductance=Prop(1e-2, unit="H", minimum=1e-9, maximum=1e3, step=1e-3,
                        group="Valeur", tip="Inductance"),
        r_w=Prop(0.01, unit="Ω", minimum=0.0, maximum=1e3, step=0.01,
                 group="Valeur", tip="Résistance du fil"),
        p_max=Prop(100.0, unit="W", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites"),
    )

    @property
    def inductance(self) -> float:
        return float(self._props["inductance"])

    @property
    def r_w(self) -> float:
        return float(self._props["r_w"])

    def display_value(self) -> str:
        return si_format(self.inductance, "H")


# ---------------------------------------------------------------------------
# Semi-conducteurs (modèle linéaire par morceaux, itéré)
# ---------------------------------------------------------------------------

class Diode(Component):
    """Diode idéale améliorée : chute ``vf`` + ``r_on`` / ``r_off``.

    Le composant alterne entre branchement conducteur et bloqué jusqu'à
    convergence (itérations gérées par le solveur).
    """

    kind = Kind.DIODE
    prefix = "D"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        vf=Prop(0.7, unit="V", minimum=0.0, maximum=5.0, step=0.1,
                group="Jeu", tip="Tension de seuil (0,7 V au silicium)"),
        r_on=Prop(2.0, unit="Ω", minimum=1e-3, maximum=1e3, step=0.5,
                  group="Jeu", tip="Résistance dynamique en conduction"),
        p_max=Prop(1.0, unit="W", minimum=0.0, maximum=1e6, step=0.5,
                   group="Limites"),
    )

    @property
    def vf(self) -> float:
        return float(self._props["vf"])

    @property
    def r_on(self) -> float:
        return float(self._props["r_on"])

    @property
    def on(self) -> bool:
        return bool(self.tstate.get("on", 0))

    def display_value(self) -> str:
        return f"Vf {si_format(self.vf, 'V')}"


class Led(Component):
    """LED : diode à seuil ``vf`` avec couleur et allumage visuel."""

    kind = Kind.LED
    prefix = "LED"
    COLORS = ("rouge", "vert", "jaune", "bleu", "blanc", "orange")
    COLOR_HEX = {
        "rouge": "#ef4444", "vert": "#22c55e", "jaune": "#eab308",
        "bleu": "#3b82f6", "blanc": "#f8fafc", "orange": "#f97316",
    }
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        vf=Prop(2.0, unit="V", minimum=0.0, maximum=6.0, step=0.1,
                group="Jeu", tip="Tension directe (≈ 2 V pour une LED)"),
        r_on=Prop(10.0, unit="Ω", minimum=1e-3, maximum=1e3, step=1.0,
                  group="Jeu", tip="Résistance dynamique en conduction"),
        color=Prop("rouge", ptype="enum", choices=COLORS,
                   group="Aspect", tip="Couleur d'émission"),
        p_max=Prop(0.5, unit="W", minimum=0.0, maximum=1e6, step=0.1,
                   group="Limites"),
    )

    @property
    def vf(self) -> float:
        return float(self._props["vf"])

    @property
    def r_on(self) -> float:
        return float(self._props["r_on"])

    @property
    def color(self) -> str:
        return str(self._props["color"])

    @property
    def color_hex(self) -> str:
        return self.COLOR_HEX.get(self.color, "#ef4444")

    @property
    def on(self) -> bool:
        return bool(self.tstate.get("on", 0))

    def display_value(self) -> str:
        return f"{self.color} {si_format(self.vf, 'V')}"


# ---------------------------------------------------------------------------
# Énergie / actionneurs
# ---------------------------------------------------------------------------

class Lamp(Component):
    """Lampe : résistance ohmique avec rendement lumineux visuel."""

    kind = Kind.LAMP
    prefix = "H"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        resistance=Prop(50.0, unit="Ω", minimum=0.1, maximum=1e6, step=5.0,
                        group="Valeur", tip="Résistance à froid / chauffée"),
        u_rated=Prop(12.0, unit="V", minimum=1.0, maximum=400.0, step=1.0,
                     group="Valeur", tip="Tension nominale (glow = P/Pmax)"),
        p_max=Prop(10.0, unit="W", minimum=0.1, maximum=1e6, step=1.0,
                   group="Valeur", tip="Puissance nominale"),
    )

    @property
    def resistance(self) -> float:
        return float(self._props["resistance"])

    @property
    def u_rated(self) -> float:
        return float(self._props["u_rated"])

    def display_value(self) -> str:
        return si_format(self.resistance, "Ω")


class Motor(Component):
    """Moteur continu à aimants permanents (modèle électromécanique linéaire).

    ``U = r_m·I + ke·ω``  et  ``kt·I = tc + b·ω``
    => branche assimilée à une conductance ``g`` + courant parasite :

        I = g·U + ih,   g = 1/(r_m + ke·kt/b),  ih = g·ke·tc/b

    Rendu mécanique affiché : ``ω = (kt·I − tc)/b`` (tr/min).
    """

    kind = Kind.MOTOR
    prefix = "M"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        r_m=Prop(2.0, unit="Ω", minimum=1e-3, maximum=1e4, step=0.5,
                 group="Électrique", tip="Résistance de l'enroulement"),
        ke=Prop(0.04, unit="V.s/rad", minimum=0.0, maximum=10.0, step=0.005,
                group="Électrique", tip="Constante de force contre-électromotrice"),
        kt=Prop(0.04, unit="N.m/A", minimum=0.0, maximum=10.0, step=0.005,
                group="Mécanique", tip="Constante de couple"),
        tc=Prop(0.01, unit="N.m", minimum=0.0, maximum=100.0, step=0.005,
                group="Mécanique", tip="Couple résistant (charge)"),
        b=Prop(0.0002, unit="N.m.s/rad", minimum=1e-6, maximum=1.0, step=1e-4,
               group="Mécanique", tip="Frottement visqueux"),
        p_max=Prop(50.0, unit="W", minimum=0.0, maximum=1e6, step=5.0,
                   group="Limites"),
    )

    @property
    def r_m(self) -> float:
        return float(self._props["r_m"])

    @property
    def ke(self) -> float:
        return float(self._props["ke"])

    @property
    def kt(self) -> float:
        return float(self._props["kt"])

    @property
    def tc(self) -> float:
        return float(self._props["tc"])

    @property
    def b(self) -> float:
        return max(float(self._props["b"]), 1e-9)

    @property
    def g_eq(self) -> float:
        """Conductance équivalente de la branche moteur."""
        return 1.0 / (max(self.r_m, 1e-6) + (self.ke * self.kt) / self.b)

    @property
    def i_offset(self) -> float:
        """Courant parasite ``ih`` (couple résistant)."""
        return self.g_eq * (self.ke * self.tc) / self.b

    def omega(self, i: float) -> float:
        """Vitesse angulaire (rad/s) pour un courant donné."""
        return (self.kt * i - self.tc) / self.b

    def rpm(self, i: float) -> float:
        """Vitesse en tours par minute (0 si le moteur est bloqué)."""
        return max(0.0, self.omega(i)) * 60.0 / (2.0 * math.pi)

    def display_value(self) -> str:
        return si_format(self.r_m, "Ω")


class Fuse(Component):
    """Fusible : se déclenche (et devient ouvert) si |I| > ``i_rated``.

    Réarmement : cocher/décocher la propriété ``blown`` (= « grillé »)
    dans le panneau propriétés ou via un scénario.
    """

    kind = Kind.FUSE
    prefix = "F"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        i_rated=Prop(5.0, unit="A", minimum=0.01, maximum=1e4, step=0.5,
                     group="Protection", tip="Courant nominal de déclenchement"),
        r_closed=Prop(0.01, unit="Ω", minimum=1e-6, maximum=10.0, step=0.01,
                      group="Protection", tip="Résistance à l'état intact"),
        blown=Prop(False, ptype="bool", group="État",
                   tip="Grillé = ouvert ; décocher pour réarmer"),
        p_max=Prop(5.0, unit="W", minimum=0.0, maximum=1e6, step=1.0,
                   group="Limites"),
    )

    @property
    def i_rated(self) -> float:
        return float(self._props["i_rated"])

    @i_rated.setter
    def i_rated(self, value: float) -> None:
        self._props["i_rated"] = self.PROPS["i_rated"].coerce(value)

    @property
    def blown(self) -> bool:
        return bool(self._props["blown"])

    @blown.setter
    def blown(self, value: bool) -> None:
        self._props["blown"] = self.PROPS["blown"].coerce(value)

    @property
    def resistance(self) -> float:
        if self.blown:
            return 1e9
        return max(float(self._props["r_closed"]), 1e-6)

    def display_value(self) -> str:
        if self.blown:
            return "Grillé"
        return f"{si_format(self.i_rated, 'A')}"


# ---------------------------------------------------------------------------
# Instruments de mesure
# ---------------------------------------------------------------------------

class Voltmeter(Component):
    """Voltmètre : se branche en parallèle, mesure ``U`` (résistance ∞)."""

    kind = Kind.VOLTMETER
    prefix = "V"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        r_int=Prop(1e6, unit="Ω", minimum=1e3, maximum=1e12, step=1e5,
                   group="Instrument", tip="Résistance interne du voltmètre"),
    )

    @property
    def r_int(self) -> float:
        return float(self._props["r_int"])

    def display_value(self) -> str:
        return ""   # valeur mesurée affichée par le solveur


class Ammeter(Component):
    """Ampèremètre : se branche en série, mesure ``I`` (shunt ≈ 0 Ω)."""

    kind = Kind.AMMETER
    prefix = "A"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        r_sh=Prop(1e-3, unit="Ω", minimum=0.0, maximum=1.0, step=1e-4,
                  group="Instrument", tip="Résistance de shunt de l'ampèremètre"),
    )

    @property
    def r_sh(self) -> float:
        return float(self._props["r_sh"])

    def display_value(self) -> str:
        return ""


class Ohmmeter(Component):
    """Ohmmètre : injecte un courant de test ``i_test`` et lit ``U/|I|``.

    Principe réel d'un ohmmètre : le courant injecté traverse
    l'appareil de mesure connecté ; ``R = U/|I|``. Un circuit ouvert
    affiche « ∞ ». Le circuit doit être **débranché** (générateur éteint)
    pour une lecture fidèle.
    """

    kind = Kind.OHMMETER
    prefix = "OH"
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
        i_test=Prop(1e-4, unit="A", minimum=1e-6, maximum=1.0, step=1e-4,
                    group="Instrument", tip="Courant de test injecté"),
        r_int=Prop(1e5, unit="Ω", minimum=1e3, maximum=1e9, step=1e4,
                   group="Instrument", tip="Résistance interne (borne d'entrée)"),
    )

    @property
    def i_test(self) -> float:
        return float(self._props["i_test"])

    @property
    def r_int(self) -> float:
        return float(self._props["r_int"])

    def measured_r(self, u: float, i: float) -> Optional[float]:
        """Résistance mesurée ; ``None`` = boucle ouverte (∞)."""
        if abs(i) < 1e-15:
            return None
        r = abs(u / i)
        if r >= 0.95 * self.r_int:
            return None
        return r

    def display_value(self) -> str:
        return ""


# ---------------------------------------------------------------------------
# Topologie
# ---------------------------------------------------------------------------

class Ground(Component):
    """Masse : point de référence 0 V. Fusionne électriquement toutes
    les masses entre elles et désigne le nœud de référence du solveur.

    Composant à **une seule borne** (pas de branche de courant).
    """

    kind = Kind.GROUND
    prefix = "PE"
    is_branch = False
    TERMINAL_OFFSETS = {"p": (0.0, -HALF_LENGTH)}     # borne au-dessus
    PROPS = OrderedDict(
        label=Prop("", ptype="str", group="Identité"),
    )

    def display_value(self) -> str:
        return "0 V"


# ---------------------------------------------------------------------------
# Usine & sérialisation
# ---------------------------------------------------------------------------

_KIND_TABLE = {
    Kind.GENERATOR: Generator,
    Kind.BATTERY: Battery,
    Kind.RESISTOR: Resistor,
    Kind.CUSTOM: CustomComponent,
    Kind.POTENTIOMETER: Potentiometer,
    Kind.SWITCH: Switch,
    Kind.CAPACITOR: Capacitor,
    Kind.INDUCTOR: Inductor,
    Kind.DIODE: Diode,
    Kind.LED: Led,
    Kind.LAMP: Lamp,
    Kind.MOTOR: Motor,
    Kind.FUSE: Fuse,
    Kind.VOLTMETER: Voltmeter,
    Kind.AMMETER: Ammeter,
    Kind.OHMMETER: Ohmmeter,
    Kind.GROUND: Ground,
}


def create_component(kind: Kind, x: float, y: float, rotation: int = 0,
                     label: Optional[str] = None, **props: Any) -> Component:
    """Fabrique un composant du type ``kind`` (usine unique du projet)."""
    cls = _KIND_TABLE[Kind(kind)]
    return cls(x, y, rotation=rotation, label=label, **props)


def component_from_dict(data: Dict[str, Any]) -> Component:
    """Reconstruit un composant depuis sa sérialisation JSON."""
    kind = Kind(data["kind"])
    comp = create_component(
        kind,
        data.get("x", 0),
        data.get("y", 0),
        rotation=data.get("rotation", 0),
        label=data.get("label"),
    )
    for k, v in (data.get("props") or {}).items():
        try:
            if k in comp.PROPS or k == "label":
                comp.set_prop(k, v)
        except (ValueError, KeyError):
            continue  # valeur corrompue -> défaut conservé
    comp.node_of = {name: None for name in comp.TERMINAL_OFFSETS}
    return comp


def component_to_dict(comp: Component) -> Dict[str, Any]:
    return {
        "kind": comp.kind.value,
        "label": comp.label,
        "x": comp.x,
        "y": comp.y,
        "rotation": comp.rotation,
        "props": {k: v for k, v in comp.props().items() if k != "label"},
    }


# ---------------------------------------------------------------------------
# Fil de connexion
# ---------------------------------------------------------------------------

class Wire:
    """Polygone de connexion : tous ses points forment un même nœud."""

    def __init__(self, points: List[Tuple[float, float]], label: Optional[str] = None):
        self.label = label or _next_label("W")
        self.points = points

    @property
    def points(self) -> List[Tuple[int, int]]:
        return self._points

    @points.setter
    def points(self, points: List[Tuple[float, float]]) -> None:
        snapped = [snap_point(px, py) for px, py in points]
        normalized = [snapped[0]] if snapped else []
        for point in snapped[1:]:
            previous = normalized[-1]
            if previous[0] != point[0] and previous[1] != point[1]:
                normalized.append((point[0], previous[1]))
            if normalized[-1] != point:
                normalized.append(point)
        self._points = self._simplify(normalized)

    @staticmethod
    def _simplify(points: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        compact: List[Tuple[int, int]] = []
        for point in points:
            if compact and point == compact[-1]:
                continue
            compact.append(point)
        return compact

    @property
    def id(self) -> str:
        return self.label

    def endpoints(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return self.points[0], self.points[-1]

    @staticmethod
    def to_dict(wire: "Wire") -> Dict[str, Any]:
        return {"label": wire.label, "points": [list(p) for p in wire.points]}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Wire":
        w = Wire([tuple(p) for p in data["points"]], label=data.get("label"))
        reserve_label(w.label)
        return w
