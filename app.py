import sys
import os
import subprocess
import threading
import re
import webbrowser
import json
import random
import numpy as np
from itertools import product as iter_product
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError
import shutil

import yt_dlp

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QProgressBar,
    QTextEdit, QTabWidget, QFrame, QComboBox, QGraphicsDropShadowEffect,
    QSizePolicy, QCheckBox, QSlider, QStackedWidget, QScrollArea,
    QGridLayout
)
from PySide6.QtCore import Qt, Signal, QObject, QSize, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QFont, QColor, QIcon, QPalette, QFontDatabase, QPainter, QPen, QBrush, QPixmap


# ─── Resource path helper (works for dev and PyInstaller bundle) ────────────

def resource_path(relative_path):
    """Get absolute path to a resource, works for dev and PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
def get_ffmpeg_path():
    """Get path to ffmpeg, checking bundled location first, then system PATH."""
    # Check if bundled (PyInstaller)
    if hasattr(sys, "_MEIPASS"):
        if sys.platform == "darwin":
            bundled = os.path.join(sys._MEIPASS, "ffmpeg")
        else:
            bundled = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.exists(bundled):
            return bundled
    # Fall back to system PATH
    ffmpeg_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    system_ffmpeg = shutil.which(ffmpeg_name)
    if system_ffmpeg:
        return system_ffmpeg
    return "ffmpeg"  # Hope it is in PATH


# ─── Signal bridge for thread-safe UI updates ───────────────────────────────

class WorkerSignals(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)


# ─── Fretboard Diagram Widget ───────────────────────────────────────────────

class FretboardDiagram(QWidget):
    """Draws a guitar chord fretboard diagram with finger positions."""

    STRING_NAMES = ["E", "A", "D", "G", "B", "e"]

    def __init__(self, frets, shape_name="", barre_fret=0, parent=None):
        super().__init__(parent)
        self.frets = frets          # List of 6 ints: fret per string (-1=muted)
        self.shape_name = shape_name
        self.barre_fret = barre_fret
        self.setMinimumSize(140, 260)
        self.setMaximumWidth(180)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(280)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Layout constants
        top_margin = 50       # Space for shape name + open/mute markers
        bottom_margin = 30
        left_margin = 30
        right_margin = 15
        fret_count = 5

        neck_w = w - left_margin - right_margin
        neck_h = h - top_margin - bottom_margin
        string_spacing = neck_w / 5
        fret_spacing = neck_h / fret_count

        # Determine the start fret for display
        non_muted = [f for f in self.frets if f > 0]
        if non_muted:
            min_fret = min(non_muted)
            max_fret = max(non_muted)
            if max_fret <= 5 and min_fret <= 5:
                start_fret = 1
            else:
                start_fret = min_fret
        else:
            start_fret = 1

        # Draw shape name
        p.setPen(QPen(QColor("#7c3aed")))
        name_font = QFont()
        name_font.setPointSize(11)
        name_font.setBold(True)
        p.setFont(name_font)
        p.drawText(0, 0, w, 22, Qt.AlignCenter, self.shape_name)

        # Draw fret number indicator
        if start_fret > 1:
            p.setPen(QPen(QColor("#999999")))
            fret_font = QFont()
            fret_font.setPointSize(9)
            p.setFont(fret_font)
            p.drawText(2, int(top_margin + fret_spacing * 0.3), f"{start_fret}fr")

        # Draw nut (thick bar at top if open position)
        if start_fret == 1:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#cccccc")))
            p.drawRect(int(left_margin - 2), int(top_margin - 3), int(neck_w + 4), 5)
        else:
            p.setPen(QPen(QColor("#444444"), 1))
            p.drawLine(int(left_margin), int(top_margin), int(left_margin + neck_w), int(top_margin))

        # Draw fret lines
        p.setPen(QPen(QColor("#444444"), 1))
        for i in range(fret_count + 1):
            y = int(top_margin + i * fret_spacing)
            p.drawLine(int(left_margin), y, int(left_margin + neck_w), y)

        # Draw strings
        p.setPen(QPen(QColor("#555555"), 1))
        for i in range(6):
            x = int(left_margin + i * string_spacing)
            p.drawLine(x, int(top_margin), x, int(top_margin + neck_h))

        # Draw barre bar if needed
        if self.barre_fret > 0:
            barre_display_fret = self.barre_fret - start_fret + 1
            if 1 <= barre_display_fret <= fret_count:
                barre_y = int(top_margin + (barre_display_fret - 0.5) * fret_spacing)
                # Find the leftmost and rightmost non-muted strings at the barre fret
                barre_strings = [i for i, f in enumerate(self.frets) if f >= self.barre_fret and f != -1]
                if len(barre_strings) >= 2:
                    x1 = int(left_margin + min(barre_strings) * string_spacing)
                    x2 = int(left_margin + max(barre_strings) * string_spacing)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor("#aaaaaa")))
                    p.drawRoundedRect(x1 - 6, barre_y - 6, x2 - x1 + 12, 12, 6, 6)

        # Draw finger dots, open circles, and mute X markers
        for i in range(6):
            x = int(left_margin + i * string_spacing)
            fret_val = self.frets[i]

            if fret_val == -1:
                # Muted string — draw X above nut
                p.setPen(QPen(QColor("#888888"), 2))
                marker_y = int(top_margin - 16)
                p.drawLine(x - 5, marker_y - 5, x + 5, marker_y + 5)
                p.drawLine(x - 5, marker_y + 5, x + 5, marker_y - 5)
            elif fret_val == 0:
                # Open string — draw circle above nut
                p.setPen(QPen(QColor("#aaaaaa"), 2))
                p.setBrush(Qt.NoBrush)
                marker_y = int(top_margin - 16)
                p.drawEllipse(x - 6, marker_y - 6, 12, 12)
            else:
                # Finger position
                display_fret = fret_val - start_fret + 1
                if 1 <= display_fret <= fret_count:
                    dot_y = int(top_margin + (display_fret - 0.5) * fret_spacing)
                    # Root note gets purple, others get white
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor("#7c3aed")))
                    p.drawEllipse(x - 9, dot_y - 9, 18, 18)

        # Draw string names at bottom
        p.setPen(QPen(QColor("#666666")))
        str_font = QFont()
        str_font.setPointSize(8)
        p.setFont(str_font)
        for i in range(6):
            x = int(left_margin + i * string_spacing)
            p.drawText(x - 6, int(top_margin + neck_h + 5), 12, 20, Qt.AlignCenter, self.STRING_NAMES[i])

        p.end()


# ─── Chord Library Diagram Widget ──────────────────────────────────────────

class ChordLibDiagram(QWidget):
    """Draws a chord diagram with interval labels and click-to-play support."""

    clicked = Signal()
    STRING_NAMES = ["E", "A", "D", "G", "B", "e"]

    def __init__(self, frets, root_idx, interval_map, tuning=None,
                 show_intervals=True, position_label="", parent=None):
        super().__init__(parent)
        self.frets = frets
        self.root_idx = root_idx
        self.interval_map = interval_map  # {semitone_offset: label_str}
        self.tuning = tuning or [4, 9, 2, 7, 11, 4]
        self.show_intervals = show_intervals
        self.position_label = position_label
        self.setMinimumSize(130, 280)
        self.setMaximumWidth(170)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(300)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        top_margin = 50
        bottom_margin = 40
        left_margin = 30
        right_margin = 15
        fret_count = 5

        neck_w = w - left_margin - right_margin
        neck_h = h - top_margin - bottom_margin
        string_spacing = neck_w / 5
        fret_spacing = neck_h / fret_count

        # Determine start fret
        non_muted = [f for f in self.frets if f > 0]
        if non_muted:
            min_fret = min(non_muted)
            max_fret = max(non_muted)
            if max_fret <= 5 and min_fret <= 5:
                start_fret = 1
            else:
                start_fret = min_fret
        else:
            start_fret = 1

        # Position label at top
        if self.position_label:
            p.setPen(QPen(QColor("#888888")))
            pf = QFont()
            pf.setPointSize(8)
            p.setFont(pf)
            p.drawText(0, 0, w, 16, Qt.AlignCenter, self.position_label)

        # Fret number indicator
        if start_fret > 1:
            p.setPen(QPen(QColor("#999999")))
            fret_font = QFont()
            fret_font.setPointSize(9)
            p.setFont(fret_font)
            p.drawText(2, int(top_margin + fret_spacing * 0.3), f"{start_fret}fr")

        # Nut
        if start_fret == 1:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor("#cccccc")))
            p.drawRect(int(left_margin - 2), int(top_margin - 3), int(neck_w + 4), 5)
        else:
            p.setPen(QPen(QColor("#444444"), 1))
            p.drawLine(int(left_margin), int(top_margin),
                       int(left_margin + neck_w), int(top_margin))

        # Fret lines
        p.setPen(QPen(QColor("#444444"), 1))
        for i in range(fret_count + 1):
            y = int(top_margin + i * fret_spacing)
            p.drawLine(int(left_margin), y, int(left_margin + neck_w), y)

        # Strings
        p.setPen(QPen(QColor("#555555"), 1))
        for i in range(6):
            x = int(left_margin + i * string_spacing)
            p.drawLine(x, int(top_margin), x, int(top_margin + neck_h))

        # Finger dots with interval labels
        label_font = QFont()
        label_font.setPointSize(7)
        label_font.setBold(True)

        ALL_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

        for i in range(6):
            x = int(left_margin + i * string_spacing)
            fret_val = self.frets[i]

            if fret_val == -1:
                # Muted
                p.setPen(QPen(QColor("#888888"), 2))
                p.setBrush(Qt.NoBrush)
                marker_y = int(top_margin - 16)
                p.drawLine(x - 5, marker_y - 5, x + 5, marker_y + 5)
                p.drawLine(x - 5, marker_y + 5, x + 5, marker_y - 5)
            elif fret_val == 0:
                # Open string
                note_val = self.tuning[i] % 12
                semitone_off = (note_val - self.root_idx) % 12
                is_root = semitone_off == 0
                p.setPen(QPen(QColor("#7c3aed") if is_root else QColor("#aaaaaa"), 2))
                p.setBrush(Qt.NoBrush)
                marker_y = int(top_margin - 16)
                p.drawEllipse(x - 6, marker_y - 6, 12, 12)
                # Interval label below open marker
                if self.show_intervals and semitone_off in self.interval_map:
                    p.setFont(label_font)
                    p.setPen(QPen(QColor("#7c3aed") if is_root else QColor("#999999")))
                    p.drawText(x - 10, marker_y + 7, 20, 12, Qt.AlignCenter,
                               self.interval_map[semitone_off])
            else:
                # Fretted note
                display_fret = fret_val - start_fret + 1
                if 1 <= display_fret <= fret_count:
                    dot_y = int(top_margin + (display_fret - 0.5) * fret_spacing)
                    note_val = (self.tuning[i] + fret_val) % 12
                    semitone_off = (note_val - self.root_idx) % 12
                    is_root = semitone_off == 0

                    p.setPen(Qt.NoPen)
                    color = QColor("#7c3aed") if is_root else QColor("#e0e0e0")
                    p.setBrush(QBrush(color))
                    p.drawEllipse(x - 9, dot_y - 9, 18, 18)

                    # Interval label on dot
                    p.setFont(label_font)
                    p.setPen(QPen(QColor("#ffffff") if is_root else QColor("#1a1a1a")))
                    label = self.interval_map.get(semitone_off, ALL_NOTES[note_val])
                    if self.show_intervals:
                        p.drawText(x - 9, dot_y - 9, 18, 18, Qt.AlignCenter, label)
                    else:
                        p.drawText(x - 9, dot_y - 9, 18, 18, Qt.AlignCenter,
                                   ALL_NOTES[note_val])

        # String names at bottom
        p.setPen(QPen(QColor("#666666")))
        str_font = QFont()
        str_font.setPointSize(8)
        p.setFont(str_font)
        tuning_notes = [ALL_NOTES[self.tuning[i] % 12] for i in range(6)]
        for i in range(6):
            x = int(left_margin + i * string_spacing)
            p.drawText(x - 8, int(top_margin + neck_h + 5), 16, 20,
                       Qt.AlignCenter, tuning_notes[i])

        p.end()


# ─── Full Fretboard Widget for Notes & Scales ──────────────────────────────

class ScaleFretboardWidget(QWidget):
    """Draws a full guitar fretboard with note labels, tuning-aware, with scale highlighting."""

    NUM_FRETS = 12
    FRET_MARKERS = [3, 5, 7, 9, 12]
    DOUBLE_MARKERS = [12]
    ALL_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    NATURAL_NOTES = {"C", "D", "E", "F", "G", "A", "B"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tuning = [4, 9, 2, 7, 11, 4]  # Standard: E A D G B E (low to high)
        self.scale_notes = set()
        self.root_note = -1
        self.natural_only = False
        # Quiz mode state
        self.quiz_mode = False
        self.quiz_string = -1   # widget string index (0=top/high e, 5=bottom/low E)
        self.quiz_fret = -1
        self.quiz_revealed = False
        self.setMinimumSize(700, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(260)

    def set_tuning(self, tuning):
        self.tuning = tuning
        self.update()

    def set_scale(self, scale_notes, root_note=-1):
        self.scale_notes = scale_notes
        self.root_note = root_note
        self.update()

    def set_natural_only(self, val):
        self.natural_only = val
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        left_margin = 36
        right_margin = 12
        top_margin = 18
        bottom_margin = 28
        neck_w = w - left_margin - right_margin
        neck_h = h - top_margin - bottom_margin
        string_sp = neck_h / 5
        col_count = self.NUM_FRETS + 1  # open + frets
        fret_sp = neck_w / col_count

        # Fretboard wood background
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#1a1612")))
        p.drawRoundedRect(int(left_margin + fret_sp - 4), int(top_margin - 4),
                          int(neck_w - fret_sp + 8), int(neck_h + 8), 4, 4)

        # Nut
        p.setBrush(QBrush(QColor("#d4d4d4")))
        p.drawRect(int(left_margin + fret_sp - 3), int(top_margin - 3), 5, int(neck_h + 6))

        # Fret wires
        p.setPen(QPen(QColor("#444444"), 1))
        for fret in range(1, self.NUM_FRETS + 1):
            x = int(left_margin + (fret + 1) * fret_sp)
            p.drawLine(x, int(top_margin), x, int(top_margin + neck_h))

        # Fret dot markers
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#2a2a2a")))
        for fret in self.FRET_MARKERS:
            if fret > self.NUM_FRETS:
                continue
            cx = int(left_margin + (fret + 0.5) * fret_sp)
            if fret in self.DOUBLE_MARKERS:
                p.drawEllipse(cx - 4, int(top_margin + string_sp * 1.5 - 4), 8, 8)
                p.drawEllipse(cx - 4, int(top_margin + string_sp * 3.5 - 4), 8, 8)
            else:
                p.drawEllipse(cx - 4, int(top_margin + neck_h / 2 - 4), 8, 8)

        # Strings (thicker for low strings)
        for i in range(6):
            y = int(top_margin + i * string_sp)
            thickness = 1.0 + (5 - i) * 0.35
            p.setPen(QPen(QColor("#888888"), thickness))
            p.drawLine(int(left_margin + fret_sp), y, int(left_margin + neck_w), y)

        # Fret numbers below neck
        p.setPen(QPen(QColor("#555555")))
        fn_font = QFont()
        fn_font.setPointSize(8)
        p.setFont(fn_font)
        for fret in range(1, self.NUM_FRETS + 1):
            cx = int(left_margin + (fret + 0.5) * fret_sp)
            p.drawText(cx - 10, int(top_margin + neck_h + 6), 20, 20, Qt.AlignCenter, str(fret))

        # Notes on fretboard
        note_font = QFont()
        note_font.setPointSize(8)
        note_font.setBold(True)
        p.setFont(note_font)

        r = 12  # note circle radius

        for si in range(6):
            # si=0 is top of widget = highest string; tuning index is reversed
            open_note = self.tuning[5 - si]
            y = int(top_margin + si * string_sp)

            for fret in range(0, self.NUM_FRETS + 1):
                nv = (open_note + fret) % 12
                name = self.ALL_NOTES[nv]
                is_nat = name in self.NATURAL_NOTES
                in_scale = nv in self.scale_notes
                is_root = nv == self.root_note

                if fret == 0:
                    cx = int(left_margin + fret_sp * 0.4)
                else:
                    cx = int(left_margin + (fret + 0.5) * fret_sp)

                # ── Quiz mode ──
                if self.quiz_mode:
                    is_quiz_pos = (si == self.quiz_string and fret == self.quiz_fret)
                    if is_quiz_pos:
                        if self.quiz_revealed:
                            # Show the answer in green
                            p.setPen(Qt.NoPen)
                            p.setBrush(QBrush(QColor("#22c55e")))
                            p.drawEllipse(cx - r, y - r, r * 2, r * 2)
                            p.setPen(QPen(QColor("#ffffff")))
                            p.drawText(cx - r, y - r, r * 2, r * 2, Qt.AlignCenter, name)
                        else:
                            # Question marker — circle with "?"
                            p.setPen(Qt.NoPen)
                            p.setBrush(QBrush(QColor("#7c3aed")))
                            p.drawEllipse(cx - r, y - r, r * 2, r * 2)
                            p.setPen(QPen(QColor("#ffffff")))
                            p.drawText(cx - r, y - r, r * 2, r * 2, Qt.AlignCenter, "?")
                    # Skip drawing all other notes in quiz mode
                    continue

                # ── Normal mode ──
                if self.natural_only and not is_nat:
                    continue

                if self.scale_notes:
                    if is_root:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QBrush(QColor("#7c3aed")))
                        p.drawEllipse(cx - r, y - r, r * 2, r * 2)
                        p.setPen(QPen(QColor("#ffffff")))
                        p.drawText(cx - r, y - r, r * 2, r * 2, Qt.AlignCenter, name)
                    elif in_scale:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QBrush(QColor("#4c2889")))
                        p.drawEllipse(cx - r, y - r, r * 2, r * 2)
                        p.setPen(QPen(QColor("#e0e0e0")))
                        p.drawText(cx - r, y - r, r * 2, r * 2, Qt.AlignCenter, name)
                    else:
                        p.setPen(QPen(QColor("#333333")))
                        p.setBrush(Qt.NoBrush)
                        p.drawText(cx - r, y - r, r * 2, r * 2, Qt.AlignCenter, name)
                else:
                    if is_nat:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QBrush(QColor("#2a2a2a")))
                        p.drawEllipse(cx - r, y - r, r * 2, r * 2)
                        p.setPen(QPen(QColor("#ffffff")))
                    else:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QBrush(QColor("#1e1e1e")))
                        p.drawEllipse(cx - r, y - r, r * 2, r * 2)
                        p.setPen(QPen(QColor("#777777")))
                    p.drawText(cx - r, y - r, r * 2, r * 2, Qt.AlignCenter, name)

        # String names on the left
        p.setPen(QPen(QColor("#bbbbbb")))
        lbl_font = QFont()
        lbl_font.setPointSize(10)
        lbl_font.setBold(True)
        p.setFont(lbl_font)
        for i in range(6):
            open_note = self.tuning[5 - i]
            name = self.ALL_NOTES[open_note]
            y = int(top_margin + i * string_sp)
            p.drawText(0, y - 10, int(left_margin - 4), 20, Qt.AlignRight | Qt.AlignVCenter, name)

        p.end()


# ─── Stylesheet ─────────────────────────────────────────────────────────────

STYLE = """
QMainWindow {
    background-color: #0f0f0f;
}

