"""Thin ctypes wrappers around the handful of Win32 calls Drift needs.

Importing this module on a non-Windows platform raises ImportError, so callers
can fall back gracefully during development.
"""
from __future__ import annotations

import sys

if sys.platform != "win32":
    raise ImportError("drift.win32 is only available on Windows")

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t

# Virtual keys
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_ESCAPE = 0x1B

MODIFIER_VK = {"shift": VK_SHIFT, "ctrl": VK_CONTROL, "alt": VK_MENU}

# System metrics
SM_CXDRAG = 68
SM_CYDRAG = 69

# Window styles
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

# SendInput
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001

# Marker placed in dwExtraInfo of input we synthesise, so our own hook can
# recognise (and ignore) it.
DRIFT_INPUT_MARKER = 0x44524654  # "DRFT"

# SHQueryUserNotificationState
QUNS_BUSY = 2  # a full-screen app is running
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    # MOUSEINPUT is the largest member of the real union, so it alone gives
    # the correct size.
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(ctypes.c_int)]
shell32.SHQueryUserNotificationState.restype = ctypes.c_long
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

ERROR_ALREADY_EXISTS = 183


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def modifier_down(name: str) -> bool:
    return key_down(MODIFIER_VK[name])


def any_mouse_button_down() -> bool:
    # GetAsyncKeyState reports logical buttons (swap setting applied), so
    # check both: right-drags of files are real OLE drags too.
    return key_down(VK_LBUTTON) or key_down(VK_RBUTTON)


def drag_threshold() -> tuple[int, int]:
    return user32.GetSystemMetrics(SM_CXDRAG), user32.GetSystemMetrics(SM_CYDRAG)


def nudge_cursor() -> None:
    """Move the cursor 1px and back.

    OLE's DoDragDrop loop only re-hit-tests drop targets on input. When our
    window appears under a cursor that is standing still, this makes OLE
    notice it immediately instead of on the user's next movement.
    """
    inputs = (INPUT * 2)()
    for i, dx in enumerate((1, -1)):
        inputs[i].type = INPUT_MOUSE
        inputs[i].u.mi = MOUSEINPUT(dx, 0, 0, MOUSEEVENTF_MOVE, 0, DRIFT_INPUT_MARKER)
    user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def make_noactivate_toolwindow(hwnd: int) -> None:
    """Never take focus away from Explorer and stay out of Alt+Tab."""
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def fullscreen_app_running() -> bool:
    state = ctypes.c_int(0)
    if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value in (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)


_mutex_handle = None


def acquire_single_instance(name: str) -> bool:
    """Return False if another instance already holds the named mutex."""
    global _mutex_handle
    _mutex_handle = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS
