import logging
from dataclasses import dataclass
from typing import Callable, Optional

from hannah.models.routine import Routine as RoutineModel

log = logging.getLogger(__name__)

def _normalize(s: str) -> str:
    s = s.lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return s


@dataclass
class RoutineAction:
    topic: str = ""
    value: str = ""
    say: str = ""
    room: str = "all"


@dataclass
class Routine:
    name: str
    triggers: list[str]
    actions: list[RoutineAction]
    reply: str = ""


class RoutineManager:
    def __init__(self, db: Callable):
        self._db = db
        self._routines: list[Routine] = []
        self._load()

    def match(self, text: str) -> Optional[Routine]:
        """Prüft ob text einen Routine-Trigger enthält. Lädt vorher aus der Datenbank neu."""
        self._load()
        norm = _normalize(text)
        for routine in self._routines:
            for trigger in routine.triggers:
                if trigger in norm:
                    log.info(f"Routine '{routine.name}' getriggert durch '{trigger}'")
                    return routine
        return None

    def _load(self) -> None:
        try:
            rows = RoutineModel.select(self._db()).all()

            routines: list[Routine] = []
            for r in rows:
                actions = []
                for a in r.actions:
                    if "say" in a:
                        actions.append(RoutineAction(say=a["say"], room=a.get("room", "all")))
                    else:
                        actions.append(RoutineAction(topic=a["topic"], value=str(a.get("value", "true"))))
                routines.append(Routine(
                    name=r.name,
                    triggers=[_normalize(t) for t in r.triggers],
                    actions=actions,
                    reply=r.reply or "",
                ))

            self._routines = routines
            log.info(f"Routines: {len(routines)} Routine(n) aus der Datenbank geladen")
        except Exception as e:
            log.error(f"Routines: Fehler beim Laden der Routinen aus der Datenbank: {e}")
