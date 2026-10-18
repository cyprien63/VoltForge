"""VoltForge — auto-tests du cœur métier (headless).

Exécution :  ``python -m core``

Vérifie la topologie (nœuds, jonctions, masses), le solveur MNA (régimes
permanent et transitoire, diodes/LED, moteur, fusible, instruments) et les
sessions de simulation interactives. Aucun prérequis graphique.
"""

from __future__ import annotations

import math
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .circuit import Circuit
from .components import (
    Component,
    Kind,
    create_component,
    reset_labels,
)
from .formatting import parse_time, parse_value, si_format
from .simulation import SimulationEngine
from .solver import Solution, Solver

# ---------------------------------------------------------------------------
# Mini framework de test
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL: List[str] = []


def check(name: str, got, expected, tol: float = 1e-9) -> None:
    global _PASS
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        ok = abs(float(got) - float(expected)) <= tol
    elif isinstance(expected, bool):
        ok = bool(got) is expected
    else:
        ok = got == expected
    if ok:
        _PASS += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        _FAIL.append(name)
        print(f"  \033[31m✗\033[0m {name}  (obtenu {got!r}, attendu {expected!r} ± {tol})")


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ---------------------------------------------------------------------------
# Aides de construction
# ---------------------------------------------------------------------------
# Disposition type « série » :  G1 en bas à gauche, les composants
# alignés en haut, retour par le bas. La borne p du premier composant
# rejoint la borne p du générateur -> U et I positifs dans le sens p→n.
#
#     (80,100) ──[ D1 ]──[ D2 ]── ...
#        │                          │
#     ┌──┴──┐                       │
#     │ G1  │                       │
#     └──┬──┘ (120,300) ────────────┘
# ---------------------------------------------------------------------------

Device = Tuple[Kind, Dict[str, Any], int]


def gen(circuit: Circuit, x: float, y: float, voltage: float = 12.0,
        ri: float = 0.0, source_type: str = "voltage",
        current: float = 1.0) -> Component:
    return circuit.add(create_component(
        Kind.GENERATOR, x, y, voltage=voltage, ri=ri,
        source_type=source_type, current=current))


def comp(circuit: Circuit, kind: Kind, x: float, y: float, rot: int = 0,
         label: Optional[str] = None, **props: Any) -> Component:
    return circuit.add(create_component(kind, x, y, rotation=rot,
                                        label=label, **props))


def wire(circuit: Circuit, *points: Sequence[float]) -> None:
    circuit.add_wire([tuple(p) for p in points])


def build_series(circuit: Circuit, voltage: float = 12.0, ri: float = 0.0,
                 devices: Optional[Sequence[Device]] = None,
                 source_type: str = "voltage", current: float = 1.0,
                 ) -> Tuple[Component, List[Component]]:
    """Construit ``G1 -- devices en série -- masse`` et retourne les pièces."""
    g = gen(circuit, 100, 300, voltage=voltage, ri=ri,
            source_type=source_type, current=current)
    devices = list(devices or [(Kind.RESISTOR, {"resistance": 100.0}, 0)])
    placed: List[Component] = []
    x = 300.0
    for kind, props, rot in devices:
        placed.append(comp(circuit, kind, x, 100, rot=rot, **props))
        x += 200.0
    p0 = placed[0].terminal_positions()["p"]
    wire(circuit, (80, 300), (80, 100), p0)
    for a, b in zip(placed, placed[1:]):
        wire(circuit, a.terminal_positions()["n"], b.terminal_positions()["p"])
    pn = placed[-1].terminal_positions()["n"]
    wire(circuit, pn, (pn[0], 300), (120, 300))
    return g, placed


def solve(circuit: Circuit) -> Solution:
    return Solver(circuit).solve()


# ---------------------------------------------------------------------------
# Topologie
# ---------------------------------------------------------------------------

