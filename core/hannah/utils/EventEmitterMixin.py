from typing import Callable

class EventEmitterMixin:
    # Event-System
    @property
    def _listeners(self) -> dict:
        if not hasattr(self, '_lazy_listeners'):
            self._lazy_listeners = {}
        return self._lazy_listeners

    def on(self, event: str, fn: Callable):
        self._listeners.setdefault(event, []).append(fn)

    def _emit(self, event: str, *args):
        for fn in self._listeners.get(event, []):
            fn(self, *args)