QTabWidget::pane {
    border: 1px solid #2a2a2a;
    background-color: #161616;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background-color: #1a1a1a;
    color: #808080;
    padding: 12px 32px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    min-width: 120px;
}

QTabBar::tab:selected {
    background-color: #161616;
    color: #ffffff;
    border-bottom: 2px solid #7c3aed;
}

QTabBar::tab:hover:!selected {
    background-color: #222222;
    color: #bbbbbb;
}

QLabel {
    color: #e0e0e0;
    font-size: 13px;
}

QLineEdit {
    background-color: #1e1e1e;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 10px 14px;
    color: #ffffff;
    font-size: 13px;
    selection-background-color: #7c3aed;
}

QLineEdit:focus {
    border: 1px solid #7c3aed;
}

QLineEdit:disabled {
    background-color: #141414;
    color: #555555;
}

QPushButton {
    background-color: #7c3aed;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 10px 24px;
    font-size: 13px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #6d28d9;
}

QPushButton:pressed {
    background-color: #5b21b6;
}

QPushButton:disabled {
    background-color: #2a2a2a;
    color: #555555;
}

QPushButton#secondaryBtn {
    background-color: #2a2a2a;
    color: #cccccc;
}

QPushButton#secondaryBtn:hover {
    background-color: #333333;
}

QComboBox {
    background-color: #1e1e1e;
    border: 1px solid #333333;
    border-radius: 8px;
    padding: 10px 14px;
    color: #ffffff;
    font-size: 13px;
    min-width: 180px;
}

QComboBox:focus {
    border: 1px solid #7c3aed;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #808080;
    margin-right: 10px;
}

QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    border: 1px solid #333333;
    color: #ffffff;
    selection-background-color: #7c3aed;
    outline: none;
}

QProgressBar {
    background-color: #1e1e1e;
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #7c3aed;
    border-radius: 6px;
}

QTextEdit {
    background-color: #111111;
    border: 1px solid #222222;
    border-radius: 8px;
    color: #999999;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    padding: 10px;
}

QCheckBox {
    color: #e0e0e0;
    font-size: 13px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #444444;
    background-color: #1e1e1e;
}

QCheckBox::indicator:checked {
    background-color: #7c3aed;
    border-color: #7c3aed;
}

QSlider::groove:horizontal {
    background-color: #1e1e1e;
    height: 6px;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #7c3aed;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background-color: #6d28d9;
}