def test_topology() -> None:
    section("Topologie — nœuds, jonctions, masses")
    reset_labels()

    c = Circuit()
    g, (r,) = build_series(c, voltage=10.0, devices=[(Kind.RESISTOR, {"resistance": 100.0}, 0)])
    check("masse = nœud du générateur (n)", c.ground_id, g.node_n)
    check("R1.n relié à G1.n (retour)", r.node_n, g.node_n)
    check("simple coude => aucune jonction", len(c.junction_points()), 0)
    check("mesh_count = 1 (maille série)", c.mesh_count(), 1)

    # Jonction en T : le fil A passe par la borne R1.p et continue
    c2 = Circuit()
    gen(c2, 100, 100, voltage=10.0)
    r1 = comp(c2, Kind.RESISTOR, 300, 100, resistance=100.0)
    comp(c2, Kind.RESISTOR, 300, 300, resistance=100.0)
    wire(c2, (120, 100), (280, 100), (280, 300))
    wire(c2, (320, 100), (320, 300), (120, 300), (80, 300), (80, 100))
    check("jonction T détectée (3 segments)", len(c2.junction_points()) >= 1, True)
    check("jonction située sur R1.p",
          (int(r1.terminal_positions()["p"][0]), int(r1.terminal_positions()["p"][1]))
          in c2.junction_points(), True)

    # Fusion des masses : deux moitiés isolées + 2 masses -> 1 nœud commun
    c3 = Circuit()
    comp(c3, Kind.RESISTOR, 100, 100, resistance=10.0)
    comp(c3, Kind.RESISTOR, 500, 100, resistance=10.0)
    pe1 = comp(c3, Kind.GROUND, 100, 220)
    pe2 = comp(c3, Kind.GROUND, 500, 220)
    wire(c3, (80, 100), (80, 200), (100, 200))
    wire(c3, (480, 100), (480, 200), (500, 200))
    check("terres fusionnées", pe1.node_p, pe2.node_p)
    check("masse de référence = masse explicite", c3.ground_id, pe1.node_p)
    check("mesh_count = 0 (circuit ouvert)", c3.mesh_count(), 0)


# ---------------------------------------------------------------------------
# Régime permanent (DC)
# ---------------------------------------------------------------------------

def test_dc_basic() -> None:
    section("Régime permanent — loi d'Ohm, diviseur, source de courant, interrupteur")
    reset_labels()

    c = Circuit()
    g, (r,) = build_series(c, voltage=10.0,
                           devices=[(Kind.RESISTOR, {"resistance": 100.0}, 0)])
    s = solve(c)
    check("série : I = 0,1 A", s.branch(r.label).i, 0.1, 1e-9)
    check("série : U(R1) = 10 V", s.branch(r.label).u, 10.0, 1e-9)
    check("série : P(R1) = 1 W", s.branch(r.label).p, 1.0, 1e-9)
    check("générateur délivre (P < 0)", s.branch(g.label).p < 0, True)
    check("générateur : sourcing", s.branch(g.label).sourcing, True)
    check("U(G1) = 10 V", s.branch(g.label).u, 10.0, 1e-9)
    check("aucune erreur", len(s.errors), 0)

    # Diviseur de tension : R1 = R2 = 1 kΩ -> 6 V
    c = Circuit()
    _, (r1, r2) = build_series(c, voltage=12.0, devices=[
        (Kind.RESISTOR, {"resistance": 1000.0}, 0),
        (Kind.RESISTOR, {"resistance": 1000.0}, 0)])
    s2 = solve(c)
    check("diviseur : U(R2) = 6 V", s2.branch(r2.label).u, 6.0, 1e-3)
    check("diviseur : I = 6 mA", s2.branch(r2.label).i, 6e-3, 1e-6)
    check("diviseur : U(R1) = 6 V", s2.branch(r1.label).u, 6.0, 1e-3)
    check("diviseur : U(R1)+U(R2) = 12 V",
          s2.branch(r1.label).u + s2.branch(r2.label).u, 12.0, 1e-4)

    # Source de courant idéale : I = 2 A dans 10 Ω -> 20 V
    c = Circuit()
    _, (r,) = build_series(c, source_type="current", current=2.0, ri=0.0,
                           devices=[(Kind.RESISTOR, {
                               "resistance": 10.0, "p_max": 100.0,
                           }, 0)])
    s3 = solve(c)
    check("source courant : U(R1) = 20 V", s3.branch(r.label).u, 20.0, 1e-6)
    check("source courant : I = 2 A", abs(s3.branch(r.label).i), 2.0, 1e-6)

    # Interrupteur ouvert / fermé
    c = Circuit()
    _, (k, r) = build_series(c, voltage=12.0, devices=[
        (Kind.SWITCH, {"closed": True}, 0),
        (Kind.RESISTOR, {"resistance": 100.0, "p_max": 100.0}, 0)])
    s4 = solve(c)
    check("interrupteur fermé : I ≈ 0,12 A", s4.branch(r.label).i, 0.12, 1e-4)
    k.closed = False
    s5 = solve(c)
    check("interrupteur ouvert : I ≈ 0", s5.branch(r.label).i, 12.0 / (100 + 1e6), 1e-6)
    check("interrupteur ouvert : état OK", s5.branch(k.label).ok, True)


