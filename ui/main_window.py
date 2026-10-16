"""Main VoltForge desktop window and application workflows."""

from __future__ import annotations

import json
import io
import html
import math
from pathlib import Path
import sys
import zipfile

from PyQt6.QtCore import QByteArray, QPointF, QSize, Qt, QTimer, QSettings
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QScrollArea,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.circuit import Circuit
from core.components import (
    Ammeter,
    Capacitor,
    Component,
    Diode,
    Fuse,
    Generator,
    Inductor,
    Kind,
    Lamp,
    Led,
    Motor,
    Ohmmeter,
    Potentiometer,
    PushButton,
    Resistor,
    SourceType,
    Switch,
    Voltmeter,
    create_component,
)
from core.simulation import SimulationEngine
from core.solver import BranchResult
from exporters.gif import export_gif
from exporters.static import export_static
from ui.canvas import CircuitCanvas
from core.formatting import parse_value
from core.voltage_arrow import VoltageArrow
from core.scenario import PROP_ALIASES


class PropertyDialog(QDialog):
    """Editor generated from the component property specifications."""

    def __init__(self, component: Component, parent=None):
        super().__init__(parent)
        self.component = component
        self.setWindowTitle(f"Propriétés — {component.label}")
        self.setMinimumWidth(360)
        self.fields = {}
        form = QFormLayout(self)
        for name, spec in component.prop_specs().items():
            value = component.get_prop(name)
            if spec.ptype == "bool":
                editor = QCheckBox()
                editor.setChecked(bool(value))
            elif spec.ptype == "enum":
                editor = QComboBox()
                editor.addItems(spec.choices or ())
                editor.setCurrentText(str(value))
            elif spec.ptype == "float":
                editor = QDoubleSpinBox()
                editor.setRange(
                    spec.minimum if spec.minimum is not None else -1e12,
                    spec.maximum if spec.maximum is not None else 1e12,
                )
                editor.setDecimals(max(4, spec.decimals))
                editor.setSingleStep(spec.step)
                editor.setValue(float(value))
                if spec.unit:
                    editor.setSuffix(f" {spec.unit}")
            else:
                editor = QLineEdit(str(value))
            editor.setToolTip(spec.tip)
            self.fields[name] = editor
            form.addRow(name.replace("_", " ").capitalize(), editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self) -> None:
        for name, editor in self.fields.items():
            if isinstance(editor, QCheckBox):
                value = editor.isChecked()
            elif isinstance(editor, QComboBox):
                value = editor.currentText()
            elif isinstance(editor, QDoubleSpinBox):
                value = editor.value()
            else:
                value = editor.text()
            self.component.set_prop(name, value)


class CustomComponentDialog(QDialog):
    """Define a custom two-terminal resistive element."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Créer un composant personnalisé")
        form = QFormLayout(self)
        self.name_field = QLineEdit("Composant perso")
        self.symbol_field = QLineEdit("X")
        self.symbol_field.setMaxLength(4)
        self.resistance_field = QDoubleSpinBox()
        self.resistance_field.setRange(1e-6, 1e12)
        self.resistance_field.setDecimals(4)
        self.resistance_field.setValue(100)
        self.resistance_field.setSuffix(" Ω")
        form.addRow("Nom", self.name_field)
        form.addRow("Symbole (4 caractères max.)", self.symbol_field)
        form.addRow("Résistance équivalente", self.resistance_field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class OhmCalculatorDialog(QDialog):
    """Calculate the four basic electrical quantities from any two values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calculateur — loi d'Ohm")
        form = QFormLayout(self)
        self.fields = {}
        for key, label, unit in (
            ("u", "Tension U", "V"),
            ("i", "Courant I", "A"),
            ("r", "Résistance R", "Ω"),
            ("p", "Puissance P", "W"),
        ):
            field = QLineEdit()
            field.setPlaceholderText(f"Laisser vide pour calculer ({unit})")
            self.fields[key] = field
            form.addRow(label, field)
        self.result = QLabel("Formules : U = R × I · P = U × I")
        self.result.setWordWrap(True)
        form.addRow(self.result)
        calculate = QPushButton("Calculer")
        calculate.clicked.connect(self.calculate)
        form.addRow(calculate)

    def calculate(self) -> None:
        values = {}
        try:
            for key, field in self.fields.items():
                raw = field.text().strip()
                values[key] = parse_value(raw) if raw else None
            known = [key for key, value in values.items() if value is not None]
            if len(known) != 2:
                raise ValueError("Renseignez exactement deux grandeurs.")
            u, i, r, p = (values[key] for key in ("u", "i", "r", "p"))
            if u is not None and i is not None:
                r, p = u / i if i else None, u * i
            elif u is not None and r is not None:
                i, p = u / r if r else None, u * (u / r) if r else None
            elif u is not None and p is not None:
                i = p / u if u else None
                r = u / i if i else None
            elif i is not None and r is not None:
                u, p = r * i, r * i * i
            elif i is not None and p is not None:
                u = p / i if i else None
                r = u / i if i else None
            else:
                if r is None or p is None or r <= 0 or p < 0:
                    raise ValueError("R doit être positive et P non négative.")
                i = (p / r) ** 0.5
                u = i * r
            if any(value is None for value in (u, i, r, p)):
                raise ValueError("Le calcul est impossible avec une valeur nulle.")
            formulae = {
                frozenset(("u", "i")): f"R = U/I = {u:.6g}/{i:.6g} ; P = U×I",
                frozenset(("u", "r")): f"I = U/R = {u:.6g}/{r:.6g} ; P = U²/R",
                frozenset(("u", "p")): f"I = P/U = {p:.6g}/{u:.6g} ; R = U²/P",
                frozenset(("i", "r")): f"U = R×I = {r:.6g}×{i:.6g} ; P = I²×R",
                frozenset(("i", "p")): f"U = P/I = {p:.6g}/{i:.6g} ; R = P/I²",
                frozenset(("r", "p")): "I = √(P/R) ; U = √(P×R)",
            }
            formula = formulae[frozenset(known)]
            for key, value in zip(("u", "i", "r", "p"), (u, i, r, p)):
                self.fields[key].setText(f"{value:.6g}")
            self.result.setText(
                f"Formule utilisée : {formula}\n"
                f"U = {u:.6g} V · I = {i:.6g} A · "
                f"R = {r:.6g} Ω · P = {p:.6g} W"
            )
        except (ValueError, ZeroDivisionError) as exc:
            self.result.setText(str(exc))


