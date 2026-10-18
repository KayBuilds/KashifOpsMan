"""Drift: tray app wiring (Phase 1 — detection and an empty wheel)."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from drift import APP_NAME, __version__
from drift.config import Settings, log_dir
from drift.modes import Mode
from drift.wheel import RadialWheel

log = logging.getLogger("drift")


def setup_logging(debug: bool) -> None:
    handler = logging.handlers.RotatingFileHandler(
        log_dir() / "drift.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [handler]
    if sys.stderr is not None:  # None in a windowed PyInstaller build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def make_icon(paused: bool = False) -> QIcon:
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(size / 2, size / 2)
    color = QColor(150, 150, 150) if paused else QColor(255, 138, 61)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    rect = QRectF(-29, -29, 58, 58)
    for i in range(6):  # six wedges with small gaps
        p.drawPie(rect, int((90 - 30 - i * 60 + 4) * 16), int((60 - 8) * 16))
    p.setBrush(QColor(30, 30, 34))
    p.drawEllipse(QPointF(0, 0), 13, 13)
    p.end()
    return QIcon(pix)


class DriftApp:
    def __init__(self, qt_app: QApplication, settings: Settings) -> None:
        self.app = qt_app
        self.settings = settings
        self.hook = None
        self.detector = None

        self.wheel = RadialWheel(settings)
        self.wheel.dropped.connect(self._on_dropped)

        self.tray = QSystemTrayIcon(make_icon(), qt_app)
        self.tray.setToolTip(f"{APP_NAME} — Shift while dragging a file")
        self.tray.setContextMenu(self._build_menu())
        self.tray.show()

        self.wheel.warm_up()
        if sys.platform == "win32":
            self._start_windows_detection()
        else:
            log.warning("Global drag detection is Windows-only; use the tray's test wheel")

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        header = QAction(f"{APP_NAME} {__version__}", menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()

        self.pause_action = QAction("Pause detection", menu, checkable=True)
        self.pause_action.toggled.connect(self._set_paused)
        menu.addAction(self.pause_action)

        test = QAction("Show test wheel", menu)
        test.triggered.connect(lambda: self.wheel.show_preview(Mode.CONVERT))
        menu.addAction(test)
        test_tools = QAction("Show test tools wheel", menu)
        test_tools.triggered.connect(lambda: self.wheel.show_preview(Mode.TOOLS))
        menu.addAction(test_tools)

        logs = QAction("Open log folder", menu)
        logs.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir()))))
        menu.addAction(logs)
        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(quit_action)
        self._menu = menu  # keep alive
        return menu

    def _start_windows_detection(self) -> None:
        from drift.detector import DragDetector
        from drift.win32 import api
        from drift.win32.mouse_hook import MouseHook

        api.make_noactivate_toolwindow(int(self.wheel.winId()))

        self.hook = MouseHook()
        if not self.hook.start():
            self.notify("Drift could not install its mouse hook", "Drag detection is unavailable. See the log.", error=True)
            return
        self.detector = DragDetector(self.settings, self.hook)
        self.detector.probe.connect(self.wheel.start_probe)
        self.detector.mode_changed.connect(self.wheel.set_mode)
        self.detector.dismiss.connect(self.wheel.dismiss)
        self.wheel.probe_shown.connect(api.nudge_cursor)
        self.wheel.probe_rejected.connect(self.detector.suppress_until_modifier_release)
        self.app.aboutToQuit.connect(self.hook.stop)

    def _set_paused(self, paused: bool) -> None:
        self.tray.setIcon(make_icon(paused))
        if self.detector:
            self.detector.set_enabled(not paused)
        self.wheel.dismiss()

    def _on_dropped(self, paths: list, wedge: int, mode: Mode) -> None:
        names = ", ".join(p.name for p in paths[:3]) + ("…" if len(paths) > 3 else "")
        where = "the centre" if wedge < 0 else f"wedge {wedge + 1}"
        log.info("Dropped %s on %s (%s)", [str(p) for p in paths], where, mode.value)
        self.notify(f"Dropped on {where} ({mode.value})", f"{names}\nActions arrive in Phase 2 — nothing was changed.")

    def notify(self, title: str, message: str, error: bool = False) -> None:
        icon = QSystemTrayIcon.Critical if error else QSystemTrayIcon.Information
        self.tray.showMessage(title, message, icon, 4000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drift")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--show-probe", action="store_true", help="tint the invisible probe window")
    args = parser.parse_args(argv)

    setup_logging(args.debug)
    log.info("Starting %s %s (pid %d)", APP_NAME, __version__, os.getpid())

    if sys.platform == "win32":
        from drift.win32 import api

        if not api.acquire_single_instance("Local\\DriftRadialMenuSingleInstance"):
            log.info("Another instance is already running; exiting")
            return 0

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName(APP_NAME)
    qt_app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl+C in the console quits

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("No system tray available")

    settings = Settings.load()
    if args.show_probe:
        settings.debug_show_probe = True
    drift = DriftApp(qt_app, settings)  # noqa: F841 — keep a reference
    return qt_app.exec()