def test_semiconductors() -> None:
    section("Semi-conducteurs — diode & LED")
    reset_labels()

    # Diode passante : I = (5 − 0,7)/102
    c = Circuit()
    _, (r, d) = build_series(c, voltage=5.0, devices=[
        (Kind.RESISTOR, {"resistance": 100.0}, 0),
        (Kind.DIODE, {"vf": 0.7, "r_on": 2.0}, 0)])
    s = solve(c)
    check("diode passante : I = 42,2 mA", s.branch(d.label).i, 4.3 / 102, 2e-4)
    check("diode passante : U ≈ 0,78 V", s.branch(d.label).u,
          0.7 + 2.0 * 4.3 / 102, 1e-3)
    check("diode : état conducteur", d.tstate.get("on"), 1)

    # Diode bloquée : le courant entre par la cathode (n) -> montage manuel
    c = Circuit()
    _, (r,) = build_series(c, voltage=5.0, devices=[(Kind.RESISTOR, {"resistance": 100.0}, 0)])
    c.remove(d.label)
    d = comp(c, Kind.DIODE, 500, 100, vf=0.7, r_on=2.0)
    wire(c, (320, 100), (320, 60), (520, 60), (520, 100))   # R.n -> D.n (bloquant)
    wire(c, (480, 100), (480, 300), (120, 300))             # D.p -> masse
    s2 = solve(c)
    check("diode bloquée : I ≈ 0", abs(s2.branch(d.label).i) < 1e-5, True)
    check("diode bloquée : état bloqué", d.tstate.get("on", 0), 0)

    # LED : I = (5 − 2)/230
    c = Circuit()
    _, (r, led) = build_series(c, voltage=5.0, devices=[
        (Kind.RESISTOR, {"resistance": 220.0}, 0),
        (Kind.LED, {"vf": 2.0, "r_on": 10.0, "color": "vert"}, 0)])
    s3 = solve(c)
    check("LED : I = 13 mA", s3.branch(led.label).i, 3.0 / 230, 1e-4)
    check("LED : allumée (on)", led.tstate.get("on"), 1)
    check("LED : couleur hex", led.color_hex, "#22c55e")


def test_transient() -> None:
    section("Transitoire — charge RC (τ = 1 s) et montée RL")
    reset_labels()

    # Condensateur : ouvert en DC, charge exponentielle en transitoire
    c = Circuit()
    _, (r, cap) = build_series(c, voltage=12.0, devices=[
        (Kind.RESISTOR, {"resistance": 1000.0}, 0),
        (Kind.CAPACITOR, {"capacitance": 1e-3, "v0": 0.0}, 0)])
    dc = solve(c)
    check("DC : condensateur ouvert -> U(C) = 12 V", dc.branch(cap.label).u, 12.0, 1e-3)

    solver = Solver(c)
    solver.reset_transient()
    dt = 5e-3
    sol = solver.solve(dt=dt, t=0.0)
    for k in range(1, 139):          # ~0,694 s ≈ τ·ln2
        sol = solver.solve(dt=dt, t=k * dt)
    expected = 12.0 * (1.0 - math.exp(-0.694 / 1.0))
    check("RC : U(C) ≈ 6 V à t = τ·ln2", sol.branch(cap.label).u, expected, 0.12)
    check("RC : état interne cohérent", cap.tstate.get("v"),
          sol.branch(cap.label).u, 1e-12)

    # Bobine : courant qui tend vers U/R (τ = L/R)
    c2 = Circuit()
    _, (r2, l) = build_series(c2, voltage=5.0, devices=[
        (Kind.RESISTOR, {"resistance": 100.0}, 0),
        (Kind.INDUCTOR, {"inductance": 1.0, "r_w": 0.0}, 0)])
    solver2 = Solver(c2)
    solver2.reset_transient()
    sol2 = sol2 = None
    for k in range(0, 500):
        sol2 = solver2.solve(dt=1e-3, t=k * 1e-3)
    check("RL : I ≈ U/R à l'équilibre (50 mA)",
          sol2.branch(l.label).i, 0.05, 2e-3)


