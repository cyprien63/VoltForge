"""Main VoltForge desktop window and application workflows."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from PyQt6.QtCore import QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.circuit import Circuit
from core.components import Component, Kind, Motor, create_component
from core.simulation import SimulationEngine
from exporters.gif import export_gif
from exporters.static import export_static
from ui.canvas import CircuitCanvas


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


class MainWindow(QMainWindow):
    """Window for circuit authoring, simulation, and export."""

    TOOL_COMPONENTS = (
        (Kind.GENERATOR, "Générateur"),
        (Kind.BATTERY, "Pile"),
        (Kind.RESISTOR, "Résistance"),
        (Kind.POTENTIOMETER, "Potentiomètre"),
        (Kind.SWITCH, "Interrupteur"),
        (Kind.CAPACITOR, "Condensateur"),
        (Kind.INDUCTOR, "Bobine"),
        (Kind.DIODE, "Diode"),
        (Kind.LED, "LED"),
        (Kind.LAMP, "Lampe"),
        (Kind.MOTOR, "Moteur"),
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
         (Kind.RESISTOR, Kind.POTENTIOMETER, Kind.SWITCH,
          Kind.CAPACITOR, Kind.INDUCTOR)),
        ("Semi-conducteurs", "diode.svg", (Kind.DIODE, Kind.LED)),
        ("Actionneurs", "motor.svg", (Kind.LAMP, Kind.MOTOR, Kind.FUSE)),
        ("Mesure", "voltmeter.svg",
         (Kind.VOLTMETER, Kind.AMMETER, Kind.OHMMETER)),
        ("Topologie", "ground.svg", (Kind.GROUND,)),
    )
    ICONS = {
        Kind.GENERATOR: "generator-voltage.svg",
        Kind.BATTERY: "battery.svg",
        Kind.RESISTOR: "resistor.svg",
        Kind.CUSTOM: "custom.svg",
        Kind.POTENTIOMETER: "potentiometer.svg",
        Kind.SWITCH: "switch.svg",
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
        self.setWindowTitle("VoltForge — Conception et simulation électrique")
        self.resize(1280, 800)
        self.circuit = Circuit()
        self.engine = SimulationEngine(self.circuit)
        self.project_path: Path | None = None
        self.scenario_text = ""
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(20)
        self._play_timer.timeout.connect(self._advance_playback)

        self._create_menu()
        self._create_layout()
        self.engine.recompute()
        self.refresh_inspector()
        self.refresh_results()
        self.statusBar().showMessage("Prêt — choisissez un outil et cliquez sur la grille.")

    def _create_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Fichier")
        self._add_action(file_menu, "Nouveau", self.new_project, QKeySequence.StandardKey.New)
        self._add_action(file_menu, "Ouvrir…", self.open_project, QKeySequence.StandardKey.Open)
        self._add_action(file_menu, "Enregistrer", self.save_project, QKeySequence.StandardKey.Save)
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
        self._add_action(simulation_menu, "Scénario…", self.open_scenario_dialog)
        self._add_action(simulation_menu, "Exporter un GIF…", self.open_scenario_dialog)
        self._add_action(simulation_menu, "Recalculer", self.recompute)

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
            button.setIcon(QIcon(str(self._icon_path(icon))))
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(button)
            for kind in kinds:
                action = QAction(
                    QIcon(str(self._icon_path(self.ICONS[kind]))),
                    labels[kind],
                    menu,
                )
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
            QIcon(str(self._icon_path(self.ICONS[Kind.CUSTOM]))),
            "Créer perso…",
            self,
        )
        custom_action.triggered.connect(self.create_custom_component)
        passives_menu.addAction(custom_action)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter = splitter
        outer.addWidget(splitter, 1)

        self.canvas = CircuitCanvas(self.circuit, self.engine)
        self.canvas.circuitChanged.connect(self._circuit_changed)
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.canvas.statusMessage.connect(self.statusBar().showMessage)
        splitter.addWidget(self.canvas)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self.selection_group = QGroupBox("Propriétés")
        self.selection_layout = QVBoxLayout(self.selection_group)
        self.selection_label = QLabel("Aucun élément sélectionné")
        self.selection_label.setWordWrap(True)
        self.selection_layout.addWidget(self.selection_label)
        selection_buttons = QHBoxLayout()
        self.edit_button = QPushButton("Modifier")
        self.edit_button.clicked.connect(self.edit_selected)
        self.rotate_button = QPushButton("Tourner")
        self.rotate_button.clicked.connect(self.rotate_selected)
        self.delete_button = QPushButton("Supprimer")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.edit_button, self.rotate_button, self.delete_button):
            selection_buttons.addWidget(button)
        self.selection_layout.addLayout(selection_buttons)
        right_layout.addWidget(self.selection_group)

        self.results_group = QGroupBox("Résultats MNA")
        results_layout = QVBoxLayout(self.results_group)
        self.results_text = QLabel("En attente de calcul.")
        self.results_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.results_text.setWordWrap(True)
        results_layout.addWidget(self.results_text)
        result_scroll = QScrollArea()
        result_scroll.setWidgetResizable(True)
        result_scroll.setWidget(self.results_group)
        right_layout.addWidget(result_scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([900, 320])
        simulation_toolbar = self.addToolBar("Simulation")
        simulation_toolbar.setMovable(False)
        self._toolbar_action(
            simulation_toolbar, "Scénario / GIF…", self.open_scenario_dialog
        )

    @staticmethod
    def _icon_path(filename: str) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        return base / "assets" / "icons" / filename

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
        self.refresh_inspector()
        self.refresh_results()

    def _selection_changed(self, item) -> None:
        self.refresh_inspector()

    def refresh_inspector(self) -> None:
        item = self.canvas.selected
        if item is None:
            self.selection_label.setText(
                f"{len(self.circuit.components)} composant(s), "
                f"{len(self.circuit.wires)} fil(s), "
                f"{self.circuit.mesh_count()} maille(s)"
            )
            self.edit_button.setEnabled(False)
            self.rotate_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        if isinstance(item, Component):
            result = self.engine.solution.branches.get(item.label)
            detail = f"{item.short_description()}\n{item.display_value()}"
            if result is not None:
                detail += f"\nU = {result.u:.5g} V\nI = {result.i:.5g} A"
                if result.message:
                    detail += f"\n{result.message}"
                if isinstance(item, Motor):
                    detail += f"\nVitesse = {item.rpm(result.i):.0f} tr/min"
        else:
            detail = f"Fil {getattr(item, 'label', '')}"
        self.selection_label.setText(detail)
        self.edit_button.setEnabled(isinstance(item, Component))
        self.rotate_button.setEnabled(isinstance(item, Component))
        self.delete_button.setEnabled(True)

    def refresh_results(self) -> None:
        solution = self.engine.solution
        lines = [
            f"<b>{'Transitoire' if solution.mode == 'transient' else 'Régime DC'}</b>",
            f"{len(self.circuit.nodes)} nœud(s) · {self.circuit.mesh_count()} maille(s)",
        ]
        for component in self.circuit.components:
            result = solution.branches.get(component.label)
            if result is None:
                continue
            state = f" — {result.message}" if result.message else ""
            lines.append(
                f"<b>{component.label}</b>: {result.u:.5g} V · "
                f"{result.i:.5g} A · {result.p:.5g} W{state}"
            )
        lines.extend(f"<font color='#ff6978'>{error}</font>" for error in solution.errors)
        lines.extend(f"<font color='#ffc857'>{warning}</font>"
                     for warning in solution.warnings)
        self.results_text.setText("<br>".join(lines))
        self.refresh_inspector()
        self.canvas.update()

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
        item = self.canvas.selected
        if item is not None:
            self.circuit.remove(getattr(item, "label", ""))
            self.canvas.set_selection(None)
            self.engine.recompute()
            self._circuit_changed()

    def new_project(self) -> None:
        self.circuit = Circuit()
        self.engine = SimulationEngine(self.circuit)
        self.canvas.circuit = self.circuit
        self.canvas.engine = self.engine
        self.canvas.set_selection(None)
        self.project_path = None
        self.scenario_text = ""
        self.engine.recompute()
        self._circuit_changed()

    def open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet VoltForge", "",
            "Projets VoltForge (*.vfproj.json);;Fichiers JSON (*.json)",
        )
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            circuit = Circuit.from_dict(data)
            self.circuit = circuit
            self.engine = SimulationEngine(circuit)
            self.canvas.circuit = circuit
            self.canvas.engine = self.engine
            self.canvas.set_selection(None)
            self.project_path = Path(filename)
            self.scenario_text = data.get("scenario", "")
            self.engine.recompute()
            self._circuit_changed()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Ouverture impossible", str(exc))

    def save_project(self) -> None:
        if self.project_path is None:
            self.save_project_as()
            return
        self._write_project(self.project_path)

    def save_project_as(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le projet", "circuit.vfproj.json",
            "Projet VoltForge (*.vfproj.json)",
        )
        if filename:
            path = Path(filename)
            if not path.name.endswith(".vfproj.json"):
                path = path.with_name(path.name + ".vfproj.json")
            if self._write_project(path):
                self.project_path = path

    def _write_project(self, path: Path) -> bool:
        try:
            path.write_text(
                json.dumps(self.circuit.to_dict(self.scenario_text),
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.statusBar().showMessage(f"Projet enregistré : {path}", 5000)
            return True
        except OSError as exc:
            QMessageBox.critical(self, "Enregistrement impossible", str(exc))
            return False

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
            self.scenario_text = editor.toPlainText()
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
            self.scenario_text = editor.toPlainText()
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
        dialog.finished.connect(lambda: setattr(
            self, "scenario_text", editor.toPlainText()
        ))
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
        event.accept()


def QApplication_process_events() -> None:
    from PyQt6.QtWidgets import QApplication
    QApplication.processEvents()