class ResistorSizerDialog(QDialog):
    """Size a series resistor to keep a load within its nominal rating."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calculer une résistance de protection")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.source_voltage = QLineEdit()
        self.source_voltage.setPlaceholderText("ex. 12 V")
        self.load_voltage = QLineEdit()
        self.load_voltage.setPlaceholderText("ex. 5 V")
        self.load_current = QLineEdit()
        self.load_current.setPlaceholderText("ex. 300 mA")
        self.load_power = QLineEdit()
        self.load_power.setPlaceholderText("ex. 1,5 W (facultatif)")
        self.load_current.textChanged.connect(
            lambda value: self.load_power.setEnabled(not value.strip())
        )
        self.load_power.textChanged.connect(
            lambda value: self.load_current.setEnabled(not value.strip())
        )
        form.addRow("Tension de la source", self.source_voltage)
        form.addRow("Tension nominale du récepteur", self.load_voltage)
        form.addRow("Courant nominal du récepteur", self.load_current)
        form.addRow("ou puissance nominale", self.load_power)
        self.result = QLabel("Renseignez les caractéristiques nominales du récepteur.")
        self.result.setWordWrap(True)
        form.addRow(self.result)
        calculate = QPushButton("Calculer")
        calculate.clicked.connect(self.calculate)
        form.addRow(calculate)

    @staticmethod
    def _next_e12(value: float) -> float:
        if value <= 0:
            return 0.0
        base = 10 ** math.floor(math.log10(value))
        for coefficient in (1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3,
                            3.9, 4.7, 5.6, 6.8, 8.2, 10.0):
            candidate = coefficient * base
            if candidate >= value:
                return candidate
        return 10 * base

    def calculate(self) -> None:
        try:
            source = parse_value(self.source_voltage.text())
            load = parse_value(self.load_voltage.text())
            current_text = self.load_current.text().strip()
            power_text = self.load_power.text().strip()
            if bool(current_text) == bool(power_text):
                raise ValueError("Renseignez soit le courant, soit la puissance nominale.")
            if source <= 0 or load <= 0 or source < load:
                raise ValueError("La tension source doit être au moins égale à la tension nominale.")
            current = (
                parse_value(current_text)
                if current_text else parse_value(power_text) / load
            )
            if current <= 0:
                raise ValueError("Le courant nominal doit être positif.")
            theoretical = (source - load) / current
            resistance = self._next_e12(theoretical)
            resistor_power = current * current * resistance
            safe_power = next(
                (rating for rating in (0.25, 0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500)
                 if rating >= resistor_power * 2),
                resistor_power * 2,
            )
            current_formula = (
                f"I = {current:.4g} A"
                if current_text
                else f"I = P/U = {parse_value(power_text):.4g}/{load:.4g}"
                f" = {current:.4g} A"
            )
            self.result.setText(
                f"Formules : R = (Usource − Urécepteur)/I ; "
                f"PR = I²×R\n"
                f"{current_formula}\n"
                f"R = ({source:.4g} − {load:.4g})/{current:.4g} "
                f"= {theoretical:.4g} Ω\n"
                f"Valeur normalisée conseillée : {resistance:.4g} Ω\n"
                f"PR = {current:.4g}²×{resistance:.4g} "
                f"= {resistor_power:.4g} W — "
                f"choisissez une résistance d'au moins {safe_power:g} W."
            )
        except (ValueError, ZeroDivisionError) as exc:
            self.result.setText(str(exc))


class MainWindow(QMainWindow):
    """Window for circuit authoring, simulation, and export."""

    TOOL_COMPONENTS = (
        (Kind.GENERATOR, "Générateur"),
        (Kind.BATTERY, "Pile"),
        (Kind.RESISTOR, "Résistance"),
        (Kind.THERMISTOR, "Thermistance NTC"),
        (Kind.PHOTORESISTOR, "Photorésistance"),
        (Kind.HEATER, "Résistance chauffante"),
        (Kind.POTENTIOMETER, "Potentiomètre"),
        (Kind.SWITCH, "Interrupteur"),
        (Kind.PUSH_BUTTON, "Bouton-poussoir"),
        (Kind.CAPACITOR, "Condensateur"),
        (Kind.INDUCTOR, "Bobine"),
        (Kind.DIODE, "Diode"),
        (Kind.LED, "LED"),
        (Kind.LAMP, "Lampe"),
        (Kind.MOTOR, "Moteur"),
        (Kind.SPEAKER, "Haut-parleur"),
        (Kind.BUZZER, "Buzzer"),
        (Kind.FUSE, "Fusible"),
        (Kind.GROUND, "Masse"),
        (Kind.VOLTMETER, "Voltmètre"),
        (Kind.AMMETER, "Ampèremètre"),
        (Kind.OHMMETER, "Ohmmètre"),
    )
    COMPONENT_CATEGORIES = (
        ("Sources", "generator-voltage.svg",
         (Kind.GENERATOR, Kind.BATTERY)),
        ("Passifs", "resistor.svg",
         (Kind.RESISTOR, Kind.THERMISTOR, Kind.PHOTORESISTOR, Kind.HEATER,
          Kind.POTENTIOMETER, Kind.SWITCH, Kind.PUSH_BUTTON,
          Kind.CAPACITOR, Kind.INDUCTOR)),
        ("Semi-conducteurs", "diode.svg", (Kind.DIODE, Kind.LED)),
        ("Actionneurs", "motor.svg",
         (Kind.LAMP, Kind.MOTOR, Kind.SPEAKER, Kind.BUZZER, Kind.FUSE)),
        ("Mesure", "voltmeter.svg",
         (Kind.VOLTMETER, Kind.AMMETER, Kind.OHMMETER)),
        ("Topologie", "ground.svg", (Kind.GROUND,)),
    )
    QUICK_PARAMETER_ORDER = {
        Kind.GENERATOR: ("voltage", "current", "ri", "p_max"),
        Kind.BATTERY: ("voltage", "ri", "p_max"),
        Kind.LAMP: ("resistance", "u_rated", "p_max"),
        Kind.RESISTOR: ("resistance", "p_max"),
        Kind.CUSTOM: ("resistance", "p_max"),
        Kind.THERMISTOR: ("temperature", "r_ref", "beta"),
        Kind.PHOTORESISTOR: ("illumination", "dark_resistance", "sensitivity"),
        Kind.HEATER: ("resistance", "p_max"),
        Kind.SPEAKER: ("resistance", "p_max"),
        Kind.BUZZER: ("resistance", "voltage", "p_max"),
        Kind.LED: ("vf", "r_on", "p_max"),
        Kind.DIODE: ("vf", "r_on", "p_max"),
        Kind.MOTOR: ("r_m", "ke", "kt", "tc"),
        Kind.CAPACITOR: ("capacitance", "v0"),
        Kind.INDUCTOR: ("inductance", "r_w"),
        Kind.POTENTIOMETER: ("resistance", "level"),
        Kind.SWITCH: ("r_on",),
        Kind.PUSH_BUTTON: ("r_on",),
        Kind.FUSE: ("i_rated",),
        Kind.VOLTMETER: ("r_int",),
        Kind.AMMETER: ("r_sh",),
        Kind.OHMMETER: ("i_test", "r_int"),
    }
    QUICK_PARAMETER_RANGES = {
        "voltage": (-24.0, 24.0),
        "current": (-5.0, 5.0),
        "ri": (0.0, 5.0),
        "p_max": (0.01, 100.0),
        "resistance": (0.1, 1000.0),
        "temperature": (-40.0, 150.0),
        "r_ref": (1.0, 1e6),
        "beta": (100.0, 10_000.0),
        "illumination": (0.0, 100_000.0),
        "dark_resistance": (1.0, 1e9),
        "sensitivity": (0.1, 2.0),
        "u_rated": (1.0, 24.0),
        "vf": (0.0, 6.0),
        "r_on": (0.001, 100.0),
        "r_m": (0.1, 50.0),
        "ke": (0.0, 1.0),
        "kt": (0.0, 1.0),
        "tc": (0.0, 10.0),
        "capacitance": (1e-9, 1.0),
        "v0": (-24.0, 24.0),
        "inductance": (1e-6, 10.0),
        "r_w": (0.0, 10.0),
        "level": (0.0, 1.0),
        "i_rated": (0.01, 20.0),
        "r_int": (1e3, 1e9),
        "r_sh": (0.0, 1.0),
        "i_test": (1e-6, 1.0),
    }
    QUICK_PARAMETER_LABELS = {
        "voltage": "Tension",
        "current": "Courant",
        "ri": "Résistance interne",
        "p_max": "Puissance maximale",
        "resistance": "Résistance",
        "temperature": "Température ambiante",
        "r_ref": "Résistance de référence",
        "beta": "Coefficient bêta",
        "illumination": "Éclairement",
        "dark_resistance": "Résistance dans l’obscurité",
        "sensitivity": "Sensibilité lumineuse",
        "u_rated": "Tension nominale",
        "vf": "Tension directe",
        "r_on": "Résistance à l’état passant",
        "r_m": "Résistance moteur",
        "ke": "Constante de tension",
        "kt": "Constante de couple",
        "tc": "Couple résistant",
        "capacitance": "Capacité",
        "v0": "Tension initiale",
        "inductance": "Inductance",
        "r_w": "Résistance du bobinage",
        "level": "Position du curseur",
        "i_rated": "Courant nominal",
        "r_int": "Résistance interne",
        "r_sh": "Résistance du shunt",
        "i_test": "Courant de test",
    }
    THEMES = {
        "light": {
            "background": "#f3f6fb",
            "chrome": "#ffffff",
            "panel": "#eaeff6",
            "card": "#ffffff",
            "field": "#ffffff",
            "inset": "#f1f5fa",
            "text": "#1f2937",
            "muted": "#64748b",
            "border": "#dbe3ed",
            "accent": "#0f9f86",
            "accent_text": "#ffffff",
            "accent_hover": "#0c8a74",
            "hover": "#e9f7f4",
            "selected": "#d8f3ed",
            "danger": "#b42318",
            "danger_tint": "#fdeceb",
            "warning": "#b54708",
            "error": "#b42318",
        },
        "dark": {
            "background": "#111a24",
            "chrome": "#192532",
            "panel": "#151f2b",
            "card": "#1d2b3a",
            "field": "#111a24",
            "inset": "#141f2b",
            "text": "#e5edf5",
            "muted": "#91a2b3",
            "border": "#304252",
            "accent": "#45d2b4",
            "accent_text": "#0b1a20",
            "accent_hover": "#5fe0c6",
            "hover": "#253a46",
            "selected": "#23483f",
            "danger": "#ff8a92",
            "danger_tint": "#2c1c22",
            "warning": "#ffc857",
            "error": "#ff8a92",
        },
    }
    ICONS = {
        Kind.GENERATOR: "generator-voltage.svg",
        Kind.BATTERY: "battery.svg",
        Kind.RESISTOR: "resistor.svg",
        Kind.CUSTOM: "custom.svg",
        Kind.THERMISTOR: "thermistor.svg",
        Kind.PHOTORESISTOR: "photoresistor.svg",
        Kind.HEATER: "heater.svg",
        Kind.SPEAKER: "speaker.svg",
        Kind.BUZZER: "buzzer.svg",
        Kind.POTENTIOMETER: "potentiometer.svg",
        Kind.SWITCH: "switch.svg",
        Kind.PUSH_BUTTON: "push-button.svg",
        Kind.CAPACITOR: "capacitor.svg",
        Kind.INDUCTOR: "inductor.svg",
        Kind.DIODE: "diode.svg",
        Kind.LED: "led.svg",
        Kind.LAMP: "lamp.svg",
        Kind.MOTOR: "motor.svg",
        Kind.FUSE: "fuse.svg",
        Kind.GROUND: "ground.svg",
        Kind.VOLTMETER: "voltmeter.svg",
        Kind.AMMETER: "ammeter.svg",
        Kind.OHMMETER: "ohmmeter.svg",
    }

    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(str(self._icon_path("voltforge.svg"))))
        self.setWindowTitle("VoltForge — Conception et simulation électrique")
        self.resize(1280, 800)
        self.circuit = Circuit()
        self.engine = SimulationEngine(self.circuit)
        self.project_path: Path | None = None
        self.scenario_text = ""
        self.is_dirty = False
        stored_theme = QSettings("VoltForge", "VoltForge").value("theme", "dark")
        self.theme = "light" if stored_theme == "light" else "dark"
        self.colors = self.THEMES[self.theme]
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(20)
        self._play_timer.timeout.connect(self._advance_playback)

        self._create_menu()
        self._create_layout()
        self.set_theme(self.theme)
        self.engine.recompute()
        self.refresh_inspector()
        self.refresh_results()
        self.statusBar().showMessage("Prêt — choisissez un outil et cliquez sur la grille.")
        self._refresh_title()

    def _scenario_text_changed(self, text: str) -> None:
        if text != self.scenario_text:
            self.scenario_text = text
            self.is_dirty = True
            self._refresh_title()

    def _create_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Fichier")
        self._add_action(file_menu, "Nouveau", self.new_project, QKeySequence.StandardKey.New)
        self._add_action(file_menu, "Ouvrir…", self.open_project, QKeySequence.StandardKey.Open)
        self._add_action(file_menu, "Enregistrer le projet", self.save_project,
                         QKeySequence.StandardKey.Save)
        self._add_action(file_menu, "Enregistrer sous…", self.save_project_as)
        file_menu.addSeparator()
        export_menu = file_menu.addMenu("Exporter le schéma")
        for label, extension in (
            ("PNG", "png"), ("JPEG", "jpg"), ("SVG", "svg"), ("PDF", "pdf")
        ):
            self._add_action(
                export_menu, label,
                lambda checked=False, ext=extension: self.export_diagram(ext),
            )
        file_menu.addSeparator()
        self._add_action(file_menu, "Quitter", self.close, QKeySequence.StandardKey.Quit)

        simulation_menu = self.menuBar().addMenu("Simulation")
        self._add_action(simulation_menu, "Configurer / lancer…", self.open_scenario_dialog)
        self._add_action(simulation_menu, "Exporter un GIF…", self.open_scenario_dialog)
        self._add_action(simulation_menu, "Recalculer", self.recompute)
        tools_menu = self.menuBar().addMenu("Outils")
        self._add_action(tools_menu, "Calculateur loi d'Ohm…", self.open_ohm_calculator)
        self._add_action(tools_menu, "Calculer une résistance de protection…",
                         self.open_resistor_sizer)
        view_menu = self.menuBar().addMenu("Affichage")
        self.node_labels_action = QAction("Afficher les nœuds A, B, C…", self)
        self.node_labels_action.setCheckable(True)
        self.node_labels_action.toggled.connect(self._toggle_node_labels)
        view_menu.addAction(self.node_labels_action)
        self.meshes_action = QAction("Afficher les mailles M1, M2…", self)
        self.meshes_action.setCheckable(True)
        self.meshes_action.toggled.connect(self._toggle_meshes)
        view_menu.addAction(self.meshes_action)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Thème")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        for label, theme in (("Sombre", "dark"), ("Clair", "light")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(theme)
            action.setChecked(theme == self.theme)
            action.triggered.connect(
                lambda checked, value=theme: self.set_theme(value) if checked else None
            )
            self.theme_group.addAction(action)
            theme_menu.addAction(action)

    @staticmethod
    def _add_action(menu, text, callback, shortcut=None):
        action = QAction(text, menu)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _create_layout(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        self.setCentralWidget(central)

        toolbar = self.addToolBar("Outils")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(24, 24))
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.mode_actions = {}
        for label, mode, icon in (
            ("Sélection", "select", "select.svg"),
            ("Fil", "wire", "wire.svg"),
            ("Flèche U", "voltage", "voltage-arrow.svg"),
        ):
            action = QAction(QIcon(str(self._icon_path(icon))), label, self)
            action.setProperty("iconName", icon)
            action.setCheckable(True)
            if label == "Sélection":
                action.setChecked(True)
            action.setData(mode)
            self.mode_actions[mode] = action
            self.tool_group.addAction(action)
            toolbar.addAction(action)
            action.triggered.connect(
                lambda checked, m=mode: self._set_tool_mode(m)
                if checked else None
            )

        components_toolbar = self.addToolBar("Composants")
        components_toolbar.setMovable(False)
        components_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        components_toolbar.setIconSize(QSize(22, 22))
        self.component_categories = {}
        labels = dict((kind, label) for kind, label in self.TOOL_COMPONENTS)
        for category, icon, kinds in self.COMPONENT_CATEGORIES:
            button = QToolButton(self)
            button.setText(category)
            button.setProperty("iconName", icon)
            button.setIcon(self._icon(icon))
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            for kind in kinds:
                action = QAction(
                    self._icon(self.ICONS[kind]),
                    labels[kind],
                    menu,
                )
                action.setData(kind.value)
                action.triggered.connect(
                    lambda checked=False, selected_kind=kind:
                    self.select_component_tool(selected_kind)
                )
                menu.addAction(action)
            button.setMenu(menu)
            components_toolbar.addWidget(button)
            self.component_categories[category] = (button, menu)

        passives_menu = self.component_categories["Passifs"][1]
        passives_menu.addSeparator()
        custom_action = QAction(
            self._icon(self.ICONS[Kind.CUSTOM]),
            "Créer perso…",
            self,
        )
        custom_action.triggered.connect(self.create_custom_component)
        passives_menu.addAction(custom_action)
        self.custom_component_action = custom_action

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter
        outer.addWidget(splitter, 1)

        self.canvas = CircuitCanvas(self.circuit, self.engine)
        self.canvas.circuitChanged.connect(self._circuit_changed)
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.canvas.statusMessage.connect(self.statusBar().showMessage)
        splitter.addWidget(self.canvas)

        right = QWidget()
        right.setObjectName("inspectorPanel")
        right.setMinimumWidth(320)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 8, 10, 8)
        right_layout.setSpacing(8)

        panel_title = QLabel("Inspecteur")
        panel_title.setObjectName("panelTitle")
        right_layout.addWidget(panel_title)

        self.selection_group = QGroupBox("Propriétés")
        self.selection_group.setObjectName("selectionGroup")
        self.selection_layout = QVBoxLayout(self.selection_group)
        self.selection_layout.setContentsMargins(8, 10, 8, 10)
        self.selection_layout.setSpacing(8)
        self.selection_label = QLabel("Aucun élément sélectionné")
        self.selection_label.setObjectName("selectionSummary")
        self.selection_label.setTextFormat(Qt.TextFormat.RichText)
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.selection_layout.addWidget(self.selection_label)

        self.quick_controls_group = QWidget()
        self.quick_controls_group.setObjectName("quickControls")
        quick_layout = QVBoxLayout(self.quick_controls_group)
        quick_layout.setContentsMargins(8, 8, 8, 8)
        quick_layout.setSpacing(6)
        quick_title = QLabel("Réglage en direct")
        quick_title.setObjectName("sectionTitle")
        quick_layout.addWidget(quick_title)
        quick_hint = QLabel("Les résultats se recalculent pendant le réglage.")
        quick_hint.setObjectName("mutedText")
        quick_hint.setWordWrap(True)
        quick_layout.addWidget(quick_hint)
        self.quick_controls_layout = QVBoxLayout()
        self.quick_controls_layout.setSpacing(8)
        quick_layout.addLayout(self.quick_controls_layout)
        self.quick_controls_group.hide()
        self._quick_controls_component: Component | None = None
        self._quick_parameter_controls = {}
        self.selection_layout.addWidget(self.quick_controls_group)

        primary_buttons = QHBoxLayout()
        primary_buttons.setSpacing(6)
        self.edit_button = QPushButton("Modifier")
        self.edit_button.setObjectName("primaryButton")
        self.edit_button.clicked.connect(self.edit_selected)
        self.rotate_button = QPushButton("Tourner")
        self.rotate_button.clicked.connect(self.rotate_selected)
        primary_buttons.addWidget(self.edit_button, 1)
        primary_buttons.addWidget(self.rotate_button, 1)
        self.selection_layout.addLayout(primary_buttons)
        self.delete_button = QPushButton("Supprimer")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self.delete_selected)
        self.selection_layout.addWidget(self.delete_button)
        self.repair_button = QPushButton("Réparer le composant")
        self.repair_button.setObjectName("primaryButton")
        self.repair_button.clicked.connect(self.repair_selected_component)
        self.repair_button.hide()
        self.selection_layout.addWidget(self.repair_button)
        self.switch_button = QPushButton()
        self.switch_button.setObjectName("primaryButton")
        self.switch_button.clicked.connect(self.toggle_selected_switch)
        self.switch_button.hide()
        self.selection_layout.addWidget(self.switch_button)
        right_layout.addWidget(self.selection_group)

        self.results_group = QGroupBox("Résultats")
        self.results_group.setObjectName("resultsGroup")
        results_layout = QVBoxLayout(self.results_group)
        results_layout.setContentsMargins(8, 10, 8, 10)
        results_layout.setSpacing(6)
        self.results_summary = QLabel("En attente de calcul.")
        self.results_summary.setObjectName("resultsSummary")
        self.results_summary.setWordWrap(True)
        results_layout.addWidget(self.results_summary)
        self.results_text = QLabel("En attente de calcul.")
        self.results_text.setObjectName("resultsBody")
        self.results_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.results_text.setWordWrap(True)
        results_layout.addWidget(self.results_text)
        right_layout.addWidget(self.results_group, 1)
        inspector_scroll = QScrollArea()
        inspector_scroll.setObjectName("inspectorScroll")
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        inspector_scroll.setWidget(right)
        splitter.addWidget(inspector_scroll)
        splitter.setSizes([900, 340])
        simulation_toolbar = self.addToolBar("Simulation")
        simulation_toolbar.setMovable(False)
        self._toolbar_action(
            simulation_toolbar, "Simulation…", self.open_scenario_dialog
        )
        self._toolbar_action(
            simulation_toolbar, "Calculateur U/I/R/P", self.open_ohm_calculator
        )

    def _toggle_node_labels(self, enabled: bool) -> None:
        self.canvas.show_node_labels = enabled
        self.canvas.update()

    def _toggle_meshes(self, enabled: bool) -> None:
        self.canvas.show_meshes = enabled
        self.canvas.update()

    def open_ohm_calculator(self) -> None:
        OhmCalculatorDialog(self).exec()

    def open_resistor_sizer(self) -> None:
        ResistorSizerDialog(self).exec()

    def set_theme(self, theme: str) -> None:
        self.theme = theme if theme == "light" else "dark"
        colors = self.THEMES[self.theme]
        self.colors = colors
        if hasattr(self, "canvas"):
            self.canvas.set_theme(self.theme)
        background = colors["background"]
        chrome = colors["chrome"]
        panel = colors["panel"]
        card = colors["card"]
        field = colors["field"]
        inset = colors["inset"]
        text = colors["text"]
        muted = colors["muted"]
        border = colors["border"]
        accent = colors["accent"]
        accent_text = colors["accent_text"]
        accent_hover = colors["accent_hover"]
        hover = colors["hover"]
        selected = colors["selected"]
        danger = colors["danger"]
        danger_tint = colors["danger_tint"]
        self.setStyleSheet(f"""
            QWidget {{
                color: {text};
                font-size: 10pt;
            }}
            QMainWindow, QDialog {{ background: {background}; }}
            QMenuBar, QMenu, QToolBar {{
                background: {chrome};
                color: {text};
                border: none;
            }}
            QMenuBar {{ padding: 4px 8px; }}
            QMenuBar::item {{ padding: 6px 10px; border-radius: 5px; }}
            QMenuBar::item:selected, QMenu::item:selected {{ background: {hover}; }}
            QMenu {{ border: 1px solid {border}; padding: 5px; }}
            QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 4px; }}
            QToolBar {{ spacing: 6px; padding: 6px 8px; }}
            QToolBar::separator {{ background: {border}; width: 1px; margin: 4px; }}
            QToolButton {{
                background: transparent; border: 1px solid transparent;
                border-radius: 6px; padding: 6px 9px;
            }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:checked {{ background: {selected}; color: {accent}; }}
            QPushButton {{
                background: transparent; border: 1px solid {border};
                border-radius: 6px; padding: 6px 10px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {selected}; }}
            QPushButton:disabled {{ color: {muted}; border-color: {border}; }}
            QPushButton#primaryButton {{
                background: {accent}; border: 1px solid {accent};
                color: {accent_text}; font-weight: 600;
            }}
            QPushButton#primaryButton:hover {{
                background: {accent_hover}; border-color: {accent_hover};
            }}
            QPushButton#primaryButton:disabled {{
                background: transparent; color: {muted}; border-color: {border};
            }}
            QPushButton#dangerButton {{ color: {danger}; }}
            QPushButton#dangerButton:hover {{
                background: {danger_tint}; border-color: {danger};
            }}
            QPushButton#dangerButton:disabled {{
                color: {muted}; background: transparent; border-color: {border};
            }}
            QGroupBox {{
                background: {card}; border: 1px solid {border}; border-radius: 8px;
                margin-top: 12px; padding: 6px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 0 4px;
                font-weight: 600; font-size: 10pt; color: {text};
            }}
            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTableWidget,
            QPlainTextEdit {{
                background: {field}; color: {text}; border: 1px solid {border};
                border-radius: 6px; padding: 5px 7px;
                selection-background-color: {accent};
                selection-color: {accent_text};
            }}
            QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
            QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {accent}; }}
            QTableWidget {{ gridline-color: {border}; }}
            QHeaderView::section {{
                background: {chrome}; color: {muted}; border: none;
                border-bottom: 1px solid {border}; padding: 4px 6px;
            }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical, QScrollBar:horizontal {{
                background: transparent; margin: 3px;
            }}
            QScrollBar:vertical {{ width: 10px; }}
            QScrollBar:horizontal {{ height: 10px; }}
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
                background: {border}; border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{ min-height: 24px; }}
            QScrollBar::handle:horizontal {{ min-width: 24px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                width: 0; height: 0; border: none; background: transparent;
            }}
            QSplitter::handle {{ background: {border}; width: 1px; }}
            QStatusBar {{
                background: {chrome}; color: {muted};
                border-top: 1px solid {border};
            }}
            QToolTip {{
                background: {card}; color: {text};
                border: 1px solid {border}; padding: 4px 6px;
            }}
            QWidget#inspectorPanel {{ background: {panel}; }}
            QWidget#quickControls {{
                background: {inset}; border: 1px solid {border}; border-radius: 8px;
            }}
            QLabel#panelTitle {{ font-size: 11pt; font-weight: 600; }}
            QLabel#sectionTitle {{ font-weight: 600; font-size: 10pt; }}
            QLabel#mutedText {{ color: {muted}; font-size: 9pt; }}
            QLabel#selectionSummary {{ font-size: 10pt; line-height: 150%; }}
            QLabel#resultsSummary {{ color: {muted}; font-size: 9pt; }}
            QLabel#resultsBody {{ font-size: 9.5pt; line-height: 150%; }}
            QLabel#quickParameterLabel {{ font-weight: 600; }}
            QLabel#quickParameterValue {{ color: {accent}; font-weight: 600; }}
            QSlider::groove:horizontal {{
                height: 5px; background: {border}; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {accent}; width: 14px; margin: -5px 0;
                border: 2px solid {card}; border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{ background: {accent_hover}; }}
        """)
        QSettings("VoltForge", "VoltForge").setValue("theme", self.theme)
        self._refresh_icons()

    def _refresh_title(self) -> None:
        name = self.project_path.name if self.project_path else "Nouveau projet"
        self.setWindowTitle(
            f"{'* ' if self.is_dirty else ''}{name} — VoltForge"
        )

    @staticmethod
    def _icon_path(filename: str) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        return base / "assets" / "icons" / filename

    def _icon(self, filename: str) -> QIcon:
        source = self._icon_path(filename).read_text(encoding="utf-8")
        foreground = "#243746" if self.theme == "light" else "#e8f2f2"
        source = source.replace("#e8f2f2", foreground)
        source = source.replace("#dce7ef", foreground)
        if self.theme == "light":
            source = source.replace("#c6d1d8", "#526477")
        renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
        if not renderer.isValid():
            raise ValueError(f"SVG d'icône invalide : {filename}")
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def _refresh_icons(self) -> None:
        if not hasattr(self, "mode_actions"):
            return
        for action in self.mode_actions.values():
            action.setIcon(self._icon(action.property("iconName")))
        for button, menu in self.component_categories.values():
            button.setIcon(self._icon(button.property("iconName")))
            for action in menu.actions():
                if action.data():
                    action.setIcon(self._icon(self.ICONS[Kind(action.data())]))
        if hasattr(self, "custom_component_action"):
            self.custom_component_action.setIcon(
                self._icon(self.ICONS[Kind.CUSTOM])
            )

    def _set_tool_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)

    def select_component_tool(self, kind: Kind) -> None:
        self.tool_group.setExclusive(False)
        for action in self.mode_actions.values():
            action.setChecked(False)
        self.tool_group.setExclusive(True)
        self.canvas.set_mode("place", kind)

    @staticmethod
    def _toolbar_action(toolbar, text, callback):
        action = QAction(text, toolbar)
        action.triggered.connect(callback)
        toolbar.addAction(action)

    def _circuit_changed(self) -> None:
        self.is_dirty = True
        self._refresh_title()
        self.refresh_inspector()
        self.refresh_results()

    def _selection_changed(self, item) -> None:
        self.refresh_inspector()

    def refresh_inspector(self) -> None:
        item = self.canvas.selected
        selected_count = len(self.canvas.selected_items)
        colors = self.colors
        muted = colors["muted"]
        if selected_count > 1:
            self._refresh_quick_controls(None)
            self.selection_label.setText(
                f"{selected_count} éléments sélectionnés"
                f"\n<br><span style='color:{muted}'>Faites glisser pour les "
                "déplacer ensemble ; Supprimer pour tout effacer.</span>"
            )
            self.edit_button.setEnabled(False)
            self.rotate_button.setEnabled(False)
            self.delete_button.setEnabled(True)
            self.repair_button.hide()
            self.switch_button.hide()
            return
        if item is None:
            self._refresh_quick_controls(None)
            self.selection_label.setText(
                "Aucun élément sélectionné"
                f"\n<br><span style='color:{muted}'>"
                f"{len(self.circuit.components)} composant(s) · "
                f"{len(self.circuit.wires)} fil(s) · "
                f"{len(self.circuit.nodes)} nœud(s) · "
                f"{self.circuit.mesh_count()} maille(s)</span>"
            )
            self.edit_button.setEnabled(False)
            self.rotate_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.repair_button.hide()
            self.switch_button.hide()
            return
        if isinstance(item, Component):
            self._refresh_quick_controls(item)
            result = self.engine.solution.branches.get(item.label)
            lines = [f"<b>{html.escape(item.short_description())}</b>"]
            value = item.display_value()
            if value:
                lines.append(
                    f"<span style='color:{muted}'>{html.escape(value)}</span>"
                )
            if result is not None:
                lines.append(self._metrics_table(result, muted))
                lines.append(
                    f"<span style='color:{muted}'><i>"
                    f"{html.escape(self._calculation_formula(item, result))}"
                    "</i></span>"
                )
                if result.message:
                    lines.append(
                        f"<span style='color:{colors['warning']}'>"
                        f"{html.escape(result.message)}</span>"
                    )
                if isinstance(item, Motor):
                    lines.append(
                        f"<span style='color:{muted}'>Vitesse = "
                        f"{item.rpm(result.i):.0f} tr/min</span>"
                    )
            detail = self._html_block(lines)
        elif isinstance(item, VoltageArrow):
            self._refresh_quick_controls(None)
            item.resolve_nodes(self.circuit)
            value = item.voltage(self.engine.solution)
            lines = [
                f"<b>{html.escape(item.label)}</b>",
                f"<span style='color:{muted}'>Flèche de tension orientée A → B</span>",
            ]
            if item.node_a in self.circuit.nodes:
                lines.append(
                    "Nœud de départ : "
                    + html.escape(self.circuit.nodes[item.node_a].name)
                )
            if item.node_b in self.circuit.nodes:
                lines.append(
                    "Nœud d'arrivée : "
                    + html.escape(self.circuit.nodes[item.node_b].name)
                )
            if value is not None:
                lines.append(f"<b>Tension : {value:.5g} V</b>")
            detail = self._html_block(lines)
        else:
            self._refresh_quick_controls(None)
            label = html.escape(str(getattr(item, "label", "") or ""))
            detail = f"<b>Fil {label}</b>".strip()
        self.selection_label.setText(detail)
        self.edit_button.setEnabled(isinstance(item, Component))
        self.rotate_button.setEnabled(isinstance(item, Component))
        self.delete_button.setEnabled(True)
        self.repair_button.setVisible(
            isinstance(item, Component) and bool(item.get_prop("blown"))
        )
        if isinstance(item, Switch):
            if isinstance(item, PushButton):
                text = "Relâcher le bouton" if item.closed else "Appuyer sur le bouton"
            else:
                text = (
                    "Ouvrir l'interrupteur" if item.closed
                    else "Fermer l'interrupteur"
                )
            self.switch_button.setText(text)
            self.switch_button.show()
        else:
            self.switch_button.hide()

    def _refresh_quick_controls(self, component: Component | None) -> None:
        if component is not self._quick_controls_component:
            while self.quick_controls_layout.count():
                item = self.quick_controls_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._quick_parameter_controls.clear()
            self._quick_controls_component = component
            if component is not None:
                specs = component.prop_specs()
                for name in self.QUICK_PARAMETER_ORDER.get(component.kind, ()):
                    spec = specs.get(name)
                    if spec is None or spec.ptype != "float":
                        continue
                    self._add_quick_parameter_control(component, name, spec)
        self.quick_controls_group.setVisible(component is not None
                                             and bool(self._quick_parameter_controls))
        if component is not None:
            self._sync_quick_parameter_controls(component)

    def _add_quick_parameter_control(self, component, name, spec) -> None:
        low, high = self.QUICK_PARAMETER_RANGES.get(
            name,
            (
                spec.minimum if spec.minimum is not None else float(spec.default) - 10,
                spec.maximum if spec.maximum is not None else float(spec.default) + 10,
            ),
        )
        value = float(component.get_prop(name))
        low, high = min(low, value), max(high, value)
        logarithmic = low > 0 and high / low >= 100
        if high <= low:
            high = low + 1.0

        row = QVBoxLayout()
        row.setSpacing(3)
        heading = QHBoxLayout()
        label = QLabel(self.QUICK_PARAMETER_LABELS.get(
            name, name.replace("_", " ").capitalize()
        ))
        label.setObjectName("quickParameterLabel")
        value_label = QLabel()
        value_label.setObjectName("quickParameterValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        heading.addWidget(label)
        heading.addWidget(value_label, 1)
        row.addLayout(heading)

        controls = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 1000)
        slider.setToolTip(spec.tip or label.text())
        spinbox = QDoubleSpinBox()
        spinbox.setRange(
            spec.minimum if spec.minimum is not None else -1e12,
            spec.maximum if spec.maximum is not None else 1e12,
        )
        precision = (
            math.ceil(-math.log10(low)) + 2 if low > 0 else 4
        )
        spinbox.setDecimals(max(4, spec.decimals, min(12, precision)))
        spinbox.setSingleStep(spec.step)
        if spec.unit:
            spinbox.setSuffix(f" {spec.unit}")
        spinbox.setFixedWidth(112)
        controls.addWidget(slider, 1)
        controls.addWidget(spinbox)
        row.addLayout(controls)

        container = QWidget()
        container.setObjectName("quickRow")
        container.setLayout(row)
        self.quick_controls_layout.addWidget(container)
        self._quick_parameter_controls[name] = (
            slider, spinbox, value_label, low, high, logarithmic
        )
        slider.valueChanged.connect(
            lambda position, prop=name, current=component:
            self._quick_slider_changed(current, prop, position)
        )
        spinbox.valueChanged.connect(
            lambda new_value, prop=name, current=component:
            self._quick_parameter_changed(current, prop, new_value)
        )
        self._sync_quick_parameter_controls(component)

    def _quick_slider_to_value(self, control, position: int) -> float:
        _, _, _, low, high, logarithmic = control
        fraction = position / 1000
        if logarithmic:
            return low * (high / low) ** fraction
        return low + (high - low) * fraction

    def _quick_value_to_slider(self, control, value: float) -> int:
        _, _, _, low, high, logarithmic = control
        if logarithmic:
            fraction = math.log(max(value, low) / low) / math.log(high / low)
        else:
            fraction = (value - low) / (high - low)
        return round(max(0.0, min(1.0, fraction)) * 1000)

    def _quick_slider_changed(self, component, name: str, position: int) -> None:
        control = self._quick_parameter_controls.get(name)
        if control is None:
            return
        value = self._quick_slider_to_value(control, position)
        spinbox = control[1]
        spinbox.blockSignals(True)
        spinbox.setValue(value)
        spinbox.blockSignals(False)
        self._quick_parameter_changed(component, name, spinbox.value())

    def _quick_parameter_changed(self, component, name: str, value: float) -> None:
        if component is not self._quick_controls_component:
            return
        try:
            component.set_prop(name, value)
        except (ValueError, KeyError) as exc:
            self.statusBar().showMessage(f"Paramètre invalide : {exc}", 5000)
            return
        self.engine.recompute()
        self.is_dirty = True
        self._refresh_title()
        self.refresh_results()

    def _sync_quick_parameter_controls(self, component: Component) -> None:
        for name, control in self._quick_parameter_controls.items():
            slider, spinbox, value_label, _, _, _ = control
            value = float(component.get_prop(name))
            slider.blockSignals(True)
            slider.setValue(self._quick_value_to_slider(control, value))
            slider.blockSignals(False)
            spinbox.blockSignals(True)
            spinbox.setValue(value)
            spinbox.blockSignals(False)
            spec = component.prop_specs()[name]
            suffix = f" {spec.unit}" if spec.unit else ""
            value_label.setText(f"{value:.4g}{suffix}")

    def repair_selected_component(self) -> None:
        component = self.canvas.selected
        if not isinstance(component, Component) or not component.get_prop("blown"):
            return
        component.set_prop("blown", False)
        if hasattr(component, "tstate"):
            component.tstate.clear()
        self.circuit.recompute_nodes()
        self.engine.recompute()
        self._circuit_changed()

    def toggle_selected_switch(self) -> None:
        item = self.canvas.selected
        if not isinstance(item, Switch):
            return
        item.closed = not item.closed
        self.engine.recompute()
        self._circuit_changed()

    def refresh_results(self) -> None:
        solution = self.engine.solution
        colors = self.colors
        muted = colors["muted"]
        mode = "Transitoire" if solution.mode == "transient" else "Régime DC"
        self.results_summary.setText(
            f"{mode} · {len(self.circuit.nodes)} nœud(s) · "
            f"{self.circuit.mesh_count()} maille(s)"
        )
        header = (
            "<tr>"
            f"<td style='color:{muted}; font-size:9pt'>Composant</td>"
            f"<td align='right' style='color:{muted}; font-size:9pt'>U (V)</td>"
            f"<td align='right' style='color:{muted}; font-size:9pt'>I (A)</td>"
            f"<td align='right' style='color:{muted}; font-size:9pt'>P (W)</td>"
            "</tr>"
        )
        rows = []
        for component in self.circuit.components:
            result = solution.branches.get(component.label)
            if result is None:
                continue
            state = (
                f" · <span style='color:{colors['warning']}'>"
                f"{html.escape(result.message)}</span>"
                if result.message else ""
            )
            formula = html.escape(self._calculation_formula(component, result))
            rows.append(
                "<tr>"
                f"<td><b>{html.escape(component.label)}</b></td>"
                f"<td align='right'>{result.u:.5g}</td>"
                f"<td align='right'>{result.i:.5g}</td>"
                f"<td align='right'>{result.p:.5g}</td>"
                "</tr>"
                "<tr>"
                f"<td colspan='4' style='color:{muted}; font-size:9pt'>"
                f"{formula}{state}</td>"
                "</tr>"
            )
        if rows:
            body = (
                "<table cellpadding='3' cellspacing='0' width='100%'>"
                f"{header}{''.join(rows)}</table>"
            )
        else:
            body = (
                f"<span style='color:{muted}'>Aucune branche à calculer pour "
                "l'instant.</span>"
            )
        notices = [
            f"<span style='color:{colors['error']}'>{html.escape(error)}</span>"
            for error in solution.errors
        ]
        notices.extend(
            f"<span style='color:{colors['warning']}'>{html.escape(warning)}</span>"
            for warning in solution.warnings
        )
        if notices:
            body += "<br>" + "<br>".join(notices)
        self.results_text.setText(body)
        self.refresh_inspector()
        self.canvas.update()

    @staticmethod
    def _html_block(lines: list[str]) -> str:
        return "\n<br>".join(lines)

    @staticmethod
    def _metrics_table(result: BranchResult, muted: str) -> str:
        rows = (
            ("U", f"{result.u:.5g} V"),
            ("I", f"{result.i:.5g} A"),
            ("P", f"{result.p:.5g} W"),
        )
        cells = "".join(
            f"<tr><td style='color:{muted}'>{name}</td>"
            f"<td align='right'><b>{value}</b></td></tr>"
            for name, value in rows
        )
        return (
            "<table cellpadding='2' cellspacing='0' width='100%'>"
            f"{cells}</table>"
        )

    @staticmethod
    def _calculation_formula(
        component: Component, result: BranchResult
    ) -> str:
        u, i, p = result.u, result.i, result.p
        power = f"P = U×I = {u:.5g}×{i:.5g} = {p:.5g} W"
        if component.get_prop("blown"):
            return "I = 0 (branche ouverte)"
        if isinstance(component, Generator):
            if component.source_type is SourceType.VOLTAGE:
                return f"U = Us + ri×I ; {power}"
            if component.ri == 0:
                return f"I = −Is ; {power}"
            return f"I = U/ri − Is ; {power}"
        if isinstance(component, Fuse):
            return "I = 0 (fusible ouvert)" if component.blown else (
                f"I = U/Rf = {u:.5g}/{component.resistance:.5g} A ; {power}"
            )
        if isinstance(component, (Diode, Led)):
            if component.on:
                return (
                    f"I = (U−Vf)/Ron = ({u:.5g}−{component.vf:.5g})/"
                    f"{component.r_on:.5g} A ; {power}"
                )
            return f"I ≈ U/Roff ; {power}"
        if isinstance(component, Motor):
            return f"I = geq×U + i0 ; {power}"
        if isinstance(component, Lamp):
            return f"I = U/R = {u:.5g}/{component.resistance:.5g} A ; {power}"
        if isinstance(component, Capacitor):
            return "I = C×dU/dt (transitoire ; I ≈ 0 en DC) ; " + power
        if isinstance(component, Inductor):
            return "U = L×dI/dt + Rw×I ; " + power
        if isinstance(component, Potentiometer):
            r1, r2 = component.sections
            return f"I1 = U1/R1 ({r1:.5g} Ω), I2 = U2/R2 ({r2:.5g} Ω) ; {power}"
        if isinstance(component, Voltmeter):
            return f"I = U/Rint = {u:.5g}/{component.r_int:.5g} A ; {power}"
        if isinstance(component, Ammeter):
            return f"U = I×Rsh = {i:.5g}×{component.r_sh:.5g} V ; {power}"
        if isinstance(component, Ohmmeter):
            return f"I = U/Rint − Itest ; {power}"
        if isinstance(component, Switch):
            return (
                f"I = U/Rcontact = {u:.5g}/{component.resistance:.5g} A ; "
                f"{power}"
            )
        if isinstance(component, Resistor):
            return (
                f"I = U/R = {u:.5g}/{component.resistance:.5g} A ; {power}"
            )
        return f"U = Vp−Vn ; {power}"

    def recompute(self) -> None:
        self.engine.recompute()
        self.refresh_results()

    def edit_selected(self) -> None:
        component = self.canvas.selected
        if not isinstance(component, Component):
            return
        dialog = PropertyDialog(component, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                dialog.apply()
                self.circuit.recompute_nodes()
                self.engine.recompute()
                self._circuit_changed()
            except (ValueError, KeyError) as exc:
                QMessageBox.critical(self, "Propriété invalide", str(exc))

    def rotate_selected(self) -> None:
        if isinstance(self.canvas.selected, Component):
            self.canvas.rotate_component(self.canvas.selected)

    def create_custom_component(self) -> None:
        dialog = CustomComponentDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_field.text().strip()
        symbol = dialog.symbol_field.text().strip()
        if not name or not symbol:
            QMessageBox.warning(self, "Composant incomplet",
                                "Le nom et le symbole sont obligatoires.")
            return
        x, y = self.canvas.scene_pos(QPointF(
            self.canvas.width() / 2, self.canvas.height() / 2
        ))
        component = create_component(
            Kind.CUSTOM, x, y,
            custom_name=name,
            symbol=symbol,
            resistance=dialog.resistance_field.value(),
        )
        self.circuit.add(component)
        self.engine.recompute()
        self.canvas.set_mode("select")
        self.canvas.set_selection(component)
        self._circuit_changed()

    def delete_selected(self) -> None:
        items = list(self.canvas.selected_items)
        if not items and self.canvas.selected is not None:
            items = [self.canvas.selected]
        if items:
            for item in items:
                if isinstance(item, VoltageArrow):
                    self.circuit.remove_arrow(item)
                else:
                    self.circuit.remove(getattr(item, "label", ""))
            self.canvas.set_selections([])
            self.engine.recompute()
            self._circuit_changed()

    def new_project(self) -> None:
        if not self._confirm_unsaved_changes():
            return
        self.circuit = Circuit()
        self.engine = SimulationEngine(self.circuit)
        self.canvas.circuit = self.circuit
        self.canvas.engine = self.engine
        self.canvas.set_selections([])
        self.project_path = None
        self.scenario_text = ""
        self.is_dirty = False
        self.engine.recompute()
        self._circuit_changed()
        self.is_dirty = False
        self._refresh_title()

    def open_project(self) -> None:
        if not self._confirm_unsaved_changes():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet VoltForge", "",
            "Projet VoltForge (*.voltforge);;"
            "Anciens projets JSON (*.vfproj.json *.json)",
        )
        if not filename:
            return
        try:
            path = Path(filename)
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    data = json.loads(archive.read("circuit.vfdata").decode("utf-8"))
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
            circuit = Circuit.from_dict(data)
            self.circuit = circuit
            self.engine = SimulationEngine(circuit)
            self.canvas.circuit = circuit
            self.canvas.engine = self.engine
            self.canvas.set_selection(None)
            self.project_path = path
            self.scenario_text = data.get("scenario", "")
            self.engine.recompute()
            self._circuit_changed()
            self.is_dirty = False
            self._refresh_title()
        except (
            OSError, ValueError, KeyError, TypeError, UnicodeDecodeError,
            zipfile.BadZipFile,
        ) as exc:
            QMessageBox.critical(self, "Ouverture impossible", str(exc))

    def save_project(self) -> bool:
        if self.project_path is None:
            return self.save_project_as()
        return self._write_project(self.project_path)

    def save_project_as(self) -> bool:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le projet", "Mon circuit.voltforge",
            "Projet VoltForge (*.voltforge)",
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != ".voltforge":
            path = path.with_name(path.name + ".voltforge")
        if self._write_project(path):
            self.project_path = path
            self._refresh_title()
            return True
        return False

    def _write_project(self, path: Path) -> bool:
        try:
            data = json.dumps(
                self.circuit.to_dict(self.scenario_text),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            package = io.BytesIO()
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.txt", "VoltForge project\nformat=1\n")
                archive.writestr("circuit.vfdata", data)
            path.write_bytes(package.getvalue())
            self.is_dirty = False
            self._refresh_title()
            self.statusBar().showMessage(f"Projet enregistré : {path}", 5000)
            return True
        except OSError as exc:
            QMessageBox.critical(self, "Enregistrement impossible", str(exc))
            return False

    def _confirm_unsaved_changes(self) -> bool:
        if not self.is_dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Modifications non enregistrées")
        box.setText("Voulez-vous enregistrer les modifications du circuit ?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def export_diagram(self, extension: str | None = None) -> None:
        filters = (
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;SVG (*.svg);;PDF (*.pdf)"
        )
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "Exporter le schéma", f"circuit.{extension or 'png'}", filters
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            suffix = extension or selected_filter.split("*.")[-1].split(")")[0]
            path = path.with_suffix("." + suffix)
        try:
            export_static(self.canvas, str(path))
            self.statusBar().showMessage(f"Schéma exporté : {path}", 5000)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.critical(self, "Export impossible", str(exc))

    def open_scenario_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Simulation pas à pas")
        dialog.resize(780, 520)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "Réglez les paramètres, puis ajoutez les changements souhaités. "
            "Aucun code de scénario à saisir."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        settings = QFormLayout()
        duration = QDoubleSpinBox()
        duration.setRange(0.1, 600)
        duration.setDecimals(2)
        duration.setValue(3)
        duration.setSuffix(" s")
        fps = QSpinBox()
        fps.setRange(1, 60)
        fps.setValue(15)
        step = QDoubleSpinBox()
        step.setRange(0.1, 1000)
        step.setDecimals(1)
        step.setValue(5)
        step.setSuffix(" ms")
        settings.addRow("Durée", duration)
        settings.addRow("Images par seconde", fps)
        settings.addRow("Pas de calcul", step)
        layout.addLayout(settings)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(
            ["Temps (s)", "Composant", "Paramètre", "Nouvelle valeur"]
        )
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(220)
        layout.addWidget(table, 1)
        row_buttons = QHBoxLayout()
        add_button = QPushButton("Ajouter un changement")
        remove_button = QPushButton("Retirer la ligne")
        row_buttons.addWidget(add_button)
        row_buttons.addWidget(remove_button)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        supported_properties = set(PROP_ALIASES.values())
        property_labels = {
            "voltage": "Tension",
            "current": "Courant",
            "ri": "Résistance interne",
            "resistance": "Résistance",
            "closed": "Interrupteur fermé",
            "r_on": "Résistance (fermé)",
            "r_off": "Résistance (ouvert)",
            "capacitance": "Capacité",
            "v0": "Tension initiale",
            "inductance": "Inductance",
            "r_w": "Résistance de bobine",
            "p_max": "Puissance maximale",
        }

        def add_event_row() -> None:
            if not self.circuit.components:
                QMessageBox.information(
                    dialog, "Aucun composant",
                    "Placez un composant avant de configurer un événement.",
                )
                return
            row = table.rowCount()
            table.insertRow(row)
            time_editor = QDoubleSpinBox()
            time_editor.setRange(0, 600)
            time_editor.setDecimals(3)
            time_editor.setSingleStep(0.1)
            time_editor.setValue(min(0.5, duration.value()))
            table.setCellWidget(row, 0, time_editor)
            target_editor = QComboBox()
            target_editor.addItems(
                [component.label for component in self.circuit.components]
            )
            table.setCellWidget(row, 1, target_editor)
            property_editor = QComboBox()
            table.setCellWidget(row, 2, property_editor)
            value_editor = QLineEdit()
            table.setCellWidget(row, 3, value_editor)

            def update_value() -> None:
                component = self.circuit.get(target_editor.currentText())
                prop = property_editor.currentData()
                if component is None or not prop:
                    current = table.cellWidget(row, 3)
                    if isinstance(current, QLineEdit):
                        current.clear()
                    return
                value = component.get_prop(prop)
                spec = component.prop_specs()[prop]
                current = table.cellWidget(row, 3)
                if spec.ptype == "bool":
                    if not isinstance(current, QComboBox):
                        current = QComboBox()
                        current.addItem("Fermé / activé", "true")
                        current.addItem("Ouvert / désactivé", "false")
                        table.setCellWidget(row, 3, current)
                    current.setCurrentIndex(
                        current.findData(str(bool(value)).lower())
                    )
                else:
                    if not isinstance(current, QLineEdit):
                        current = QLineEdit()
                        table.setCellWidget(row, 3, current)
                    current.setText(str(value))
                    current.setPlaceholderText(
                        f"Valeur en {spec.unit}" if spec.unit else "Nouvelle valeur"
                    )

            def update_properties() -> None:
                component = self.circuit.get(target_editor.currentText())
                property_editor.clear()
                if component is None:
                    return
                names = [
                    name for name, spec in component.prop_specs().items()
                    if name in supported_properties and spec.ptype in ("float", "bool")
                ]
                for name in names:
                    property_editor.addItem(property_labels.get(name, name), name)
                update_value()

            target_editor.currentTextChanged.connect(update_properties)
            property_editor.currentTextChanged.connect(update_value)
            update_properties()

        def build_scenario() -> str:
            lines = [
                f"loop 0s {duration.value():g}s",
                f"fps {fps.value()}",
                f"dt {step.value():g}ms",
            ]
            for row in range(table.rowCount()):
                time_editor = table.cellWidget(row, 0)
                target_editor = table.cellWidget(row, 1)
                property_editor = table.cellWidget(row, 2)
                value_editor = table.cellWidget(row, 3)
                if time_editor.value() > duration.value():
                    raise ValueError(
                        f"Le temps de la ligne {row + 1} dépasse la durée choisie."
                    )
                prop = property_editor.currentData()
                if not target_editor.currentText() or not prop:
                    raise ValueError(f"Complétez les paramètres de la ligne {row + 1}.")
                value = (
                    str(value_editor.currentData())
                    if isinstance(value_editor, QComboBox)
                    else value_editor.text().strip()
                )
                if not value:
                    raise ValueError(f"Indiquez une valeur à la ligne {row + 1}.")
                lines.append(
                    f"t={time_editor.value():g}s: "
                    f"{target_editor.currentText()}.{prop}={value}"
                )
            scenario_text = "\n".join(lines)
            self.engine.load_program(scenario_text)
            if self.engine.program_errors:
                raise ValueError("\n".join(self.engine.program_errors))
            self._scenario_text_changed(scenario_text)
            return scenario_text

        add_button.clicked.connect(add_event_row)
        remove_button.clicked.connect(
            lambda: table.removeRow(table.currentRow())
            if table.currentRow() >= 0 else None
        )
        if self.circuit.components:
            add_event_row()

        buttons = QHBoxLayout()
        play_button = QPushButton("Lancer la simulation")
        stop_button = QPushButton("Arrêter")
        gif_button = QPushButton("Exporter en GIF…")
        close_button = QPushButton("Fermer")
        for button in (play_button, stop_button, gif_button, close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        def start_playback() -> None:
            try:
                build_scenario()
                if self.engine.is_transient:
                    self.engine.end_transient(restore=True)
                self.engine.begin_transient(self.engine.program)
                self.canvas.update()
                self.refresh_results()
                self._play_timer.start()
            except (RuntimeError, ValueError) as exc:
                QMessageBox.warning(dialog, "Simulation impossible", str(exc))

        def stop_playback() -> None:
            self._play_timer.stop()
            if self.engine.is_transient:
                self.engine.end_transient(restore=True)
            self.refresh_results()

        def make_gif() -> None:
            try:
                build_scenario()
            except ValueError as exc:
                QMessageBox.warning(dialog, "Paramètres à vérifier", str(exc))
                return
            filename, _ = QFileDialog.getSaveFileName(
                dialog, "Exporter l'animation", "simulation.gif", "GIF animé (*.gif)"
            )
            if not filename:
                return
            if not filename.lower().endswith(".gif"):
                filename += ".gif"
            progress = QProgressDialog(
                "Simulation et capture des images…", None, 0,
                max(1, self.engine.program.frame_count), dialog,
            )
            progress.setWindowTitle("Export GIF")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            try:
                count = export_gif(
                    self.engine, self.canvas, self.scenario_text, filename,
                    lambda current, total: (
                        progress.setMaximum(total),
                        progress.setValue(current),
                        QApplication_process_events(),
                    ),
                )
                QMessageBox.information(
                    dialog, "Export terminé",
                    f"GIF créé avec {count} images :\n{filename}",
                )
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.critical(dialog, "Export impossible", str(exc))
            finally:
                progress.close()
                self.refresh_results()

        play_button.clicked.connect(start_playback)
        stop_button.clicked.connect(stop_playback)
        gif_button.clicked.connect(make_gif)
        close_button.clicked.connect(dialog.accept)
        dialog.exec()

    def _open_legacy_scenario_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Programme de simulation")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlaceholderText(
            "loop 0s 3s\nfps 15\nt=0s: G1.voltage = 0V\nt=1s: G1.voltage = 12V"
        )
        editor.setPlainText(self.scenario_text)
        layout.addWidget(editor, 1)
        info = QLabel(
            "Syntaxe : t=1s: G1.voltage=12V ; K1.closed=true "
            "— propriétés séparées par des points-virgules."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        button_row = QHBoxLayout()
        load_button = QPushButton("Charger…")
        save_button = QPushButton("Enregistrer…")
        play_button = QPushButton("Lancer")
        stop_button = QPushButton("Arrêter")
        gif_button = QPushButton("Exporter en GIF…")
        close_button = QPushButton("Fermer")
        for button in (load_button, save_button, play_button, stop_button,
                       gif_button, close_button):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        def load_text():
            filename, _ = QFileDialog.getOpenFileName(
                dialog, "Charger un scénario", "", "Scénarios texte (*.txt);;Tous les fichiers (*)"
            )
            if filename:
                try:
                    editor.setPlainText(Path(filename).read_text(encoding="utf-8"))
                except OSError as exc:
                    QMessageBox.critical(dialog, "Lecture impossible", str(exc))

        def save_text():
            filename, _ = QFileDialog.getSaveFileName(
                dialog, "Enregistrer le scénario", "scenario.txt",
                "Scénarios texte (*.txt)",
            )
            if filename:
                try:
                    Path(filename).write_text(editor.toPlainText(), encoding="utf-8")
                except OSError as exc:
                    QMessageBox.critical(dialog, "Écriture impossible", str(exc))

        def start_playback():
            self._scenario_text_changed(editor.toPlainText())
            program = self.engine.load_program(self.scenario_text)
            if self.engine.program_errors:
                QMessageBox.warning(
                    dialog, "Scénario invalide",
                    "\n".join(self.engine.program_errors),
                )
                return
            if program.duration <= 0:
                QMessageBox.warning(dialog, "Scénario vide",
                                    "Ajoutez un événement ou une directive loop.")
                return
            try:
                self.engine.begin_transient(program)
                self.canvas.update()
                self.refresh_results()
                self._play_timer.start()
            except (RuntimeError, ValueError) as exc:
                QMessageBox.critical(dialog, "Simulation impossible", str(exc))

        def stop_playback():
            self._play_timer.stop()
            if self.engine.is_transient:
                self.engine.end_transient(restore=True)
            self.refresh_results()

        def make_gif():
            self._scenario_text_changed(editor.toPlainText())
            filename, _ = QFileDialog.getSaveFileName(
                dialog, "Exporter l'animation", "simulation.gif", "GIF animé (*.gif)"
            )
            if not filename:
                return
            if not filename.lower().endswith(".gif"):
                filename += ".gif"
            self.engine.load_program(self.scenario_text)
            if self.engine.program_errors:
                QMessageBox.warning(
                    dialog, "Scénario invalide",
                    "\n".join(self.engine.program_errors),
                )
                return
            progress = QProgressDialog(
                "Simulation et capture des images…", None, 0,
                max(1, self.engine.program.frame_count), dialog,
            )
            progress.setWindowTitle("Export GIF")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            try:
                count = export_gif(
                    self.engine, self.canvas, self.scenario_text, filename,
                    lambda current, total: (
                        progress.setMaximum(total),
                        progress.setValue(current),
                        QApplication_process_events(),
                    ),
                )
                QMessageBox.information(
                    dialog, "Export terminé",
                    f"GIF créé avec {count} images :\n{filename}",
                )
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.critical(dialog, "Export impossible", str(exc))
            finally:
                progress.close()
                self.refresh_results()

        load_button.clicked.connect(load_text)
        save_button.clicked.connect(save_text)
        play_button.clicked.connect(start_playback)
        stop_button.clicked.connect(stop_playback)
        gif_button.clicked.connect(make_gif)
        close_button.clicked.connect(dialog.accept)
        dialog.finished.connect(
            lambda: self._scenario_text_changed(editor.toPlainText())
        )
        dialog.exec()

    def _advance_playback(self) -> None:
        self.engine.advance(0.02)
        self.canvas.update()
        self.refresh_results()
        if self.engine.finished:
            self._play_timer.stop()
            self.engine.end_transient(restore=False)
            self.refresh_results()

    def closeEvent(self, event) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.engine.end_transient(restore=True)
        if self._confirm_unsaved_changes():
            event.accept()
        else:
            event.ignore()


def QApplication_process_events() -> None:
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