def test_machines_instruments() -> None:
    section("Moteur, fusible, potentiomètre, instruments, masse")
    reset_labels()

    # Moteur CC : I ≈ 1,4 A -> ≈ 2197 tr/min
    c = Circuit()
    _, (m,) = build_series(c, voltage=12.0, devices=[(Kind.MOTOR, {}, 0)])
    s = solve(c)
    check("moteur : I ≈ 1,4 A", s.branch(m.label).i, 1.4, 0.02)
    check("moteur : U = 12 V", s.branch(m.label).u, 12.0, 1e-6)
    check("moteur : vitesse ≈ 2197 tr/min", s.branch(m.label).reading, 2197, 25)
    check("moteur : dissipation > 0", s.branch(m.label).p > 0, True)

    # Fusible qui grille : 12 V / 10 Ω = 1,2 A > 0,5 A
    c = Circuit()
    _, (f, r) = build_series(c, voltage=12.0, devices=[
        (Kind.FUSE, {"i_rated": 0.5, "r_closed": 0.01}, 0),
        (Kind.RESISTOR, {"resistance": 10.0, "p_max": 100.0}, 0)])
    s2 = solve(c)
    check("fusible : grillé", f.blown, True)
    check("fusible : état blown", s2.branch(f.label).state, "blown")
    check("fusible ouvert : I ≈ 0", abs(s2.branch(r.label).i) < 1e-5, True)
    f.blown = False                    # réarmement
    f.i_rated = 5.0
    s4 = solve(c)
    check("fusible 5 A : tient (I = 1,2 A)", f.blown, False)
    check("fusible 5 A : I = 12/(10+0,01)", s4.branch(r.label).i, 12.0 / 10.01, 1e-4)

    # Potentiomètre diviseur : 12 V, curseur à 50 % -> 6 V
    c = Circuit()
    _, (pot,) = build_series(c, voltage=12.0, devices=[
        (Kind.POTENTIOMETER, {"resistance": 1000.0, "level": 0.5}, 0)])
    s5 = solve(c)
    check("potentiomètre : V(curseur) = 6 V",
          s5.node_voltage(pot.node_of["w"]), 6.0, 0.02)
    check("potentiomètre : I entrant = 12 mA", s5.branch(pot.label).i, 12e-3, 1e-4)

    # Ampèremètre en série + voltmètre en parallèle (au-dessus) de R1
    c = Circuit()
    _, (a, r1) = build_series(c, voltage=10.0, devices=[
        (Kind.AMMETER, {}, 0),
        (Kind.RESISTOR, {"resistance": 100.0, "p_max": 100.0}, 0)])
    v = comp(c, Kind.VOLTMETER, 500, 20, rot=270)   # p=(500,40) n=(500,0)
    wire(c, (480, 100), (480, 40), (500, 40))       # R1.p -> V.p
    wire(c, (520, 100), (520, 0), (500, 0))         # R1.n -> V.n
    s6 = solve(c)
    check("ampèremètre : lecture = 0,1 A", s6.branch(a.label).reading, 0.1, 1e-5)
    check("voltmètre : lecture ≈ 10 V", s6.branch(v.label).reading, 10.0, 0.02)

    # Ohmmètre : mesure d'une résistance de 100 Ω (circuit hors tension)
    c = Circuit()
    oh = comp(c, Kind.OHMMETER, 300, 100, i_test=1e-4, r_int=1e5)
    comp(c, Kind.RESISTOR, 300, 220, resistance=100.0)
    wire(c, (280, 100), (280, 220))
    wire(c, (320, 100), (320, 220))
    s7 = solve(c)
    check("ohmmètre : R ≈ 100 Ω", s7.branch(oh.label).reading, 100.0, 1.0)

    # Ohmmètre sur circuit ouvert -> ∞ (None)
    c = Circuit()
    oh = comp(c, Kind.OHMMETER, 300, 100, i_test=1e-4, r_int=1e5)
    s8 = solve(c)
    check("ohmmètre : ∞ si boucle ouverte", s8.branch(oh.label).reading, None)

    # Masse explicite comme référence
    c = Circuit()
    g = gen(c, 100, 300, voltage=10.0)
    r = comp(c, Kind.RESISTOR, 300, 100, resistance=100.0)
    gnd = comp(c, Kind.GROUND, 320, 320)            # borne en (320, 300)
    wire(c, (80, 300), (80, 100), (280, 100))       # G.p -> R.p
    wire(c, (320, 100), (320, 300), (120, 300))     # R.n -> [masse] -> G.n
    s9 = solve(c)
    check("masse explicite : nœud de R1.n = 0 V", s9.node_voltage(r.node_n), 0.0, 1e-9)
    check("masse : référence = masse posée", c.ground_id, gnd.node_p)
    check("masse : U(R1) = 10 V", s9.branch(r.label).u, 10.0, 1e-3)
    check("masse : jonction à la masse",
          (320, 300) in c.junction_points(), True)


