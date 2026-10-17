"""VoltForge — pile d'annulation (Undo/Redo) indépendante de Qt.

Conserve des instantanés sérialisés d'un document (typiquement
``Circuit.to_dict()``) dans une pile bornée. ``reset`` installe l'état de
référence, ``push`` enregistre un nouvel état et ``undo`` / ``redo``
renvoient l'instantané à restaurer sans connaître le modèle.

Aucun import Qt : ce module reste testable en headless.
"""

from __future__ import annotations

from typing import Any, List, Optional


class History:
    """Pile d'instantanés avec profondeur maximale et déduplication.

    Un nouvel enregistrement identique à l'état courant est ignoré ; dès
    qu'une édition suit un ``undo``, la branche rétablie est abandonnée.
    """

    def __init__(self, limit: int = 50) -> None:
        if limit < 1:
            raise ValueError("La profondeur d'historique doit être positive.")
        self.limit = limit
        self._states: List[Any] = []
        self._index = -1

    def reset(self, state: Any) -> None:
        """Installe ``state`` comme point de départ (vide l'historique)."""
        self._states = [state]
        self._index = 0

    def push(self, state: Any) -> None:
        """Enregistre un nouvel état après une édition."""
        if self._index >= 0 and state == self._states[self._index]:
            return
        del self._states[self._index + 1:]
        self._states.append(state)
        if len(self._states) > self.limit:
            self._states.pop(0)
        self._index = len(self._states) - 1

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def undo(self) -> Optional[Any]:
        """Recule d'un cran et renvoie l'état à restaurer (sinon ``None``)."""
        if not self.can_undo:
            return None
        self._index -= 1
        return self._states[self._index]

    def redo(self) -> Optional[Any]:
        """Avance d'un cran et renvoie l'état à restaurer (sinon ``None``)."""
        if not self.can_redo:
            return None
        self._index += 1
        return self._states[self._index]

    def __len__(self) -> int:
        return len(self._states)