QSlider::sub-page:horizontal {
    background-color: #7c3aed;
    border-radius: 3px;
}
"""


# ─── Main Window ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    # Page indices
    PAGE_HOME = 0
    PAGE_DOWNLOAD = 1
    PAGE_STEMS = 2
    PAGE_KEY = 3
    PAGE_CONVERT = 4
    PAGE_PLAYER = 5
    PAGE_METRONOME = 6
    PAGE_TUNER = 7
    PAGE_TABS = 8
    PAGE_CAGED = 9
    PAGE_SCALES = 10
    PAGE_CHORDLIB = 11

    ACTION_BTN_STYLE = """
        QPushButton {
            background-color: #7c3aed !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 700;
            letter-spacing: 1px;
        }
        QPushButton:hover {
            background-color: #6d28d9 !important;
        }
        QPushButton:pressed {
            background-color: #5b21b6 !important;
        }
        QPushButton:disabled {
            background-color: #2a2a2a !important;
            color: #555555 !important;
        }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Riff Pilot")
        self.setMinimumSize(750, 620)
        self.resize(820, 700)
        self.setStyleSheet(STYLE)

        # Window icon
        _logo_path = resource_path("Logo.png")
        if os.path.exists(_logo_path):
            self.setWindowIcon(QIcon(_logo_path))

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Stacked widget for page navigation
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Page 0: Home menu
        self.stack.addWidget(self._build_home_page())

        # Feature pages (each wrapped with a back-button header)
        features = [
            ("YouTube Download",  self._build_download_tab),
            ("Stem Separator",    self._build_stems_tab),
            ("Key & BPM",         self._build_key_tab),
            ("Audio Converter",   self._build_convert_tab),
            ("Practice Player",   self._build_player_tab),
            ("Metronome",         self._build_metronome_tab),
            ("Guitar Tuner",      self._build_tuner_tab),
            ("Guitar Tabs",       self._build_tabs_tab),
            ("CAGED Chords",      self._build_caged_tab),
            ("Notes & Scales",    self._build_scales_tab),
            ("Chord Library",     self._build_chordlib_tab),
        ]
        self._page_widgets = {}
        for i, (title, builder) in enumerate(features):
            page = self._wrap_page(title, builder())
            self.stack.addWidget(page)
            self._page_widgets[i + 1] = page

        self.stack.setCurrentIndex(self.PAGE_HOME)

    # ── Home Page ─────────────────────────────────────────────────────────

    def _build_home_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #0f0f0f;")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #0f0f0f; border: none; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        # Header — logo image
        _logo_path = resource_path("Logo.png")
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        if os.path.exists(_logo_path):
            pixmap = QPixmap(_logo_path)
            logo_label.setPixmap(pixmap.scaledToHeight(120, Qt.SmoothTransformation))
        else:
            logo_label.setText("Riff Pilot")
            logo_label.setStyleSheet("font-size: 32px; font-weight: 800; color: #ffffff;")
        layout.addWidget(logo_label)

        subtitle = QLabel("Your all-in-one music toolkit")
        subtitle.setStyleSheet("font-size: 14px; color: #666666;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # ── Sectioned feature cards ──
        sections = [
            ("Production Tools", [
                (self.PAGE_DOWNLOAD,  "YT Download",    "Download audio from\nYouTube in WAV,\nMP3 or FLAC",       "\u2B07"),
                (self.PAGE_STEMS,     "Stem Splitter",   "Separate vocals,\ndrums, bass &\ninstrumentals",       "\u266B"),
                (self.PAGE_KEY,       "Key & BPM",       "Detect musical key,\ntempo & Camelot\ncode",             "\u266A"),
                (self.PAGE_CONVERT,   "Converter",       "Convert between\naudio formats with\ncustom settings",   "\u21C4"),
            ]),
            ("Practice Tools", [
                (self.PAGE_PLAYER,    "Practice Player", "Slow down tracks\nwith pitch preserved\nfor practicing",  "\u25B6"),
                (self.PAGE_METRONOME, "Metronome",       "Tap tempo, auto-\ndetect BPM & keep\ntime while playing", "\u23F2"),
                (self.PAGE_TUNER,     "Guitar Tuner",    "Tune your guitar\nwith real-time pitch\ndetection",       "\u266F"),
                (self.PAGE_TABS,      "Guitar Tabs",     "Search for guitar\ntabs & chords\nonline",               "\U0001D11E"),
            ]),
            ("Fretboard & Theory", [
                (self.PAGE_SCALES,    "Notes & Scales",  "Full fretboard with\nnotes, tunings &\nscale highlights", "\U0001F3BC"),
                (self.PAGE_CAGED,     "CAGED Chords",    "View all CAGED\nvoicings for any\nchord on guitar",     "\U0001F3B8"),
                (self.PAGE_CHORDLIB,  "Chord Library",   "Every voicing for\nany chord in any\ntuning with audio", "\U0001F3B5"),
            ]),
        ]

        for section_title, cards in sections:
            section_label = QLabel(section_title)
            section_label.setAlignment(Qt.AlignCenter)
            section_label.setStyleSheet(
                "font-size: 13px; font-weight: 700; color: #7c3aed; "
                "text-transform: uppercase; letter-spacing: 2px; "
                "padding-bottom: 4px;"
            )
            layout.addWidget(section_label)

            row_layout = QHBoxLayout()
            row_layout.setSpacing(12)
            row_layout.addStretch()
            for page_idx, name, desc, icon in cards:
                card = self._make_menu_card(icon, name, desc, page_idx)
                row_layout.addWidget(card)
            row_layout.addStretch()
            layout.addLayout(row_layout)
            layout.addSpacing(12)

        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)
        return page

    def _make_menu_card(self, icon_text, title, description, page_index):
        card = QPushButton()
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedSize(160, 120)
        card.setStyleSheet("""
            QPushButton {
                background-color: #161616;
                border: 1px solid #2a2a2a;
                border-radius: 10px;
                text-align: center;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #1c1c1c;
                border: 1px solid #7c3aed;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(2, 2, 2, 2)
        card_layout.setSpacing(4)

        card_layout.addStretch()

        # Icon
        icon_label = QLabel(icon_text)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 20px; color: #7c3aed; background: transparent; border: none;")
        card_layout.addWidget(icon_label)

        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffffff; background: transparent; border: none;")
        card_layout.addWidget(title_label)

        # Description
        desc_label = QLabel(description)
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setStyleSheet("font-size: 10px; color: #777777; background: transparent; border: none;")
        desc_label.setWordWrap(True)
        card_layout.addWidget(desc_label)

        card_layout.addStretch()

        card.clicked.connect(lambda: self._navigate_to(page_index))
        return card

    def _wrap_page(self, title, content_widget):
        """Wrap a feature page with a header containing a back button and title."""
        page = QWidget()
        page.setStyleSheet("background-color: #0f0f0f;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setStyleSheet("background-color: #111111; border-bottom: 1px solid #222222;")
        header.setFixedHeight(56)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        back_btn = QPushButton("\u2190  Back")
        back_btn.setFixedSize(100, 36)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a !important;
                color: #ffffff !important;
                border: 1px solid #3a3a3a !important;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                padding: 0px 12px;
            }
            QPushButton:hover {
                background-color: #7c3aed !important;
                border-color: #7c3aed !important;
            }
            QPushButton:pressed {
                background-color: #5b21b6 !important;
            }
        """)
        back_btn.clicked.connect(self._navigate_home)
        header_layout.addWidget(back_btn)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()
        layout.addWidget(header)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #0f0f0f; border: none; }")
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)

        return page

    def _navigate_to(self, page_index):
        self.stack.setCurrentIndex(page_index)

    def _navigate_home(self):
        self.stack.setCurrentIndex(self.PAGE_HOME)

    # ── YouTube Download Tab ─────────────────────────────────────────────

    def _build_download_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # URL input
        url_label = QLabel("YouTube URL")
        url_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(url_label)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste a YouTube link here...")
        self.url_input.textChanged.connect(self._on_url_changed)
        layout.addWidget(self.url_input)

        # Output directory
        dir_label = QLabel("Save To")
        dir_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(dir_label)

        dir_row = QHBoxLayout()
        self.dl_dir_input = QLineEdit()
        self.dl_dir_input.setPlaceholderText("Select output folder...")
        self.dl_dir_input.setText(str(Path.home() / "Music"))
        dir_row.addWidget(self.dl_dir_input)

        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(lambda: self._browse_folder(self.dl_dir_input))
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # Format selector
        fmt_row = QHBoxLayout()
        fmt_label = QLabel("Format")
        fmt_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        fmt_row.addWidget(fmt_label)
        fmt_row.addStretch()

        self.format_combo = QComboBox()
        self.format_combo.addItems(["WAV", "MP3", "FLAC"])
        fmt_row.addWidget(self.format_combo)
        layout.addLayout(fmt_row)

        # Auto-split option
        self.auto_split_cb = QCheckBox("Automatically split stems after download")
        layout.addWidget(self.auto_split_cb)

        layout.addStretch()

        # Progress
        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 0)
        self.dl_progress.setVisible(False)
        layout.addWidget(self.dl_progress)

        # Success banner (hidden by default)
        self.dl_success_banner = QFrame()
        self.dl_success_banner.setStyleSheet("""
            QFrame {
                background-color: #052e16;
                border: 1px solid #16a34a;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        self.dl_success_banner.setVisible(False)
        banner_layout = QHBoxLayout(self.dl_success_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)

        self.dl_success_icon = QLabel("\u2714")
        self.dl_success_icon.setStyleSheet("font-size: 20px; color: #22c55e; border: none; background: transparent;")
        banner_layout.addWidget(self.dl_success_icon)

        self.dl_success_text = QLabel("Download complete!")
        self.dl_success_text.setStyleSheet("font-size: 13px; font-weight: 600; color: #22c55e; border: none; background: transparent;")
        banner_layout.addWidget(self.dl_success_text)
        banner_layout.addStretch()
        layout.addWidget(self.dl_success_banner)

        # Log
        self.dl_log = QTextEdit()
        self.dl_log.setReadOnly(True)
        self.dl_log.setMaximumHeight(130)
        self.dl_log.setVisible(False)
        layout.addWidget(self.dl_log)

        # Download button
        self.dl_btn = QPushButton("Download")
        self.dl_btn.setFixedHeight(50)
        self.dl_btn.setCursor(Qt.PointingHandCursor)
        self.dl_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.dl_btn.clicked.connect(self._start_download)
        layout.addWidget(self.dl_btn)

        return tab

    # ── Stem Separator Tab ───────────────────────────────────────────────

    def _build_stems_tab(self):
        tab = QWidget()
        self._stems_tab_widget = tab  # Store reference for open folder button
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # File input
        file_label = QLabel("Audio File")
        file_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(file_label)

        file_row = QHBoxLayout()
        self.stem_file_input = QLineEdit()
        self.stem_file_input.setPlaceholderText("Select an audio file...")
        file_row.addWidget(self.stem_file_input)

        pick_btn = QPushButton("Browse")
        pick_btn.setObjectName("secondaryBtn")
        pick_btn.setFixedWidth(90)
        pick_btn.clicked.connect(self._browse_audio_file)
        file_row.addWidget(pick_btn)
        layout.addLayout(file_row)

        # Output directory
        out_label = QLabel("Output Folder")
        out_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(out_label)

        out_row = QHBoxLayout()
        self.stem_out_input = QLineEdit()
        self.stem_out_input.setPlaceholderText("Select output folder...")
        self.stem_out_input.setText(str(Path.home() / "Music" / "Stems"))
        out_row.addWidget(self.stem_out_input)

        out_btn = QPushButton("Browse")
        out_btn.setObjectName("secondaryBtn")
        out_btn.setFixedWidth(90)
        out_btn.clicked.connect(lambda: self._browse_folder(self.stem_out_input))
        out_row.addWidget(out_btn)
        layout.addLayout(out_row)

        # Model selector
        model_row = QHBoxLayout()
        model_label = QLabel("Model")
        model_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        model_row.addWidget(model_label)
        model_row.addStretch()

        self.model_combo = QComboBox()
        self.model_combo.addItems(["htdemucs", "htdemucs_ft", "mdx_extra"])
        self.model_combo.setToolTip(
            "htdemucs: Fast, good quality\n"
            "htdemucs_ft: Best quality (slower)\n"
            "mdx_extra: Alternative model"
        )
        model_row.addWidget(self.model_combo)
        layout.addLayout(model_row)

        # Stems selector
        stems_row = QHBoxLayout()
        stems_label = QLabel("Stems")
        stems_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        stems_row.addWidget(stems_label)
        stems_row.addStretch()

        self.stems_combo = QComboBox()
        self.stems_combo.addItems(["All (vocals, drums, bass, other)", "Vocals only", "Instrumental only"])
        stems_row.addWidget(self.stems_combo)
        layout.addLayout(stems_row)

        # Separate button (prominent, near top)
        self.stem_btn = QPushButton("Separate Stems")
        self.stem_btn.setFixedHeight(50)
        self.stem_btn.setCursor(Qt.PointingHandCursor)
        self.stem_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.stem_btn.clicked.connect(self._start_separation)
        layout.addWidget(self.stem_btn)

        # Progress
        self.stem_progress = QProgressBar()
        self.stem_progress.setRange(0, 0)
        self.stem_progress.setVisible(False)
        layout.addWidget(self.stem_progress)

        # Log
        self.stem_log = QTextEdit()
        self.stem_log.setReadOnly(True)
        self.stem_log.setMaximumHeight(130)
        self.stem_log.setVisible(False)
        layout.addWidget(self.stem_log)

        layout.addStretch()

        return tab

    # ── Key & BPM Detection Tab ─────────────────────────────────────────

    def _build_key_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # File input row (label + input + browse all inline)
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_label = QLabel("Audio File:")
        file_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        file_row.addWidget(file_label)

        self.key_file_input = QLineEdit()
        self.key_file_input.setPlaceholderText("Select an audio file...")
        file_row.addWidget(self.key_file_input)

        pick_btn = QPushButton("Browse")
        pick_btn.setObjectName("secondaryBtn")
        pick_btn.setFixedWidth(90)
        pick_btn.clicked.connect(self._browse_key_audio_file)
        file_row.addWidget(pick_btn)
        layout.addLayout(file_row)

        # Analyze button
        self.key_btn = QPushButton("Analyze")
        self.key_btn.setFixedHeight(44)
        self.key_btn.setCursor(Qt.PointingHandCursor)
        self.key_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.key_btn.clicked.connect(self._start_key_detection)
        layout.addWidget(self.key_btn)

        # Progress
        self.key_progress = QProgressBar()
        self.key_progress.setRange(0, 0)
        self.key_progress.setVisible(False)
        layout.addWidget(self.key_progress)

        # Log
        self.key_log = QTextEdit()
        self.key_log.setReadOnly(True)
        self.key_log.setMaximumHeight(60)
        self.key_log.setVisible(False)
        layout.addWidget(self.key_log)

        # Results card — three columns side by side
        results_frame = QFrame()
        results_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        results_row = QHBoxLayout(results_frame)
        results_row.setSpacing(0)

        # Helper to build each result column
        def _make_result_col(header_text, value_style):
            col = QVBoxLayout()
            col.setSpacing(4)
            hdr = QLabel(header_text)
            hdr.setAlignment(Qt.AlignCenter)
            hdr.setStyleSheet("font-weight: 600; color: #666666; font-size: 11px; letter-spacing: 2px; border: none;")
            col.addWidget(hdr)
            val = QLabel("---")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet(value_style + " border: none;")
            col.addWidget(val)
            return col, val

        # Key column
        key_col, self.key_result_label = _make_result_col(
            "DETECTED KEY",
            "font-size: 32px; font-weight: 700; color: #7c3aed;"
        )
        results_row.addLayout(key_col)

        # Vertical separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #2a2a2a;")
        results_row.addWidget(sep1)

        # BPM column
        bpm_col, self.bpm_result_label = _make_result_col(
            "TEMPO (BPM)",
            "font-size: 32px; font-weight: 700; color: #7c3aed;"
        )
        results_row.addLayout(bpm_col)

        # Vertical separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #2a2a2a;")
        results_row.addWidget(sep2)

        # Camelot column
        camelot_col, self.camelot_label = _make_result_col(
            "CAMELOT CODE",
            "font-size: 32px; font-weight: 700; color: #a78bfa;"
        )
        results_row.addLayout(camelot_col)

        # Confidence label below results
        layout.addWidget(results_frame)

        self.key_confidence_label = QLabel("")
        self.key_confidence_label.setAlignment(Qt.AlignCenter)
        self.key_confidence_label.setStyleSheet("font-size: 11px; color: #666666;")
        layout.addWidget(self.key_confidence_label)

        layout.addStretch()

        return tab

    # ── Audio Conversion Tab ─────────────────────────────────────────────

    def _build_convert_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Input file
        in_label = QLabel("Input File")
        in_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(in_label)

        in_row = QHBoxLayout()
        self.conv_file_input = QLineEdit()
        self.conv_file_input.setPlaceholderText("Select an audio file to convert...")
        in_row.addWidget(self.conv_file_input)

        pick_btn = QPushButton("Browse")
        pick_btn.setObjectName("secondaryBtn")
        pick_btn.setFixedWidth(90)
        pick_btn.clicked.connect(self._browse_convert_file)
        in_row.addWidget(pick_btn)
        layout.addLayout(in_row)

        # Output directory
        out_label = QLabel("Save To")
        out_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(out_label)

        out_row = QHBoxLayout()
        self.conv_out_input = QLineEdit()
        self.conv_out_input.setPlaceholderText("Select output folder...")
        self.conv_out_input.setText(str(Path.home() / "Music"))
        out_row.addWidget(self.conv_out_input)

        out_btn = QPushButton("Browse")
        out_btn.setObjectName("secondaryBtn")
        out_btn.setFixedWidth(90)
        out_btn.clicked.connect(lambda: self._browse_folder(self.conv_out_input))
        out_row.addWidget(out_btn)
        layout.addLayout(out_row)

        # Output format
        fmt_row = QHBoxLayout()
        fmt_label = QLabel("Output Format")
        fmt_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        fmt_row.addWidget(fmt_label)
        fmt_row.addStretch()

        self.conv_format_combo = QComboBox()
        self.conv_format_combo.addItems(["WAV", "MP3", "FLAC", "OGG", "AAC", "M4A"])
        fmt_row.addWidget(self.conv_format_combo)
        layout.addLayout(fmt_row)

        # Bitrate (for lossy formats)
        br_row = QHBoxLayout()
        br_label = QLabel("Bitrate (lossy)")
        br_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        br_row.addWidget(br_label)
        br_row.addStretch()

        self.conv_bitrate_combo = QComboBox()
        self.conv_bitrate_combo.addItems(["128k", "192k", "256k", "320k"])
        self.conv_bitrate_combo.setCurrentIndex(3)  # Default 320k
        br_row.addWidget(self.conv_bitrate_combo)
        layout.addLayout(br_row)

        # Sample rate
        sr_row = QHBoxLayout()
        sr_label = QLabel("Sample Rate")
        sr_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        sr_row.addWidget(sr_label)
        sr_row.addStretch()

        self.conv_samplerate_combo = QComboBox()
        self.conv_samplerate_combo.addItems(["Keep original", "44100 Hz", "48000 Hz", "96000 Hz"])
        sr_row.addWidget(self.conv_samplerate_combo)
        layout.addLayout(sr_row)

        # Convert button (moved to top for visibility)
        self.conv_btn = QPushButton("Convert")
        self.conv_btn.setFixedHeight(50)
        self.conv_btn.setCursor(Qt.PointingHandCursor)
        self.conv_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.conv_btn.clicked.connect(self._start_conversion)
        layout.addWidget(self.conv_btn)

        # Progress
        self.conv_progress = QProgressBar()
        self.conv_progress.setRange(0, 0)
        self.conv_progress.setVisible(False)
        layout.addWidget(self.conv_progress)

        # Log
        self.conv_log = QTextEdit()
        self.conv_log.setReadOnly(True)
        self.conv_log.setMaximumHeight(130)
        self.conv_log.setVisible(False)
        layout.addWidget(self.conv_log)

        layout.addStretch()

        return tab

    def _browse_convert_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", str(Path.home() / "Music"),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma *.opus *.aiff);;All Files (*)"
        )
        if file_path:
            self.conv_file_input.setText(file_path)
            self._share_file_to_modules(file_path, source="convert")

    def _start_conversion(self):
        file_path = self.conv_file_input.text().strip()
        out_dir = self.conv_out_input.text().strip()

        if not file_path or not os.path.isfile(file_path):
            self.conv_log.setVisible(True)
            self.conv_log.setText("Please select a valid audio file.")
            return
        if not out_dir:
            self.conv_log.setVisible(True)
            self.conv_log.setText("Please select an output folder.")
            return

        self.conv_btn.setEnabled(False)
        self.conv_btn.setText("Converting...")
        self.conv_progress.setVisible(True)
        self.conv_log.setVisible(True)
        self.conv_log.clear()

        out_fmt = self.conv_format_combo.currentText().lower()
        bitrate = self.conv_bitrate_combo.currentText()
        sr_text = self.conv_samplerate_combo.currentText()

        signals = WorkerSignals()
        signals.log.connect(lambda msg: self.conv_log.append(msg))
        signals.finished.connect(self._on_conversion_done)

        t = threading.Thread(
            target=self._run_conversion,
            args=(file_path, out_dir, out_fmt, bitrate, sr_text, signals),
            daemon=True
        )
        t.start()

    def _run_conversion(self, file_path, out_dir, out_fmt, bitrate, sr_text, signals):
        try:
            os.makedirs(out_dir, exist_ok=True)

            stem = Path(file_path).stem
            # Map format names to ffmpeg codec and extension
            fmt_map = {
                "wav": {"ext": "wav", "codec": "pcm_s16le"},
                "mp3": {"ext": "mp3", "codec": "libmp3lame"},
                "flac": {"ext": "flac", "codec": "flac"},
                "ogg": {"ext": "ogg", "codec": "libvorbis"},
                "aac": {"ext": "aac", "codec": "aac"},
                "m4a": {"ext": "m4a", "codec": "aac"},
            }

            info = fmt_map.get(out_fmt, fmt_map["wav"])
            out_path = os.path.join(out_dir, f"{stem}.{info['ext']}")

            # Avoid overwriting — add suffix if needed
            counter = 1
            while os.path.exists(out_path):
                out_path = os.path.join(out_dir, f"{stem}_{counter}.{info['ext']}")
                counter += 1

            cmd = [get_ffmpeg_path(), "-y", "-i", file_path]

            # Codec
            cmd.extend(["-c:a", info["codec"]])

            # Bitrate for lossy formats
            if out_fmt in ("mp3", "ogg", "aac", "m4a"):
                cmd.extend(["-b:a", bitrate])

            # Sample rate
            if sr_text != "Keep original":
                sr_val = sr_text.split()[0]  # e.g. "44100"
                cmd.extend(["-ar", sr_val])

            cmd.append(out_path)

            signals.log.emit(f"Converting: {os.path.basename(file_path)}")
            signals.log.emit(f"Format: {out_fmt.upper()} | Codec: {info['codec']}")
            if out_fmt in ("mp3", "ogg", "aac", "m4a"):
                signals.log.emit(f"Bitrate: {bitrate}")
            if sr_text != "Keep original":
                signals.log.emit(f"Sample rate: {sr_text}")

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            for line in process.stdout:
                line = line.strip()
                if line:
                    signals.log.emit(line)

            process.wait()
            if process.returncode == 0:
                signals.log.emit(f"\nDone! Saved to:\n{out_path}")
                signals.finished.emit(True, out_path)
            else:
                signals.log.emit(f"\nConversion failed (exit code {process.returncode})")
                signals.finished.emit(False, "")

        except FileNotFoundError:
            signals.log.emit("\nError: ffmpeg not found. Please install ffmpeg and add it to your PATH.")
            signals.finished.emit(False, "")
        except Exception as e:
            signals.log.emit(f"\nError: {e}")
            signals.finished.emit(False, "")

    def _on_conversion_done(self, success, result):
        self.conv_btn.setEnabled(True)
        self.conv_btn.setText("Convert")
        self.conv_progress.setVisible(False)

    # ── Practice Player Tab ─────────────────────────────────────────────

    def _build_player_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Player state
        self._player_audio = None       # Original audio (numpy array)
        self._player_sr = None          # Sample rate
        self._player_stretched = None   # Time-stretched audio cache
        self._player_speed = 1.0        # Current speed factor
        self._player_playing = False
        self._player_position = 0       # Sample position in stretched audio
        self._player_stream = None      # sounddevice stream
        self._player_lock = threading.Lock()
        self._loop_a = None             # Loop start (sample position in stretched audio)
        self._loop_b = None             # Loop end (sample position in stretched audio)

        # File input
        file_label = QLabel("Audio File")
        file_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(file_label)

        file_row = QHBoxLayout()
        self.player_file_input = QLineEdit()
        self.player_file_input.setPlaceholderText("Select an audio file...")
        file_row.addWidget(self.player_file_input)

        pick_btn = QPushButton("Browse")
        pick_btn.setObjectName("secondaryBtn")
        pick_btn.setFixedWidth(90)
        pick_btn.clicked.connect(self._browse_player_file)
        file_row.addWidget(pick_btn)
        layout.addLayout(file_row)

        # Track info
        self.player_info_label = QLabel("No file loaded")
        self.player_info_label.setStyleSheet("font-size: 12px; color: #666666;")
        layout.addWidget(self.player_info_label)

        # Speed control section (prominent, near the top)
        speed_label = QLabel("Playback Speed")
        speed_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(speed_label)

        speed_slider_row = QHBoxLayout()
        self.player_speed_slider = QSlider(Qt.Horizontal)
        self.player_speed_slider.setRange(25, 100)  # 25% to 100%
        self.player_speed_slider.setValue(100)
        self.player_speed_slider.setTickInterval(5)
        self.player_speed_slider.valueChanged.connect(self._on_speed_slider_changed)

        self.player_speed_label = QLabel("100%")
        self.player_speed_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #7c3aed; min-width: 60px;")
        self.player_speed_label.setAlignment(Qt.AlignCenter)

        speed_slider_row.addWidget(self.player_speed_slider)
        speed_slider_row.addWidget(self.player_speed_label)
        layout.addLayout(speed_slider_row)

        # Speed preset buttons
        preset_row = QHBoxLayout()
        for pct in [25, 50, 60, 70, 75, 80, 90, 100]:
            btn = QPushButton(f"{pct}%")
            btn.setObjectName("secondaryBtn")
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda checked, p=pct: self._set_speed_preset(p))
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

        # Status label for processing feedback
        self.player_status_label = QLabel("")
        self.player_status_label.setStyleSheet("font-size: 11px; color: #666666;")
        self.player_status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.player_status_label)

        # Now Playing card
        now_frame = QFrame()
        now_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 12px;
                padding: 16px;
            }
        """)
        now_layout = QVBoxLayout(now_frame)
        now_layout.setSpacing(12)

        # Track name
        self.player_track_label = QLabel("---")
        self.player_track_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        self.player_track_label.setAlignment(Qt.AlignCenter)
        now_layout.addWidget(self.player_track_label)

        # Time display
        time_row = QHBoxLayout()
        self.player_time_current = QLabel("0:00")
        self.player_time_current.setStyleSheet("font-size: 12px; color: #999999; font-family: 'Consolas', monospace;")
        self.player_time_total = QLabel("0:00")
        self.player_time_total.setStyleSheet("font-size: 12px; color: #999999; font-family: 'Consolas', monospace;")

        # Position slider
        self.player_seek_slider = QSlider(Qt.Horizontal)
        self.player_seek_slider.setRange(0, 1000)
        self.player_seek_slider.setValue(0)
        self.player_seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.player_seek_slider.sliderReleased.connect(self._on_seek_released)

        time_row.addWidget(self.player_time_current)
        time_row.addWidget(self.player_seek_slider)
        time_row.addWidget(self.player_time_total)
        now_layout.addLayout(time_row)

        # Transport controls
        transport_row = QHBoxLayout()
        transport_row.addStretch()

        self.player_play_btn = QPushButton("Play")
        self.player_play_btn.setFixedSize(100, 40)
        self.player_play_btn.clicked.connect(self._toggle_playback)
        self.player_play_btn.setEnabled(False)
        transport_row.addWidget(self.player_play_btn)

        self.player_stop_btn = QPushButton("Stop")
        self.player_stop_btn.setObjectName("secondaryBtn")
        self.player_stop_btn.setFixedSize(80, 40)
        self.player_stop_btn.clicked.connect(self._stop_playback)
        self.player_stop_btn.setEnabled(False)
        transport_row.addWidget(self.player_stop_btn)

        transport_row.addStretch()
        now_layout.addLayout(transport_row)

        # A/B Loop controls
        loop_sep = QFrame()
        loop_sep.setFrameShape(QFrame.HLine)
        loop_sep.setStyleSheet("background-color: #2a2a2a; max-height: 1px;")
        now_layout.addWidget(loop_sep)

        loop_header = QLabel("A/B LOOP")
        loop_header.setStyleSheet("font-weight: 600; color: #666666; font-size: 11px; letter-spacing: 2px;")
        loop_header.setAlignment(Qt.AlignCenter)
        now_layout.addWidget(loop_header)

        loop_row = QHBoxLayout()
        loop_row.addStretch()

        self.loop_a_btn = QPushButton("Set A")
        self.loop_a_btn.setFixedSize(80, 34)
        self.loop_a_btn.setEnabled(False)
        self.loop_a_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a !important;
                color: #ffffff !important;
                border: 1px solid #3a3a3a !important;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #444444 !important; }
            QPushButton:disabled { color: #555555 !important; }
        """)
        self.loop_a_btn.clicked.connect(self._set_loop_a)
        loop_row.addWidget(self.loop_a_btn)

        self.loop_b_btn = QPushButton("Set B")
        self.loop_b_btn.setFixedSize(80, 34)
        self.loop_b_btn.setEnabled(False)
        self.loop_b_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a !important;
                color: #ffffff !important;
                border: 1px solid #3a3a3a !important;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #444444 !important; }
            QPushButton:disabled { color: #555555 !important; }
        """)
        self.loop_b_btn.clicked.connect(self._set_loop_b)
        loop_row.addWidget(self.loop_b_btn)

        self.loop_clear_btn = QPushButton("Clear Loop")
        self.loop_clear_btn.setFixedSize(100, 34)
        self.loop_clear_btn.setEnabled(False)
        self.loop_clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a !important;
                color: #ffffff !important;
                border: 1px solid #3a3a3a !important;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #dc2626 !important; border-color: #dc2626 !important; }
            QPushButton:disabled { color: #555555 !important; }
        """)
        self.loop_clear_btn.clicked.connect(self._clear_loop)
        loop_row.addWidget(self.loop_clear_btn)

        loop_row.addStretch()
        now_layout.addLayout(loop_row)

        # Loop status label
        self.loop_status_label = QLabel("No loop set")
        self.loop_status_label.setStyleSheet("font-size: 11px; color: #555555;")
        self.loop_status_label.setAlignment(Qt.AlignCenter)
        now_layout.addWidget(self.loop_status_label)

        layout.addWidget(now_frame)

        layout.addStretch()

        # Timer for updating UI during playback
        self._player_timer = QTimer()
        self._player_timer.setInterval(100)  # Update every 100ms
        self._player_timer.timeout.connect(self._update_player_ui)

        return tab

    # ── A/B Loop Methods ───────────────────────────────────────────────

    def _set_loop_a(self):
        if self._player_stretched is None:
            return
        self._loop_a = self._player_position
        time_a = self._loop_a / self._player_sr
        self.loop_a_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed !important;
                color: #ffffff !important;
                border: none !important;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #6d28d9 !important; }
        """)
        self._update_loop_status()

    def _set_loop_b(self):
        if self._player_stretched is None:
            return
        self._loop_b = self._player_position
        # Ensure B is after A; if not, swap
        if self._loop_a is not None and self._loop_b <= self._loop_a:
            self._loop_a, self._loop_b = self._loop_b, self._loop_a
        self.loop_b_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed !important;
                color: #ffffff !important;
                border: none !important;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #6d28d9 !important; }
        """)
        self.loop_clear_btn.setEnabled(True)
        self._update_loop_status()

    def _clear_loop(self):
        self._loop_a = None
        self._loop_b = None
        self.loop_clear_btn.setEnabled(False)
        inactive_style = """
            QPushButton {
                background-color: #2a2a2a !important;
                color: #ffffff !important;
                border: 1px solid #3a3a3a !important;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #444444 !important; }
            QPushButton:disabled { color: #555555 !important; }
        """
        self.loop_a_btn.setStyleSheet(inactive_style)
        self.loop_b_btn.setStyleSheet(inactive_style)
        self.loop_status_label.setText("No loop set")
        self.loop_status_label.setStyleSheet("font-size: 11px; color: #555555;")

    def _update_loop_status(self):
        parts = []
        if self._loop_a is not None:
            parts.append(f"A: {self._format_time(self._loop_a / self._player_sr)}")
        if self._loop_b is not None:
            parts.append(f"B: {self._format_time(self._loop_b / self._player_sr)}")

        if self._loop_a is not None and self._loop_b is not None:
            duration = (self._loop_b - self._loop_a) / self._player_sr
            text = f"Looping {parts[0]} \u2192 {parts[1]}  ({self._format_time(duration)} loop)"
            self.loop_status_label.setText(text)
            self.loop_status_label.setStyleSheet("font-size: 11px; color: #7c3aed; font-weight: 600;")
        elif parts:
            self.loop_status_label.setText(" | ".join(parts) + "  \u2014  set the other point")
            self.loop_status_label.setStyleSheet("font-size: 11px; color: #999999;")
        else:
            self.loop_status_label.setText("No loop set")
            self.loop_status_label.setStyleSheet("font-size: 11px; color: #555555;")

    def _is_loop_active(self):
        return self._loop_a is not None and self._loop_b is not None

    def _browse_player_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", str(Path.home() / "Music"),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)"
        )
        if file_path:
            self.player_file_input.setText(file_path)
            self._load_player_audio(file_path)
            self._share_file_to_modules(file_path, source="player")

    def _load_player_audio(self, file_path):
        self._stop_playback()
        self._clear_loop()
        self.player_play_btn.setEnabled(False)
        self.player_status_label.setText("Loading audio...")
        self.player_track_label.setText(Path(file_path).stem)

        def load():
            try:
                import librosa
                y, sr = librosa.load(file_path, sr=None, mono=False)
                # If mono, keep as 1D; if stereo, shape is (2, N)
                if y.ndim == 1:
                    y = y.reshape(1, -1)
                self._player_audio = y
                self._player_sr = sr
                self._player_speed = self.player_speed_slider.value() / 100.0
                self._rebuild_stretched_audio()

                duration = y.shape[1] / sr
                self.player_info_label.setText(
                    f"{sr} Hz | {y.shape[0]} ch | {duration:.1f}s"
                )
                self.player_time_total.setText(self._format_time(duration))
                self.player_play_btn.setEnabled(True)
                self.player_stop_btn.setEnabled(True)
                self.loop_a_btn.setEnabled(True)
                self.loop_b_btn.setEnabled(True)
                self.player_status_label.setText("Ready")
            except Exception as e:
                self.player_status_label.setText(f"Error: {e}")

        threading.Thread(target=load, daemon=True).start()

    def _rebuild_stretched_audio(self):
        import librosa
        speed = self._player_speed
        if speed == 1.0:
            self._player_stretched = self._player_audio.copy()
        else:
            rate = speed  # time_stretch rate: <1 = slower playback, >1 = faster
            channels = []
            for ch in range(self._player_audio.shape[0]):
                stretched = librosa.effects.time_stretch(self._player_audio[ch], rate=rate)
                channels.append(stretched)
            self._player_stretched = np.array(channels)

    def _on_speed_slider_changed(self, value):
        self.player_speed_label.setText(f"{value}%")

    def _set_speed_preset(self, pct):
        self.player_speed_slider.setValue(pct)

    def _apply_speed_change(self):
        new_speed = self.player_speed_slider.value() / 100.0
        if new_speed == self._player_speed or self._player_audio is None:
            return

        was_playing = self._player_playing
        # Calculate current position as a fraction of the track
        if self._player_stretched is not None and self._player_stretched.shape[1] > 0:
            frac = self._player_position / self._player_stretched.shape[1]
        else:
            frac = 0.0

        if was_playing:
            self._pause_stream()

        self._player_speed = new_speed
        self.player_status_label.setText(f"Adjusting speed to {int(new_speed * 100)}%...")

        def rebuild():
            self._rebuild_stretched_audio()
            # Restore position proportionally
            self._player_position = int(frac * self._player_stretched.shape[1])
            self.player_status_label.setText("Ready")
            if was_playing:
                self._start_stream()

        threading.Thread(target=rebuild, daemon=True).start()

    def _toggle_playback(self):
        if self._player_audio is None:
            return

        # Check if speed changed since last play
        new_speed = self.player_speed_slider.value() / 100.0
        if new_speed != self._player_speed:
            # Need to rebuild stretched audio first
            self._player_speed = new_speed
            was_at_start = self._player_position == 0

            if self._player_playing:
                self._pause_stream()
                self.player_play_btn.setText("Play")
                self._player_playing = False

            self.player_status_label.setText(f"Adjusting speed to {int(new_speed * 100)}%...")
            self.player_play_btn.setEnabled(False)

            def rebuild_and_play():
                if self._player_stretched is not None and not was_at_start:
                    frac = self._player_position / self._player_stretched.shape[1]
                else:
                    frac = 0.0
                self._rebuild_stretched_audio()
                self._player_position = int(frac * self._player_stretched.shape[1])
                self.player_status_label.setText("Ready")
                self.player_play_btn.setEnabled(True)
                self._start_stream()
                self._player_playing = True
                self.player_play_btn.setText("Pause")
                self._player_timer.start()

            threading.Thread(target=rebuild_and_play, daemon=True).start()
            return

        if self._player_playing:
            self._pause_stream()
            self._player_playing = False
            self.player_play_btn.setText("Play")
            self._player_timer.stop()
        else:
            # If at the end, restart
            if self._player_stretched is not None and self._player_position >= self._player_stretched.shape[1]:
                self._player_position = 0
            self._start_stream()
            self._player_playing = True
            self.player_play_btn.setText("Pause")
            self._player_timer.start()

    def _start_stream(self):
        import sounddevice as sd
        channels = self._player_stretched.shape[0]
        sr = self._player_sr

        def callback(outdata, frames, time_info, status):
            with self._player_lock:
                pos = self._player_position
                total = self._player_stretched.shape[1]
                loop_active = self._loop_a is not None and self._loop_b is not None
                loop_end = self._loop_b if loop_active else total

                written = 0
                remaining = frames

                while remaining > 0:
                    # How many samples until the boundary (loop end or track end)
                    boundary = loop_end if (loop_active and pos < loop_end) else total
                    avail = boundary - pos

                    if avail <= 0:
                        if loop_active:
                            # Loop back to A
                            pos = self._loop_a
                            continue
                        else:
                            # End of track
                            outdata[written:] = 0
                            self._player_position = total
                            raise sd.CallbackStop

                    chunk = min(remaining, avail)
                    outdata[written:written + chunk] = self._player_stretched[:, pos:pos + chunk].T
                    pos += chunk
                    written += chunk
                    remaining -= chunk

                    # If we hit the loop boundary, wrap back
                    if loop_active and pos >= loop_end:
                        pos = self._loop_a

                self._player_position = pos

        self._player_stream = sd.OutputStream(
            samplerate=sr,
            channels=channels,
            callback=callback,
            finished_callback=self._on_stream_finished,
        )
        self._player_stream.start()

    def _pause_stream(self):
        if self._player_stream is not None:
            self._player_stream.stop()
            self._player_stream.close()
            self._player_stream = None

    def _stop_playback(self):
        self._pause_stream()
        self._player_playing = False
        self._player_position = 0
        self._player_timer.stop()
        self.player_play_btn.setText("Play")
        self.player_seek_slider.setValue(0)
        self.player_time_current.setText("0:00")

    def _on_stream_finished(self):
        self._player_playing = False
        self._player_timer.stop()
        # Update UI from main thread
        QTimer.singleShot(0, lambda: self.player_play_btn.setText("Play"))

    def _update_player_ui(self):
        if self._player_stretched is None:
            return
        total = self._player_stretched.shape[1]
        if total == 0:
            return

        pos = self._player_position
        frac = pos / total

        if not self.player_seek_slider.isSliderDown():
            self.player_seek_slider.setValue(int(frac * 1000))

        elapsed_sec = pos / self._player_sr
        total_sec = total / self._player_sr
        self.player_time_current.setText(self._format_time(elapsed_sec))
        self.player_time_total.setText(self._format_time(total_sec))

    def _on_seek_pressed(self):
        pass  # Just prevents slider from updating while dragging

    def _on_seek_released(self):
        if self._player_stretched is None:
            return
        frac = self.player_seek_slider.value() / 1000.0
        total = self._player_stretched.shape[1]
        new_pos = int(frac * total)

        was_playing = self._player_playing
        if was_playing:
            self._pause_stream()

        with self._player_lock:
            self._player_position = new_pos

        if was_playing:
            self._start_stream()

    @staticmethod
    def _format_time(seconds):
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}:{s:02d}"

    # ── Metronome Tab ────────────────────────────────────────────────────

    def _build_metronome_tab(self):
        tab = QWidget()
        self._met_tab_widget = tab  # Store reference for time signature updates
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Metronome state
        self._met_running = False
        self._met_stream = None
        self._met_sr = 44100
        self._met_beat = 0
        self._met_tap_times = []
        self._met_lock = threading.Lock()

        # Generate click samples (high tick for beat 1, normal tick for others)
        self._met_click_hi = self._generate_click(self._met_sr, freq=1200, duration=0.03, volume=0.8)
        self._met_click_lo = self._generate_click(self._met_sr, freq=800, duration=0.025, volume=0.6)

        # ── Auto-detect BPM from file ──
        detect_label = QLabel("Auto-Detect BPM from File")
        detect_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(detect_label)

        detect_row = QHBoxLayout()
        self.met_file_input = QLineEdit()
        self.met_file_input.setPlaceholderText("Select an audio file to detect BPM...")
        detect_row.addWidget(self.met_file_input)

        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_met_file)
        detect_row.addWidget(browse_btn)

        detect_btn = QPushButton("Detect")
        detect_btn.setFixedWidth(90)
        detect_btn.clicked.connect(self._detect_met_bpm)
        detect_row.addWidget(detect_btn)
        layout.addLayout(detect_row)

        self.met_detect_status = QLabel("")
        self.met_detect_status.setStyleSheet("font-size: 11px; color: #666666;")
        layout.addWidget(self.met_detect_status)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #2a2a2a; max-height: 1px;")
        layout.addWidget(sep)

        # ── BPM display card ──
        bpm_frame = QFrame()
        bpm_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 12px;
                padding: 20px;
            }
        """)
        bpm_layout = QVBoxLayout(bpm_frame)
        bpm_layout.setSpacing(12)

        # Large BPM display
        self.met_bpm_label = QLabel("120")
        self.met_bpm_label.setStyleSheet("font-size: 64px; font-weight: 700; color: #7c3aed;")
        self.met_bpm_label.setAlignment(Qt.AlignCenter)
        bpm_layout.addWidget(self.met_bpm_label)

        bpm_sub = QLabel("BPM")
        bpm_sub.setStyleSheet("font-size: 14px; font-weight: 600; color: #666666; letter-spacing: 3px;")
        bpm_sub.setAlignment(Qt.AlignCenter)
        bpm_layout.addWidget(bpm_sub)

        # Beat indicators
        self.met_beat_indicators = []
        beat_row = QHBoxLayout()
        beat_row.addStretch()
        for i in range(4):
            indicator = QLabel()
            indicator.setFixedSize(24, 24)
            indicator.setStyleSheet("""
                background-color: #2a2a2a;
                border-radius: 12px;
            """)
            indicator.setAlignment(Qt.AlignCenter)
            self.met_beat_indicators.append(indicator)
            beat_row.addWidget(indicator)
        beat_row.addStretch()
        bpm_layout.addLayout(beat_row)

        layout.addWidget(bpm_frame)

        # ── BPM slider ──
        slider_row = QHBoxLayout()
        self.met_bpm_slider = QSlider(Qt.Horizontal)
        self.met_bpm_slider.setRange(20, 300)
        self.met_bpm_slider.setValue(120)
        self.met_bpm_slider.valueChanged.connect(self._on_met_bpm_changed)
        slider_row.addWidget(self.met_bpm_slider)

        # Manual BPM input
        self.met_bpm_input = QLineEdit("120")
        self.met_bpm_input.setFixedWidth(70)
        self.met_bpm_input.setAlignment(Qt.AlignCenter)
        self.met_bpm_input.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.met_bpm_input.returnPressed.connect(self._on_met_bpm_typed)
        slider_row.addWidget(self.met_bpm_input)

        layout.addLayout(slider_row)

        # ── Time signature & controls row ──
        controls_row = QHBoxLayout()

        # Time signature
        ts_label = QLabel("Time Sig")
        ts_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        controls_row.addWidget(ts_label)

        self.met_timesig_combo = QComboBox()
        self.met_timesig_combo.addItems(["4/4", "3/4", "6/8", "2/4", "5/4", "7/8"])
        self.met_timesig_combo.setFixedWidth(100)
        self.met_timesig_combo.currentIndexChanged.connect(self._on_met_timesig_changed)
        controls_row.addWidget(self.met_timesig_combo)

        controls_row.addStretch()

        # Tap Tempo button
        self.met_tap_btn = QPushButton("Tap Tempo")
        self.met_tap_btn.setObjectName("secondaryBtn")
        self.met_tap_btn.setFixedSize(120, 40)
        self.met_tap_btn.clicked.connect(self._on_tap_tempo)
        controls_row.addWidget(self.met_tap_btn)

        layout.addLayout(controls_row)

        layout.addStretch()

        # ── Start / Stop button ──
        self.met_start_btn = QPushButton("Start Metronome")
        self.met_start_btn.setFixedHeight(50)
        self.met_start_btn.setCursor(Qt.PointingHandCursor)
        self.met_start_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.met_start_btn.clicked.connect(self._toggle_metronome)
        layout.addWidget(self.met_start_btn)

        # Timer for beat scheduling
        self._met_timer = QTimer()
        self._met_timer.timeout.connect(self._on_met_tick)

        return tab

    @staticmethod
    def _generate_click(sr, freq=1000, duration=0.03, volume=0.7):
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        # Sine wave with fast exponential decay for a sharp click
        envelope = np.exp(-t * 60)
        click = np.sin(2 * np.pi * freq * t) * envelope * volume
        return click.astype(np.float32)

    def _browse_met_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", str(Path.home() / "Music"),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)"
        )
        if file_path:
            self.met_file_input.setText(file_path)
            self._share_file_to_modules(file_path, source="metronome")

    def _detect_met_bpm(self):
        file_path = self.met_file_input.text().strip()
        if not file_path or not os.path.isfile(file_path):
            self.met_detect_status.setText("Please select a valid audio file.")
            return

        self.met_detect_status.setText("Detecting BPM...")

        def detect():
            try:
                import librosa
                y, sr = librosa.load(file_path, sr=22050, mono=True)
                tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                bpm = float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo)
                bpm_int = int(round(bpm))
                # Update UI from main thread
                QTimer.singleShot(0, lambda: self._set_met_bpm(bpm_int))
                QTimer.singleShot(0, lambda: self.met_detect_status.setText(
                    f"Detected: {bpm:.1f} BPM (rounded to {bpm_int})"
                ))
            except Exception as e:
                QTimer.singleShot(0, lambda: self.met_detect_status.setText(f"Error: {e}"))

        threading.Thread(target=detect, daemon=True).start()

    def _set_met_bpm(self, bpm):
        bpm = max(20, min(300, bpm))
        self.met_bpm_slider.setValue(bpm)
        self.met_bpm_input.setText(str(bpm))
        self.met_bpm_label.setText(str(bpm))
        # Update timer interval if running
        if self._met_running:
            self._met_timer.setInterval(self._get_met_interval())

    def _on_met_bpm_changed(self, value):
        self.met_bpm_label.setText(str(value))
        self.met_bpm_input.setText(str(value))
        if self._met_running:
            self._met_timer.setInterval(self._get_met_interval())

    def _on_met_bpm_typed(self):
        try:
            bpm = int(self.met_bpm_input.text().strip())
            self._set_met_bpm(bpm)
        except ValueError:
            pass

    def _on_met_timesig_changed(self):
        # Update beat indicators count
        beats = self._get_met_beats_per_bar()
        # Rebuild indicators
        for ind in self.met_beat_indicators:
            ind.setParent(None)
        self.met_beat_indicators.clear()

        # Find the beat_row layout inside the bpm_frame
        # We need to re-add them. The parent frame's layout has the beat row.
        bpm_frame = None
        met_tab = self._met_tab_widget
        for child in met_tab.findChildren(QFrame):
            if child.styleSheet() and "border-radius: 12px" in child.styleSheet():
                bpm_frame = child
                break

        if bpm_frame:
            # Find or create beat row
            frame_layout = bpm_frame.layout()
            # Remove old beat row (last layout item that is a QHBoxLayout)
            for i in range(frame_layout.count() - 1, -1, -1):
                item = frame_layout.itemAt(i)
                if item.layout() is not None:
                    # Clear the layout
                    old_layout = item.layout()
                    while old_layout.count():
                        child_item = old_layout.takeAt(0)
                        if child_item.widget():
                            child_item.widget().setParent(None)
                    frame_layout.removeItem(item)
                    break

            beat_row = QHBoxLayout()
            beat_row.addStretch()
            for i in range(beats):
                indicator = QLabel()
                indicator.setFixedSize(24, 24)
                indicator.setStyleSheet("background-color: #2a2a2a; border-radius: 12px;")
                indicator.setAlignment(Qt.AlignCenter)
                self.met_beat_indicators.append(indicator)
                beat_row.addWidget(indicator)
            beat_row.addStretch()
            frame_layout.addLayout(beat_row)

        self._met_beat = 0
        if self._met_running:
            self._met_timer.setInterval(self._get_met_interval())

    def _get_met_beats_per_bar(self):
        ts = self.met_timesig_combo.currentText()
        return int(ts.split("/")[0])

    def _get_met_interval(self):
        bpm = self.met_bpm_slider.value()
        ts = self.met_timesig_combo.currentText()
        denom = int(ts.split("/")[1])
        # For x/8 time signatures, each beat is an eighth note
        if denom == 8:
            return int(30000 / bpm)  # twice as fast
        return int(60000 / bpm)

    def _on_tap_tempo(self):
        import time
        now = time.time()
        # Reset if more than 2 seconds since last tap
        if self._met_tap_times and (now - self._met_tap_times[-1]) > 2.0:
            self._met_tap_times.clear()
        self._met_tap_times.append(now)

        if len(self._met_tap_times) >= 2:
            # Average the intervals between taps
            intervals = []
            for i in range(1, len(self._met_tap_times)):
                intervals.append(self._met_tap_times[i] - self._met_tap_times[i - 1])
            avg_interval = sum(intervals) / len(intervals)
            bpm = int(round(60.0 / avg_interval))
            self._set_met_bpm(bpm)

        # Keep only last 8 taps
        if len(self._met_tap_times) > 8:
            self._met_tap_times = self._met_tap_times[-8:]

    def _toggle_metronome(self):
        if self._met_running:
            self._stop_metronome()
        else:
            self._start_metronome()

    def _start_metronome(self):
        self._met_running = True
        self._met_beat = 0
        self.met_start_btn.setText("Stop Metronome")
        self.met_start_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:pressed { background-color: #991b1b; }
        """)
        self._on_met_tick()  # Play first beat immediately
        self._met_timer.setInterval(self._get_met_interval())
        self._met_timer.start()

    def _stop_metronome(self):
        self._met_running = False
        self._met_timer.stop()
        self._met_beat = 0
        self.met_start_btn.setText("Start Metronome")
        self.met_start_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        # Reset all indicators
        for ind in self.met_beat_indicators:
            ind.setStyleSheet("background-color: #2a2a2a; border-radius: 12px;")

    def _on_met_tick(self):
        beats_per_bar = self._get_met_beats_per_bar()
        beat_in_bar = self._met_beat % beats_per_bar

        # Play click sound (high pitch on beat 1, lower on others)
        click = self._met_click_hi if beat_in_bar == 0 else self._met_click_lo

        def play_click():
            try:
                import sounddevice as sd
                sd.play(click, self._met_sr)
            except Exception:
                pass

        threading.Thread(target=play_click, daemon=True).start()

        # Update visual indicators
        for i, ind in enumerate(self.met_beat_indicators):
            if i == beat_in_bar:
                color = "#7c3aed" if beat_in_bar == 0 else "#a78bfa"
                ind.setStyleSheet(f"background-color: {color}; border-radius: 12px;")
            else:
                ind.setStyleSheet("background-color: #2a2a2a; border-radius: 12px;")

        self._met_beat += 1

    # ── Guitar Tuner Tab ───────────────────────────────────────────────

    # Standard tuning frequencies and common alternate tunings
    TUNINGS = {
        "Standard (EADGBe)": [
            ("E2", 82.41), ("A2", 110.00), ("D3", 146.83),
            ("G3", 196.00), ("B3", 246.94), ("E4", 329.63),
        ],
        "Drop D (DADGBe)": [
            ("D2", 73.42), ("A2", 110.00), ("D3", 146.83),
            ("G3", 196.00), ("B3", 246.94), ("E4", 329.63),
        ],
        "Half Step Down": [
            ("Eb2", 77.78), ("Ab2", 103.83), ("Db3", 138.59),
            ("Gb3", 185.00), ("Bb3", 233.08), ("Eb4", 311.13),
        ],
        "Full Step Down": [
            ("D2", 73.42), ("G2", 98.00), ("C3", 130.81),
            ("F3", 174.61), ("A3", 220.00), ("D4", 293.66),
        ],
        "Open G (DGDGBd)": [
            ("D2", 73.42), ("G2", 98.00), ("D3", 146.83),
            ("G3", 196.00), ("B3", 246.94), ("D4", 293.66),
        ],
        "Open D (DADf#Ad)": [
            ("D2", 73.42), ("A2", 110.00), ("D3", 146.83),
            ("F#3", 185.00), ("A3", 220.00), ("D4", 293.66),
        ],
        "DADGAD": [
            ("D2", 73.42), ("A2", 110.00), ("D3", 146.83),
            ("G3", 196.00), ("A3", 220.00), ("D4", 293.66),
        ],
    }

    # All chromatic note frequencies for general detection (C1 to C7)
    _NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    def _build_tuner_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        # Tuner state
        self._tuner_running = False
        self._tuner_stream = None
        self._tuner_sr = 44100
        self._tuner_buffer_size = 8192  # ~186ms window for better low-freq detection
        self._tuner_hold_frames = 0     # Countdown to hold last reading on display
        self._tuner_hold_max = 15       # Hold for ~1.2 sec (15 * 80ms timer)

        # Top row: tuning selector + start button
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        tuning_label = QLabel("Tuning:")
        tuning_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        top_row.addWidget(tuning_label)

        self.tuner_tuning_combo = QComboBox()
        self.tuner_tuning_combo.addItems(list(self.TUNINGS.keys()))
        self.tuner_tuning_combo.setFixedWidth(220)
        self.tuner_tuning_combo.currentIndexChanged.connect(self._on_tuning_changed)
        top_row.addWidget(self.tuner_tuning_combo)

        top_row.addStretch()

        self.tuner_start_btn = QPushButton("Start Tuner")
        self.tuner_start_btn.setFixedHeight(40)
        self.tuner_start_btn.setFixedWidth(140)
        self.tuner_start_btn.setCursor(Qt.PointingHandCursor)
        self.tuner_start_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.tuner_start_btn.clicked.connect(self._toggle_tuner)
        top_row.addWidget(self.tuner_start_btn)

        layout.addLayout(top_row)

        # String indicators row
        self.tuner_string_btns = []
        strings_row = QHBoxLayout()
        strings_row.addStretch()
        tuning = list(self.TUNINGS.values())[0]
        for i, (name, freq) in enumerate(tuning):
            btn = QLabel(name)
            btn.setFixedSize(42, 42)
            btn.setAlignment(Qt.AlignCenter)
            btn.setStyleSheet("""
                background-color: #1e1e1e;
                border: 2px solid #333333;
                border-radius: 21px;
                font-size: 13px;
                font-weight: 700;
                color: #888888;
            """)
            self.tuner_string_btns.append(btn)
            strings_row.addWidget(btn)
        strings_row.addStretch()
        self._tuner_strings_layout = strings_row
        layout.addLayout(strings_row)

        # Main tuner display card
        tuner_frame = QFrame()
        tuner_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 12px;
                padding: 14px;
            }
        """)
        tuner_card_layout = QVBoxLayout(tuner_frame)
        tuner_card_layout.setSpacing(4)

        # Detected note + frequency on one line
        note_row = QHBoxLayout()
        note_row.addStretch()

        self.tuner_note_label = QLabel("--")
        self.tuner_note_label.setStyleSheet("font-size: 52px; font-weight: 700; color: #7c3aed;")
        self.tuner_note_label.setAlignment(Qt.AlignCenter)
        note_row.addWidget(self.tuner_note_label)

        self.tuner_freq_label = QLabel("-- Hz")
        self.tuner_freq_label.setStyleSheet("font-size: 13px; color: #666666; padding-top: 18px;")
        note_row.addWidget(self.tuner_freq_label)

        note_row.addStretch()
        tuner_card_layout.addLayout(note_row)

        # Cents offset gauge
        gauge_row = QHBoxLayout()
        gauge_row.addStretch()

        flat_label = QLabel("FLAT")
        flat_label.setStyleSheet("font-size: 9px; font-weight: 600; color: #666666; letter-spacing: 2px;")
        gauge_row.addWidget(flat_label)

        self.tuner_gauge_segments = []
        for i in range(21):
            seg = QLabel()
            seg.setFixedSize(8, 22)
            if i == 10:
                seg.setFixedSize(4, 28)
                seg.setStyleSheet("background-color: #444444; border-radius: 2px;")
            else:
                seg.setStyleSheet("background-color: #222222; border-radius: 2px;")
            self.tuner_gauge_segments.append(seg)
            gauge_row.addWidget(seg)

        sharp_label = QLabel("SHARP")
        sharp_label.setStyleSheet("font-size: 9px; font-weight: 600; color: #666666; letter-spacing: 2px;")
        gauge_row.addWidget(sharp_label)

        gauge_row.addStretch()
        tuner_card_layout.addLayout(gauge_row)

        # Cents + status on one line
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()

        self.tuner_cents_label = QLabel("0 cents")
        self.tuner_cents_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #666666;")
        bottom_row.addWidget(self.tuner_cents_label)

        self.tuner_status_label = QLabel("Start tuner to begin")
        self.tuner_status_label.setStyleSheet("font-size: 12px; color: #555555; padding-left: 16px;")
        bottom_row.addWidget(self.tuner_status_label)

        bottom_row.addStretch()
        tuner_card_layout.addLayout(bottom_row)

        layout.addWidget(tuner_frame)

        layout.addStretch()

        # Timer for processing mic input
        self._tuner_timer = QTimer()
        self._tuner_timer.setInterval(80)  # ~12 fps updates
        self._tuner_timer.timeout.connect(self._process_tuner)

        # Audio buffer for mic input
        self._tuner_audio_buf = np.zeros(self._tuner_buffer_size, dtype=np.float32)

        return tab

    def _on_tuning_changed(self):
        tuning_name = self.tuner_tuning_combo.currentText()
        tuning = self.TUNINGS[tuning_name]

        # Update string buttons
        for i, btn in enumerate(self.tuner_string_btns):
            if i < len(tuning):
                btn.setText(tuning[i][0])
                btn.setVisible(True)
                btn.setStyleSheet("""
                    background-color: #1e1e1e;
                    border: 2px solid #333333;
                    border-radius: 21px;
                    font-size: 14px;
                    font-weight: 700;
                    color: #888888;
                """)
            else:
                btn.setVisible(False)

    def _toggle_tuner(self):
        if self._tuner_running:
            self._stop_tuner()
        else:
            self._start_tuner()

    def _start_tuner(self):
        import sounddevice as sd

        self._tuner_running = True
        self.tuner_start_btn.setText("Stop Tuner")
        self.tuner_start_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:pressed { background-color: #991b1b; }
        """)
        self.tuner_status_label.setText("Listening...")
        self.tuner_status_label.setStyleSheet("font-size: 13px; color: #999999;")

        def audio_callback(indata, frames, time_info, status):
            # Copy latest audio into our buffer
            data = indata[:, 0].copy()
            buf_len = len(self._tuner_audio_buf)
            if len(data) >= buf_len:
                self._tuner_audio_buf[:] = data[-buf_len:]
            else:
                self._tuner_audio_buf[:-len(data)] = self._tuner_audio_buf[len(data):]
                self._tuner_audio_buf[-len(data):] = data

        try:
            self._tuner_stream = sd.InputStream(
                samplerate=self._tuner_sr,
                channels=1,
                dtype='float32',
                blocksize=2048,
                callback=audio_callback,
            )
            self._tuner_stream.start()
            self._tuner_timer.start()
        except Exception as e:
            self.tuner_status_label.setText(f"Mic error: {e}")
            self._tuner_running = False
            self.tuner_start_btn.setText("Start Tuner")

    def _stop_tuner(self):
        self._tuner_running = False
        self._tuner_timer.stop()
        self._tuner_hold_frames = 0

        if self._tuner_stream is not None:
            self._tuner_stream.stop()
            self._tuner_stream.close()
            self._tuner_stream = None

        self.tuner_start_btn.setText("Start Tuner")
        self.tuner_start_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.tuner_note_label.setText("--")
        self.tuner_freq_label.setText("-- Hz")
        self.tuner_cents_label.setText("0 cents")
        self.tuner_status_label.setText("Start tuner to begin")
        self.tuner_status_label.setStyleSheet("font-size: 13px; color: #555555;")
        self._reset_tuner_gauge()
        self._on_tuning_changed()  # Reset string highlights

    def _process_tuner(self):
        buf = self._tuner_audio_buf.copy()

        # Check if there's enough signal (low threshold to catch string decay)
        rms = np.sqrt(np.mean(buf ** 2))
        if rms < 0.002:
            # Signal too quiet — count down hold timer before clearing display
            if self._tuner_hold_frames > 0:
                self._tuner_hold_frames -= 1
                return  # Keep showing last detected note
            # Hold expired, clear display
            self.tuner_note_label.setText("--")
            self.tuner_freq_label.setText("-- Hz")
            self.tuner_cents_label.setText("0 cents")
            self.tuner_cents_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #666666;")
            self.tuner_note_label.setStyleSheet("font-size: 52px; font-weight: 700; color: #666666;")
            self.tuner_status_label.setText("Play a note...")
            self.tuner_status_label.setStyleSheet("font-size: 13px; color: #999999;")
            self._reset_tuner_gauge()
            return

        # Pitch detection using YIN via librosa
        try:
            import librosa
            f0 = librosa.yin(
                buf,
                fmin=60,  # Just below lowest guitar string
                fmax=1000,
                sr=self._tuner_sr,
                frame_length=self._tuner_buffer_size,
            )
            # Take the median of detected pitches to reduce jitter
            valid = f0[f0 > 0]
            if len(valid) == 0:
                self._tuner_hold_frames = max(self._tuner_hold_frames - 1, 0)
                return
            freq = float(np.median(valid))
        except Exception:
            return

        if freq < 50 or freq > 1000:
            return

        # Reset hold timer — we have a good reading
        self._tuner_hold_frames = self._tuner_hold_max

        # Find closest note
        note_name, note_freq, cents = self._freq_to_note(freq)

        # Find closest string in current tuning
        tuning_name = self.tuner_tuning_combo.currentText()
        tuning = self.TUNINGS[tuning_name]
        closest_string_idx = -1
        closest_string_dist = float('inf')
        for i, (sname, sfreq) in enumerate(tuning):
            # Distance in cents
            if sfreq > 0:
                dist = abs(1200 * np.log2(freq / sfreq))
                if dist < closest_string_dist:
                    closest_string_dist = dist
                    closest_string_idx = i

        # Update note display
        self.tuner_note_label.setText(note_name)
        self.tuner_freq_label.setText(f"{freq:.1f} Hz")

        # Update cents display and color
        cents_abs = abs(cents)
        if cents_abs <= 5:
            color = "#22c55e"  # Green - in tune
            status = "In Tune!"
        elif cents_abs <= 15:
            color = "#eab308"  # Yellow - close
            status = "Almost there..."
        else:
            color = "#ef4444"  # Red - out of tune
            status = "Sharp" if cents > 0 else "Flat"

        sign = "+" if cents > 0 else ""
        self.tuner_cents_label.setText(f"{sign}{cents:.0f} cents")
        self.tuner_cents_label.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {color};")
        self.tuner_note_label.setStyleSheet(f"font-size: 52px; font-weight: 700; color: {color};")
        self.tuner_status_label.setText(status)
        self.tuner_status_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {color};")

        # Update gauge
        self._update_tuner_gauge(cents, color)

        # Highlight closest string
        for i, btn in enumerate(self.tuner_string_btns):
            if i == closest_string_idx and closest_string_dist < 200:
                btn.setStyleSheet(f"""
                    background-color: #1e1e1e;
                    border: 2px solid {color};
                    border-radius: 21px;
                    font-size: 14px;
                    font-weight: 700;
                    color: {color};
                """)
            else:
                btn.setStyleSheet("""
                    background-color: #1e1e1e;
                    border: 2px solid #333333;
                    border-radius: 21px;
                    font-size: 14px;
                    font-weight: 700;
                    color: #888888;
                """)

    def _freq_to_note(self, freq):
        """Convert frequency to nearest note name, note frequency, and cents offset."""
        if freq <= 0:
            return "--", 0, 0
        # A4 = 440 Hz
        semitones_from_a4 = 12 * np.log2(freq / 440.0)
        nearest_semitone = round(semitones_from_a4)
        cents = (semitones_from_a4 - nearest_semitone) * 100

        # Calculate note name and octave
        note_idx = int(nearest_semitone + 9) % 12  # A is index 9 from C
        octave = int((nearest_semitone + 9) // 12) + 4  # A4 octave

        note_name = self._NOTE_NAMES[note_idx] + str(octave)
        note_freq = 440.0 * (2 ** (nearest_semitone / 12.0))

        return note_name, note_freq, cents

    def _update_tuner_gauge(self, cents, color):
        # Map cents (-50 to +50) to gauge segments (0 to 20)
        # Center is index 10
        for i, seg in enumerate(self.tuner_gauge_segments):
            # Each segment represents ~5 cents
            seg_cents = (i - 10) * 5
            is_center = (i == 10)

            if is_center:
                # Center marker always visible
                if abs(cents) <= 5:
                    seg.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
                else:
                    seg.setStyleSheet("background-color: #444444; border-radius: 2px;")
            else:
                # Light up segments between center and current position
                if cents >= 0:
                    active = 0 <= seg_cents <= cents and seg_cents > 0
                else:
                    active = cents <= seg_cents <= 0 and seg_cents < 0
                if active:
                    seg.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
                else:
                    seg.setStyleSheet("background-color: #222222; border-radius: 2px;")

    def _reset_tuner_gauge(self):
        for i, seg in enumerate(self.tuner_gauge_segments):
            if i == 10:
                seg.setStyleSheet("background-color: #444444; border-radius: 2px;")
            else:
                seg.setStyleSheet("background-color: #222222; border-radius: 2px;")

    # ── CAGED Chord Voicings Tab ─────────────────────────────────────────

    # CAGED shape data: each shape is {quality: [(fret_per_string), ...]}
    # Strings: low E(6) A(5) D(4) G(3) B(2) high e(1)
    # -1 = muted, 0 = open
    # "root_string" = which string holds the root in this shape (0-indexed from low E)
    # "base_fret" = the open-position fret offset for transposing

    CAGED_SHAPES = {
        "C": {
            "name": "C Shape",
            "root_string": 4,  # A string
            "open_root": 3,    # C is 3 semitones above A
            "major":  [-1, 3, 2, 0, 1, 0],
            "minor":  [-1, 3, 1, 0, 1, -1],
            "7":      [-1, 3, 2, 3, 1, 0],
            "m7":     [-1, 3, 1, 3, 1, -1],
            "maj7":   [-1, 3, 2, 0, 0, 0],
            "sus2":   [-1, 3, 0, 0, 1, 0],
            "sus4":   [-1, 3, 3, 0, 1, -1],
        },
        "A": {
            "name": "A Shape",
            "root_string": 4,  # A string
            "open_root": 0,    # A is 0 semitones above A
            "major":  [-1, 0, 2, 2, 2, 0],
            "minor":  [-1, 0, 2, 2, 1, 0],
            "7":      [-1, 0, 2, 0, 2, 0],
            "m7":     [-1, 0, 2, 0, 1, 0],
            "maj7":   [-1, 0, 2, 1, 2, 0],
            "sus2":   [-1, 0, 2, 2, 0, 0],
            "sus4":   [-1, 0, 2, 2, 3, 0],
        },
        "G": {
            "name": "G Shape",
            "root_string": 5,  # low E string
            "open_root": 3,    # G is 3 semitones above E
            "major":  [3, 2, 0, 0, 0, 3],
            "minor":  [3, 1, 0, 0, -1, 3],
            "7":      [3, 2, 0, 0, 0, 1],
            "m7":     [3, 1, 0, 0, -1, 1],
            "maj7":   [3, 2, 0, 0, 0, 2],
            "sus2":   [3, 0, 0, 0, 0, 3],
            "sus4":   [3, 2, 0, 0, 1, 3],
        },
        "E": {
            "name": "E Shape",
            "root_string": 5,  # low E string
            "open_root": 0,    # E is 0 semitones above E
            "major":  [0, 2, 2, 1, 0, 0],
            "minor":  [0, 2, 2, 0, 0, 0],
            "7":      [0, 2, 0, 1, 0, 0],
            "m7":     [0, 2, 0, 0, 0, 0],
            "maj7":   [0, 2, 1, 1, 0, 0],
            "sus2":   [0, 2, 4, 1, 0, 0],
            "sus4":   [0, 2, 2, 2, 0, 0],
        },
        "D": {
            "name": "D Shape",
            "root_string": 3,  # D string
            "open_root": 0,    # D is 0 semitones above D
            "major":  [-1, -1, 0, 2, 3, 2],
            "minor":  [-1, -1, 0, 2, 3, 1],
            "7":      [-1, -1, 0, 2, 1, 2],
            "m7":     [-1, -1, 0, 2, 1, 1],
            "maj7":   [-1, -1, 0, 2, 2, 2],
            "sus2":   [-1, -1, 0, 2, 3, 0],
            "sus4":   [-1, -1, 0, 2, 3, 3],
        },
    }

    NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    # Semitone index for each root string in open position
    OPEN_STRING_NOTES = {
        5: 4,   # low E = semitone 4
        4: 9,   # A = semitone 9
        3: 2,   # D = semitone 2
    }

    def _build_caged_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Root note selector
        root_label = QLabel("Root Note")
        root_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(root_label)

        selector_row = QHBoxLayout()
        selector_row.setSpacing(12)

        self.caged_root_combo = QComboBox()
        self.caged_root_combo.addItems(self.NOTE_NAMES)
        self.caged_root_combo.setCurrentText("C")
        self.caged_root_combo.setFixedWidth(100)
        selector_row.addWidget(self.caged_root_combo)

        self.caged_quality_combo = QComboBox()
        self.caged_quality_combo.addItems(["major", "minor", "7", "m7", "maj7", "sus2", "sus4"])
        self.caged_quality_combo.setFixedWidth(120)
        selector_row.addWidget(self.caged_quality_combo)

        selector_row.addStretch()
        layout.addLayout(selector_row)

        # Show button
        self.caged_show_btn = QPushButton("Show Voicings")
        self.caged_show_btn.setFixedHeight(50)
        self.caged_show_btn.setCursor(Qt.PointingHandCursor)
        self.caged_show_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.caged_show_btn.clicked.connect(self._show_caged_voicings)
        layout.addWidget(self.caged_show_btn)

        layout.addSpacing(8)

        # Chord name display
        self.caged_chord_title = QLabel("")
        self.caged_chord_title.setStyleSheet("font-size: 28px; font-weight: 700; color: #7c3aed;")
        self.caged_chord_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.caged_chord_title)

        # Container for the 5 fretboard diagrams
        self.caged_diagrams_widget = QWidget()
        self.caged_diagrams_layout = QHBoxLayout(self.caged_diagrams_widget)
        self.caged_diagrams_layout.setSpacing(12)
        self.caged_diagrams_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.caged_diagrams_widget)

        layout.addStretch()

        return tab

    def _get_caged_voicing(self, shape_key, quality, root_note):
        """Calculate the fret positions for a CAGED shape transposed to a root note."""
        shape = self.CAGED_SHAPES[shape_key]
        base_frets = shape.get(quality)
        if base_frets is None:
            return None, 0

        root_idx = self.NOTE_NAMES.index(root_note)
        root_string = shape["root_string"]
        open_note = self.OPEN_STRING_NOTES[root_string]

        # How many frets to shift from the open shape
        offset = (root_idx - open_note - shape["open_root"]) % 12

        if offset == 0:
            # Open position — return as-is
            return list(base_frets), 0

        # Transpose: shift all non-muted frets up by offset
        transposed = []
        for f in base_frets:
            if f == -1:
                transposed.append(-1)
            else:
                transposed.append(f + offset)
        return transposed, offset

    def _show_caged_voicings(self):
        root = self.caged_root_combo.currentText()
        quality = self.caged_quality_combo.currentText()

        # Build chord display name
        if quality == "major":
            chord_name = root
        elif quality == "minor":
            chord_name = root + "m"
        else:
            chord_name = root + quality

        self.caged_chord_title.setText(chord_name)

        # Clear previous diagrams
        while self.caged_diagrams_layout.count():
            child = self.caged_diagrams_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Generate all 5 CAGED shapes
        for shape_key in ["C", "A", "G", "E", "D"]:
            frets, barre_fret = self._get_caged_voicing(shape_key, quality, root)
            if frets is None:
                continue

            diagram = FretboardDiagram(
                frets=frets,
                shape_name=f"{shape_key} Shape",
                barre_fret=barre_fret,
                parent=self
            )
            self.caged_diagrams_layout.addWidget(diagram)

    # ── Chord Library Tab ───────────────────────────────────────────────

    CHORD_QUALITIES = {
        "major":   {"intervals": [0, 4, 7],          "labels": {0: "R", 4: "3", 7: "5"}},
        "minor":   {"intervals": [0, 3, 7],          "labels": {0: "R", 3: "b3", 7: "5"}},
        "7":       {"intervals": [0, 4, 7, 10],      "labels": {0: "R", 4: "3", 7: "5", 10: "b7"}},
        "m7":      {"intervals": [0, 3, 7, 10],      "labels": {0: "R", 3: "b3", 7: "5", 10: "b7"}},
        "maj7":    {"intervals": [0, 4, 7, 11],      "labels": {0: "R", 4: "3", 7: "5", 11: "7"}},
        "dim":     {"intervals": [0, 3, 6],          "labels": {0: "R", 3: "b3", 6: "b5"}},
        "aug":     {"intervals": [0, 4, 8],          "labels": {0: "R", 4: "3", 8: "#5"}},
        "sus2":    {"intervals": [0, 2, 7],          "labels": {0: "R", 2: "2", 7: "5"}},
        "sus4":    {"intervals": [0, 5, 7],          "labels": {0: "R", 5: "4", 7: "5"}},
        "add9":    {"intervals": [0, 2, 4, 7],       "labels": {0: "R", 2: "9", 4: "3", 7: "5"}},
        "m9":      {"intervals": [0, 2, 3, 7, 10],   "labels": {0: "R", 2: "9", 3: "b3", 7: "5", 10: "b7"}},
        "6":       {"intervals": [0, 4, 7, 9],       "labels": {0: "R", 4: "3", 7: "5", 9: "6"}},
        "m6":      {"intervals": [0, 3, 7, 9],       "labels": {0: "R", 3: "b3", 7: "5", 9: "6"}},
        "9":       {"intervals": [0, 2, 4, 7, 10],   "labels": {0: "R", 2: "9", 4: "3", 7: "5", 10: "b7"}},
        "11":      {"intervals": [0, 4, 5, 7, 10],   "labels": {0: "R", 4: "3", 5: "11", 7: "5", 10: "b7"}},
        "13":      {"intervals": [0, 4, 7, 9, 10],   "labels": {0: "R", 4: "3", 7: "5", 9: "13", 10: "b7"}},
        "power 5": {"intervals": [0, 7],             "labels": {0: "R", 7: "5"}},
        "dim7":    {"intervals": [0, 3, 6, 9],       "labels": {0: "R", 3: "b3", 6: "b5", 9: "bb7"}},
        "m7b5":    {"intervals": [0, 3, 6, 10],      "labels": {0: "R", 3: "b3", 6: "b5", 10: "b7"}},
        "7sus4":   {"intervals": [0, 5, 7, 10],      "labels": {0: "R", 5: "4", 7: "5", 10: "b7"}},
        "add11":   {"intervals": [0, 4, 5, 7],       "labels": {0: "R", 4: "3", 5: "11", 7: "5"}},
        "madd9":   {"intervals": [0, 2, 3, 7],       "labels": {0: "R", 2: "9", 3: "b3", 7: "5"}},
    }

    # Base MIDI note numbers for standard tuning open strings (low E to high e)
    STANDARD_MIDI = [40, 45, 50, 55, 59, 64]
    STANDARD_SEMITONES = [4, 9, 2, 7, 11, 4]

    # Progression templates: degrees are semitone offsets from key root
    PROGRESSION_TEMPLATES = [
        {"name": "I \u2013 IV \u2013 V",          "degrees": [0, 5, 7],       "quals": ["major", "major", "major"]},
        {"name": "I \u2013 V \u2013 vi \u2013 IV",      "degrees": [0, 7, 9, 5],    "quals": ["major", "major", "minor", "major"]},
        {"name": "I \u2013 vi \u2013 IV \u2013 V",      "degrees": [0, 9, 5, 7],    "quals": ["major", "minor", "major", "major"]},
        {"name": "ii \u2013 V \u2013 I",          "degrees": [2, 7, 0],       "quals": ["minor", "major", "major"]},
        {"name": "I \u2013 IV \u2013 vi \u2013 V",      "degrees": [0, 5, 9, 7],    "quals": ["major", "major", "minor", "major"]},
        {"name": "vi \u2013 IV \u2013 I \u2013 V",      "degrees": [9, 5, 0, 7],    "quals": ["minor", "major", "major", "major"]},
        {"name": "I \u2013 iii \u2013 IV \u2013 V",     "degrees": [0, 4, 5, 7],    "quals": ["major", "minor", "major", "major"]},
        {"name": "I \u2013 V \u2013 IV",          "degrees": [0, 7, 5],       "quals": ["major", "major", "major"]},
        {"name": "I \u2013 IV \u2013 V \u2013 IV",      "degrees": [0, 5, 7, 5],    "quals": ["major", "major", "major", "major"]},
        {"name": "I \u2013 bVII \u2013 IV",       "degrees": [0, 10, 5],      "quals": ["major", "major", "major"]},
    ]

    def _build_chordlib_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # ── Row 1: Tuning ──
        tuning_label = QLabel("Tuning")
        tuning_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(tuning_label)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self.cl_tuning_combo = QComboBox()
        self.cl_tuning_combo.addItems(list(self.GUITAR_TUNINGS.keys()))
        self.cl_tuning_combo.setCurrentIndex(0)
        self.cl_tuning_combo.setFixedWidth(220)
        row1.addWidget(self.cl_tuning_combo)

        row1.addStretch()
        layout.addLayout(row1)

        # ── Row 2: Root + Quality ──
        chord_label = QLabel("Chord")
        chord_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(chord_label)

        row2 = QHBoxLayout()
        row2.setSpacing(12)

        root_lbl = QLabel("Root:")
        root_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row2.addWidget(root_lbl)

        self.cl_root_combo = QComboBox()
        self.cl_root_combo.addItems(self.NOTE_NAMES)
        self.cl_root_combo.setCurrentText("C")
        self.cl_root_combo.setFixedWidth(80)
        row2.addWidget(self.cl_root_combo)

        qual_lbl = QLabel("Quality:")
        qual_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row2.addWidget(qual_lbl)

        self.cl_quality_combo = QComboBox()
        self.cl_quality_combo.addItems(list(self.CHORD_QUALITIES.keys()))
        self.cl_quality_combo.setFixedWidth(130)
        row2.addWidget(self.cl_quality_combo)

        row2.addStretch()
        layout.addLayout(row2)

        # ── Row 3: Filters ──
        filter_label = QLabel("Filters")
        filter_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(filter_label)

        row3 = QHBoxLayout()
        row3.setSpacing(12)

        type_lbl = QLabel("Type:")
        type_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row3.addWidget(type_lbl)

        self.cl_type_combo = QComboBox()
        self.cl_type_combo.addItems(["All", "Open chords only", "Barre chords only"])
        self.cl_type_combo.setFixedWidth(170)
        row3.addWidget(self.cl_type_combo)

        pos_lbl = QLabel("Position:")
        pos_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row3.addWidget(pos_lbl)

        self.cl_position_combo = QComboBox()
        self.cl_position_combo.addItems(["All frets", "Frets 0\u20134", "Frets 5\u20139", "Frets 10\u201314"])
        self.cl_position_combo.setFixedWidth(130)
        row3.addWidget(self.cl_position_combo)

        stretch_lbl = QLabel("Max stretch:")
        stretch_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row3.addWidget(stretch_lbl)

        self.cl_stretch_slider = QSlider(Qt.Horizontal)
        self.cl_stretch_slider.setMinimum(3)
        self.cl_stretch_slider.setMaximum(5)
        self.cl_stretch_slider.setValue(4)
        self.cl_stretch_slider.setFixedWidth(80)
        self.cl_stretch_slider.setTickPosition(QSlider.TicksBelow)
        self.cl_stretch_slider.setTickInterval(1)
        row3.addWidget(self.cl_stretch_slider)

        self.cl_stretch_val = QLabel("4 frets")
        self.cl_stretch_val.setStyleSheet("font-size: 13px; color: #e0e0e0; min-width: 50px;")
        self.cl_stretch_slider.valueChanged.connect(
            lambda v: self.cl_stretch_val.setText(f"{v} frets"))
        row3.addWidget(self.cl_stretch_val)

        row3.addStretch()
        layout.addLayout(row3)

        # ── Row 4: Display toggle + Generate button ──
        row4 = QHBoxLayout()
        row4.setSpacing(12)

        self.cl_show_intervals_chk = QCheckBox("Show intervals (R, 3, 5\u2026)")
        self.cl_show_intervals_chk.setChecked(True)
        self.cl_show_intervals_chk.stateChanged.connect(self._cl_refresh_display)
        row4.addWidget(self.cl_show_intervals_chk)

        row4.addStretch()

        self.cl_generate_btn = QPushButton("Find Voicings")
        self.cl_generate_btn.setFixedHeight(50)
        self.cl_generate_btn.setFixedWidth(200)
        self.cl_generate_btn.setCursor(Qt.PointingHandCursor)
        self.cl_generate_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.cl_generate_btn.clicked.connect(self._cl_generate)
        row4.addWidget(self.cl_generate_btn)

        layout.addLayout(row4)

        # ── Chord title ──
        self.cl_chord_title = QLabel("")
        self.cl_chord_title.setStyleSheet("font-size: 28px; font-weight: 700; color: #7c3aed;")
        self.cl_chord_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.cl_chord_title)

        self.cl_count_label = QLabel("")
        self.cl_count_label.setStyleSheet("font-size: 12px; color: #888888;")
        self.cl_count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.cl_count_label)

        # ── Voicings grid (scrollable) ──
        self.cl_scroll = QScrollArea()
        self.cl_scroll.setWidgetResizable(True)
        self.cl_scroll.setFrameShape(QFrame.NoFrame)
        self.cl_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.cl_scroll.setMinimumHeight(320)

        self.cl_grid_container = QWidget()
        self.cl_grid_layout = QGridLayout(self.cl_grid_container)
        self.cl_grid_layout.setSpacing(10)
        self.cl_grid_layout.setContentsMargins(0, 0, 0, 0)
        self.cl_scroll.setWidget(self.cl_grid_container)
        layout.addWidget(self.cl_scroll)

        # ── Legend ──
        legend_row = QHBoxLayout()
        legend_row.setSpacing(20)
        legend_row.addStretch()
        for color, label in [("#7c3aed", "Root"), ("#e0e0e0", "Chord tone")]:
            dot = QLabel("\u25CF")
            dot.setStyleSheet(f"font-size: 16px; color: {color}; background: transparent;")
            legend_row.addWidget(dot)
            ltxt = QLabel(label)
            ltxt.setStyleSheet("font-size: 11px; color: #888888; background: transparent;")
            legend_row.addWidget(ltxt)
        click_hint = QLabel("\u266A Click a voicing to hear it")
        click_hint.setStyleSheet("font-size: 11px; color: #666666; background: transparent; margin-left: 16px;")
        legend_row.addWidget(click_hint)
        legend_row.addStretch()
        layout.addLayout(legend_row)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a2a;")
        layout.addWidget(sep)

        # ── Common Progressions Section ──
        prog_label = QLabel("Common Progressions")
        prog_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(prog_label)

        self.cl_prog_desc = QLabel("Select a chord and click Find Voicings to see progressions that use it.")
        self.cl_prog_desc.setStyleSheet("font-size: 12px; color: #666666;")
        self.cl_prog_desc.setWordWrap(True)
        layout.addWidget(self.cl_prog_desc)

        self.cl_prog_container = QWidget()
        self.cl_prog_layout = QVBoxLayout(self.cl_prog_container)
        self.cl_prog_layout.setSpacing(8)
        self.cl_prog_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.cl_prog_container)

        layout.addStretch()

        # Internal state
        self._cl_voicings = []  # List of fret arrays
        self._cl_current_tuning = [4, 9, 2, 7, 11, 4]
        self._cl_current_root = 0
        self._cl_current_quality = "major"
        self._cl_audio_thread = None

        return tab

    def _cl_get_tuning(self):
        tuning_name = self.cl_tuning_combo.currentText()
        return self.GUITAR_TUNINGS.get(tuning_name, [4, 9, 2, 7, 11, 4])

    def _cl_get_open_midi(self, tuning):
        """Get MIDI note numbers for open strings in a given tuning."""
        midi = []
        for i in range(6):
            diff = (tuning[i] - self.STANDARD_SEMITONES[i]) % 12
            if diff > 6:
                diff -= 12
            midi.append(self.STANDARD_MIDI[i] + diff)
        return midi

    def _cl_generate_voicings(self, tuning, root_idx, quality_key, max_stretch=4, max_fret=15):
        """Algorithmically generate all playable voicings for a chord."""
        q = self.CHORD_QUALITIES[quality_key]
        chord_tones = {(root_idx + iv) % 12 for iv in q["intervals"]}
        intervals = q["intervals"]

        # For each string, find frets that produce chord tones
        string_options = []
        for string_note in tuning:
            frets = [-1]  # muted option
            for fret in range(0, max_fret + 1):
                if (string_note + fret) % 12 in chord_tones:
                    frets.append(fret)
            string_options.append(frets)

        # Essential tones: root + defining intervals
        # For extended chords (5+ tones), the 5th can be omitted
        essential_tones = set()
        essential_tones.add(root_idx % 12)
        if len(intervals) >= 2:
            essential_tones.add((root_idx + intervals[1]) % 12)
        if len(intervals) >= 4:
            # Include the 7th/extension for 7th+ chords
            essential_tones.add((root_idx + intervals[-1]) % 12)

        voicings = []
        seen = set()

        for combo in iter_product(*string_options):
            frets = list(combo)

            # Count sounding strings
            sounding = [(i, f) for i, f in enumerate(frets) if f != -1]
            num_sounding = len(sounding)
            if num_sounding < 4:
                continue

            # Check for internal muted strings (only allow edge mutes)
            first_sound = sounding[0][0]
            last_sound = sounding[-1][0]
            expected_count = last_sound - first_sound + 1
            if num_sounding != expected_count:
                continue  # has internal mute

            # Fret span check
            fretted = [f for _, f in sounding if f > 0]
            if fretted:
                span = max(fretted) - min(fretted)
                if span > max_stretch:
                    continue
            # Also check that no more than 4 distinct frets are used (finger limit)
            if fretted and len(set(fretted)) > 4:
                continue

            # Bass note must be root
            bass_note = (tuning[sounding[0][0]] + sounding[0][1]) % 12
            if bass_note != root_idx % 12:
                continue

            # Check essential tones present
            present = {(tuning[i] + f) % 12 for i, f in sounding}
            if not essential_tones.issubset(present):
                continue

            # Deduplicate by note tuple
            note_key = tuple(
                (tuning[i] + f) % 12 if f != -1 else -1 for i, f in enumerate(frets)
            )
            if note_key in seen:
                continue
            seen.add(note_key)

            voicings.append(frets)

        # Sort by: lowest fret position, then fewer muted strings, then open strings first
        def sort_key(v):
            fretted = [f for f in v if f > 0]
            min_f = min(fretted) if fretted else 0
            muted = sum(1 for f in v if f == -1)
            opens = sum(1 for f in v if f == 0)
            return (min_f, muted, -opens)

        voicings.sort(key=sort_key)
        return voicings

    def _cl_filter_voicings(self, voicings):
        """Apply UI filters to the voicing list."""
        filtered = list(voicings)

        # Type filter
        type_filter = self.cl_type_combo.currentText()
        if type_filter == "Open chords only":
            filtered = [v for v in filtered if any(f == 0 for f in v)]
        elif type_filter == "Barre chords only":
            filtered = [v for v in filtered if not any(f == 0 for f in v) and any(f > 0 for f in v)]

        # Position filter
        pos_filter = self.cl_position_combo.currentText()
        if pos_filter == "Frets 0\u20134":
            filtered = [v for v in filtered if all(f <= 4 for f in v if f > 0)]
        elif pos_filter == "Frets 5\u20139":
            filtered = [v for v in filtered
                        if any(5 <= f <= 9 for f in v if f > 0)
                        and all(f <= 9 for f in v if f > 0)]
        elif pos_filter == "Frets 10\u201314":
            filtered = [v for v in filtered
                        if any(f >= 10 for f in v if f > 0)
                        and all(f <= 14 for f in v if f > 0)]

        return filtered

    def _cl_generate(self):
        """Generate and display voicings based on current selections."""
        tuning = self._cl_get_tuning()
        root_name = self.cl_root_combo.currentText()
        root_idx = self.NOTE_NAMES.index(root_name)
        quality = self.cl_quality_combo.currentText()
        max_stretch = self.cl_stretch_slider.value()

        self._cl_current_tuning = tuning
        self._cl_current_root = root_idx
        self._cl_current_quality = quality

        # Build chord display name
        if quality == "major":
            chord_name = root_name
        elif quality == "minor":
            chord_name = root_name + "m"
        elif quality == "power 5":
            chord_name = root_name + "5"
        else:
            chord_name = root_name + quality

        self.cl_chord_title.setText(chord_name)

        # Generate voicings
        self._cl_voicings = self._cl_generate_voicings(
            tuning, root_idx, quality, max_stretch=max_stretch
        )

        self._cl_refresh_display()
        self._cl_show_progressions(root_name, quality)

    def _cl_refresh_display(self):
        """Refresh the voicing grid display (after generate or toggle change)."""
        # Clear existing
        while self.cl_grid_layout.count():
            child = self.cl_grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self._cl_voicings:
            self.cl_count_label.setText("No voicings found with current settings")
            return

        filtered = self._cl_filter_voicings(self._cl_voicings)

        if not filtered:
            self.cl_count_label.setText("No voicings match the current filters (try changing filters)")
            return

        # Cap display at 40 voicings
        display_voicings = filtered[:40]
        total = len(filtered)
        showing = len(display_voicings)
        self.cl_count_label.setText(
            f"{total} voicing{'s' if total != 1 else ''} found"
            + (f" (showing first {showing})" if showing < total else "")
        )

        tuning = self._cl_current_tuning
        root_idx = self._cl_current_root
        quality = self._cl_current_quality
        q_data = self.CHORD_QUALITIES[quality]
        interval_map = q_data["labels"]
        show_intervals = self.cl_show_intervals_chk.isChecked()

        cols = 5
        for idx, voicing in enumerate(display_voicings):
            # Determine position label
            fretted = [f for f in voicing if f > 0]
            if fretted:
                pos = f"Pos {min(fretted)}"
            else:
                pos = "Open"

            diagram = ChordLibDiagram(
                frets=voicing,
                root_idx=root_idx,
                interval_map=interval_map,
                tuning=tuning,
                show_intervals=show_intervals,
                position_label=pos,
                parent=self
            )
            # Connect click to play audio
            v_copy = list(voicing)
            t_copy = list(tuning)
            diagram.clicked.connect(lambda v=v_copy, t=t_copy: self._cl_play_voicing(v, t))

            row = idx // cols
            col = idx % cols
            self.cl_grid_layout.addWidget(diagram, row, col)

    def _cl_play_voicing(self, frets, tuning):
        """Synthesize and play a chord voicing as a strummed sound."""
        def _play():
            try:
                import sounddevice as sd
            except ImportError:
                return

            sr = 44100
            duration = 1.8
            strum_delay = 0.035  # 35ms between strings

            total_len = int(sr * (duration + strum_delay * 6))
            samples = np.zeros(total_len, dtype=np.float32)
            open_midi = self._cl_get_open_midi(tuning)

            for i in range(6):
                fret = frets[i]
                if fret == -1:
                    continue
                midi_note = open_midi[i] + fret
                freq = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

                t = np.linspace(0, duration, int(sr * duration), endpoint=False)
                # Guitar-like tone: fundamental + harmonics with decay
                wave = (np.sin(2 * np.pi * freq * t) * 0.50 +
                        np.sin(2 * np.pi * freq * 2 * t) * 0.25 +
                        np.sin(2 * np.pi * freq * 3 * t) * 0.12 +
                        np.sin(2 * np.pi * freq * 4 * t) * 0.06 +
                        np.sin(2 * np.pi * freq * 5 * t) * 0.03)
                envelope = np.exp(-t * 2.5)
                wave *= envelope * 0.25

                offset = int(i * strum_delay * sr)
                end = offset + len(wave)
                if end > total_len:
                    end = total_len
                    wave = wave[:end - offset]
                samples[offset:end] += wave

            # Normalize
            peak = np.max(np.abs(samples))
            if peak > 0:
                samples = samples / peak * 0.7

            sd.play(samples, sr)

        # Run in thread to avoid blocking UI
        t = threading.Thread(target=_play, daemon=True)
        t.start()
        self._cl_audio_thread = t

    def _cl_show_progressions(self, root_name, quality):
        """Show common progressions that include the selected chord."""
        # Clear existing
        while self.cl_prog_layout.count():
            child = self.cl_prog_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        root_idx = self.NOTE_NAMES.index(root_name)
        found = []

        # Check only simple qualities for progression matching
        simple_qual = quality
        if simple_qual not in ("major", "minor"):
            # Progressions mainly work with major/minor
            self.cl_prog_desc.setText(
                f"Progressions are shown for major and minor chords. "
                f"Try selecting {root_name} major or {root_name}m to see progressions."
            )
            return

        for template in self.PROGRESSION_TEMPLATES:
            for pos_idx, (deg, qual) in enumerate(zip(template["degrees"], template["quals"])):
                if qual != simple_qual:
                    continue
                # If chord at this position matches, compute the key
                key_root = (root_idx - deg) % 12
                key_name = self.NOTE_NAMES[key_root]

                # Build the full progression chord names
                chord_names = []
                for d, q in zip(template["degrees"], template["quals"]):
                    note = self.NOTE_NAMES[(key_root + d) % 12]
                    if q == "minor":
                        chord_names.append(note + "m")
                    else:
                        chord_names.append(note)

                prog_str = " \u2013 ".join(chord_names)
                display = f"{template['name']}  (key of {key_name}):  {prog_str}"
                found.append((display, chord_names))

        if not found:
            self.cl_prog_desc.setText("No common progressions found for this chord.")
            return

        self.cl_prog_desc.setText(
            f"Progressions featuring {root_name}{'m' if quality == 'minor' else ''}:"
        )

        for display_text, chord_names in found[:8]:  # Limit to 8
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            label = QLabel(display_text)
            label.setStyleSheet("font-size: 13px; color: #e0e0e0;")
            row_layout.addWidget(label)

            row_layout.addStretch()

            # Quick-view buttons for each chord in the progression
            for cn in chord_names:
                # Parse chord name to root + quality
                if cn.endswith("m") and len(cn) >= 2 and cn[-2] != "#":
                    c_root = cn[:-1]
                    c_qual = "minor"
                else:
                    c_root = cn
                    c_qual = "major"

                btn = QPushButton(cn)
                btn.setFixedHeight(28)
                btn.setFixedWidth(50)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet("""
                    QPushButton { background-color: #2a2a2a; color: #7c3aed; border: 1px solid #3a3a3a;
                                  border-radius: 6px; font-size: 11px; font-weight: 600; }
                    QPushButton:hover { background-color: #3a3a3a; }
                """)
                btn.clicked.connect(
                    lambda checked=False, r=c_root, q=c_qual:
                        self._cl_jump_to_chord(r, q)
                )
                row_layout.addWidget(btn)

            self.cl_prog_layout.addWidget(row_widget)

    def _cl_jump_to_chord(self, root_name, quality):
        """Set the selectors to a chord and generate voicings."""
        self.cl_root_combo.setCurrentText(root_name)
        self.cl_quality_combo.setCurrentText(quality)
        self._cl_generate()

    # ── Notes & Scales Tab ──────────────────────────────────────────────

    GUITAR_TUNINGS = {
        "Standard (EADGBE)":      [4, 9, 2, 7, 11, 4],
        "Drop D (DADGBE)":        [2, 9, 2, 7, 11, 4],
        "DADGAD":                 [2, 9, 2, 7, 9, 2],
        "Open G (DGDGBD)":       [2, 7, 2, 7, 11, 2],
        "Open D (DADF#AD)":      [2, 9, 2, 6, 9, 2],
        "Open E (EBEG#BE)":      [4, 11, 4, 8, 11, 4],
        "Open A (EAEAC#E)":      [4, 9, 4, 9, 1, 4],
        "Open C (CGCGCE)":       [0, 7, 0, 7, 0, 4],
        "Drop C (CADGBE)":       [0, 7, 0, 5, 9, 2],
        "Half Step Down (Eb)":   [3, 8, 1, 6, 10, 3],
        "Full Step Down (D)":    [2, 7, 0, 5, 9, 2],
        "Double Drop D (DADGBD)":[2, 9, 2, 7, 11, 2],
    }

    SCALE_DEFINITIONS = {
        "Major (Ionian)":       [0, 2, 4, 5, 7, 9, 11],
        "Natural Minor (Aeolian)": [0, 2, 3, 5, 7, 8, 10],
        "Pentatonic Major":     [0, 2, 4, 7, 9],
        "Pentatonic Minor":     [0, 3, 5, 7, 10],
        "Blues":                [0, 3, 5, 6, 7, 10],
        "Dorian":               [0, 2, 3, 5, 7, 9, 10],
        "Mixolydian":           [0, 2, 4, 5, 7, 9, 10],
        "Phrygian":             [0, 1, 3, 5, 7, 8, 10],
        "Lydian":               [0, 2, 4, 6, 7, 9, 11],
        "Locrian":              [0, 1, 3, 5, 6, 8, 10],
        "Harmonic Minor":       [0, 2, 3, 5, 7, 8, 11],
        "Melodic Minor":        [0, 2, 3, 5, 7, 9, 11],
        "Whole Tone":           [0, 2, 4, 6, 8, 10],
        "Chromatic":            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    }

    def _build_scales_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── Controls row ──
        ctrl_label = QLabel("Tuning & Scale")
        ctrl_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(ctrl_label)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        # Tuning selector
        tuning_lbl = QLabel("Tuning:")
        tuning_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row1.addWidget(tuning_lbl)

        self.scales_tuning_combo = QComboBox()
        self.scales_tuning_combo.addItems(list(self.GUITAR_TUNINGS.keys()))
        self.scales_tuning_combo.setCurrentIndex(0)
        self.scales_tuning_combo.setFixedWidth(220)
        self.scales_tuning_combo.currentIndexChanged.connect(self._update_scale_fretboard)
        self.scales_tuning_combo.currentIndexChanged.connect(self._update_quiz_string_labels)
        row1.addWidget(self.scales_tuning_combo)

        row1.addSpacing(16)

        # Natural notes toggle
        self.scales_natural_chk = QCheckBox("Natural notes only")
        self.scales_natural_chk.stateChanged.connect(self._update_scale_fretboard)
        row1.addWidget(self.scales_natural_chk)

        row1.addStretch()
        layout.addLayout(row1)

        # ── Scale selection row ──
        row2 = QHBoxLayout()
        row2.setSpacing(12)

        root_lbl = QLabel("Root:")
        root_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row2.addWidget(root_lbl)

        self.scales_root_combo = QComboBox()
        self.scales_root_combo.addItems(self.NOTE_NAMES)
        self.scales_root_combo.setCurrentText("C")
        self.scales_root_combo.setFixedWidth(80)
        self.scales_root_combo.currentIndexChanged.connect(self._update_scale_fretboard)
        row2.addWidget(self.scales_root_combo)

        scale_lbl = QLabel("Scale:")
        scale_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        row2.addWidget(scale_lbl)

        self.scales_type_combo = QComboBox()
        self.scales_type_combo.addItem("None (show all notes)")
        self.scales_type_combo.addItems(list(self.SCALE_DEFINITIONS.keys()))
        self.scales_type_combo.setCurrentIndex(0)
        self.scales_type_combo.setFixedWidth(220)
        self.scales_type_combo.currentIndexChanged.connect(self._update_scale_fretboard)
        row2.addWidget(self.scales_type_combo)

        row2.addStretch()
        layout.addLayout(row2)

        layout.addSpacing(8)

        # ── Scale info label ──
        self.scales_info_label = QLabel("")
        self.scales_info_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #7c3aed;")
        self.scales_info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.scales_info_label)

        # ── Fretboard widget ──
        self.scale_fretboard = ScaleFretboardWidget()
        layout.addWidget(self.scale_fretboard)

        # ── Legend ──
        legend_row = QHBoxLayout()
        legend_row.setSpacing(20)
        legend_row.addStretch()

        for color, label in [("#7c3aed", "Root"), ("#4c2889", "Scale note"), ("#2a2a2a", "Other note")]:
            dot = QLabel("\u25CF")
            dot.setStyleSheet(f"font-size: 16px; color: {color}; background: transparent;")
            legend_row.addWidget(dot)
            ltxt = QLabel(label)
            ltxt.setStyleSheet("font-size: 11px; color: #888888; background: transparent;")
            legend_row.addWidget(ltxt)

        legend_row.addStretch()
        layout.addLayout(legend_row)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a2a;")
        layout.addSpacing(8)
        layout.addWidget(sep)
        layout.addSpacing(4)

        # ── Note Quiz Section ──
        quiz_label = QLabel("Note Quiz")
        quiz_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(quiz_label)

        quiz_desc = QLabel("Test your fretboard knowledge! Select which strings to include, then quiz yourself.")
        quiz_desc.setStyleSheet("font-size: 12px; color: #666666;")
        quiz_desc.setWordWrap(True)
        layout.addWidget(quiz_desc)

        # String selection checkboxes
        strings_row = QHBoxLayout()
        strings_row.setSpacing(16)

        strings_lbl = QLabel("Strings:")
        strings_lbl.setStyleSheet("font-size: 13px; color: #999999;")
        strings_row.addWidget(strings_lbl)

        # String names for standard tuning display — updated dynamically
        self._quiz_string_checks = []
        string_display_names = ["High e", "B", "G", "D", "A", "Low E"]
        for i, sname in enumerate(string_display_names):
            chk = QCheckBox(sname)
            chk.setChecked(True)
            self._quiz_string_checks.append(chk)
            strings_row.addWidget(chk)

        strings_row.addStretch()
        layout.addLayout(strings_row)

        # Quiz buttons row
        quiz_btn_row = QHBoxLayout()
        quiz_btn_row.setSpacing(12)

        self.quiz_start_btn = QPushButton("Start Quiz")
        self.quiz_start_btn.setFixedHeight(44)
        self.quiz_start_btn.setFixedWidth(140)
        self.quiz_start_btn.setCursor(Qt.PointingHandCursor)
        self.quiz_start_btn.setStyleSheet(self.ACTION_BTN_STYLE)
        self.quiz_start_btn.clicked.connect(self._quiz_start)
        quiz_btn_row.addWidget(self.quiz_start_btn)

        self.quiz_reveal_btn = QPushButton("Reveal")
        self.quiz_reveal_btn.setFixedHeight(44)
        self.quiz_reveal_btn.setFixedWidth(120)
        self.quiz_reveal_btn.setCursor(Qt.PointingHandCursor)
        self.quiz_reveal_btn.setStyleSheet("""
            QPushButton { background-color: #0d9488; color: #ffffff; border: none; border-radius: 10px; font-size: 14px; font-weight: 700; }
            QPushButton:hover { background-color: #0f766e; }
            QPushButton:pressed { background-color: #115e59; }
            QPushButton:disabled { background-color: #1a2e2b; color: #555555; }
        """)
        self.quiz_reveal_btn.clicked.connect(self._quiz_reveal)
        self.quiz_reveal_btn.setEnabled(False)
        quiz_btn_row.addWidget(self.quiz_reveal_btn)

        self.quiz_next_btn = QPushButton("Next")
        self.quiz_next_btn.setFixedHeight(44)
        self.quiz_next_btn.setFixedWidth(120)
        self.quiz_next_btn.setCursor(Qt.PointingHandCursor)
        self.quiz_next_btn.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; border-radius: 10px; font-size: 14px; font-weight: 700; }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:pressed { background-color: #1e40af; }
            QPushButton:disabled { background-color: #1a2040; color: #555555; }
        """)
        self.quiz_next_btn.clicked.connect(self._quiz_next)
        self.quiz_next_btn.setEnabled(False)
        quiz_btn_row.addWidget(self.quiz_next_btn)

        self.quiz_stop_btn = QPushButton("End Quiz")
        self.quiz_stop_btn.setFixedHeight(44)
        self.quiz_stop_btn.setFixedWidth(120)
        self.quiz_stop_btn.setCursor(Qt.PointingHandCursor)
        self.quiz_stop_btn.setStyleSheet("""
            QPushButton { background-color: #dc2626; color: #ffffff; border: none; border-radius: 10px; font-size: 14px; font-weight: 700; }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:pressed { background-color: #991b1b; }
            QPushButton:disabled { background-color: #2a1a1a; color: #555555; }
        """)
        self.quiz_stop_btn.clicked.connect(self._quiz_stop)
        self.quiz_stop_btn.setEnabled(False)
        quiz_btn_row.addWidget(self.quiz_stop_btn)

        quiz_btn_row.addStretch()
        layout.addLayout(quiz_btn_row)

        # Quiz prompt / feedback label
        self.quiz_prompt_label = QLabel("")
        self.quiz_prompt_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #e0e0e0;")
        self.quiz_prompt_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.quiz_prompt_label)

        # Score tracker
        self._quiz_total = 0
        self._quiz_active = False

        layout.addStretch()

        # Initial render
        self._update_scale_fretboard()

        return tab

    def _update_scale_fretboard(self):
        # Tuning
        tuning_name = self.scales_tuning_combo.currentText()
        tuning = self.GUITAR_TUNINGS.get(tuning_name, [4, 9, 2, 7, 11, 4])
        self.scale_fretboard.set_tuning(tuning)

        # Natural only
        self.scale_fretboard.set_natural_only(self.scales_natural_chk.isChecked())

        # Scale
        scale_name = self.scales_type_combo.currentText()
        if scale_name == "None (show all notes)":
            self.scale_fretboard.set_scale(set(), -1)
            self.scales_info_label.setText("")
        else:
            root_name = self.scales_root_combo.currentText()
            root_val = self.NOTE_NAMES.index(root_name)
            intervals = self.SCALE_DEFINITIONS[scale_name]
            scale_set = {(root_val + iv) % 12 for iv in intervals}
            self.scale_fretboard.set_scale(scale_set, root_val)

            note_names = [self.NOTE_NAMES[(root_val + iv) % 12] for iv in intervals]
            self.scales_info_label.setText(f"{root_name} {scale_name}:  {' \u2013 '.join(note_names)}")

    # ── Note Quiz Logic ──────────────────────────────────────────────────

    def _update_quiz_string_labels(self):
        """Update the string checkbox labels to reflect the current tuning."""
        tuning_name = self.scales_tuning_combo.currentText()
        tuning = self.GUITAR_TUNINGS.get(tuning_name, [4, 9, 2, 7, 11, 4])
        notes = ScaleFretboardWidget.ALL_NOTES
        # Widget index 0 = top = highest string (tuning[5]), index 5 = bottom = lowest (tuning[0])
        for i in range(6):
            note = notes[tuning[5 - i]]
            if i == 0:
                label = f"High {note}"
            elif i == 5:
                label = f"Low {note}"
            else:
                label = note
            self._quiz_string_checks[i].setText(label)

    def _quiz_get_selected_strings(self):
        """Return list of widget string indices (0=high e top, 5=low E bottom) that are checked."""
        return [i for i, chk in enumerate(self._quiz_string_checks) if chk.isChecked()]

    def _quiz_pick_random(self):
        """Pick a random string + fret from the selected strings."""
        strings = self._quiz_get_selected_strings()
        if not strings:
            return
        si = random.choice(strings)
        fret = random.randint(0, ScaleFretboardWidget.NUM_FRETS)
        self.scale_fretboard.quiz_string = si
        self.scale_fretboard.quiz_fret = fret
        self.scale_fretboard.quiz_revealed = False
        self.scale_fretboard.update()

        # Build prompt text showing string name + fret number
        tuning_name = self.scales_tuning_combo.currentText()
        tuning = self.GUITAR_TUNINGS.get(tuning_name, [4, 9, 2, 7, 11, 4])
        open_note = tuning[5 - si]
        string_name = ScaleFretboardWidget.ALL_NOTES[open_note]
        if si == 0:
            string_label = f"High {string_name} string"
        elif si == 5:
            string_label = f"Low {string_name} string"
        else:
            string_label = f"{string_name} string"

        fret_label = "open" if fret == 0 else f"fret {fret}"
        self.quiz_prompt_label.setText(f"What note is on the {string_label}, {fret_label}?")
        self.quiz_prompt_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #e0e0e0;")

    def _quiz_start(self):
        selected = self._quiz_get_selected_strings()
        if not selected:
            self.quiz_prompt_label.setText("Select at least one string to quiz on.")
            self.quiz_prompt_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #ef4444;")
            return

        self._quiz_active = True
        self._quiz_total = 0
        self.scale_fretboard.quiz_mode = True

        # Disable scale/tuning controls during quiz to avoid confusion
        self.scales_tuning_combo.setEnabled(False)
        self.scales_root_combo.setEnabled(False)
        self.scales_type_combo.setEnabled(False)
        self.scales_natural_chk.setEnabled(False)

        # Update button states
        self.quiz_start_btn.setEnabled(False)
        self.quiz_reveal_btn.setEnabled(True)
        self.quiz_next_btn.setEnabled(False)
        self.quiz_stop_btn.setEnabled(True)

        # Disable string checkboxes during quiz
        for chk in self._quiz_string_checks:
            chk.setEnabled(False)

        self._quiz_pick_random()

    def _quiz_reveal(self):
        if not self._quiz_active:
            return
        self.scale_fretboard.quiz_revealed = True
        self.scale_fretboard.update()

        # Show the answer in the prompt label
        tuning_name = self.scales_tuning_combo.currentText()
        tuning = self.GUITAR_TUNINGS.get(tuning_name, [4, 9, 2, 7, 11, 4])
        si = self.scale_fretboard.quiz_string
        fret = self.scale_fretboard.quiz_fret
        open_note = tuning[5 - si]
        answer = ScaleFretboardWidget.ALL_NOTES[(open_note + fret) % 12]
        self.quiz_prompt_label.setText(f"The answer is:  {answer}")
        self.quiz_prompt_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #22c55e;")

        self.quiz_reveal_btn.setEnabled(False)
        self.quiz_next_btn.setEnabled(True)

    def _quiz_next(self):
        if not self._quiz_active:
            return
        self._quiz_total += 1
        self.quiz_reveal_btn.setEnabled(True)
        self.quiz_next_btn.setEnabled(False)
        self._quiz_pick_random()

    def _quiz_stop(self):
        self._quiz_active = False
        self.scale_fretboard.quiz_mode = False
        self.scale_fretboard.quiz_string = -1
        self.scale_fretboard.quiz_fret = -1
        self.scale_fretboard.quiz_revealed = False
        self.scale_fretboard.update()

        # Re-enable controls
        self.scales_tuning_combo.setEnabled(True)
        self.scales_root_combo.setEnabled(True)
        self.scales_type_combo.setEnabled(True)
        self.scales_natural_chk.setEnabled(True)

        self.quiz_start_btn.setEnabled(True)
        self.quiz_reveal_btn.setEnabled(False)
        self.quiz_next_btn.setEnabled(False)
        self.quiz_stop_btn.setEnabled(False)

        for chk in self._quiz_string_checks:
            chk.setEnabled(True)

        total = self._quiz_total
        self.quiz_prompt_label.setText(f"Quiz ended \u2014 {total} note{'s' if total != 1 else ''} practiced.")
        self.quiz_prompt_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #7c3aed;")

        # Restore normal fretboard view
        self._update_scale_fretboard()

    # ── Guitar Tabs Search Tab ───────────────────────────────────────────

    def _build_tabs_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Search input
        search_label = QLabel("Search for Tabs & Chords")
        search_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(search_label)

        search_row = QHBoxLayout()
        self.tabs_search_input = QLineEdit()
        self.tabs_search_input.setPlaceholderText("Enter song name or artist...")
        self.tabs_search_input.returnPressed.connect(self._search_tabs)
        search_row.addWidget(self.tabs_search_input)

        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(100)
        search_btn.clicked.connect(self._search_tabs)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # Status
        self.tabs_status_label = QLabel("")
        self.tabs_status_label.setStyleSheet("font-size: 11px; color: #666666;")
        layout.addWidget(self.tabs_status_label)

        # Results container (scrolls via the parent page's scroll area)
        self.tabs_results_widget = QWidget()
        self.tabs_results_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs_results_layout = QVBoxLayout(self.tabs_results_widget)
        self.tabs_results_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs_results_layout.setSpacing(8)
        layout.addWidget(self.tabs_results_widget, 1)  # Stretch factor so it expands

        # Quick search buttons for popular sources
        source_label = QLabel("Or browse directly")
        source_label.setStyleSheet("font-weight: 600; color: #bbbbbb; font-size: 12px; text-transform: uppercase; letter-spacing: 1px;")
        layout.addWidget(source_label)

        source_row = QHBoxLayout()
        for site_name, site_url_tpl in [
            ("Ultimate Guitar", "https://www.ultimate-guitar.com/search.php?search_type=title&value={query}"),
            ("Songsterr", "https://www.songsterr.com/?pattern={query}"),
            ("Chordify", "https://chordify.net/search/{query}"),
        ]:
            btn = QPushButton(site_name)
            btn.setObjectName("secondaryBtn")
            btn.setFixedHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, tpl=site_url_tpl: self._open_tab_site(tpl))
            source_row.addWidget(btn)
        layout.addLayout(source_row)

        return tab

    def _search_tabs(self):
        query = self.tabs_search_input.text().strip()
        if not query:
            self.tabs_status_label.setText("Please enter a search term.")
            return

        self.tabs_status_label.setText("Searching...")
        self._clear_tab_results()

        # Use signals for thread-safe UI updates
        signals = WorkerSignals()
        signals.finished.connect(self._on_tab_search_done)
        signals.log.connect(lambda msg: self.tabs_status_label.setText(msg))

        def search():
            try:
                url = f"https://www.songsterr.com/api/songs?pattern={quote_plus(query)}"
                req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
                response = urlopen(req, timeout=10)
                raw = response.read().decode("utf-8")
                self._tab_search_results = json.loads(raw)
                self._tab_search_query = query

                if not self._tab_search_results:
                    signals.log.emit("No results found.")
                    signals.finished.emit(False, "")
                else:
                    signals.finished.emit(True, query)

            except URLError as e:
                signals.log.emit(f"Network error: {e.reason}")
                signals.finished.emit(False, "")
            except Exception as e:
                signals.log.emit(f"Error: {e}")
                signals.finished.emit(False, "")

        self._tab_search_signals = signals  # prevent garbage collection
        threading.Thread(target=search, daemon=True).start()

    def _on_tab_search_done(self, success, query):
        if success and hasattr(self, '_tab_search_results'):
            self._display_tab_results(self._tab_search_results, self._tab_search_query)

    def _clear_tab_results(self):
        while self.tabs_results_layout.count():
            item = self.tabs_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                pass  # Spacer items are removed by takeAt

    def _display_tab_results(self, results, query):
        self._clear_tab_results()
        count = min(len(results), 30)  # Limit to 30 results
        self.tabs_status_label.setText(f"Found {len(results)} results for \"{query}\"")

        for i in range(count):
            song = results[i]
            title = song.get("title", "Unknown")
            artist = song.get("artist", "Unknown Artist")
            song_id = song.get("songId", "")

            # Build the Songsterr URL
            # Songsterr URLs follow: /a/wsa/ARTIST-TITLE-tab-sNNNNN
            slug_artist = re.sub(r'[^a-zA-Z0-9]+', '-', artist).strip('-').lower()
            slug_title = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-').lower()
            songsterr_url = f"https://www.songsterr.com/a/wsa/{slug_artist}-{slug_title}-tab-s{song_id}"

            # Create result card
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #161616;
                    border: 1px solid #2a2a2a;
                    border-radius: 8px;
                    padding: 4px;
                }
                QFrame:hover {
                    border: 1px solid #7c3aed;
                }
            """)
            card.setCursor(Qt.PointingHandCursor)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)

            # Song info
            info_layout = QVBoxLayout()
            info_layout.setSpacing(2)

            title_label = QLabel(title)
            title_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff; border: none; background: transparent;")
            info_layout.addWidget(title_label)

            artist_label = QLabel(artist)
            artist_label.setStyleSheet("font-size: 12px; color: #888888; border: none; background: transparent;")
            info_layout.addWidget(artist_label)

            card_layout.addLayout(info_layout)
            card_layout.addStretch()

            # Open buttons
            btn_layout = QHBoxLayout()
            btn_layout.setSpacing(8)

            songsterr_btn = QPushButton("  Songsterr  ")
            songsterr_btn.setFixedHeight(32)
            songsterr_btn.setMinimumWidth(110)
            songsterr_btn.setStyleSheet("""
                QPushButton {
                    background-color: #7c3aed !important;
                    color: #ffffff !important;
                    border: none !important;
                    border-radius: 6px;
                    padding: 4px 14px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #6d28d9 !important; }
            """)
            songsterr_btn.setCursor(Qt.PointingHandCursor)
            songsterr_btn.clicked.connect(lambda checked, u=songsterr_url: webbrowser.open(u))
            btn_layout.addWidget(songsterr_btn)

            # Also offer UG search for this specific song
            ug_query = quote_plus(f"{artist} {title}")
            ug_url = f"https://www.ultimate-guitar.com/search.php?search_type=title&value={ug_query}"
            ug_btn = QPushButton("  Ultimate Guitar  ")
            ug_btn.setToolTip("Search on Ultimate Guitar")
            ug_btn.setFixedHeight(32)
            ug_btn.setMinimumWidth(140)
            ug_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a !important;
                    color: #ffffff !important;
                    border: none !important;
                    border-radius: 6px;
                    padding: 4px 14px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #444444 !important; }
            """)
            ug_btn.setCursor(Qt.PointingHandCursor)
            ug_btn.clicked.connect(lambda checked, u=ug_url: webbrowser.open(u))
            btn_layout.addWidget(ug_btn)

            card_layout.addLayout(btn_layout)

            card.show()
            self.tabs_results_layout.addWidget(card)

        # Force the parent scroll area to recalculate content size
        self.tabs_results_widget.adjustSize()
        self.tabs_results_widget.updateGeometry()

    def _open_tab_site(self, url_template):
        query = self.tabs_search_input.text().strip()
        if query:
            url = url_template.replace("{query}", quote_plus(query))
        else:
            # Open the site homepage if no query
            url = url_template.replace("search.php?search_type=title&value={query}", "").replace("?pattern={query}", "").replace("search/{query}", "")
        webbrowser.open(url)

    def _browse_key_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", str(Path.home() / "Music"),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)"
        )
        if file_path:
            self.key_file_input.setText(file_path)
            self._share_file_to_modules(file_path, source="key")

    def _start_key_detection(self):
        file_path = self.key_file_input.text().strip()
        if not file_path or not os.path.isfile(file_path):
            self.key_log.setVisible(True)
            self.key_log.setText("Please select a valid audio file.")
            return

        self.key_btn.setEnabled(False)
        self.key_btn.setText("Analyzing...")
        self.key_progress.setVisible(True)
        self.key_log.setVisible(True)
        self.key_log.clear()
        self.key_result_label.setText("...")
        self.bpm_result_label.setText("...")
        self.camelot_label.setText("...")
        self.key_confidence_label.setText("")

        signals = WorkerSignals()
        signals.log.connect(lambda msg: self.key_log.append(msg))
        signals.finished.connect(self._on_key_detection_done)

        t = threading.Thread(target=self._run_key_detection, args=(file_path, signals), daemon=True)
        t.start()

    def _run_key_detection(self, file_path, signals):
        try:
            signals.log.emit(f"Loading: {os.path.basename(file_path)}")

            import librosa

            # Load audio (mono, resampled to 22050 Hz)
            y, sr = librosa.load(file_path, sr=22050, mono=True)
            duration = len(y) / sr
            signals.log.emit(f"Duration: {duration:.1f}s | Sample rate: {sr} Hz")

            # ── Key Detection (Krumhansl-Schmuckler) ──
            signals.log.emit("Analyzing key...")
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            chroma_vals = np.mean(chroma, axis=1)

            # Krumhansl-Kessler major and minor profiles
            major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
            minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

            note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

            best_corr = -2
            best_key = "C"
            best_mode = "Major"

            for i in range(12):
                rotated = np.roll(chroma_vals, -i)
                major_corr = np.corrcoef(rotated, major_profile)[0, 1]
                minor_corr = np.corrcoef(rotated, minor_profile)[0, 1]

                if major_corr > best_corr:
                    best_corr = major_corr
                    best_key = note_names[i]
                    best_mode = "Major"
                if minor_corr > best_corr:
                    best_corr = minor_corr
                    best_key = note_names[i]
                    best_mode = "Minor"

            confidence = max(0, min(100, int(best_corr * 100)))

            # ── BPM Detection ──
            signals.log.emit("Analyzing tempo...")
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(tempo[0]) if hasattr(tempo, '__len__') else float(tempo)

            # ── Camelot Wheel Code ──
            camelot_major = {
                'B': '1B', 'F#': '2B', 'C#': '3B', 'G#': '4B', 'D#': '5B',
                'A#': '6B', 'F': '7B', 'C': '8B', 'G': '9B', 'D': '10B',
                'A': '11B', 'E': '12B'
            }
            camelot_minor = {
                'G#': '1A', 'D#': '2A', 'A#': '3A', 'F': '4A', 'C': '5A',
                'G': '6A', 'D': '7A', 'A': '8A', 'E': '9A', 'B': '10A',
                'F#': '11A', 'C#': '12A'
            }
            camelot_map = camelot_major if best_mode == "Major" else camelot_minor
            camelot_code = camelot_map.get(best_key, "?")

            result = f"{best_key} {best_mode}"
            signals.log.emit(f"\nResult: {result} (Camelot: {camelot_code}) | BPM: {bpm:.1f}")

            # Pack results into the finished signal
            signals.finished.emit(True, f"{best_key}|{best_mode}|{confidence}|{bpm:.1f}|{camelot_code}")

        except Exception as e:
            signals.log.emit(f"\nError: {e}")
            signals.finished.emit(False, "")

    def _on_key_detection_done(self, success, result_data):
        self.key_btn.setEnabled(True)
        self.key_btn.setText("Analyze")
        self.key_progress.setVisible(False)

        if success and result_data:
            parts = result_data.split("|")
            key, mode, confidence, bpm, camelot = parts[0], parts[1], parts[2], parts[3], parts[4]
            self.key_result_label.setText(f"{key} {mode}")
            self.key_confidence_label.setText(f"Confidence: {confidence}%")
            self.bpm_result_label.setText(f"{bpm}")
            self.camelot_label.setText(camelot)
        else:
            self.key_result_label.setText("Error")
            self.bpm_result_label.setText("---")
            self.camelot_label.setText("---")

    # ── Shared helpers ───────────────────────────────────────────────────

    def _share_file_to_modules(self, file_path, source=None):
        """Populate all audio file inputs across modules when a file is selected.

        source: name of the module that triggered this, so we don't overwrite
        the field that the user just set (it's already set by the caller).
        """
        if not file_path or not os.path.isfile(file_path):
            return

        if source != "stems":
            self.stem_file_input.setText(file_path)
        if source != "key":
            self.key_file_input.setText(file_path)
        if source != "convert":
            self.conv_file_input.setText(file_path)
        if source != "player":
            self.player_file_input.setText(file_path)
        if source != "metronome":
            self.met_file_input.setText(file_path)

    def _browse_folder(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", str(Path.home()))
        if folder:
            line_edit.setText(folder)

    def _browse_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", str(Path.home() / "Music"),
            "Audio Files (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.wma);;All Files (*)"
        )
        if file_path:
            self.stem_file_input.setText(file_path)
            self._share_file_to_modules(file_path, source="stems")

    def _set_ui_busy(self, tab, busy):
        if tab == "download":
            self.dl_btn.setEnabled(not busy)
            self.dl_btn.setText("Downloading..." if busy else "Download")
            self.dl_progress.setVisible(busy)
            self.dl_log.setVisible(True)
        elif tab == "stems":
            self.stem_btn.setEnabled(not busy)
            self.stem_btn.setText("Processing..." if busy else "Separate Stems")
            self.stem_progress.setVisible(busy)
            self.stem_log.setVisible(True)

    # ── YouTube Download Logic ───────────────────────────────────────────

    def _on_url_changed(self):
        """Re-enable download button when URL changes."""
        self.dl_btn.setEnabled(True)
        self.dl_btn.setText("Download")
        self.dl_success_banner.setVisible(False)

    def _start_download(self):
        url = self.url_input.text().strip()
        out_dir = self.dl_dir_input.text().strip()

        if not url:
            self.dl_log.setVisible(True)
            self.dl_log.setText("Please enter a YouTube URL.")
            return
        if not out_dir:
            self.dl_log.setVisible(True)
            self.dl_log.setText("Please select an output folder.")
            return

        self._set_ui_busy("download", True)
        self.dl_log.clear()
        self.dl_success_banner.setVisible(False)

        fmt = self.format_combo.currentText().lower()
        signals = WorkerSignals()
        signals.log.connect(lambda msg: self.dl_log.append(msg))
        signals.finished.connect(self._on_download_done)
        self._dl_signals = signals  # prevent garbage collection

        t = threading.Thread(target=self._run_download, args=(url, out_dir, fmt, signals), daemon=True)
        t.start()

    def _run_download(self, url, out_dir, fmt, signals):
        """Download audio from URL using yt-dlp Python API."""
        try:
            os.makedirs(out_dir, exist_ok=True)
            output_template = os.path.join(out_dir, "%(title)s.%(ext)s")

            signals.log.emit("Starting download...")
            signals.log.emit(f"Format: {fmt.upper()}")

            output_file = None

            def progress_hook(d):
                if d['status'] == 'downloading':
                    pct = d.get('_percent_str', '')
                    speed = d.get('_speed_str', '')
                    if pct:
                        signals.log.emit(f"[download] {pct} at {speed}")
                elif d['status'] == 'finished':
                    signals.log.emit("[download] Download complete, converting...")

            def postprocessor_hook(d):
                nonlocal output_file
                if d['status'] == 'finished':
                    info = d.get('info_dict', {})
                    output_file = info.get('filepath', '')
                    if output_file:
                        signals.log.emit(f"[ExtractAudio] Destination: {output_file}")

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'noplaylist': True,
                'extractaudio': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': fmt,
                    'preferredquality': '192',
                }],
                'ffmpeg_location': get_ffmpeg_path(),
                'progress_hooks': [progress_hook],
                'postprocessor_hooks': [postprocessor_hook],
                'quiet': True,
                'no_warnings': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            signals.log.emit("")
            signals.log.emit(f"Done! Saved to: {out_dir}")
            signals.finished.emit(True, output_file or "")

        except Exception as e:
            signals.log.emit("")
            signals.log.emit(f"Error: {e}")
            signals.finished.emit(False, "")

    def _on_download_done(self, success, output_path):
        self._set_ui_busy("download", False)
        # Explicitly ensure button is re-enabled and clickable
        self.dl_btn.setEnabled(True)
        self.dl_btn.setText("Download")
        self.dl_progress.setVisible(False)

        if success:
            # Show green success banner
            filename = os.path.basename(output_path) if output_path else "audio file"
            self.dl_success_text.setText(f"Download complete!  \u2014  {filename}")
            self.dl_success_banner.setVisible(True)

            # Share downloaded file to all modules
            if output_path:
                self._share_file_to_modules(output_path, source="download")

            if self.auto_split_cb.isChecked() and output_path and os.path.isfile(output_path):
                # Switch to stems page and auto-fill the file
                self._navigate_to(self.PAGE_STEMS)
                self._start_separation()
        else:
            self.dl_success_banner.setVisible(False)

    # ── Stem Separation Logic ────────────────────────────────────────────

    def _start_separation(self):
        file_path = self.stem_file_input.text().strip()
        out_dir = self.stem_out_input.text().strip()

        if not file_path or not os.path.isfile(file_path):
            self.stem_log.setVisible(True)
            self.stem_log.setText("Please select a valid audio file.")
            return
        if not out_dir:
            self.stem_log.setVisible(True)
            self.stem_log.setText("Please select an output folder.")
            return

        self._set_ui_busy("stems", True)
        self.stem_log.clear()

        model = self.model_combo.currentText()
        stems_choice = self.stems_combo.currentIndex()
        signals = WorkerSignals()
        signals.log.connect(lambda msg: self.stem_log.append(msg))
        signals.finished.connect(lambda ok, msg: self._on_separation_done(ok, msg))

        t = threading.Thread(
            target=self._run_separation,
            args=(file_path, out_dir, model, stems_choice, signals),
            daemon=True
        )
        t.start()

    def _run_separation(self, file_path, out_dir, model, stems_choice, signals):
        """Separate audio stems using demucs Python API."""
        try:
            import demucs.separate
            os.makedirs(out_dir, exist_ok=True)

            signals.log.emit(f"Model: {model}")
            signals.log.emit(f"Processing: {os.path.basename(file_path)}")
            signals.log.emit("This may take a few minutes...")
            signals.log.emit("")

            # Build command-line style args for demucs.separate.main()
            args = [
                "-n", model,
                "-o", out_dir,
            ]

            # Handle stem selection
            if stems_choice == 1:  # Vocals only
                args.extend(["--two-stems", "vocals"])
            elif stems_choice == 2:  # Instrumental only
                args.extend(["--two-stems", "vocals"])

            args.append(file_path)

            # Run demucs separation
            demucs.separate.main(args)

            # Find the output
            song_name = Path(file_path).stem
            stem_dir = os.path.join(out_dir, model, song_name)
            signals.log.emit("")
            signals.log.emit(f"Done! Stems saved to:")
            signals.log.emit(stem_dir)
            signals.finished.emit(True, stem_dir)

        except Exception as e:
            signals.log.emit("")
            signals.log.emit(f"Error: {e}")
            signals.finished.emit(False, "")

    def _on_separation_done(self, success, msg):
        self._set_ui_busy("stems", False)
        if success and msg:
            # Offer to open the output folder
            self.stem_log.append("\nClick 'Open Folder' below to view your stems.")
            open_btn = QPushButton("Open Folder")
            open_btn.setFixedWidth(120)
            open_btn.clicked.connect(lambda: os.startfile(msg) if sys.platform == "win32" else subprocess.run(["xdg-open", msg]))
            # Insert button into layout
            self._stems_tab_widget.layout().addWidget(open_btn)


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette as fallback
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0f0f0f"))
    palette.setColor(QPalette.WindowText, QColor("#ffffff"))
    palette.setColor(QPalette.Base, QColor("#161616"))
    palette.setColor(QPalette.AlternateBase, QColor("#1e1e1e"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1e1e1e"))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.Text, QColor("#ffffff"))
    palette.setColor(QPalette.Button, QColor("#1e1e1e"))
    palette.setColor(QPalette.ButtonText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor("#7c3aed"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
