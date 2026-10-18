"""The radial wheel: a frameless, topmost, translucent OLE drop target.

Phases:
  HIDDEN   not shown.
  WARMUP   shown fully transparent once at startup so the native window,
           backing store and layered-window setup are paid for before the
           first real drag.
  PROBE    shown under the cursor, painted at alpha 3/255 (invisible but
           hit-testable, so OLE routes the drag to us). Waits for DragEnter.
  SHOWN    a file drag was confirmed; the wheel animates in.
  PREVIEW  opened from the tray menu without a drag, for checking visuals.
"""
from __future__ import annotations

import enum
import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from drift.config import Settings
from drift.modes import Mode
from drift.util import describe, local_paths

log = logging.getLogger(__name__)

ANIM_MS = 120
PROBE_TIMEOUT_MS = 400
PREVIEW_MS = 3000
PAD = 8  # room for antialiasing at the rim

# Phase 1 wheels are empty: the wedge counts match the planned action lists.
WEDGE_COUNT = {Mode.CONVERT: 6, Mode.TOOLS: 7}
ACCENT = {Mode.CONVERT: QColor(255, 138, 61), Mode.TOOLS: QColor(61, 199, 255)}
MODE_LABEL = {Mode.CONVERT: "CONVERT", Mode.TOOLS: "TOOLS"}


class Phase(enum.Enum):
    HIDDEN = 0
    WARMUP = 1
    PROBE = 2
    SHOWN = 3
    PREVIEW = 4


