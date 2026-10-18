"""Decides when the wheel should be probing, showing, or hidden.

Detection is two-stage:

1. Gesture (cheap, global): the low-level mouse hook reports "button held and
   moved past the drag threshold". While that lasts, we poll the modifier keys
   every 10 ms with GetAsyncKeyState.
2. Confirmation (exact): when the trigger modifier goes down, the wheel window
   is shown as a near-invisible *probe* under the cursor. It is a registered
   OLE drop target, so if a real file drag is in progress, OLE sends it
   DragEnter carrying the file list within one mouse move. Only then does the
   wheel animate in. A non-file drag or no OLE drag at all (rubber-band
   selection, window move, text selection) never produces a file DragEnter,
   so the wheel stays invisible and is withdrawn.
"""
from __future__ import annotations

import enum
import logging

from PySide6.QtCore import QObject, QTimer, Signal

from drift.config import Settings
from drift.modes import Mode
from drift.win32 import api

log = logging.getLogger(__name__)

POLL_MS = 10


class _Suppress(enum.Enum):
    NONE = 0
    UNTIL_MODIFIER_RELEASE = 1  # probe was rejected; try again on next press
    UNTIL_BUTTON_UP = 2  # Esc cancelled the drag in the source app


class DragDetector(QObject):
    probe = Signal(object)  # Mode: show the probe at the cursor
    mode_changed = Signal(object)  # Mode: switch wheel while it is up
    dismiss = Signal()  # hide the wheel/probe

    def __init__(self, settings: Settings, hook) -> None:
        super().__init__()
        self._settings = settings
        self._enabled = True
        self._active = False  # a drag gesture is in progress
        self._mode: Mode | None = None
        self._suppress = _Suppress.NONE
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        hook.drag_started.connect(self._on_drag_started)
        hook.drag_ended.connect(self._end)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._end()

    def suppress_until_modifier_release(self) -> None:
        """Called when the probe found no file drag."""
        self._mode = None
        self._suppress = _Suppress.UNTIL_MODIFIER_RELEASE

    def _on_drag_started(self) -> None:
        if not self._enabled or self._active:
            return
        if api.fullscreen_app_running():
            log.debug("Drag ignored: full-screen app in foreground")
            return
        self._active = True
        self._mode = None
        self._suppress = _Suppress.NONE
        self._timer.start()
        self._tick()

    def _end(self) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        if self._mode is not None:
            self.dismiss.emit()
        self._mode = None
        self._suppress = _Suppress.NONE

    def _wanted_mode(self) -> Mode | None:
        if not api.modifier_down(self._settings.trigger_modifier):
            return None
        if api.modifier_down(self._settings.tools_modifier):
            return Mode.TOOLS
        return Mode.CONVERT

    def _tick(self) -> None:
        # Safety net in case the hook missed the button-up (e.g. UAC prompt
        # switched desktops mid-drag).
        if not api.any_mouse_button_down():
            self._end()
            return
        if self._suppress is _Suppress.UNTIL_BUTTON_UP:
            return
        if api.key_down(api.VK_ESCAPE):
            if self._mode is not None:
                self.dismiss.emit()
            self._mode = None
            self._suppress = _Suppress.UNTIL_BUTTON_UP
            return

        mode = self._wanted_mode()
        if self._suppress is _Suppress.UNTIL_MODIFIER_RELEASE:
            if mode is None:
                self._suppress = _Suppress.NONE
            return
        if mode == self._mode:
            return
        previous, self._mode = self._mode, mode
        if mode is None:
            self.dismiss.emit()
        elif previous is None:
            self.probe.emit(mode)
        else:
            self.mode_changed.emit(mode)
