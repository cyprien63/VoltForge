"""VoltForge — cœur métier (modèle, topologie, solveur, scénarios).

Aucun import Qt : ce paquet est testable en headless via
``python -m core``.
"""

from .circuit import Circuit, CircuitNode
from .components import (
    GRID_SIZE,
    Ammeter,
    Capacitor,
    Buzzer,
    Component,
    Diode,
    Fuse,
    Generator,
    Ground,
    Heater,
    Inductor,
    Kind,
    Lamp,
    Led,
    Motor,
    Ohmmeter,
    Photoresistor,
    Potentiometer,
    PushButton,
    Resistor,
    Speaker,
    SourceType,
    Switch,
    Thermistor,
    Terminal,
    Voltmeter,
    Wire,
    create_component,
    snap,
)
from .scenario import (
    ScenarioError,
    ScenarioEvent,
    ScenarioProgram,
    parse_scenario,
)
from .simulation import SimulationEngine
from .solver import BranchResult, Solution, Solver
from .voltage_arrow import VoltageArrow

__all__ = [
    "Circuit", "CircuitNode", "Component", "Kind", "SourceType", "Terminal",
    "Wire", "create_component", "snap", "GRID_SIZE",
    "Generator", "Resistor", "Thermistor", "Photoresistor", "Heater",
    "Speaker", "Buzzer", "Potentiometer", "Switch", "PushButton", "Capacitor",
    "Inductor", "Diode", "Led", "Lamp", "Motor", "Fuse",
    "Voltmeter", "Ammeter", "Ohmmeter", "Ground",
    "Solver", "Solution", "BranchResult",
    "ScenarioProgram", "ScenarioEvent", "ScenarioError", "parse_scenario",
    "SimulationEngine", "VoltageArrow",
]