def test_states() -> None:
    section("États dynamiques — court-circuit, puissance, non connecté")
    reset_labels()

    c = Circuit()
    g, (r,) = build_series(c, voltage=12.0, devices=[
        (Kind.RESISTOR, {"resistance": 1e-3, "p_max": 1e6}, 0)])
    g.set_prop("p_max", 1e6)
    s = solve(c)
    check("court-circuit détecté", s.branch(r.label).state, "fault")
    check("court-circuit : avertissement global",
          any("Court-circuit" in w for w in s.warnings), True)

    c = Circuit()
    _, (r,) = build_series(c, voltage=12.0, devices=[
        (Kind.RESISTOR, {"resistance": 10.0, "p_max": 1.0}, 0)])
    s2 = solve(c)
    check("dépassement de puissance : composant grillé",
          s2.branch(r.label).state, "blown")

    # Terminal non connecté : un seul fil relie G1.n à R1.p
    c = Circuit()
    gen(c, 100, 100, voltage=12.0)
    r = comp(c, Kind.RESISTOR, 300, 100, resistance=100.0)
    wire(c, (120, 100), (280, 100))
    s3 = solve(c)
    check("composant non connecté", s3.branch(r.label).state, "disconnected")

    c = Circuit()
    comp(c, Kind.RESISTOR, 100, 100, resistance=10.0)
    comp(c, Kind.RESISTOR, 300, 100, resistance=10.0)
    wire(c, (120, 100), (280, 100))
    s4 = solve(c)
    check("avertissement générateur manquant",
          any("générateur" in w for w in s4.warnings), True)


# ---------------------------------------------------------------------------
# Sessions de lecture
# ---------------------------------------------------------------------------