class RadialWheel(QWidget):
    dropped = Signal(list, int, object)  # paths, wedge index (-1 = centre), Mode
    probe_shown = Signal()  # the platform layer nudges the cursor on this
    probe_rejected = Signal()  # no file drag found under the probe

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setWindowTitle("Drift")

        self._settings = settings
        self._radius = settings.wheel_diameter / 2
        self._inner = self._radius * 0.38
        side = int(settings.wheel_diameter + 2 * PAD)
        self.setFixedSize(side, side)

        self._phase = Phase.HIDDEN
        self._mode = Mode.CONVERT
        self._files: list[Path] = []
        self._title = ""
        self._subtitle = ""
        self._hover: int | None = None
        self._progress = 0.0
        self._probe_started = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

        self._probe_timer = QTimer(self, singleShot=True, interval=PROBE_TIMEOUT_MS)
        self._probe_timer.timeout.connect(self._on_probe_timeout)
        self._preview_timer = QTimer(self, singleShot=True, interval=PREVIEW_MS)
        self._preview_timer.timeout.connect(self.dismiss)

        self._title_font = QFont(self.font())
        self._title_font.setPointSizeF(10.5)
        self._title_font.setWeight(QFont.DemiBold)
        self._small_font = QFont(self.font())
        self._small_font.setPointSizeF(8.5)
        self._label_font = QFont(self.font())
        self._label_font.setPointSizeF(7.5)
        self._label_font.setWeight(QFont.Bold)
        self._label_font.setLetterSpacing(QFont.PercentageSpacing, 115)

    # ----------------------------------------------------------------- control

    @property
    def phase(self) -> Phase:
        return self._phase

    def warm_up(self) -> None:
        self._phase = Phase.WARMUP
        self.show()
        QTimer.singleShot(50, self._end_warm_up)

    def _end_warm_up(self) -> None:
        if self._phase is Phase.WARMUP:
            self._hide_now()

    def start_probe(self, mode: Mode) -> None:
        self._mode = mode
        self._files = []
        self._hover = None
        self._progress = 0.0
        self._phase = Phase.PROBE
        self._center_on_cursor()
        self._probe_started = time.perf_counter()
        self.show()
        self.raise_()
        self.update()
        self._probe_timer.start()
        self.probe_shown.emit()

    def set_mode(self, mode: Mode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        self._hover = None
        self.update()

    def show_preview(self, mode: Mode = Mode.CONVERT) -> None:
        """Open the wheel at the cursor without a drag (tray menu)."""
        self._mode = mode
        self._files = []
        self._title, self._subtitle = "photo.heic", "2.4 MB"
        self._hover = None
        self._phase = Phase.PREVIEW
        self._center_on_cursor()
        self.show()
        self.raise_()
        self._anim.start()
        self._preview_timer.start()

    def dismiss(self) -> None:
        if self._phase in (Phase.HIDDEN, Phase.WARMUP):
            return
        self._hide_now()

    def _hide_now(self) -> None:
        self._anim.stop()
        self._probe_timer.stop()
        self._preview_timer.stop()
        self._phase = Phase.HIDDEN
        self._hover = None
        self._files = []
        self.hide()

    def _center_on_cursor(self) -> None:
        # QCursor.pos() is in Qt's logical, DPI-scaled coordinates, which is
        # what move() expects, on any monitor.
        pos = QCursor.pos()
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() // 2)

    def _reveal(self) -> None:
        latency = (time.perf_counter() - self._probe_started) * 1000
        log.info("File drag confirmed %.0f ms after trigger: %s", latency, [p.name for p in self._files])
        self._probe_timer.stop()
        self._title, self._subtitle = describe(self._files)
        self._phase = Phase.SHOWN
        self._anim.start()

    def _on_probe_timeout(self) -> None:
        if self._phase is Phase.PROBE:
            log.debug("No OLE file drag under probe after %d ms; withdrawing", PROBE_TIMEOUT_MS)
            self._reject()

    def _reject(self) -> None:
        self._hide_now()
        self.probe_rejected.emit()

    def _on_anim(self, value: float) -> None:
        self._progress = value
        self.update()

    # ------------------------------------------------------------ drag & drop
    #
    # Shift during an Explorer drag proposes MOVE, Ctrl+Shift proposes LINK.
    # We always answer COPY, so Explorer never deletes or relinks the source.

    def dragEnterEvent(self, event) -> None:
        if self._phase not in (Phase.PROBE, Phase.SHOWN, Phase.PREVIEW):
            event.ignore()
            return
        paths = local_paths(event.mimeData())
        if not paths or not (event.possibleActions() & Qt.CopyAction):
            log.debug("Drag is not local files (formats: %s)", event.mimeData().formats())
            event.ignore()
            if self._phase is Phase.PROBE:
                # Get out of the way so the drop reaches the app underneath.
                QTimer.singleShot(0, self._reject)
            return
        self._files = paths
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if self._phase is Phase.PREVIEW:
            self._preview_timer.stop()
            self._title, self._subtitle = describe(paths)
            self._phase = Phase.SHOWN
            self.update()
        elif self._phase is Phase.PROBE:
            self._reveal()

    def dragMoveEvent(self, event) -> None:
        if not self._files:
            event.ignore()
            return
        self._set_hover(self._wedge_at(event.position()))
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event) -> None:
        self._set_hover(None)

    def dropEvent(self, event) -> None:
        files = list(self._files)
        if not files:
            event.ignore()
            return
        index = self._wedge_at(event.position())
        event.setDropAction(Qt.CopyAction)
        event.accept()
        mode = self._mode
        self._hide_now()
        self.dropped.emit(files, -1 if index is None else index, mode)

    def mousePressEvent(self, event) -> None:
        self.dismiss()

    # ----------------------------------------------------------------- geometry

    def _wedge_count(self) -> int:
        return WEDGE_COUNT[self._mode]

    def _wedge_at(self, pos: QPointF) -> int | None:
        """Wedge under a local position; None for the centre or outside."""
        dx = pos.x() - self.width() / 2
        dy = pos.y() - self.height() / 2
        r = math.hypot(dx, dy)
        if r < self._inner or r > self._radius:
            return None
        n = self._wedge_count()
        span = 360 / n
        # Degrees clockwise from 12 o'clock; wedge 0 is centred at the top.
        angle = (math.degrees(math.atan2(dy, dx)) + 90) % 360
        return int(((angle + span / 2) % 360) // span)

    def _set_hover(self, index: int | None) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    def _wedge_path(self, index: int, outer: float, inner: float, gap_deg: float) -> QPainterPath:
        n = self._wedge_count()
        span = 360 / n
        start_cw = index * span - span / 2 + gap_deg / 2
        sweep = span - gap_deg
        # Qt arcs: degrees counter-clockwise from 3 o'clock.
        qt_start = 90 - start_cw
        outer_rect = QRectF(-outer, -outer, 2 * outer, 2 * outer)
        inner_rect = QRectF(-inner, -inner, 2 * inner, 2 * inner)
        path = QPainterPath()
        path.arcMoveTo(outer_rect, qt_start)
        path.arcTo(outer_rect, qt_start, -sweep)
        path.arcTo(inner_rect, qt_start - sweep, sweep)
        path.closeSubpath()
        return path

    # ----------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        if self._phase in (Phase.HIDDEN, Phase.WARMUP):
            return  # fully transparent
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        R = self._radius

        # Hit-test base. Layered windows are click/drop-through where alpha
        # is 0, so the whole disc always keeps a tiny alpha.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 0, 128, 90) if self._settings.debug_show_probe else QColor(0, 0, 0, 3))
        p.drawEllipse(QPointF(0, 0), R, R)
        if self._phase is Phase.PROBE:
            return

        t = self._progress
        p.setOpacity(t)
        p.scale(0.82 + 0.18 * t, 0.82 + 0.18 * t)
        accent = ACCENT[self._mode]

        # Disc
        p.setBrush(QColor(20, 20, 24, 205))
        p.setPen(QPen(QColor(255, 255, 255, 38), 1))
        p.drawEllipse(QPointF(0, 0), R - 1, R - 1)

        # Wedges
        ring_outer = R - 10
        ring_inner = self._inner + 6
        for i in range(self._wedge_count()):
            path = self._wedge_path(i, ring_outer, ring_inner, gap_deg=2.2)
            if i == self._hover:
                fill = QColor(accent)
                fill.setAlpha(210)
                p.setPen(Qt.NoPen)
            else:
                fill = QColor(255, 255, 255, 16)
                p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.setBrush(fill)
            p.drawPath(path)

        # Centre
        c = self._inner
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 150), 1.5))
        p.setBrush(QColor(12, 12, 14, 235))
        p.drawEllipse(QPointF(0, 0), c, c)
        text_w = int(c * 1.6)

        p.setFont(self._label_font)
        p.setPen(accent)
        p.drawText(QRectF(-c, -c * 0.62, 2 * c, 14), Qt.AlignHCenter | Qt.AlignTop, MODE_LABEL[self._mode])

        p.setFont(self._title_font)
        p.setPen(QColor(245, 245, 247))
        title = QFontMetrics(self._title_font).elidedText(self._title, Qt.ElideMiddle, text_w)
        p.drawText(QRectF(-c, -12, 2 * c, 22), Qt.AlignCenter, title)

        p.setFont(self._small_font)
        p.setPen(QColor(170, 170, 178))
        p.drawText(QRectF(-c, 12, 2 * c, 18), Qt.AlignHCenter | Qt.AlignTop, self._subtitle)
