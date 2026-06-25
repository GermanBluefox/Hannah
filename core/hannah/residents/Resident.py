from abc import ABC, abstractmethod
from typing import Callable, Optional

from hannah.utils import EventEmitterMixin

HOME_PRESENCE_STATE = 1


class Resident(EventEmitterMixin, ABC):
    def __init__(self, roomie_id: str, display_name: str, presence_state: Optional[int] = None, mood: Optional[int] = None):
        self.roomie_id = roomie_id
        self.display_name = display_name
        self.presence_state = presence_state
        self.mood = mood

    @property
    @abstractmethod
    def id(self) -> str:
        """Gibt die berechnete ID des Bewohners zurück."""
        pass

    # ------------------------------------------------------------------
    # Presence

    def is_home(self) -> bool:
        return self.presence_state == HOME_PRESENCE_STATE

    def update(self, display_name: str, presence_state: int, mood: Optional[int] = None):
        """Aktualisiert den Resident und feuert arrival/departure/mood_changed bei Zustandswechsel.

        presence_state ist beim ersten Update None (unbekannt) — dann wird keine
        Transition gemeldet, da es keinen Vorher-Zustand zum Vergleich gibt.
        """
        old_presence = self.presence_state
        old_mood = self.mood

        self.display_name = display_name
        self.presence_state = presence_state
        if mood is not None:
            self.mood = mood

        if old_presence is not None:
            was_home = old_presence == HOME_PRESENCE_STATE
            is_home = self.is_home()
            if is_home and not was_home:
                self._emit("arrival")
            elif was_home and not is_home:
                self._emit("departure")

        if mood is not None and mood != old_mood:
            self._emit("mood_changed", old_mood, mood)
