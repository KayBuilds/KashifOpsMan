"""System-wide low-level mouse hook (WH_MOUSE_LL) on a dedicated thread.

The hook only answers "is a mouse button held and has the cursor moved past
the system drag threshold?". It cannot tell an Explorer file drag from a
rubber-band selection or a window move; the drag detector confirms that
separately with an OLE probe (see detector.py).

Windows silently removes low-level hooks whose callback is slow
(LowLevelHooksTimeout), so the callback does nothing but compare integers and
emit a Qt signal on state changes.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from drift.win32 import api
from drift.win32.api import LRESULT, ULONG_PTR, kernel32, user32

log = logging.getLogger(__name__)

WH_MOUSE_LL = 14
HC_ACTION = 0
WM_QUIT = 0x0012
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205

_DOWN = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right"}
_UP = {WM_LBUTTONUP: "left", WM_RBUTTONUP: "right"}


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class MouseHook(QObject):
    """Emits drag_started / drag_ended from a background hook thread.

    Signals are delivered to the GUI thread as queued connections.
    """

    drag_started = Signal()
    drag_ended = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._proc = HOOKPROC(self._callback)  # keep a reference: ctypes won't
        self._threshold = api.drag_threshold()
        self._button: str | None = None
        self._origin = (0, 0)
        self._dragging = False

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="drift-mouse-hook", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self._thread_id != 0

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(1.0)

    def _run(self) -> None:
        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            log.error("SetWindowsHookExW failed: error %d", ctypes.get_last_error())
            self._ready.set()
            return
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        log.info("Mouse hook installed (drag threshold %s)", self._threshold)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWindowsHookEx(hook)
            log.info("Mouse hook removed")

    def _callback(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == HC_ACTION:
            info = MSLLHOOKSTRUCT.from_address(l_param)
            if info.dwExtraInfo != api.DRIFT_INPUT_MARKER:
                self._handle(w_param, info.pt.x, info.pt.y)
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle(self, msg: int, x: int, y: int) -> None:
        if msg == WM_MOUSEMOVE:
            if self._button and not self._dragging:
                if abs(x - self._origin[0]) > self._threshold[0] or abs(y - self._origin[1]) > self._threshold[1]:
                    self._dragging = True
                    self.drag_started.emit()
        elif msg in _DOWN:
            if self._button is None:
                self._button = _DOWN[msg]
                self._origin = (x, y)
                self._dragging = False
        elif msg in _UP:
            if self._button == _UP[msg]:
                self._button = None
                if self._dragging:
                    self._dragging = False
                    self.drag_ended.emit()
