"""Regression checks for the Qt-free undo/redo history stack."""

from __future__ import annotations

import unittest

from core.circuit import Circuit
from core.components import Resistor
from core.history import History


class HistoryTests(unittest.TestCase):
    def test_undo_redo_walk_through_recorded_states(self) -> None:
        history = History(limit=10)
        history.reset({"value": 0})
        self.assertFalse(history.can_undo)
        self.assertFalse(history.can_redo)

        history.push({"value": 1})
        history.push({"value": 2})
        self.assertTrue(history.can_undo)
        self.assertFalse(history.can_redo)

        self.assertEqual(history.undo(), {"value": 1})
        self.assertTrue(history.can_redo)
        self.assertEqual(history.undo(), {"value": 0})
        self.assertIsNone(history.undo())
        self.assertTrue(history.can_redo)

        self.assertEqual(history.redo(), {"value": 1})
        self.assertEqual(history.redo(), {"value": 2})
        self.assertIsNone(history.redo())

    def test_push_ignores_identical_state_and_drops_redo_branch(self) -> None:
        history = History(limit=10)
        history.reset({"value": 0})
        history.push({"value": 0})
        self.assertFalse(history.can_undo)

        history.push({"value": 1})
        history.undo()
        history.push({"value": 2})
        self.assertFalse(history.can_redo)
        self.assertEqual(history.undo(), {"value": 0})

    def test_depth_limit_drops_oldest_states(self) -> None:
        history = History(limit=3)
        history.reset({"value": 0})
        for value in range(1, 6):
            history.push({"value": value})
        self.assertEqual(len(history), 3)
        self.assertEqual(history.undo(), {"value": 4})
        self.assertEqual(history.undo(), {"value": 3})
        self.assertIsNone(history.undo())

    def test_history_stores_serialized_circuit_snapshots(self) -> None:
        circuit = Circuit()
        circuit.add(Resistor(0, 0, label="R_SNAP", resistance=100))
        history = History(limit=10)
        history.reset(circuit.to_dict())

        circuit.get("R_SNAP").set_prop("resistance", 220)
        history.push(circuit.to_dict())

        restored = Circuit.from_dict(history.undo())
        self.assertEqual(restored.get("R_SNAP").resistance, 100)
        restored = Circuit.from_dict(history.redo())
        self.assertEqual(restored.get("R_SNAP").resistance, 220)

    def test_rejects_a_non_positive_limit(self) -> None:
        with self.assertRaises(ValueError):
            History(limit=0)


if __name__ == "__main__":
    unittest.main()