def test_play_session() -> None:
    section("Sessions de lecture — temps réel, interactions, bouclage")
    reset_labels()

    # Charge RC pilotée par la session (durée finie, sans boucle)
    c = Circuit()
    _, (r, cap) = build_series(c, voltage=12.0, devices=[
        (Kind.RESISTOR, {"resistance": 100.0, "p_max": 50.0}, 0),
        (Kind.CAPACITOR, {"capacitance": 1e-3, "v0": 0.0}, 0)])
    engine = SimulationEngine(c)
    engine.start_play(duration=0.4, loop=False)
    check("session : lecture en cours", engine.playing, True)
    samples = [engine.solution.branch(cap.label).u]
    while engine.playing:
        engine.advance(0.02)
        samples.append(engine.solution.branch(cap.label).u)
    check("session : durée épuisée -> arrêt", engine.playing, False)
    check("session : charge monotone",
          all(b >= a - 1e-9 for a, b in zip(samples, samples[1:])), True)
    expected = 12.0 * (1.0 - math.exp(-0.4 / (100.0 * 1e-3)))
    check("session : U(C) finale ≈ modèle analytique",
          samples[-1], expected, 0.3)
    check("session : horloge conservée à l'arrêt", engine.t, 0.4, 1e-6)

    # Bouclage : la session repart de t = 0 sans s'arrêter
    engine.start_play(duration=0.1, loop=True)
    engine.advance(0.25)
    check("bouclage : toujours en lecture", engine.playing, True)
    check("bouclage : horloge repliée après deux tours", engine.t, 0.05, 1e-6)

    # Pause / reprise
    engine.pause_play()
    engine.advance(0.5)
    check("pause : l'horloge ne bouge pas", engine.t, 0.05, 1e-12)
    engine.resume_play()
    engine.advance(0.02)
    check("reprise : l'horloge reprend", engine.t, 0.07, 1e-6)
    engine.stop_play()
    check("arrêt explicite : horloge remise à zéro", engine.t, 0.0, 1e-12)

    # Interaction pendant la lecture : bascule d'un interrupteur
    c2 = Circuit()
    g2, (k2, r2) = build_series(c2, voltage=12.0, devices=[
        (Kind.SWITCH, {"closed": False, "p_max": 50.0}, 0),
        (Kind.RESISTOR, {"resistance": 100.0, "p_max": 50.0}, 0)])
    engine2 = SimulationEngine(c2)
    engine2.start_play(duration=5.0)
    engine2.advance(0.5)
    check("interaction : circuit ouvert avant",
          abs(engine2.solution.branch(r2.label).i) < 1e-3, True)
    k2.set_prop("closed", True)
    engine2.recompute()
    check("interaction : courant immédiat après bascule",
          engine2.solution.branch(r2.label).i, 0.12, 1e-3)
    check("interaction : session préservée", engine2.playing, True)
    check("interaction : recompute n'avance pas l'horloge",
          engine2.t, 0.5, 1e-12)

    # Réglage fait en cours de lecture : conservé après l'arrêt
    g2.set_prop("voltage", 24.0)
    engine2.recompute()
    engine2.stop_play()
    check("arrêt : session terminée", engine2.playing, False)
    check("arrêt : tension modifiée conservée", g2.voltage, 24.0, 1e-12)
    check("arrêt : solution DC à jour",
          engine2.solution.branch(r2.label).i, 0.24, 1e-3)

    # Surcharge pendant la lecture : le composant reste grillé
    c3 = Circuit()
    g3, (r3,) = build_series(c3, voltage=9.0, devices=[
        (Kind.RESISTOR, {"resistance": 10.0, "p_max": 1.0}, 0)])
    engine3 = SimulationEngine(c3)
    engine3.start_play(duration=0.1, loop=False)
    g3.set_prop("voltage", 220.0)
    engine3.recompute()
    check("surcharge : grillé pendant la lecture", r3.get_prop("blown"), True)
    engine3.advance(0.1)
    engine3.stop_play()
    check("surcharge : toujours grillé après l'arrêt",
          r3.get_prop("blown"), True)
    check("surcharge : tension élevée conservée", g3.voltage, 220.0, 1e-12)


def test_formatting() -> None:
    section("Formatage & analyse des valeurs")
    check("parse_value 4.7k", parse_value("4.7k"), 4700.0)
    check("parse_value 4,7k (virgule)", parse_value("4,7k"), 4700.0)
    check("parse_value 12V", parse_value("12V"), 12.0)
    check("parse_value 1mA", parse_value("1mA"), 1e-3)
    check("parse_value 2M", parse_value("2M"), 2e6)
    check("parse_value 470 ohm", parse_value("470 ohm"), 470.0)
    check("parse_time 500ms", parse_time("500ms"), 0.5)
    check("parse_time 1.5s", parse_time("1.5s"), 1.5)
    check("parse_time 2", parse_time("2"), 2.0)
    check("si_format 4700 Ω", si_format(4700.0, "Ω"), "4.7 kΩ")
    check("si_format 0.1 A", si_format(0.1, "A"), "100 mA")
    check("si_format 0", si_format(0.0, "V"), "0 V")


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------

def main() -> int:
    print("\033[1mVoltForge — auto-tests du cœur métier\033[0m")
    tests: List[Callable[[], None]] = [
        test_topology,
        test_dc_basic,
        test_semiconductors,
        test_transient,
        test_machines_instruments,
        test_states,
        test_play_session,
        test_formatting,
    ]
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001 — harness de test
            import traceback
            _FAIL.append(f"{t.__name__} (exception)")
            print(f"  \033[31m✗ EXCEPTION dans {t.__name__} : {exc}\033[0m")
            traceback.print_exc()

    print(f"\n\033[1mRésultat : {_PASS} vérifications OK, "
          f"{len(_FAIL)} échec(s)\033[0m")
    for name in _FAIL:
        print(f"  \033[31m- {name}\033[0m")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
