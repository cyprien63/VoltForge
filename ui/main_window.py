"""Main VoltForge desktop window and application workflows."""

from __future__ import annotations

import json
import io
import math
from pathlib import Path
import sys
import zipfile

from PyQt6.QtCore import QByteArray, QPointF, QSize, Qt, QTimer, QSettings
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
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
from core.history import History
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
        self.is_dirty = False
        self.history = History()
        self._restoring_history = False
        self._gif_recording = False
        self.theme = QSettings("VoltForge", "VoltForge").value("theme", "dark")
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(20)
        self._play_timer.timeout.connect(self._advance_playback)

        self._create_menu()
        self._create_layout()
        self.set_theme(self.theme)
        self.engine.recompute()
        self.refresh_inspector()
        self.refresh_results()
        self._reset_history()
        self._refresh_playback_ui()
        self.statusBar().showMessage("Prêt — choisissez un outil et cliquez sur la grille.")
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

        edit_menu = self.menuBar().addMenu("Édition")
        self.undo_action = QAction(
            QIcon(str(self._icon_path("undo.svg"))), "Annuler", self
        )
        self.undo_action.setProperty("iconName", "undo.svg")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        edit_menu.addAction(self.undo_action)
        self.redo_action = QAction(
            QIcon(str(self._icon_path("redo.svg"))), "Rétablir", self
        )
        self.redo_action.setProperty("iconName", "redo.svg")
        self.redo_action.setShortcuts([
            QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z"),
        ])
        self.redo_action.triggered.connect(self.redo)
        edit_menu.addAction(self.redo_action)

        simulation_menu = self.menuBar().addMenu("Simulation")
        self.play_action = QAction("Lecture", self)
        self.play_action.setCheckable(True)
        self.play_action.triggered.connect(self.toggle_playback)
        simulation_menu.addAction(self.play_action)
        self.stop_action = QAction("Arrêt", self)
        self.stop_action.triggered.connect(self.stop_playback)
        simulation_menu.addAction(self.stop_action)
        self._add_action(
            simulation_menu, "Enregistrer une animation GIF…",
            self.open_gif_dialog,
        )
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
        toolbar.setObjectName("mainToolbar")
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

        toolbar.addSeparator()
        for action in (self.undo_action, self.redo_action):
            toolbar.addAction(action)
            button = toolbar.widgetForAction(action)
            if button is not None:
                button.setObjectName("historyButton")
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly
                )
                button.setIconSize(QSize(18, 18))

        components_toolbar = self.addToolBar("Composants")
        components_toolbar.setMovable(False)
        components_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        components_toolbar.setIconSize(QSize(22, 22))
        components_toolbar.setObjectName("componentsToolbar")
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
        right.setMinimumWidth(280)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)
        self.selection_group = QGroupBox("Sélection")
        self.selection_layout = QVBoxLayout(self.selection_group)
        self.selection_layout.setSpacing(8)
        self.selection_title = QLabel("Aucun élément sélectionné")
        self.selection_title.setObjectName("selectionTitle")
        self.selection_title.setWordWrap(True)
        self.selection_layout.addWidget(self.selection_title)
        self.selection_label = QLabel("Aucun élément sélectionné")
        self.selection_label.setObjectName("selectionDetail")
        self.selection_label.setWordWrap(True)
        self.selection_label.setStyleSheet("background: transparent; padding: 4px; border: 1px solid transparent;")
        self.selection_layout.addWidget(self.selection_label)
        self.quick_controls_group = QWidget()
        quick_layout = QVBoxLayout(self.quick_controls_group)
        quick_layout.setContentsMargins(0, 4, 0, 0)
        quick_layout.setSpacing(6)
        quick_heading = QLabel("Réglage en direct")
        quick_heading.setObjectName("sectionHeading")
        quick_layout.addWidget(quick_heading)
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
        selection_buttons = QHBoxLayout()
        self.edit_button = QPushButton("Modifier")
        self.edit_button.clicked.connect(self.edit_selected)
        self.rotate_button = QPushButton("Tourner")
        self.rotate_button.clicked.connect(self.rotate_selected)
        self.delete_button = QPushButton("Supprimer")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.edit_button, self.rotate_button, self.delete_button):
            selection_buttons.addWidget(button)
        self.selection_layout.addLayout(selection_buttons)
        self.repair_button = QPushButton("Réparer le composant")
        self.repair_button.clicked.connect(self.repair_selected_component)
        self.repair_button.hide()
        self.selection_layout.addWidget(self.repair_button)
        self.switch_button = QPushButton()
        self.switch_button.clicked.connect(self.toggle_selected_switch)
        self.switch_button.hide()
        self.selection_layout.addWidget(self.switch_button)
        right_layout.addWidget(self.selection_group)

        self.results_group = QGroupBox("Résultats")
        results_layout = QVBoxLayout(self.results_group)
        results_layout.setSpacing(8)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setObjectName("resultsTable")
        self.results_table.setHorizontalHeaderLabels(
            ["Composant", "U (V)", "I (A)", "P (W)"]
        )
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setStretchLastSection(False)
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 4):
            self.results_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.results_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.results_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results_table.setShowGrid(False)
        self.results_table.setAlternatingRowColors(False)
        self.results_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.results_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.results_table.setMinimumHeight(120)
        results_layout.addWidget(self.results_table)

        self.results_text = QLabel("En attente de calcul.")
        self.results_text.setObjectName("resultsDetail")
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
        splitter.setSizes([900, 320])
        simulation_toolbar = self.addToolBar("Simulation")
        simulation_toolbar.setMovable(False)
        simulation_toolbar.setObjectName("simToolbar")
        simulation_toolbar.addAction(self.play_action)
        simulation_toolbar.addAction(self.stop_action)
        simulation_toolbar.addSeparator()
        self.sim_duration = QDoubleSpinBox()
        self.sim_duration.setRange(0.0, 600.0)
        self.sim_duration.setDecimals(1)
        self.sim_duration.setSingleStep(0.5)
        self.sim_duration.setSuffix(" s")
        self.sim_duration.setSpecialValueText("illimitée")
        self.sim_duration.setValue(0.0)
        self.sim_duration.setToolTip(
            "Durée d'une session de lecture (« illimitée » = jusqu'à l'arrêt)."
        )
        simulation_toolbar.addWidget(self.sim_duration)
        self.sim_loop = QCheckBox("Boucler")
        self.sim_loop.setChecked(True)
        self.sim_loop.setToolTip(
            "Repartir de t = 0 à la fin de chaque session (à la manière "
            "du drapeau vert de Scratch)."
        )
        simulation_toolbar.addWidget(self.sim_loop)
        self.sim_time_label = QLabel("t = 0,00 s")
        self.sim_time_label.setObjectName("simTimeLabel")
        simulation_toolbar.addWidget(self.sim_time_label)
        simulation_toolbar.addSeparator()
        self._toolbar_action(
            simulation_toolbar, "Enregistrer GIF…", self.open_gif_dialog
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
        if hasattr(self, "canvas"):
            self.canvas.set_theme(self.theme)
        if self.theme == "light":
            background, panel, field = "#f3f6fb", "#ffffff", "#ffffff"
            text, muted, border = "#1f2937", "#64748b", "#dbe3ed"
            accent, hover, selected = "#0f9f86", "#e9f7f4", "#d8f3ed"
            danger, danger_hover = "#c0392b", "#fbe9e7"
        else:
            background, panel, field = "#111a24", "#192532", "#111a24"
            text, muted, border = "#e5edf5", "#91a2b3", "#304252"
            accent, hover, selected = "#45d2b4", "#253a46", "#23483f"
            danger, danger_hover = "#ff8b93", "#4a2530"
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {background};
                color: {text};
                font-size: 10pt;
            }}
            QMenuBar, QMenu, QToolBar {{
                background: {panel};
                color: {text};
                border: none;
            }}
            QMenuBar {{ padding: 4px 8px; border-bottom: 1px solid {border}; }}
            QMenuBar::item {{ padding: 6px 10px; border-radius: 5px; }}
            QMenuBar::item:selected, QMenu::item:selected {{ background: {hover}; }}
            QMenu {{ border: 1px solid {border}; padding: 5px; }}
            QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 4px; }}
            QToolBar {{ spacing: 6px; padding: 6px 8px; border-bottom: 1px solid {border}; }}
            QToolBar::separator {{ background: {border}; width: 1px; margin: 4px; }}
            QToolButton {{
                background: transparent; border: 1px solid transparent;
                border-radius: 4px; padding: 6px 8px;
            }}
            QToolButton#historyButton {{ padding: 6px 2px; }}
            QToolButton:hover, QPushButton:hover {{ background: {hover}; }}
            QToolButton:checked {{ background: {selected}; color: {accent}; border: 1px solid {accent}; }}
            QPushButton {{
                background: {panel}; border: 1px solid {border};
                border-radius: 4px; padding: 7px 10px;
            }}
            QPushButton:pressed {{ background: {selected}; }}
            QPushButton:disabled {{ color: {muted}; }}
            QPushButton#dangerButton:hover {{
                background: {danger_hover}; color: {danger};
                border: 1px solid {danger};
            }}
            QGroupBox {{
                background: {panel}; border: 1px solid {border}; border-radius: 6px;
                margin-top: 10px; padding: 9px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                left: 10px; padding: 0 6px; background: {panel};
                color: {text}; font-weight: 600; font-size: 10pt;
            }}
            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTableWidget,
            QPlainTextEdit {{
                background: {field}; color: {text}; border: 1px solid {border};
                border-radius: 6px; padding: 5px 7px;
                selection-background-color: {accent};
            }}
            QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus,
            QPlainTextEdit:focus {{ border: 1px solid {accent}; }}
            QTableWidget#resultsTable {{
                background: transparent; border: none; border-radius: 0;
                padding: 0; alternate-background-color: {hover};
                gridline-color: {border};
            }}
            QTableWidget#resultsTable::item {{ padding: 3px 6px; }}
            QHeaderView::section {{
                background: transparent; color: {muted};
                border: none; border-bottom: 1px solid {border};
                padding: 4px 6px; font-weight: 600; font-size: 9pt;
            }}
            QTableCornerButton::section {{ background: transparent; border: none; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 10px; margin: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {border}; min-height: 24px; border-radius: 5px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
            QSplitter::handle {{ background: {border}; width: 1px; }}
            QStatusBar {{
                background: {panel}; color: {muted};
                border-top: 1px solid {border};
            }}
            QLabel#selectionTitle {{
                font-size: 12pt; font-weight: 600; padding-bottom: 2px;
            }}
            QLabel#selectionDetail {{ color: {text}; background: transparent; padding: 6px; border: 1px solid {border}; }}
            QLabel#sectionHeading {{
                color: {text}; font-weight: 600; font-size: 10pt;
                padding: 2px 0;
            }}
            QLabel#resultsDetail {{ color: {muted}; font-size: 9pt; }}
            QLabel#mutedText {{ color: {muted}; font-size: 9pt; }}
            QLabel#quickParameterLabel {{ font-weight: 600; }}
            QLabel#quickParameterValue {{ color: {accent}; font-weight: 600; }}
            QSlider::groove:horizontal {{
                height: 5px; background: {border}; border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
            QSlider::handle:horizontal {{
                background: {accent}; width: 14px; margin: -5px 0;
                border: 2px solid {panel}; border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{ background: {text}; }}
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
        for action in (self.undo_action, self.redo_action):
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
        if not self._restoring_history:
            self._push_history()

    def _push_history(self) -> None:
        """Enregistre l'état courant comme une étape annulable."""
        self.history.push(self.circuit.to_dict())
        self._update_history_actions()

    def _reset_history(self) -> None:
        """Repart d'un historique vierge (nouveau projet, ouverture)."""
        self.history.reset(self.circuit.to_dict())
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(self.history.can_undo)
            self.redo_action.setEnabled(self.history.can_redo)

    def _apply_history_state(self, state) -> None:
        self._restoring_history = True
        try:
            circuit = Circuit.from_dict(state)
            self.circuit = circuit
            self.engine = SimulationEngine(circuit)
            self.canvas.circuit = circuit
            self.canvas.engine = self.engine
            self.canvas.set_selections([])
            self.engine.recompute()
            self._circuit_changed()
        finally:
            self._restoring_history = False
        self._update_history_actions()

    def undo(self) -> None:
        if self._play_timer.isActive() or self.engine.playing:
            return
        state = self.history.undo()
        if state is None:
            return
        self._apply_history_state(state)

    def redo(self) -> None:
        if self._play_timer.isActive() or self.engine.playing:
            return
        state = self.history.redo()
        if state is None:
            return
        self._apply_history_state(state)

    def _selection_changed(self, item) -> None:
        self.refresh_inspector()

    def refresh_inspector(self) -> None:
        item = self.canvas.selected
        selected_count = len(self.canvas.selected_items)
        if selected_count > 1:
            self._refresh_quick_controls(None)
            self.selection_title.setText("Sélection multiple")
            self.selection_label.setText(
                f"{selected_count} éléments sélectionnés\n"
                "Faites glisser pour les déplacer ensemble ; Supprimer pour tout effacer."
            )
            self.edit_button.setEnabled(False)
            self.rotate_button.setEnabled(False)
            self.delete_button.setEnabled(True)
            self.repair_button.hide()
            self.switch_button.hide()
            return
        if item is None:
            self._refresh_quick_controls(None)
            self.selection_title.setText("Aucune sélection")
            self.selection_label.setText(
                f"{len(self.circuit.components)} composant(s), "
                f"{len(self.circuit.wires)} fil(s), {len(self.circuit.nodes)} nœud(s), "
                f"{self.circuit.mesh_count()} maille(s)\n"
                "Cliquez sur un élément pour afficher ses détails."
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
            self.selection_title.setText(item.short_description())
            lines = [item.display_value()]
            if result is not None:
                lines.append(f"U = {result.u:.5g} V")
                lines.append(f"I = {result.i:.5g} A")
                lines.append(self._calculation_formula(item, result))
                if result.message:
                    lines.append(result.message)
                if isinstance(item, Motor):
                    lines.append(f"Vitesse = {item.rpm(result.i):.0f} tr/min")
            detail = "\n".join(line for line in lines if line)
        elif isinstance(item, VoltageArrow):
            self._refresh_quick_controls(None)
            item.resolve_nodes(self.circuit)
            value = item.voltage(self.engine.solution)
            self.selection_title.setText(item.label)
            detail = "Flèche de tension orientée A → B"
            if item.node_a in self.circuit.nodes:
                detail += f"\nNœud de départ : {self.circuit.nodes[item.node_a].name}"
            if item.node_b in self.circuit.nodes:
                detail += f"\nNœud d'arrivée : {self.circuit.nodes[item.node_b].name}"
            if value is not None:
                detail += f"\nTension : {value:.5g} V"
        else:
            self._refresh_quick_controls(None)
            self.selection_title.setText("Fil")
            detail = f"{getattr(item, 'label', '')}"
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
        slider.sliderReleased.connect(self._commit_quick_parameters)
        spinbox.editingFinished.connect(self._commit_quick_parameters)
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

    def _commit_quick_parameters(self) -> None:
        """Termine un réglage en direct et l'annote dans l'historique."""
        self._push_history()

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
        components = [
            component for component in self.circuit.components
            if component.label in solution.branches
        ]
        self.results_table.setRowCount(len(components))
        for row, component in enumerate(components):
            result = solution.branches[component.label]
            cells = (
                component.label,
                f"{result.u:.5g}",
                f"{result.i:.5g}",
                f"{result.p:.5g}",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                self.results_table.setItem(row, column, item)

        header_height = self.results_table.horizontalHeader().height()
        row_height = self.results_table.verticalHeader().defaultSectionSize()
        rows = max(1, len(components))
        self.results_table.setFixedHeight(header_height + row_height * rows + 4)

        mode = "Transitoire" if solution.mode == "transient" else "Régime DC"
        lines = [
            f"<b>{mode}</b> — {len(self.circuit.nodes)} nœud(s) · "
            f"{self.circuit.mesh_count()} maille(s)",
            "<i>U = Vp − Vn · P = U×I · branche résistive : I = U/R</i>",
        ]
        for component in components:
            result = solution.branches[component.label]
            state = f" — {result.message}" if result.message else ""
            lines.append(
                f"<b>{component.label}</b>{state}<br>"
                f"<i>{self._calculation_formula(component, result)}</i>"
            )
        lines.extend(f"<font color='#ff6978'>{error}</font>" for error in solution.errors)
        lines.extend(f"<font color='#ffc857'>{warning}</font>"
                     for warning in solution.warnings)
        self.results_text.setText("<br>".join(lines))
        self.refresh_inspector()
        self.canvas.update()

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
        self._play_timer.stop()
        if self.engine.playing:
            self.engine.stop_play()
        self.circuit = Circuit()
        self.engine = SimulationEngine(self.circuit)
        self.canvas.circuit = self.circuit
        self.canvas.engine = self.engine
        self.canvas.set_selections([])
        self.project_path = None
        self.is_dirty = False
        self.engine.recompute()
        self._circuit_changed()
        self.is_dirty = False
        self._reset_history()
        self._refresh_title()
        self._refresh_playback_ui()

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
            self._play_timer.stop()
            if self.engine.playing:
                self.engine.stop_play()
            circuit = Circuit.from_dict(data)
            self.circuit = circuit
            self.engine = SimulationEngine(circuit)
            self.canvas.circuit = circuit
            self.canvas.engine = self.engine
            self.canvas.set_selection(None)
            self.project_path = path
            self.engine.recompute()
            self._circuit_changed()
            self.is_dirty = False
            self._reset_history()
            self._refresh_title()
            self._refresh_playback_ui()
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
                self.circuit.to_dict(),
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

    def _format_sim_time(self) -> str:
        """Horloge de la barre de Simulation, avec virgule décimale."""
        return f"t = {self.engine.t:.2f} s".replace(".", ",")

    def toggle_playback(self) -> None:
        """Démarre une session, ou bascule pause / reprise."""
        if self._gif_recording:
            return
        if self.engine.playing:
            if self.engine.paused:
                self.engine.resume_play()
                self._play_timer.start()
            else:
                self.engine.pause_play()
                self._play_timer.stop()
        else:
            self.engine.start_play(
                duration=self.sim_duration.value(),
                loop=self.sim_loop.isChecked(),
            )
            self._play_timer.start()
            self.statusBar().showMessage(
                "Lecture en cours — basculez un interrupteur ou réglez un "
                "curseur pour interagir."
            )
        self._refresh_playback_ui()

    def stop_playback(self) -> None:
        """Termine la session et repasse en régime permanent (DC)."""
        if self._gif_recording:
            return
        self._play_timer.stop()
        if self.engine.playing:
            self.engine.stop_play()
        self.sim_time_label.setText("t = 0,00 s")
        self._refresh_playback_ui()
        self.canvas.update()
        self.refresh_results()

    def _refresh_playback_ui(self) -> None:
        """Synchronise les commandes de Simulation avec l'état du moteur."""
        if not self.engine.playing:
            text, checked = "Lecture", False
        elif self.engine.paused:
            text, checked = "Reprendre", False
        else:
            text, checked = "Pause", True
        self.play_action.setText(text)
        self.play_action.setChecked(checked)
        self.stop_action.setEnabled(self.engine.playing)
        self.sim_time_label.setText(self._format_sim_time())

    def _advance_playback(self) -> None:
        self.engine.advance(0.02)
        self.sim_time_label.setText(self._format_sim_time())
        self.canvas.update()
        self.refresh_results()
        if not self.engine.playing:
            # Session à durée finie terminée : la frame finale reste affichée.
            self._play_timer.stop()
            self.statusBar().showMessage("Session terminée.", 3000)
            self._refresh_playback_ui()

    def open_gif_dialog(self) -> None:
        """Durée + cadence, puis enregistre la session en GIF."""
        if not self.circuit.components:
            QMessageBox.information(
                self, "Aucun composant",
                "Placez un composant avant d'enregistrer une animation.",
            )
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Enregistrer une animation")
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "Le GIF enregistre une session de lecture en direct. Pendant "
            "l'enregistrement, vous pouvez basculer les interrupteurs et "
            "régler les curseurs : vos gestes sont capturés dans le GIF."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        form = QFormLayout()
        duration = QDoubleSpinBox()
        duration.setRange(0.1, 600.0)
        duration.setDecimals(2)
        duration.setValue(3.0)
        duration.setSuffix(" s")
        fps = QSpinBox()
        fps.setRange(1, 60)
        fps.setValue(15)
        form.addRow("Durée", duration)
        form.addRow("Images par seconde", fps)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Enregistrer")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exporter l'animation", "simulation.gif", "GIF animé (*.gif)"
        )
        if not filename:
            return
        if not filename.lower().endswith(".gif"):
            filename += ".gif"
        self._export_gif(filename, duration.value(), fps.value())

    def _export_gif(self, filename: str, duration: float, fps: int) -> None:
        # L'export pilote le moteur lui-même : on coupe le timer de lecture
        # et on verrouille les commandes de session pendant la capture. Le
        # dialogue de progression n'est pas modale et traite les événements
        # Qt : le canevas reste cliquable et les interactions partent dans
        # le GIF.
        self._play_timer.stop()
        self._gif_recording = True
        self.play_action.setEnabled(False)
        self.stop_action.setEnabled(False)
        progress = QProgressDialog(
            "Simulation et capture des images…", None, 0, 100, self
        )
        progress.setWindowTitle("Export GIF")
        progress.setWindowModality(Qt.WindowModality.NonModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        try:
            count = export_gif(
                self.engine, self.canvas, filename, duration, float(fps),
                lambda current, total: (
                    progress.setMaximum(total),
                    progress.setValue(current),
                    QApplication_process_events(),
                ),
            )
            QMessageBox.information(
                self, "Export terminé",
                f"GIF créé avec {count} images :\n{filename}",
            )
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.critical(self, "Export impossible", str(exc))
        finally:
            progress.close()
            self._gif_recording = False
            self.play_action.setEnabled(True)
            self.stop_action.setEnabled(True)
            self._refresh_playback_ui()
            self.canvas.update()
            self.refresh_results()

    def closeEvent(self, event) -> None:
        self._play_timer.stop()
        if self.engine.playing:
            self.engine.stop_play()
        if self._confirm_unsaved_changes():
            event.accept()
        else:
            event.ignore()


def QApplication_process_events() -> None:
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
