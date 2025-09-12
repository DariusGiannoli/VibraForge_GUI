#!/usr/bin/env python3
import sys
import os
import time
import json
import random
import math
import itertools
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Tuple, List, Optional

from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu

from PyQt6 import uic
from PyQt6.QtCore import (
    Qt, QTimer, QProcess, pyqtSignal, QObject, QSize, QPoint,
    QThread, QPointF, QRectF
)
from PyQt6.QtGui import (
   QAction, QActionGroup, QTextCursor, QColor, QIcon, QFont,
   QPalette, QImage, QPainter, QPen, QBrush, QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit,
    QFileDialog, QMessageBox, QTabWidget, QListWidget, QListWidgetItem,
    QDialog, QDialogButtonBox, QSpinBox, QDoubleSpinBox, QMenu, QStatusBar,
    QFormLayout, QStyleFactory, QSlider, QCheckBox, QInputDialog,
    QSizePolicy, QStackedWidget, QScrollArea, QFrame, QToolButton,
    QSplitter, QTableWidget, QTableWidgetItem, QAbstractItemView
)

from core import PhantomEngine, PreviewBundle
from core.storage import save_bundle, load_bundle, list_bundles
main_gui_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(main_gui_dir)
from communication import python_serial_api
from core.vibration_patterns import *
from gui.widgets.flexible_actuator_selector import FlexibleActuatorSelector
from gui.widgets.phantom_preview_canvas import PhantomPreviewCanvas

# Event model helpers (JSON/CSV → HapticEvent)
main_gui_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(main_gui_dir)
try:
    from waveform_designer.event_data_model import (
        HapticEvent, WaveformData, load_csv_waveform,
        EventMetadata, EventCategory,
    )
except ImportError:
    HapticEvent = None


PATTERN_PARAMETERS = {
    "Single Pulse": {"parameters": []},
    "Wave": {"parameters": [
        {"name": "wave_speed", "label": "Wave speed", "type": "float", "range": (0.1, 3.0), "step": 0.1, "default": 0.6, "suffix": " s"}
    ]},
    "Pulse Train": {"parameters": [
        {"name": "pulse_on",  "label": "Pulse ON",  "type": "float", "range": (0.05, 2.0), "step": 0.05, "default": 0.2, "suffix": " s"},
        {"name": "pulse_off", "label": "Pulse OFF", "type": "float", "range": (0.05, 2.0), "step": 0.05, "default": 0.3, "suffix": " s"},
    ]},
    "Fade": {"parameters": []},
    "Circular": {"parameters": [
        {"name": "rotation_speed", "label": "Rotation speed", "type": "float", "range": (0.1, 3.0), "step": 0.1, "default": 1.0, "suffix": " s"}
    ]},
    "Random": {"parameters": [
        {"name": "change_interval", "label": "Change interval", "type": "float", "range": (0.05, 2.0), "step": 0.05, "default": 0.3, "suffix": " s"}
    ]},
    "Sine Wave": {"parameters": []},
    }
# ---- Premade Pattern catalog (templates you can expand anytime) ----
PREMADE_PATTERNS = [
    {
        "name": "Trio Burst",
        "description": "Single pulse on actuators 0–2. Good for smoke tests.",
        "config": {
            "pattern_type": "Single Pulse",
            "actuators": [0, 1, 2],
            "intensity": 9,
            "frequency": 4,  # device freq code you want as a default
            "specific_parameters": {},
            # If not present in the library, we keep the currently selected waveform
            "waveform": {"name": "Sine"}
        }
    },
    {
        "name": "3×3 Sweep",
        "description": "Wave pattern sweeping across a 3×3 grid (0–8).",
        "config": {
            "pattern_type": "Wave",
            "actuators": [0,1,2,3,4,5,6,7,8],
            "intensity": 8,
            "frequency": 4,
            "specific_parameters": {"wave_speed": 0.6},
            "waveform": {"name": "Sine"}
        }
    },
    {
        "name": "Back Ring (Circular)",
        "description": "Circular pattern over 16 actuators (0–15).",
        "config": {
            "pattern_type": "Circular",
            "actuators": list(range(16)),
            "intensity": 7,
            "frequency": 4,
            "specific_parameters": {"rotation_speed": 1.0},
            "waveform": {"name": "Sine"}
        }
    },
    {
        "name": "Pulse Train 8-Act",
        "description": "Pulse train on 0–7 with 0.2s ON / 0.3s OFF.",
        "config": {
            "pattern_type": "Pulse Train",
            "actuators": list(range(8)),
            "intensity": 9,
            "frequency": 4,
            "specific_parameters": {"pulse_on": 0.2, "pulse_off": 0.3},
            "waveform": {"name": "Sine"}
        }
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Drawing Studio: make scrollable + move “Drawn Stroke Playback” here
# ─────────────────────────────────────────────────────────────────────────────

def _make_widget_scrollable_in_place(page: QWidget) -> QScrollArea:
    """
    Wrap the *current contents* of `page` in a QScrollArea without changing the
    page itself (so setCurrentWidget(page) etc. continue to work).
    """
    outer = page.layout()
    if outer is None:
        outer = QVBoxLayout(page)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

    # If we've already wrapped it, return the existing scroll area.
    for i in range(outer.count()):
        w = outer.itemAt(i).widget()
        if isinstance(w, QScrollArea):
            return w

    # Move all existing layout items into a new content widget
    content = QWidget(page)
    content.setObjectName("DrawingStudioContent")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(8)

    # Take items out of the outer layout (widgets, sub-layouts, spacers)
    items = []
    while outer.count():
        items.append(outer.takeAt(0))
    for it in items:
        if it.widget() is not None:
            w = it.widget()
            w.setParent(None)
            content_layout.addWidget(w)
        elif it.layout() is not None:
            content_layout.addLayout(it.layout())
        elif it.spacerItem() is not None:
            content_layout.addSpacerItem(it.spacerItem())

    scroll = QScrollArea(page)
    scroll.setObjectName("DrawingStudioScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(content)

    outer.addWidget(scroll)
    return scroll


def _find_drawn_stroke_group(root: QWidget) -> QGroupBox | None:
    """
    Try hard to find the existing 'Drawn Stroke Playback' group.
    Prefer an objectName if present; otherwise match by group title.
    """
    # 1) By objectName (recommended in your code)
    gb = root.findChild(QGroupBox, "DrawnStrokePlaybackGroup")
    if gb:
        return gb

    # 2) Fallback: scan all QGroupBox by title
    for g in root.findChildren(QGroupBox):
        try:
            if g.title().strip().lower().startswith("drawn stroke playback"):
                g.setObjectName("DrawnStrokePlaybackGroup")
                return g
        except Exception:
            pass
    return None


def _add_widget_to_drawing_tab_end(gui, w: QWidget) -> None:
    """
    Append `w` at the end of the Drawing tab content (inside the scroll area).
    """
    drawing_tab = getattr(gui, "drawing_tab", None)
    if drawing_tab is None:
        QMessageBox.information(gui, "Drawing Studio", "Drawing tab not found.")
        return

    scroll = _make_widget_scrollable_in_place(drawing_tab)
    content = scroll.widget()                      # QWidget
    content_layout = content.layout()              # QVBoxLayout
    # Try to put the group near the bottom, but before a trailing stretch/spacer if any
    inserted = False
    for i in reversed(range(content_layout.count())):
        item = content_layout.itemAt(i)
        if item.spacerItem() is not None:
            content_layout.insertWidget(max(0, i), w)
            inserted = True
            break
    if not inserted:
        content_layout.addWidget(w)


def centralize_drawn_stroke_playback_in_drawing(gui) -> None:
    """
    Public one-liner:
    - Make Drawing Studio scrollable (in place).
    - Move the existing 'Drawn Stroke Playback' group into Drawing Studio.
    All signal/slot connections are preserved because we re-parent the existing widget.
    """
    # Ensure the scroll wrapper exists
    drawing_tab = getattr(gui, "drawing_tab", None)
    if drawing_tab is None:
        return
    _make_widget_scrollable_in_place(drawing_tab)

    # Find the existing group anywhere in the window
    gb = _find_drawn_stroke_group(gui)
    if gb is None:
        # Nothing to move; keep silent (no breakage).
        return

    # Detach from old parent layout cleanly
    old_parent = gb.parentWidget()
    if old_parent and old_parent is not drawing_tab:
        if old_parent.layout() is not None:
            old_parent.layout().removeWidget(gb)

    gb.setParent(None)
    gb.setObjectName("DrawnStrokePlaybackGroup")  # stable for future finds
    _add_widget_to_drawing_tab_end(gui, gb)

class WaveformLibraryManager:
    """Use the same folder as the Designer: <repo_root>/waveform_library/customized.
    Falls back to Main_GUI/waveform_library if it has more files. Supports .json/.csv/.haptic.
    """
    EXT = (".json", ".csv", ".haptic")

class WaveformLibraryManager:

    EXT = (".json", ".csv", ".haptic")

    def __init__(self):
        here = os.path.dirname(os.path.abspath(__file__))  # .../Main_GUI/Pattern_Generator/gui
        pattern_generator = os.path.dirname(here)          # .../Main_GUI/Pattern_Generator  
        main_gui = os.path.dirname(pattern_generator)      # .../Main_GUI
        project_root = os.path.dirname(main_gui)           # .../VibraForge_GUI
        
        # Vérification que c'est bien la racine
        indicators = ['requirements.txt', 'pyproject.toml', '.git', 'README.md']
        if not any(os.path.exists(os.path.join(project_root, i)) for i in indicators):
            print(f"Warning: Project root indicators not found in {project_root}")

        root_lib = os.path.join(project_root, "waveform_library")
        alt_lib  = os.path.join(main_gui,    "waveform_library")

        def count_customized(lib_root):
            d = os.path.join(lib_root, "customized")
            try:
                return sum(1 for fn in os.listdir(d) if fn.lower().endswith(self.EXT))
            except Exception:
                return -1

        # 2) Choose the lib with more files in customized/
        root_cnt = count_customized(root_lib)
        alt_cnt  = count_customized(alt_lib)
        chosen   = root_lib if root_cnt >= alt_cnt else alt_lib

        self.lib_root   = chosen
        self.custom_dir = os.path.join(self.lib_root, "customized")
        os.makedirs(self.custom_dir, exist_ok=True)

        # helpful for logs
        self._which = "repo_root" if chosen == root_lib else "Main_GUI"

    def list_entries(self):
        entries = []
        try:
            for fn in sorted(os.listdir(self.custom_dir)):
                if fn.lower().endswith(self.EXT):
                    path = os.path.join(self.custom_dir, fn)
                    name, ext = os.path.splitext(fn)
                    entries.append({"name": name, "display": name, "ext": ext.lower(), "path": path})
        except Exception as e:
            print(f"[WaveformLibrary] scan error: {e}")
        return entries

    def load_event(self, entry):
        if HapticEvent is None:
            return None
        try:
            if entry["ext"] in (".json", ".haptic"):
                return HapticEvent.load_from_file(entry["path"])
            # CSV → wrap
            t, y, sr = load_csv_waveform(entry["path"], default_sr=1000.0)
            wf = WaveformData(
                amplitude=[{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)],
                frequency=[], duration=float(t[-1] if len(t) else 0.0), sample_rate=float(sr)
            )
            ev = HapticEvent()
            ev.metadata = EventMetadata(name=entry["name"], category=EventCategory.CUSTOM,
                                        description=f"CSV from {self._which}")
            ev.waveform_data = wf
            return ev
        except Exception as e:
            print(f"[WaveformLibrary] load error: {e}")
            return None
        

class NodeCanvasWidget(QWidget):
    """
    Tiny, generic canvas that draws circular 'actuator' nodes at normalized
    positions and lets you click-toggle selection.
    """
    selection_changed = pyqtSignal(list)

    def __init__(self, nodes: list[tuple[int, float, float]], parent=None):
        super().__init__(parent)
        # nodes: list of (id, x_norm, y_norm) with x,y in [0..1]
        self.nodes = nodes[:]  # copy
        self.selected: set[int] = set()
        self.active: set[int] = set()
        self.radius_px = 18
        self.margin_px = 24
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
    
    def get_nodes(self) -> list[tuple[int, float, float]]:
        """Return a copy of (id, x_norm, y_norm) for background rendering."""
        return self.nodes[:]

    # ----- public API used by wrappers -----
    def get_selected_actuators(self) -> list[int]:
        return sorted(self.selected)
    def set_active(self, ids: list[int] | set[int]):
        """Visually highlight 'currently playing' actuators (preview)."""
        self.active = set(int(i) for i in ids)
        self.update()
    

    def clear_active(self):
        self.active.clear()
        self.update()

    def load_actuator_configuration(self, ids: list[int]):
        """Select only IDs that exist on this fixed node canvas."""
        valid = {nid for nid, _, _ in self.nodes}
        self.selected = {int(i) for i in ids if int(i) in valid}
        self.update()
        self.selection_changed.emit(self.get_selected_actuators())

    def select_all(self):
        self.selected = {nid for nid, _, _ in self.nodes}
        self.update()
        self.selection_changed.emit(self.get_selected_actuators())

    def select_none(self):
        self.selected.clear()
        self.update()
        self.selection_changed.emit(self.get_selected_actuators())

    def clear_canvas(self):
        # fixed canvases don’t place/delete nodes → treat as 'select none'
        self.select_none()

    # ----- painting & hit-testing -----
    def _xy_to_px(self, xn: float, yn: float) -> QPointF:
        w = self.width()
        h = self.height()
        x = self.margin_px + xn * max(1, (w - 2 * self.margin_px))
        y = self.margin_px + yn * max(1, (h - 2 * self.margin_px))
        return QPointF(x, y)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # background
        p.fillRect(self.rect(), self.palette().alternateBase())

        # draw nodes
        for nid, xn, yn in self.nodes:
            c = self._xy_to_px(xn, yn)
            r = self.radius_px
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)

            # base circle (fill + outline)
            p.setPen(QPen(QColor("#374151"), 2))
            if nid in self.selected:
                p.setBrush(QBrush(self.palette().highlight().color()))
            else:
                p.setBrush(QBrush(QColor("#E5E7EB")))
            p.drawEllipse(rect)

            # active ring (preview)
            if nid in self.active:
                ring = rect.adjusted(-3, -3, +3, +3)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(self.palette().highlight().color(), 4))
                p.drawEllipse(ring)

            # label
            p.setPen(QPen(QColor("#111827")))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(nid))

        p.end()

    def _hit(self, pos: QPointF) -> int | None:
        for nid, xn, yn in self.nodes:
            c = self._xy_to_px(xn, yn)
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= self.radius_px + 4:
                return nid
        return None

    def mousePressEvent(self, e):
        nid = self._hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton and nid is not None:
            if nid in self.selected:
                self.selected.remove(nid)
            else:
                self.selected.add(nid)
            self.update()
            self.selection_changed.emit(self.get_selected_actuators())
        elif e.button() == Qt.MouseButton.RightButton and nid is not None:
            if nid in self.selected:
                self.selected.remove(nid)
                self.update()
                self.selection_changed.emit(self.get_selected_actuators())
        super().mousePressEvent(e)

class Grid3x3Selector(QWidget):
    """Fixed 3×3 layout (IDs 0..8)."""
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        # normalized grid points ~ (0.2, 0.5, 0.8)
        xs = [0.2, 0.5, 0.8]
        ys = [0.2, 0.5, 0.8]
        nodes = []
        nid = 0
        for y in ys:
            for x in xs:
                nodes.append((nid, x, y))
                nid += 1

        self.canvas = NodeCanvasWidget(nodes)
        self.canvas.selection_changed.connect(self.selection_changed.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    # API passthroughs
    def get_selected_actuators(self): return self.canvas.get_selected_actuators()
    def load_actuator_configuration(self, ids): self.canvas.load_actuator_configuration(ids)
    def select_all(self): self.canvas.select_all()
    def select_none(self): self.canvas.select_none()
    def clear_canvas(self): self.canvas.clear_canvas()
    def get_nodes(self): return self.canvas.get_nodes()


class CustomLayoutSelector(QWidget):
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Four column anchors (left → right)
        x4 = [0.12, 0.38, 0.62, 0.88]

        # y-rows (top to bottom)
        y_top    = 0.10
        y_row1   = 0.30
        y_row2   = 0.50
        y_row3   = 0.70
        y_bottom = 0.90

        # Build nodes (id, x_norm, y_norm)
        nodes = [
            # TOP — align 0 above 4 (col 2), 1 above 3 (col 3)
            (0,  x4[1], y_top),
            (1,  x4[2], y_top),

            # Row 1
            (5,  x4[0], y_row1), (4, x4[1], y_row1), (3, x4[2], y_row1), (2, x4[3], y_row1),

            # Row 2
            (6,  x4[0], y_row2), (7, x4[1], y_row2), (8, x4[2], y_row2), (9, x4[3], y_row2),

            # Row 3
            (13, x4[0], y_row3), (12, x4[1], y_row3), (11, x4[2], y_row3), (10, x4[3], y_row3),

            # BOTTOM — align 14 under 12 (col 2), 15 under 11 (col 3)
            (14, x4[1], y_bottom),
            (15, x4[2], y_bottom),
        ]

        self.canvas = NodeCanvasWidget(nodes)
        self.canvas.selection_changed.connect(self.selection_changed.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    # API passthroughs
    def get_selected_actuators(self): return self.canvas.get_selected_actuators()
    def load_actuator_configuration(self, ids): self.canvas.load_actuator_configuration(ids)
    def select_all(self): self.canvas.select_all()
    def select_none(self): self.canvas.select_none()
    def clear_canvas(self): self.canvas.clear_canvas()
    def get_nodes(self): return self.canvas.get_nodes()

class PremadePatternPanel(QWidget):
    """Premade templates with search + description + primary action."""
    template_selected = pyqtSignal(dict)

    def __init__(self, presets: list[dict], parent=None):
        super().__init__(parent)
        self._all = list(presets)

        group = QGroupBox("Premade Patterns")
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.addWidget(group)
        g = QVBoxLayout(group); g.setContentsMargins(8,6,8,8); g.setSpacing(6)

        # search
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Filter premade…")
        self.search.setClearButtonEnabled(True)
        g.addWidget(self.search)

        # list
        self.list = QListWidget(self)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        g.addWidget(self.list, 1)

        # info
        self.info = QLabel("Select a template to see details.")
        self.info.setObjectName("patternDescLabel")
        self.info.setWordWrap(True)
        g.addWidget(self.info)

        # actions
        self.btnLoad = QPushButton("Load to Waveform Lab", self)
        self.btnLoad.setObjectName("loadToWaveformBtn")
        self.btnLoad.setEnabled(False)
        g.addWidget(self.btnLoad)

        # wire
        self.search.textChanged.connect(self._rebuild)
        self.list.itemSelectionChanged.connect(self._on_sel)
        self.list.itemDoubleClicked.connect(lambda *_: self._emit_selected())
        self.btnLoad.clicked.connect(self._emit_selected)

        self._rebuild()

    def _rebuild(self):
        q = self.search.text().strip().lower()
        self.list.clear()
        for p in self._all:
            if q and q not in p["name"].lower():
                continue
            it = QListWidgetItem(p["name"])
            it.setToolTip(p.get("description",""))
            it.setSizeHint(QSize(it.sizeHint().width(), 30))
            self.list.addItem(it)
        self._on_sel()

    def _current(self) -> dict | None:
        it = self.list.currentItem()
        if not it: return None
        for p in self._all:
            if p["name"] == it.text():
                return p
        return None

    def _on_sel(self):
        p = self._current()
        self.btnLoad.setEnabled(p is not None)
        self.info.setText(
            f"<b>{p['name']}</b><br>{p.get('description','')}" if p
            else "Select a template to see details."
        )

    def _emit_selected(self):
        p = self._current()
        if p:
            self.template_selected.emit(p)


class MultiCanvasSelector(QWidget):
    selection_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(QLabel("Canvas:"))
        self.canvasCombo = QComboBox()
        self.canvasCombo.addItems(["Designer", "3×3 Grid", "Back Layout"])
        self.canvasCombo.setMinimumWidth(140)
        top.addWidget(self.canvasCombo)
        top.addStretch()

        self.btnClear = QPushButton("Clear")
        self.btnCreateChain = QPushButton("Create Chain")
        self.btnAll = QPushButton("All")
        for b in (self.btnClear, self.btnCreateChain, self.btnAll):
            b.setMinimumWidth(90)
            top.addWidget(b)

        # Stack with 3 pages
        self.stack = QStackedWidget()
        # Page 0: existing Designer
        self.designer = FlexibleActuatorSelector()
        # Try to hide internal duplicates (Clear/All/None/Create Chain) after it’s built
        QTimer.singleShot(0, self._hide_internal_designer_controls)
        self._wire_selector(self.designer)

        # Page 1: 3×3
        self.grid3 = Grid3x3Selector()
        self.grid3.selection_changed.connect(self.selection_changed.emit)

        # Page 2: custom
        self.custom = CustomLayoutSelector()
        self.custom.selection_changed.connect(self.selection_changed.emit)

        self.stack.addWidget(self.designer)
        self.stack.addWidget(self.grid3)
        self.stack.addWidget(self.custom)

        # Layout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)   # remove extra padding around the whole selector
        root.setSpacing(4)
        root.addLayout(top)
        root.addWidget(self.stack)

        self._designer_preview_mode = False
        self._designer_prev_selection: set[int] | None = None

        # Wire top buttons
        self.canvasCombo.currentIndexChanged.connect(self._on_canvas_changed)
        self.btnClear.clicked.connect(self._act_clear)
        self.btnAll.clicked.connect(self._act_all)
        self.btnCreateChain.clicked.connect(self._act_create_chain)
        self._update_buttons_for_page(0)
    
    def get_active_canvas_widget(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            return getattr(self.designer, "canvas", None)
        if idx == 1:
            return self.grid3.canvas
        if idx == 2:
            return self.custom.canvas
        return None
    
    def _designer_read_selection(self) -> set[int]:
    # essaie l’API publique du sélecteur
        try:
            return set(int(i) for i in self.designer.get_selected_actuators())
        except Exception:
            pass
        # fallback: lire depuis les objets d’actuateur du canvas s’ils existent
        try:
            acts = getattr(self.designer, "canvas", None)
            if acts and hasattr(acts, "actuators"):
                out = set()
                for a in acts.actuators:
                    if getattr(a, "is_selected", False):
                        out.add(int(getattr(a, "actuator_id", -1)))
                return out
        except Exception:
            pass
        return set()

    def _designer_apply_selection(self, ids: set[int]):
        """Applique une sélection exacte sur le canvas du Designer."""
        canvas = getattr(self.designer, "canvas", None)
        if not canvas or not hasattr(canvas, "actuators"):
            return
        for a in canvas.actuators:
            try:
                a.set_selected_state(int(getattr(a, "actuator_id", -1)) in ids)
            except Exception:
                pass
        try:
            if hasattr(canvas, "on_actuator_selection_changed"):
                canvas.on_actuator_selection_changed()
            else:
                canvas.update()
        except Exception:
            pass
    def current_nodes(self) -> list[tuple[int, float, float]]:
        """Return normalized node anchors for the CURRENT fixed canvas.
        Designer is not guaranteed; returns [] for Designer."""
        idx = self.stack.currentIndex()
        if idx == 1:  # 3x3
            try: return self.grid3.get_nodes()
            except Exception: return []
        if idx == 2:  # Custom
            try: return self.custom.get_nodes()
            except Exception: return []
        # Designer page not supported here (unknown geometry)
        return []

    def set_preview_active(self, ids: list[int] | set[int]):
        try:
            self.grid3.canvas.set_active(ids)
        except Exception:
            pass
        try:
            self.custom.canvas.set_active(ids)
        except Exception:
            pass

        try:
            if hasattr(self.designer, "set_preview_active"):
                self.designer.set_preview_active(ids)
                return
        except Exception:
            pass

        try:
            if not self._designer_preview_mode:
                self._designer_prev_selection = self._designer_read_selection()
                self._designer_preview_mode = True
            target = set(self._designer_prev_selection or set()) | {int(i) for i in ids}
            self._designer_apply_selection(target)
        except Exception:
            pass

    def clear_preview(self):
        # canvases fixes
        try:
            self.grid3.canvas.clear_active()
        except Exception:
            pass
        try:
            self.custom.canvas.clear_active()
        except Exception:
            pass

        # Designer : API native ?
        try:
            if hasattr(self.designer, "clear_preview"):
                self.designer.clear_preview()
                return
        except Exception:
            pass

        # Fallback : restaurer la sélection d’origine si on l’a modifiée
        try:
            if self._designer_preview_mode and self._designer_prev_selection is not None:
                self._designer_apply_selection(set(self._designer_prev_selection))
        except Exception:
            pass
        finally:
            self._designer_preview_mode = False
            self._designer_prev_selection = None
    # ----- internal helpers -----
    def _wire_selector(self, selector_widget):
        """Connect selection_changed if the child exposes it."""
        if hasattr(selector_widget, "selection_changed"):
            try:
                selector_widget.selection_changed.connect(self.selection_changed.emit)
            except Exception:
                pass
        
    def _load_on_designer(self, ids: list[int]):
        """
        Ensure the Designer (FlexibleActuatorSelector) has at least max(id)+1
        actuators (create a chain if needed), then apply the selection.
        """
        sel = self.designer
        if not ids:
            # clear selection across designer
            try:
                sel.select_none()
            except Exception:
                pass
            try:
                sel.canvas.on_actuator_selection_changed()
            except Exception:
                pass
            return

        max_id = max(ids)
        canvas = getattr(sel, "canvas", None)
        current = getattr(canvas, "actuators", []) if canvas else []

        # Ensure we have enough actuators to cover the highest ID
        if canvas is not None and len(current) <= max_id:
            try:
                # clean start
                if hasattr(sel, "clear_canvas"):
                    sel.clear_canvas()
                elif hasattr(canvas, "clear"):
                    canvas.clear()

                # create a chain 0..max_id (default type)
                if hasattr(sel, "create_chain"):
                    sel.create_chain(max_id + 1)
                    current = getattr(sel.canvas, "actuators", [])
            except Exception:
                # Fallback: add actuators one by one if API is available
                try:
                    needed = (max_id + 1) - len(current)
                    for _ in range(max(0, needed)):
                        if hasattr(canvas, "add_actuator"):
                            canvas.add_actuator("LRA")
                    current = getattr(canvas, "actuators", [])
                except Exception:
                    pass

        # Apply the selection
        try:
            sel.select_none()
        except Exception:
            pass

        for a in getattr(sel.canvas, "actuators", []):
            try:
                a.set_selected_state(a.actuator_id in ids)
            except Exception:
                pass

        try:
            sel.canvas.on_actuator_selection_changed()
        except Exception:
            pass

    def _hide_internal_designer_controls(self):
        """
        Hide internal Clear / All / None / Create Chain buttons inside the
        FlexibleActuatorSelector to avoid duplicates in the Designer page.
        This is a best-effort approach based on button text.
        """
        try:
            from PyQt6.QtWidgets import QPushButton
            to_hide = {"clear", "all", "none", "create chain"}
            for btn in self.designer.findChildren(QPushButton):
                if btn.text().strip().lower() in to_hide:
                    btn.setVisible(False)
        except Exception:
            # harmless if it fails; you’ll just see duplicated buttons
            pass

    def _on_canvas_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self._update_buttons_for_page(idx)

    def _update_buttons_for_page(self, idx: int):
        # Create Chain is only meaningful on Designer
        self.btnCreateChain.setEnabled(idx == 0)

    # ----- top button actions -----
    def _act_clear(self):
        idx = self.stack.currentIndex()
        if idx == 0 and hasattr(self.designer, "clear_canvas"):
            # Page Designer → vrai reset du canevas (supprime les nodes/actuateurs)
            try:
                self.designer.clear_canvas()
                # Optionnel: forcer une notif de sélection vide au GUI
                if hasattr(self.designer, "canvas") and hasattr(self.designer.canvas, "on_actuator_selection_changed"):
                    self.designer.canvas.on_actuator_selection_changed()
            except Exception:
                pass
            return

        # Pages fixes → clear = désélection uniquement (non destructif)
        sel = self._current_page()
        if hasattr(sel, "select_none"):
            sel.select_none()
        elif hasattr(sel, "clear_canvas"):
            sel.clear_canvas()

    def _act_all(self):
        sel = self._current_page()
        if hasattr(sel, "select_all"):
            sel.select_all()

    def _act_create_chain(self):
        # Always run on the Designer page, like the base UI
        if self.stack.currentIndex() != 0:
            self.canvasCombo.setCurrentIndex(0)
        try:
            self.designer.create_chain()  # opens the dialog and creates the branch
        except Exception as e:
            QMessageBox.critical(self, "Create Chain", f"Failed: {e}")

    def _current_page(self):
        idx = self.stack.currentIndex()
        return [self.designer, self.grid3, self.custom][idx]

    # ----- unified public API used by HapticPatternGUI -----
    def get_selected_actuators(self) -> list[int]:
        page = self._current_page()
        if hasattr(page, "get_selected_actuators"):
            return page.get_selected_actuators()
        return []

    def load_actuator_configuration(self, ids: list[int]):
        cleaned = []
        for i in ids:
            try:
                cleaned.append(int(i))
            except Exception:
                pass
        cleaned = sorted(set(cleaned))

        # Designer first (may need to create nodes)
        self._load_on_designer(cleaned)

        # Fixed canvases just select what exists
        try:
            self.grid3.load_actuator_configuration(cleaned)
        except Exception:
            pass
        try:
            self.custom.load_actuator_configuration(cleaned)
        except Exception:
            pass

class EventLibraryManager:
    """Manager for the root-level event library"""
    
    def __init__(self):
        # Determine the event_library path relative to the project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.event_library_path = os.path.join(project_root, "event_library")
        
        # Create event_library directory if it doesn't exist
        os.makedirs(self.event_library_path, exist_ok=True)
        
        # Create __init__.py if it doesn't exist
        init_file = os.path.join(self.event_library_path, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Event Library\n")
    
    def get_all_events(self):
        """Get all available events"""
        events = {}
        
        try:
            if os.path.exists(self.event_library_path):
                for filename in os.listdir(self.event_library_path):
                    if filename.endswith('.json'):
                        event_name = filename[:-5]  # Remove .json extension
                        events[event_name] = filename
        except Exception as e:
            print(f"Error scanning event library: {e}")
        
        return events
    
    def load_event(self, event_name):
        """Load an event from the library"""
        try:
            if HapticEvent:
                filepath = os.path.join(self.event_library_path, f"{event_name}.json")
                return HapticEvent.load_from_file(filepath)
        except Exception as e:
            print(f"Error loading event {event_name}: {e}")
        return None


@dataclass
class TimelineClip:
    actuator: int
    start_s: float
    end_s: float
    waveform_name: str
    event: Optional['HapticEvent']  # can be None

    @property
    def duration(self) -> float:
        return max(0.0, float(self.end_s) - float(self.start_s))


class TimelineModel(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._clips: list[TimelineClip] = []
        self._selected: Optional[TimelineClip] = None

    def clips(self) -> list[TimelineClip]:
        return list(self._clips)

    def clear(self):
        self._clips.clear()
        self._selected = None
        self.changed.emit()

    def add_clip_for_actuators(self, actuators: list[int],
                               event: Optional['HapticEvent'],
                               waveform_name: str,
                               start_s: float, end_s: float):
        start_s = max(0.0, float(start_s))
        end_s   = max(start_s, float(end_s))
        for a in sorted(set(int(x) for x in actuators)):
            self._clips.append(TimelineClip(a, start_s, end_s, waveform_name, event))
        self.changed.emit()

    def remove_clip(self, clip: TimelineClip):
        try:
            self._clips.remove(clip)
        except ValueError:
            pass
        if self._selected is clip:
            self._selected = None
        self.changed.emit()

    def set_selected(self, clip: Optional[TimelineClip]):
        self._selected = clip
        self.changed.emit()

    def selected(self) -> Optional[TimelineClip]:
        return self._selected

    def total_duration(self) -> float:
        if not self._clips: return 0.0
        return max((c.end_s for c in self._clips), default=0.0)

    def actuators(self) -> list[int]:
        return sorted({c.actuator for c in self._clips})

    # Preview helper: who is active at time t?
    def active_actuators_at(self, t_s: float) -> list[int]:
        out = []
        for c in self._clips:
            if c.start_s <= t_s <= c.end_s:
                out.append(c.actuator)
        return sorted(set(out))


class TimelineView(QWidget):
    """Lightweight visual timeline (rows by actuator, rectangles for clips)."""
    clip_clicked = pyqtSignal(object)  # emits TimelineClip or None

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._model.changed.connect(self.update)
        self.setMinimumHeight(160)
        self.setAutoFillBackground(True)
        self._px_per_second = 120.0
        self._margin_l = 56
        self._row_h = 22
        self._row_gap = 8
        self._cursor_t = 0.0
        self.setMouseTracking(True)

    def set_seconds_per_pixel(self, sec_per_px: float):
        self._px_per_second = 1.0 / max(0.01, sec_per_px)
        self.update()

    def set_pixels_per_second(self, px_per_s: float):
        self._px_per_second = max(10.0, float(px_per_s))
        self.update()

    def set_cursor_time(self, t_s: float):
        self._cursor_t = max(0.0, float(t_s))
        self.update()

    def _rows_layout(self) -> list[int]:
        """Map actuators to row indices."""
        return self._model.actuators()

    def sizeHint(self):
        rows = len(self._rows_layout())
        height = 16 + rows * (self._row_h + self._row_gap) + 8
        width  = max(600, int(self._margin_l + self._model.total_duration() * self._px_per_second) + 40)
        return QSize(width, height)

    def minimumSizeHint(self):
        return QSize(600, 140)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), self.palette().base())

        # Grid/time marks
        total_s = self._model.total_duration()
        W = self.width() - self._margin_l - 8
        max_s = max(total_s, (W / self._px_per_second))
        step = 1.0
        # seconds grid
        p.setPen(QPen(QColor("#E5E7EB")))
        t = 0.0
        while t <= max_s + 1e-6:
            x = self._margin_l + int(t * self._px_per_second)
            p.drawLine(x, 6, x, self.height() - 6)
            p.setPen(QPen(QColor("#6B7280")))
            p.drawText(x + 2, 14, f"{t:.0f}s")
            p.setPen(QPen(QColor("#E5E7EB")))
            t += step

        # Rows
        rows = self._rows_layout()
        base_y = 24
        for ri, act in enumerate(rows):
            y = base_y + ri * (self._row_h + self._row_gap)
            # row label
            p.setPen(QPen(QColor("#374151")))
            p.drawText(6, y + int(self._row_h * 0.7), f"A{act}")
            # baseline
            p.setPen(QPen(QColor("#D1D5DB")))
            p.drawLine(self._margin_l, y + self._row_h, self.width() - 8, y + self._row_h)

        # Clips
        sel = self._model.selected()
        for clip in self._model.clips():
            try:
                ri = rows.index(clip.actuator)
            except ValueError:
                continue
            y = base_y + ri * (self._row_h + self._row_gap)
            x0 = self._margin_l + int(clip.start_s * self._px_per_second)
            x1 = self._margin_l + int(clip.end_s   * self._px_per_second)
            rect = QRectF(x0, y, max(12, x1 - x0), self._row_h)
            # fill
            p.setPen(QPen(QColor("#3B82F6"), 1))
            p.setBrush(QBrush(QColor("#93C5FD")))
            if sel is clip:
                p.setBrush(QBrush(QColor("#60A5FA")))
                p.setPen(QPen(QColor("#1D4ED8"), 2))
            p.drawRoundedRect(rect, 6, 6)
            # text
            p.setPen(QPen(QColor("#111827")))
            name = clip.waveform_name or "waveform"
            p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, f"{name} ({clip.start_s:.1f}–{clip.end_s:.1f}s)")

        # Playhead
        x_cursor = self._margin_l + int(self._cursor_t * self._px_per_second)
        p.setPen(QPen(QColor("#EF4444"), 2))
        p.drawLine(x_cursor, 6, x_cursor, self.height() - 6)

        p.end()

    def _hit_test(self, pos: QPointF) -> Optional[TimelineClip]:
        rows = self._rows_layout()
        base_y = 24
        for clip in self._model.clips():
            try:
                ri = rows.index(clip.actuator)
            except ValueError:
                continue
            y = base_y + ri * (self._row_h + self._row_gap)
            x0 = self._margin_l + int(clip.start_s * self._px_per_second)
            x1 = self._margin_l + int(clip.end_s   * self._px_per_second)
            rect = QRectF(x0, y, max(12, x1 - x0), self._row_h)
            if rect.contains(pos):
                return clip
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            c = self._hit_test(e.position())
            self.clip_clicked.emit(c)
        super().mousePressEvent(e)


def _sample_event_amplitude(ev: Optional['HapticEvent'], t_s: float) -> float:
    """Return amplitude in [0..1] for event at time t_s (wrap if needed)."""
    if ev is None or not getattr(ev, "waveform_data", None):
        return 1.0
    wf = ev.waveform_data
    duration = float(wf.duration or 0.0)
    if duration <= 0.0:
        return 1.0
    # wrap
    tt = t_s % duration
    pts = wf.amplitude or []
    if not pts:
        return 1.0
    # ensure sorted
    xs = [float(p["time"]) for p in pts]
    ys = [float(p["amplitude"]) for p in pts]
    if tt <= xs[0]: return max(0.0, min(1.0, ys[0]))
    if tt >= xs[-1]: return max(0.0, min(1.0, ys[-1]))
    # linear interp
    lo = 0
    hi = len(xs) - 1
    # binary search
    while hi - lo > 1:
        m = (lo + hi)//2
        if xs[m] <= tt: lo = m
        else: hi = m
    x0, x1 = xs[lo], xs[hi]
    y0, y1 = ys[lo], ys[hi]
    alpha = 0.0 if (x1 - x0) <= 1e-9 else (tt - x0) / (x1 - x0)
    val = y0 + alpha * (y1 - y0)
    return max(0.0, min(1.0, float(val)))


class TimelineDeviceWorker(QThread):
    """Play the timeline on hardware by streaming intensity updates."""
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)

    def __init__(self, api, model: TimelineModel, total_s: float, max_intensity: int,
                 freq_code: int, tick_ms: int = 50):
        super().__init__()
        self.api = api
        self.model = model
        self.total_s = max(0.0, float(total_s))
        self.maxI = int(max(0, min(15, max_intensity)))
        self.freq = int(max(0, min(7, freq_code)))
        self.dt_ms = int(max(10, tick_ms))
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            last_I: dict[int, int] = {}
            t0 = time.perf_counter()
            while not self._stop:
                elapsed_s = time.perf_counter() - t0
                if elapsed_s > self.total_s:
                    break

                # compute target intensity for each actuator
                # (if multiple overlapping clips on same actuator: take max)
                target: dict[int, int] = {}
                for c in self.model.clips():
                    if c.start_s <= elapsed_s <= c.end_s:
                        # time inside the clip
                        local_t = elapsed_s - c.start_s
                        amp = _sample_event_amplitude(c.event, local_t)
                        Ii = int(round(amp * self.maxI))
                        if Ii <= 0:
                            continue
                        if c.actuator not in target or Ii > target[c.actuator]:
                            target[c.actuator] = Ii

                # send diffs
                # turn on/update
                for addr, inten in target.items():
                    if last_I.get(addr, 0) != inten:
                        try:
                            self.api.send_command(int(addr), int(inten), self.freq, 1)
                        except Exception as e:
                            self.log_message.emit(f"HW error @on: {e}")
                        last_I[addr] = inten
                # turn off others that were on
                for addr in list(last_I.keys()):
                    if addr not in target and last_I.get(addr, 0) > 0:
                        try:
                            self.api.send_command(int(addr), 0, 0, 0)
                        except Exception as e:
                            self.log_message.emit(f"HW error @off: {e}")
                        last_I[addr] = 0

                time.sleep(self.dt_ms / 1000.0)

            # final off for anything left
            for addr, inten in list(last_I.items()):
                if inten > 0:
                    try:
                        self.api.send_command(int(addr), 0, 0, 0)
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")

            self.finished.emit(not self._stop, "Timeline done" if not self._stop else "Timeline stopped")

        except Exception as e:
            self.finished.emit(False, f"Timeline worker error: {e}")


class TimelinePanel(QWidget):
    """Compact panel placed UNDER the tabs; drives the Designer canvas."""
    def __init__(self, gui: 'HapticPatternGUI'):
        super().__init__(gui)
        self.gui = gui

        # --- data / state ---
        self.model = TimelineModel()
        self.view = TimelineView(self.model)
        self.view.setMinimumHeight(280)

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(30)  # ~33 FPS
        self._preview_timer.timeout.connect(self._on_preview_tick)
        self._preview_running = False
        self._preview_t0 = 0.0
        self._preview_len = 0.0

        self._dev_worker: Optional[TimelineDeviceWorker] = None
        self._canvas_selector: Optional[MultiCanvasSelector] = None

        # --- root layout ---
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 6)
        root.setSpacing(2)

        # ───────────────────────────────── Title row with all controls
        title_row = QHBoxLayout()
        title_row.setSpacing(4)

        # Title label
        title_lbl = QLabel("Timeline")
        title_lbl.setStyleSheet("font-weight:600;")
        title_row.addWidget(title_lbl)
        title_row.addSpacing(12)

        # Control spinboxes
        title_row.addWidget(QLabel("Start:"))
        self.startSpin = QDoubleSpinBox()
        self.startSpin.setRange(0.0, 3600.0)
        self.startSpin.setDecimals(2)
        self.startSpin.setSuffix(" s")
        self.startSpin.setMaximumWidth(80)
        title_row.addWidget(self.startSpin)

        title_row.addSpacing(6)
        title_row.addWidget(QLabel("Stop:"))
        self.endSpin = QDoubleSpinBox()
        self.endSpin.setRange(0.0, 3600.0)
        self.endSpin.setDecimals(2) 
        self.endSpin.setSuffix(" s")
        self.endSpin.setValue(2.0)
        self.endSpin.setMaximumWidth(80)
        title_row.addWidget(self.endSpin)

        title_row.addSpacing(8)

        # Action buttons (left side)
        self.btnAdd = QPushButton("Add clip")
        self.btnAdd.setMaximumHeight(24)
        self.btnAdd.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnAdd)

        self.btnRemove = QPushButton("Remove")
        self.btnRemove.setMaximumHeight(24)
        self.btnRemove.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnRemove)

        self.btnClear = QPushButton("Clear")
        self.btnClear.setMaximumHeight(24)
        self.btnClear.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnClear)

        # Stretch to push playback buttons to the right
        title_row.addStretch()

        # Playback buttons (right side)
        self.btnPreview = QPushButton("Play preview")
        self.btnPreview.setMaximumHeight(24)
        self.btnPreview.setMaximumWidth(80)
        self.btnPreview.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnPreview)

        self.btnDevice = QPushButton("Play on device")
        self.btnDevice.setMaximumHeight(24)
        self.btnDevice.setMaximumWidth(85)
        self.btnDevice.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnDevice)

        self.btnStop = QPushButton("Stop")
        self.btnStop.setMaximumHeight(24)
        self.btnStop.setMaximumWidth(40)
        self.btnStop.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnStop)

        self.btnSave = QPushButton("Save")
        self.btnSave.setMaximumHeight(24)
        self.btnSave.setMaximumWidth(40)
        self.btnSave.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        title_row.addWidget(self.btnSave)

        root.addLayout(title_row)

        # ───────────────────────────────── Collapsible parameters box
        self._paramsBox = QFrame(self)                       # dedicated panel
        self._paramsBox.setObjectName("TimelineParams")
        self._paramsBox.setFrameShape(QFrame.Shape.StyledPanel)
        self._paramsBox.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._paramsBox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        params_layout = QVBoxLayout(self._paramsBox)
        params_layout.setContentsMargins(8, 6, 8, 6)
        params_layout.setSpacing(6)

        # Grid with Start/Stop/Add/Remove/Clear  (UNCHANGED)
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)

        self.startSpin = QDoubleSpinBox()
        self.startSpin.setRange(0.0, 3600.0); self.startSpin.setDecimals(2); self.startSpin.setSuffix(" s")

        self.endSpin = QDoubleSpinBox()
        self.endSpin.setRange(0.0, 3600.0); self.endSpin.setDecimals(2); self.endSpin.setSuffix(" s")
        self.endSpin.setValue(2.0)

        self.btnAdd    = QPushButton("Add clip")
        self.btnRemove = QPushButton("Remove selected clip")
        self.btnClear  = QPushButton("Clear timeline")

        form.addWidget(QLabel("Start:"), 0, 0)
        form.addWidget(self.startSpin,   0, 1)
        form.addWidget(QLabel("Stop:"),  0, 2)
        form.addWidget(self.endSpin,     0, 3)
        form.addWidget(self.btnAdd,      0, 4)

        form.addWidget(self.btnRemove,   1, 1, 1, 2)
        form.addWidget(self.btnClear,    1, 3, 1, 2)

        # keep columns flexible so fields don’t stretch weirdly
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(2, 0)
        form.setColumnStretch(3, 1)
        form.setColumnStretch(4, 0)

        params_layout.addLayout(form)

        # Collapsing by height (prevents overlap)
        self._paramsBox.setVisible(True)             # always present
        self._paramsBox.setMaximumHeight(0)          # collapsed
        self._paramsBox.setMinimumHeight(0)

        root.addWidget(self._paramsBox)

        # ───────────────────────────────── Timeline view  
        view_wrap = QFrame()
        view_wrap.setObjectName("TimelineViewWrap")
        view_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view_wrap.setFrameShape(QFrame.Shape.NoFrame)
        vlay = QVBoxLayout(view_wrap)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)
        vlay.addWidget(self.view)
        root.addWidget(view_wrap)

        # Stretch ratios
        root.setStretch(0, 0)   # title row with all controls
        root.setStretch(1, 1)   # timeline view (expands)



        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Let the viewport and its wrapper grow with the panel
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ───────────────────────────────── Wiring#  
        # # Default zoom and keyboard shortcuts (Cmd+ / Cmd− map to ZoomIn/ZoomOut)
        self._zoom_pxps = 70.0
        self.view.set_pixels_per_second(self._zoom_pxps)
        sc_in  = QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomIn),  self)
        sc_out = QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomOut), self)
        sc_in.activated.connect(lambda: self._nudge_zoom(+10.0))
        sc_out.activated.connect(lambda: self._nudge_zoom(-10.0))
        self.view.clip_clicked.connect(self._on_clip_clicked)
        self.btnAdd.clicked.connect(self._on_add_clip)
        self.btnRemove.clicked.connect(self._on_remove_clip)
        self.btnClear.clicked.connect(lambda: self.model.clear())
        self.btnPreview.clicked.connect(self._toggle_preview)
        self.btnDevice.clicked.connect(self._play_on_device)
        self.btnStop.clicked.connect(self.stop_all)
        self.btnSave.clicked.connect(self._save_to_library)
        


    # External wiring
    def attach_canvas_selector(self, sel: MultiCanvasSelector):
        self._canvas_selector = sel

    def _nudge_zoom(self, delta: float):
        """Adjust timeline zoom in px/s with clamping."""
        self._zoom_pxps = float(max(20.0, min(500.0, self._zoom_pxps + delta)))
        self.view.set_pixels_per_second(self._zoom_pxps)

    # Loading/saving
    def to_config(self) -> dict:
        return {
            "pattern_type": "Timeline",
            "actuators": self.model.actuators(),
            "intensity": int(self.gui.intensitySlider.value()),
            "frequency": int(self.gui.strokeFreqCode.value() if hasattr(self.gui, "strokeFreqCode") else self.gui.frequencySlider.value()),
            "timeline": [
                {
                    "actuator": c.actuator,
                    "start": float(c.start_s),
                    "end": float(c.end_s),
                    "waveform": {"source": "Waveform Library", "name": c.waveform_name}
                } for c in self.model.clips()
            ]
        }

    def load_from_config(self, cfg: dict):
        self.model.clear()
        # ensure Designer page (requirement)
        try:
            if self._canvas_selector:
                self._canvas_selector.canvasCombo.setCurrentIndex(0)
        except Exception:
            pass
        try:
            if self._canvas_selector:
                self._canvas_selector.load_actuator_configuration(cfg.get("actuators", []))
        except Exception:
            pass
        items = cfg.get("timeline", [])
        # Map waveform names to events using the current library
        for it in items:
            name = (it.get("waveform") or {}).get("name", "")
            # pick current GUI waveform if same name; else try to resolve
            ev = None
            try:
                # refresh list then try to find by text
                self.gui.refresh_waveforms()
                idx = self.gui.waveformComboBox.findText(name)
                if idx >= 0:
                    self.gui.waveformComboBox.setCurrentIndex(idx)
                    self.gui.update_waveform_info()
                    ev = self.gui.current_event
            except Exception:
                pass
            self.model.add_clip_for_actuators(
                [int(it.get("actuator", 0))],
                ev,
                name,
                float(it.get("start", 0.0)),
                float(it.get("end", 0.0))
            )

    # UI handlers
    def _on_clip_clicked(self, clip: Optional[TimelineClip]):
        self.model.set_selected(clip)
        if clip:
            self.startSpin.setValue(clip.start_s)
            self.endSpin.setValue(clip.end_s)

    def _require_designer_page(self) -> bool:
        """Ensure the active canvas is 'Designer' (index 0)."""
        try:
            if not self._canvas_selector:
                print("DEBUG: _canvas_selector is None")
                return False
            
            current_index = self._canvas_selector.stack.currentIndex()
            combo_index = self._canvas_selector.canvasCombo.currentIndex()
            combo_text = self._canvas_selector.canvasCombo.currentText()
            
            print(f"DEBUG: stack.currentIndex() = {current_index}")
            print(f"DEBUG: canvasCombo.currentIndex() = {combo_index}")
            print(f"DEBUG: canvasCombo.currentText() = '{combo_text}'")
            
            return current_index == 0
        except Exception as e:
            print(f"DEBUG: Exception in _require_designer_page: {e}")
            return False

    def _on_add_clip(self):
        if not self._require_designer_page():
            QMessageBox.warning(self, "Timeline", "Please use the Designer canvas for timeline assignment.")
            return
        if not self._canvas_selector:
            QMessageBox.warning(self, "Timeline", "Canvas selector not ready.")
            return
        acts = self._canvas_selector.get_selected_actuators()
        if not acts:
            QMessageBox.information(self, "Timeline", "Select at least one actuator on the Designer.")
            return
        start_s = float(self.startSpin.value())
        end_s   = float(self.endSpin.value())
        if end_s <= start_s:
            QMessageBox.warning(self, "Timeline", "Stop must be greater than Start.")
            return
        # Current waveform from the Waveform Selection
        ev   = self.gui.current_event
        wname= self.gui.waveformComboBox.currentText()
        if not ev:
            QMessageBox.warning(self, "Timeline", "Pick a waveform from the Waveform Library first.")
            return
        self.model.add_clip_for_actuators(acts, ev, wname, start_s, end_s)
        # convenience: next start at previous stop
        self.startSpin.setValue(end_s)
        # default end = start + waveform duration if available
        try:
            dur = float(ev.waveform_data.duration or 0.0)
            if dur > 0.0:
                self.endSpin.setValue(end_s + dur)
        except Exception:
            pass

    def _on_remove_clip(self):
        c = self.model.selected()
        if c:
            self.model.remove_clip(c)

    # Preview
    def _toggle_preview(self):
        if self._preview_running:
            self._preview_timer.stop()
            self._preview_running = False
            self.btnPreview.setText("Play preview")
            # clear highlights
            try:
                if self._canvas_selector:
                    self._canvas_selector.clear_preview()
            except Exception:
                pass
            return

        self._preview_len = max(0.01, self.model.total_duration())
        self._preview_t0  = time.perf_counter()
        self._preview_running = True
        self.btnPreview.setText("Stop preview")
        self._preview_timer.start()

    def _on_preview_tick(self):
        t = time.perf_counter() - self._preview_t0
        if t > self._preview_len:
            self._toggle_preview()
            return
        # update view + canvas highlight
        self.view.set_cursor_time(t)
        try:
            if self._canvas_selector:
                ids = self.model.active_actuators_at(t)
                self._canvas_selector.set_preview_active(ids)
        except Exception:
            pass

    # Device playback
    def _play_on_device(self):
        if self._dev_worker and self._dev_worker.isRunning():
            QMessageBox.information(self, "Timeline", "Already playing on device.")
            return
        if not self.gui.api or not self.gui.api.connected:
            QMessageBox.warning(self, "Hardware", "Please connect to a device first.")
            return
        total = max(0.01, self.model.total_duration())
        Av    = int(self.gui.intensitySlider.value())
        fcode = int(self.gui.strokeFreqCode.value() if hasattr(self.gui, "strokeFreqCode") else self.gui.frequencySlider.value())
        self._dev_worker = TimelineDeviceWorker(self.gui.api, self.model, total, Av, fcode, tick_ms=50)
        self._dev_worker.log_message.connect(self.gui._log_info)
        self._dev_worker.finished.connect(self._on_device_finished)
        self._dev_worker.start()
        self.gui._log_info(f"Timeline device playback: {len(self.model.clips())} clip(s), length ≈ {total:.2f}s")

    def _on_device_finished(self, ok: bool, msg: str):
        self.gui._log_info(f"Timeline finished → {msg}")
        self._dev_worker = None

    def stop_all(self):
        # stop preview
        if self._preview_running:
            self._toggle_preview()
        # stop device worker
        if self._dev_worker and self._dev_worker.isRunning():
            try:
                self._dev_worker.stop()
                self._dev_worker.wait(1000)
            except Exception:
                pass
            self._dev_worker = None
        # clear UI highlights
        try:
            if self._canvas_selector:
                self._canvas_selector.clear_preview()
        except Exception:
            pass
        self.view.set_cursor_time(0.0)

    # Save
    def _save_to_library(self):
        cfg = self.to_config()
        name, ok = QInputDialog.getText(self, "Save Sequence", "Name:")
        if not ok or not name.strip():
            return
        data = {
            'name': name.strip(),
            'description': "Timeline sequence",
            'timestamp': datetime.now().isoformat(),
            'config': cfg
        }
        if self.gui.pattern_manager.save_pattern(data['name'], data):
            QMessageBox.information(self, "Saved", f"Sequence '{data['name']}' saved to Pattern Library.")
            try:
                self.gui.pattern_visualization.refresh_patterns()
            except Exception:
                pass
        else:
            QMessageBox.critical(self, "Error", "Failed to save sequence.")
    
class PatternPreviewDriver(QObject):
    """
    Lightweight UI-only animator that highlights which actuators are 'active'
    at each instant. It does NOT talk to hardware.
    """
    def __init__(self, canvas_selector: 'MultiCanvasSelector', parent=None):
        super().__init__(parent)
        self.canvas_selector = canvas_selector
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # 20 FPS
        self.timer.timeout.connect(self._on_tick)
        self.running = False

        self._elapsed = 0.0
        self._total = 0.0
        self._cycle = 1.0
        self._pattern_name = ""
        self._params = {}

    def start(self, pattern_name: str, params: dict):
        """params must contain: actuators (list[int]), duration, repeat,
           playback_rate, and any pattern-specific fields (e.g., wave_speed…)."""
        self._pattern_name = pattern_name
        self._params = dict(params)
        duration = float(params.get("duration", 1.0))
        rate = max(0.001, float(params.get("playback_rate", 1.0)))
        self._cycle = max(0.05, duration / rate)      # effective duration of 1 run
        self._total = self._cycle * max(1, int(params.get("repeat", 1)))
        self._elapsed = 0.0
        self.running = True
        self.timer.start()
        # draw first frame immediately
        self._apply_active(self._active_at_time(0.0))

    def stop(self):
        self.timer.stop()
        self.running = False
        try:
            self.canvas_selector.clear_preview()
        except Exception:
            pass

    # ---- internals
    def _on_tick(self):
        if not self.running:
            return
        self._elapsed += self.timer.interval() / 1000.0
        if self._elapsed > self._total:
            self.stop()
            return
        t_cycle = self._elapsed % self._cycle
        self._apply_active(self._active_at_time(t_cycle))

    def _apply_active(self, ids):
        try:
            self.canvas_selector.set_preview_active(ids)
        except Exception:
            pass

    def _active_at_time(self, t: float) -> list[int]:
        name = self._pattern_name
        a = list(self._params.get("actuators", []))
        if not a:
            return []

        sp = self._params

        if name == "Wave":
            n = len(a)
            sweep = max(0.05, float(sp.get("wave_speed", 0.5)))
            progress = (t % sweep) / sweep
            idx = int(progress * n) % n
            return [a[idx]]

        if name == "Circular":
            n = len(a)
            sweep = max(0.05, float(sp.get("rotation_speed", 1.0)))
            progress = (t % sweep) / sweep
            idx = int(progress * n) % n
            return [a[idx]]

        if name == "Random":
            interval = float(sp.get("change_interval", 0.3))
            k = int(t / max(0.05, interval))
            rng = random.Random(k)
            return [rng.choice(a)]

        if name == "Pulse Train":
            on_t  = float(sp.get("pulse_on", 0.2))
            off_t = float(sp.get("pulse_off", 0.3))
            cyc = max(0.05, on_t + off_t)
            return a if (t % cyc) < on_t else []

        return a  # Single Pulse / Fade / Sine Wave
    
class PatternLibraryManager:
    """Gestionnaire pour la bibliothèque de patterns"""
    
    def __init__(self):
        # Determine the pattern_library path relative to the project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.pattern_library_path = os.path.join(project_root, "pattern_library")
        
        # Create pattern_library directory if it doesn't exist
        os.makedirs(self.pattern_library_path, exist_ok=True)
        
        # Create __init__.py if it doesn't exist
        init_file = os.path.join(self.pattern_library_path, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Pattern Library\n")
    
    def save_pattern(self, pattern_name, pattern_data):
        """Sauvegarder un pattern dans la bibliothèque"""
        filename = f"{pattern_name}.json"
        filepath = os.path.join(self.pattern_library_path, filename)
        
        try:
            with open(filepath, 'w') as f:
                json.dump(pattern_data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving pattern {pattern_name}: {e}")
            return False
    
    def load_pattern(self, pattern_name):
        """Charger un pattern depuis la bibliothèque"""
        filename = f"{pattern_name}.json"
        filepath = os.path.join(self.pattern_library_path, filename)
        
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading pattern {pattern_name}: {e}")
            return None
    
    def get_all_patterns(self):
        """Obtenir tous les patterns disponibles"""
        patterns = {}
        
        try:
            if os.path.exists(self.pattern_library_path):
                for filename in os.listdir(self.pattern_library_path):
                    if filename.endswith('.json'):
                        pattern_name = filename[:-5]  # Remove .json extension
                        pattern_data = self.load_pattern(pattern_name)
                        if pattern_data:
                            patterns[pattern_name] = pattern_data
        except Exception as e:
            print(f"Error scanning pattern library: {e}")
        
        return patterns
    
    def delete_pattern(self, pattern_name):
        """Supprimer un pattern de la bibliothèque"""
        filename = f"{pattern_name}.json"
        filepath = os.path.join(self.pattern_library_path, filename)
        
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
        except Exception as e:
            print(f"Error deleting pattern {pattern_name}: {e}")
        
        return False
    
    def get_pattern_info(self, pattern_name):
        """Obtenir les informations d'un pattern"""
        pattern_data = self.load_pattern(pattern_name)
        if pattern_data:
            return {
                'name': pattern_data.get('name', pattern_name),
                'description': pattern_data.get('description', ''),
                'timestamp': pattern_data.get('timestamp', ''),
                'config': pattern_data.get('config', {})
            }
        return None

class DrawingLibraryManager:
    """Storage for freehand drawings done on the actuator canvas overlay."""
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.root = os.path.join(project_root, "drawing_library")
        os.makedirs(self.root, exist_ok=True)
        init_file = os.path.join(self.root, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w") as f:
                f.write("# Drawing Library\n")

    def list(self) -> list[str]:
        items = []
        for fn in sorted(os.listdir(self.root)):
            if fn.lower().endswith(".json"):
                items.append(fn[:-5])  # without .json
        return items

    def save_json(self, name: str, data: dict) -> bool:
        path = os.path.join(self.root, f"{name}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"[DrawingLib] save error: {e}")
            return False

    def load_json(self, name: str) -> dict | None:
        path = os.path.join(self.root, f"{name}.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[DrawingLib] load error: {e}")
            return None

    def delete(self, name: str) -> bool:
        path = os.path.join(self.root, f"{name}.json")
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception as e:
            print(f"[DrawingLib] delete error: {e}")
            return False

    def export_png_path(self, name: str) -> str:
        return os.path.join(self.root, f"{name}.png")

class DrawingCanvasOverlay(QWidget):
    """
    Freehand overlay on top of the actuator canvas.
    - Library drawings are persistent and colorized.
    - The user's own drawing: keep the last stroke after mouse release,
      but erase it automatically when starting a new stroke.
    - NEW:
      • Live phantom preview while drawing (cursor)
      • Right-click to drop a persistent phantom (P0, P1, …) with links to real actuators
      • Phantoms are saved/loaded/exported with the drawing
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        self.setMouseTracking(True)

        # Persistent library layer
        self._layer = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._layer.fill(Qt.GlobalColor.transparent)

        # One "live" stroke that persists until next press
        self._live = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._live.fill(Qt.GlobalColor.transparent)
        self._live_stroke: dict | None = None
        self._live_points: list[tuple[float, float]] = []

        # Temp while dragging (stroke preview)
        self._temp = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._temp.fill(Qt.GlobalColor.transparent)

        # NEW: HUD for ephemeral markers (phantom cursor preview)
        self._hud = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._hud.fill(Qt.GlobalColor.transparent)

        self._phantoms_layer = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)

        self._trajectory_enabled = False
        self._traj_max_phantoms = 30
        self._traj_sampling_ms = 50
        self._traj_last_drop_s = 0.0
        self._traj_last_pt = None  # (x,y) normalisé du dernier drop



        self._pen_width = 4
        self._is_erasing = False
        self._drawing = False
        self._last_pos = QPoint()

        # Actuator anchors visible in "standalone" mode (when not overlaying)
        self._nodes: list[tuple[int, float, float]] = []

        # If True, just overlay; if False, we paint nodes as a background
        self._overlay_mode = True

        # Stored strokes (library only)
        self._strokes: list[dict] = []

        # Palette for appended drawings
        self._palette = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
        ]
        self._color_idx = 0

        # NEW: phantom rendering params + storage
        self._phantom_mode: str = "Phantom (3-Act, Park 2016)"
        self._phantom_gain: int = 8
        self._phantoms: list[dict] = []   # [{id:int, pt:(x,y), bursts:[(addr,intensity), ...]}]
        self._phantom_counter: int = 0

        self._draw_enabled = True
        self._traj_count = 0
        self._traj_last_drop_ms = None
        self._traj_session_ids: list[int] = []
        self._hud_only_while_drawing = True

        self.set_mouse_passthrough(True)

    # ----- basic config -----
    def set_overlay_mode(self, on: bool):
        self._overlay_mode = bool(on); self.update()
    
    def set_draw_enabled(self, on: bool):
        self._draw_enabled = bool(on)
        if not self._draw_enabled:
            self.clear_preview_marker()  # hide dashed links immediately

    def set_mouse_passthrough(self, on: bool):
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, bool(on))

    def set_nodes(self, nodes: list[tuple[int, float, float]]):
        self._nodes = nodes[:] if nodes else []; self.update()

    def set_pen_width(self, w: int):
        self._pen_width = max(1, int(w)); self.update()

    # ----- NEW: phantom preview settings -----
    def set_phantom_mode(self, mode: str):
        self._phantom_mode = str(mode or self._phantom_mode)

    def set_phantom_gain(self, av: int):
        self._phantom_gain = int(max(1, min(15, av)))

    # ----- persistence API -----
    def clear(self):
        self._strokes.clear()
        self._layer.fill(Qt.GlobalColor.transparent)
        self._live.fill(Qt.GlobalColor.transparent)
        self._temp.fill(Qt.GlobalColor.transparent)
        self._hud.fill(Qt.GlobalColor.transparent)
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)
        self._live_stroke = None
        self._live_points = []
        # NEW: clear phantoms
        self._phantoms.clear()
        self._phantom_counter = 0
        self._traj_count = 0
        self._traj_last_drop_ms = None
        self.update()

    def to_json(self) -> dict:
        strokes = [dict(s) for s in self._strokes]
        if self._live_stroke and self._live_points:
            s = dict(self._live_stroke)
            s["points"] = list(self._live_points)
            strokes.append(s)
        return {
            "pen_default": self._pen_width,
            "strokes": strokes,
            "canvas": {"w": self.width(), "h": self.height()},
            "nodes": [{"id": i, "x": x, "y": y} for (i, x, y) in self._nodes],
            # NEW: persist phantoms
            "phantoms": [
                {"id": p["id"], "x": p["pt"][0], "y": p["pt"][1], "bursts": list(p["bursts"])}
                for p in self._phantoms
            ],
            "phantom_mode": self._phantom_mode,
            "phantom_gain": self._phantom_gain,
        }

    def load_json(self, data: dict):
        self.clear()
        # strokes
        for s in data.get("strokes", []):
            pts = list(s.get("points", []))
            width = int(s.get("width", 4))
            erase = bool(s.get("erase", False))
            color = s.get("color") or self._next_color()
            self._replay_stroke(pts, width, erase, color, record=True)
        # nodes
        nd = []
        for d in data.get("nodes", []):
            try: nd.append((int(d["id"]), float(d["x"]), float(d["y"])))
            except Exception: pass
        if nd: self._nodes = nd
        # NEW: phantoms
        self._phantom_mode = data.get("phantom_mode", self._phantom_mode)
        self._phantom_gain = int(data.get("phantom_gain", self._phantom_gain))
        for ph in data.get("phantoms", []):
            try:
                pid = int(ph.get("id", self._phantom_counter))
                pt = (float(ph["x"]), float(ph["y"]))
                bursts = [(int(a), int(i)) for (a, i) in ph.get("bursts", [])]
                self._phantoms.append({"id": pid, "pt": pt, "bursts": bursts})
                self._phantom_counter = max(self._phantom_counter, pid + 1)
                self._draw_persistent_phantom(pt, bursts, f"P{pid}")
            except Exception:
                pass
        self.update()

    def append_json(self, data: dict, color: str | None = None):
        draw_color = color or self._next_color()
        for s in data.get("strokes", []):
            pts = list(s.get("points", []))
            width = int(s.get("width", 4))
            erase = bool(s.get("erase", False))
            self._replay_stroke(pts, width, erase, draw_color, record=True)

    # ----- Qt events -----
    def resizeEvent(self, e):
        def _resize(img: QImage) -> QImage:
            new_img = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
            new_img.fill(Qt.GlobalColor.transparent)
            p = QPainter(new_img)
            p.drawImage(0, 0, img.scaled(self.size(),
                                         Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
            p.end()
            return new_img
        if self._layer.size() != self.size(): self._layer = _resize(self._layer)
        if self._live.size()  != self.size(): self._live  = _resize(self._live)
        if self._temp.size()  != self.size(): self._temp  = _resize(self._temp)
        if self._hud.size()   != self.size(): self._hud   = _resize(self._hud)
        if self._phantoms_layer.size() != self.size():
            self._phantoms_layer = _resize(self._phantoms_layer)
        super().resizeEvent(e)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._overlay_mode:
            p.fillRect(self.rect(), self.palette().base())
            self._paint_nodes(p)
        p.drawImage(0, 0, self._layer)  # library
        p.drawImage(0, 0, self._phantoms_layer) 
        p.drawImage(0, 0, self._live)   # last user stroke
        p.drawImage(0, 0, self._temp)   # current dragging
        p.drawImage(0, 0, self._hud)    # NEW: ephemeral phantom marker

        p.end()

    def mousePressEvent(self, e):
        """Left: start drawing (if draw-enabled) and optionally drop a trajectory phantom.
        Right: manual phantom drop (always allowed)."""
        if e.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            pos = e.position().toPoint()
            self._last_pos = pos
            pt_norm = self._to_norm(pos)

            # Start a new live stroke only when Draw mode is enabled
            if getattr(self, "_draw_enabled", True):
                self._live.fill(Qt.GlobalColor.transparent)
                self._hud.fill(Qt.GlobalColor.transparent)
                self._temp.fill(Qt.GlobalColor.transparent)
                self._live_points = [pt_norm]
                self._live_stroke = {
                    "points": [],
                    "width": int(self._pen_width),
                    "erase": False,
                    "color": "#111827"
                }
                # seed a tiny segment so the first dot is visible
                self._draw_temp_segment(self._last_pos, self._last_pos)

            # Trajectory mode: force a first phantom at the press location
            if getattr(self, "_trajectory_enabled", False):
                now_ms = time.perf_counter() * 1000.0
                # initialize counters if missing
                if getattr(self, "_traj_count", None) is None:
                    self._traj_count = 0
                if getattr(self, "_traj_last_drop_ms", None) is None:
                    self._traj_last_drop_ms = -1e9

                if self._traj_count < int(getattr(self, "_traj_max", 30)):
                    bursts = self._compute_bursts_for_pt(pt_norm)
                    label = f"P{self._phantom_counter}"
                    self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
                    self._traj_session_ids.append(self._phantom_counter)
                    self._phantom_counter += 1
                    self._traj_count += 1
                    self._traj_last_drop_ms = now_ms
                    self._draw_persistent_phantom(pt_norm, bursts, label)

            # Always show a HUD preview under the cursor
            try:
                bursts = self._compute_bursts_for_pt(pt_norm)
                node_map = {aid: (x, y) for (aid, x, y) in self._nodes}
                self.show_preview_marker(pt_norm, node_map, bursts)
            except Exception:
                pass

        elif e.button() == Qt.MouseButton.RightButton:
            # Manual phantom drop (independent from Draw/Trajectory toggles)
            pos = e.position().toPoint()
            pt_norm = self._to_norm(pos)
            try:
                bursts = self._compute_bursts_for_pt(pt_norm)
                label = f"P{self._phantom_counter}"
                self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
                self._traj_session_ids.append(self._phantom_counter)
                self._phantom_counter += 1
                self._draw_persistent_phantom(pt_norm, bursts, label)
                self.update()
            except Exception:
                pass

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        """While dragging: draw stroke if enabled and emit trajectory phantoms at the sampling rate.
        Always render the HUD phantom preview at the cursor."""
        pos = e.position().toPoint()
        pt_norm = self._to_norm(pos)

        if self._drawing:
            # Draw stroke only when Draw mode is enabled
            if getattr(self, "_draw_enabled", True):
                self._draw_temp_segment(self._last_pos, pos)
                self._live_points.append(pt_norm)
                self._last_pos = pos

            # Trajectory mode: drop phantoms along the path according to sampling rate
            if getattr(self, "_trajectory_enabled", False):
                now_ms = time.perf_counter() * 1000.0
                last = getattr(self, "_traj_last_drop_ms", -1e9)
                sampling = float(getattr(self, "_traj_sampling_ms", 50))
                if self._traj_count < int(getattr(self, "_traj_max", 30)) and (now_ms - last) >= sampling:
                    try:
                        bursts = self._compute_bursts_for_pt(pt_norm)
                        label = f"P{self._phantom_counter}"
                        self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
                        self._traj_session_ids.append(self._phantom_counter)
                        self._phantom_counter += 1
                        self._traj_count += 1
                        self._traj_last_drop_ms = now_ms
                        self._draw_persistent_phantom(pt_norm, bursts, label)
                    except Exception:
                        pass

        # Show HUD links only WHILE actively drawing
        if self._drawing:
            try:
                bursts = self._compute_bursts_for_pt(pt_norm)
                node_map = {aid: (x, y) for (aid, x, y) in self._nodes}
                self.show_preview_marker(pt_norm, node_map, bursts)
            except Exception:
                pass
        else:
            # ensure it's hidden when not drawing
            self.clear_preview_marker()

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        """Finish the live stroke (if any) and clear the HUD."""
        if e.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False

            # Commit the live stroke only when Draw mode is enabled
            if getattr(self, "_draw_enabled", True):
                p = QPainter(self._live)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.drawImage(0, 0, self._temp)
                p.end()
                self._temp.fill(Qt.GlobalColor.transparent)

                if self._live_stroke is not None:
                    self._live_stroke["points"] = list(self._live_points)

            # Clear HUD circle/links
            if getattr(self, "_trajectory_enabled", False):
                self._redistribute_traj_phantoms_uniform()
            self._hud.fill(Qt.GlobalColor.transparent)
            self.update()

        super().mouseReleaseEvent(e)

    # ----- helper internals -----
    def _next_color(self) -> str:
        c = self._palette[self._color_idx % len(self._palette)]
        self._color_idx += 1
        return c

    def _draw_temp_segment(self, a: QPoint, b: QPoint):
        painter = QPainter(self._temp)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#111827"), self._pen_width,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(a, b)
        painter.end()
        self.update()

    def _replay_stroke(self, points: list, width: int, erase: bool, color: str, record: bool):
        if not points: return
        painter = QPainter(self._layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if erase:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        else:
            painter.setPen(QPen(QColor(color), int(width),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        last = self._from_norm(points[0])
        for p in points[1:]:
            cur = self._from_norm(p)
            painter.drawLine(last, cur)
            last = cur
        painter.end()
        if record:
            self._strokes.append({"points": list(points), "width": int(width), "erase": bool(erase), "color": color})
        self.update()

    def export_png(self, path: str) -> bool:
        img = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.white)
        p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_nodes(p)
        p.drawImage(0, 0, self._layer)  # library strokes + persistent phantoms
        p.drawImage(0, 0, self._phantoms_layer)
        p.drawImage(0, 0, self._live)   # last user stroke
        p.end()
        return img.save(path)
    
    def enable_trajectory(self, on: bool):
        self._trajectory_enabled = bool(on)
        self._traj_last_drop_s = 0.0
        self._traj_last_pt = None

    def _maybe_drop_traj_phantom(self, pt_norm: tuple[float,float], force: bool = False):
        """Dépose un phantom persistant le long du tracé, si sampling + max OK."""
        if not self._trajectory_enabled:
            return
        if len(self._phantoms) >= self._traj_max_phantoms:
            return

        now = time.perf_counter()
        if not force and (now - self._traj_last_drop_s) < (self._traj_sampling_ms / 1000.0):
            return

        # évite les doublons trop proches
        if self._traj_last_pt is not None and not force:
            if math.hypot(pt_norm[0]-self._traj_last_pt[0], pt_norm[1]-self._traj_last_pt[1]) < 0.005:
                return

        bursts = self._compute_bursts_for_pt(pt_norm)
        label = f"P{self._phantom_counter}"
        self._phantoms.append({"id": self._phantom_counter, "pt": pt_norm, "bursts": bursts})
        self._traj_session_ids.append(self._phantom_counter)
        self._phantom_counter += 1
        self._draw_persistent_phantom(pt_norm, bursts, label)
        self._traj_last_drop_s = now
        self._traj_last_pt = pt_norm
        self.update()

    def _resample_polyline_uniform(self, pts: list[tuple[float,float]], n: int):
        if n <= 1 or len(pts) < 2:
            return pts[:1] * max(1, n)
        # distances cumulées
        d = [0.0]
        for a, b in zip(pts, pts[1:]):
            d.append(d[-1] + math.hypot(b[0]-a[0], b[1]-a[1]))
        L = d[-1] if d[-1] > 0 else 1e-9
        targets = [i * L / (n - 1) for i in range(n)]
        out, j = [], 0
        for t in targets:
            while j + 1 < len(d) and d[j+1] < t:
                j += 1
            if j + 1 >= len(d):
                out.append(pts[-1]); continue
            seg = d[j+1] - d[j]
            alpha = 0.0 if seg <= 0 else (t - d[j]) / seg
            x = pts[j][0] + alpha * (pts[j+1][0] - pts[j][0])
            y = pts[j][1] + alpha * (pts[j+1][1] - pts[j][1])
            out.append((x, y))
        return out

    def _redistribute_traj_phantoms_uniform(self):
        # rien à faire si pas en mode trajectoire
        if not getattr(self, "_trajectory_enabled", False):
            return
        if not self._traj_session_ids or len(self._live_points) < 2:
            # aucune session ou pas de trait utile
            self._traj_session_ids.clear()
            return

        n = min(len(self._traj_session_ids), int(self._traj_max_phantoms))
        samples = self._resample_polyline_uniform(self._live_points, n)

        # 1) retirer les anciens phantoms de la session courante
        ids_to_remove = set(self._traj_session_ids)
        self._phantoms = [p for p in self._phantoms if p["id"] not in ids_to_remove]
        self._traj_session_ids.clear()

        # 2) effacer et re-dessiner la couche persistante (pour garder les autres phantoms)
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)
        for p in self._phantoms:
            self._draw_persistent_phantom(p["pt"], p["bursts"], f"P{p['id']}")

        # 3) ajouter n phantoms uniformément répartis sur le trait
        for pt in samples:
            bursts = self._compute_bursts_for_pt(pt)
            pid = self._phantom_counter
            self._phantoms.append({"id": pid, "pt": pt, "bursts": bursts})
            self._draw_persistent_phantom(pt, bursts, f"P{pid}")
            self._traj_session_ids.append(pid)
            self._phantom_counter += 1

        # cette session est maintenant “reconstruite” → on vide le marqueur
        self._traj_session_ids.clear()
        self.update()
    def set_traj_limits(self, max_phantoms: int, sampling_ms: int):
        self._traj_max_phantoms = int(max(1, max_phantoms))
        self._traj_sampling_ms = int(max(10, sampling_ms))

    def clear_strokes_only(self):
        """Efface uniquement le dessin (garde les phantoms)."""
        self._strokes.clear()
        self._layer.fill(Qt.GlobalColor.transparent)
        self._live.fill(Qt.GlobalColor.transparent)
        self._temp.fill(Qt.GlobalColor.transparent)
        self._hud.fill(Qt.GlobalColor.transparent)
        self._live_stroke = None
        self._live_points = []
        self.update()

    def clear_phantoms_only(self):
        """Efface uniquement les phantoms persistants."""
        self._phantoms.clear()
        self._phantoms_layer.fill(Qt.GlobalColor.transparent)
        self._phantom_counter = 0
        self.update()

    def _paint_nodes(self, p: QPainter):
        r = 16
        for nid, xn, yn in self._nodes:
            cx = int(xn * (self.width() - 48) + 24)
            cy = int(yn * (self.height() - 48) + 24)
            rect = QRectF(cx - r, cy - r, 2*r, 2*r)
            p.setPen(QPen(QColor("#374151"), 2))
            p.setBrush(QBrush(QColor("#E5E7EB")))
            p.drawEllipse(rect)
            p.setPen(QPen(QColor("#111827")))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(nid))

    def _to_norm(self, pt: QPoint) -> tuple[float, float]:
        return (max(0.0, min(1.0, pt.x() / max(1, self.width() - 1))),
                max(0.0, min(1.0, pt.y() / max(1, self.height() - 1))))

    def _from_norm(self, xy: tuple[float, float]) -> QPoint:
        return QPoint(int(xy[0] * (self.width() - 1)), int(xy[1] * (self.height() - 1)))

    # ===== NEW: phantom computation & drawing =====
    def _compute_bursts_for_pt(self, pt_norm: tuple[float, float]) -> list[tuple[int,int]]:
        """Compute (actuator_id, intensity) set for a phantom at pt_norm,
        using current phantom mode and gain, based on nearest anchors in self._nodes."""
        id_to_xy = {aid: (x, y) for (aid, x, y) in self._nodes}
        if not id_to_xy:
            return []
        # Distances
        items = []
        for aid, (x, y) in id_to_xy.items():
            d = math.hypot(pt_norm[0] - x, pt_norm[1] - y)
            items.append((aid, d))
        items.sort(key=lambda t: t[1])

        Av = int(self._phantom_gain)
        mode = self._phantom_mode or ""
        try:
            if mode.startswith("Physical"):
                a1, _ = items[0]
                return [(a1, Av)]
            elif "2-Act" in mode:
                (a1, d1), (a2, d2) = items[:2]
                from_this = StrokePlaybackWorker._phantom_intensities_2act(d1, d2, Av)
                return [(a1, from_this[0]), (a2, from_this[1])]
            else:
                (a1, d1), (a2, d2), (a3, d3) = items[:3]
                A1, A2, A3 = StrokePlaybackWorker._phantom_intensities_3act(d1, d2, d3, Av)
                return [(a1, A1), (a2, A2), (a3, A3)]
        except Exception:
            # fallback: nearest-1
            a1, _ = items[0]
            return [(a1, Av)]
# DrawingCanvasOverlay._draw_persistent_phantom
    def _draw_persistent_phantom(self, pt_norm: tuple[float,float],
                                bursts: list[tuple[int,int]], label: str):
        """Commit un phantom (cercle + label) en PERSISTANT, sans liens."""
        p = QPainter(self._phantoms_layer)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self._from_norm(pt_norm)
        r = 12

        p.setPen(QPen(QColor("#E11D48"), 3))
        p.setBrush(QBrush(QColor(0, 0, 0, 0)))
        p.drawEllipse(QRectF(c.x()-r, c.y()-r, 2*r, 2*r))

        p.setPen(QPen(QColor("#7C3AED")))
        p.setFont(QFont("", 9, QFont.Weight.Bold))
        p.drawText(c + QPoint(14, 4), label)

        p.end()

    # ===== UPDATED: HUD preview used by GUI and by live drawing =====
    def show_preview_marker(self, pt_norm: tuple[float,float],
                            node_map: dict[int, tuple[float,float]],
                            bursts: list[tuple[int,int]]):
        """Draw an ephemeral preview (phantom circle + dashed links) on the HUD."""
        # if getattr(self, "_hud_only_while_drawing", False) and not getattr(self, "_drawing", False):
        #     # also clear any stale HUD
        #     self._hud.fill(Qt.GlobalColor.transparent)
        #     self.update()
        #     return
        self._hud.fill(Qt.GlobalColor.transparent)
        p = QPainter(self._hud)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # phantom (circle)
        c = self._from_norm(pt_norm)
        r = 10
        p.setPen(QPen(QColor("#E11D48"), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(c.x()-r, c.y()-r, 2*r, 2*r))

        # links to active actuators (with intensity labels)
        for aid, inten in bursts:
            if aid in node_map:
                nx, ny = node_map[aid]
                npt = self._from_norm((nx, ny))
                p.setPen(QPen(QColor("#7C3AED"), 2, Qt.PenStyle.DashLine))
                p.drawLine(c, npt)
                p.setPen(QPen(QColor("#111827")))
                midx = int((c.x() + npt.x())/2)
                midy = int((c.y() + npt.y())/2)
                p.drawText(midx, midy, str(inten))
        p.end()
        self.update()

    def clear_preview_marker(self):
        self._hud.fill(Qt.GlobalColor.transparent)
        self.update()

class DrawingStudioTab(QWidget):
    """
    Minimal, focused Drawing Studio:
    - Top bar: Clear · Draw mode · Save
    - Library list (double-click to load; right-click to delete)
    - High-Density Trajectory Creation (no 'Stop Drawing' button)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lib = DrawingLibraryManager()
        self.canvas_selector: MultiCanvasSelector | None = None
        self._overlay: DrawingCanvasOverlay | None = None

        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

    # ═══════════════════════════ Top bar (Clear · Save · Draw mode) - CORRECTED ═══════════════════════════
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)

        self.btnClear = QPushButton("Clear")
        self.btnSave = QPushButton("Save")
        self.chkDraw = QCheckBox("Draw mode")
        self.chkDraw.setToolTip("Enable freehand drawing on the overlay.")

        # CORRECTION: Limiter la largeur des boutons
        self.btnClear.setMaximumWidth(80)
        self.btnSave.setMaximumWidth(80)
        
        hdr.addWidget(self.btnClear)
        hdr.addWidget(self.btnSave)
        hdr.addStretch()  # push Draw mode to the right
        hdr.addWidget(self.chkDraw)
        root.addLayout(hdr)

        # ═══════════════════════════ High-Density Trajectory Creation (no Stop) ═══════════════════════════
        trajGroup = QGroupBox("High-Density Trajectory Creation")
        tg = QGridLayout(trajGroup)
        tg.setContentsMargins(8, 6, 8, 6)
        tg.setSpacing(6)

        self.spinMaxPhantoms = QSpinBox()
        self.spinMaxPhantoms.setRange(1, 300)
        self.spinMaxPhantoms.setValue(30)
        # CORRECTION: Limiter la largeur du spinbox
        self.spinMaxPhantoms.setMaximumWidth(80)
        self.spinMaxPhantoms.setMinimumWidth(60)

        self.spinSampling = QSpinBox()
        self.spinSampling.setRange(10, 500)
        self.spinSampling.setSingleStep(10)
        self.spinSampling.setSuffix(" ms")
        self.spinSampling.setValue(50)
        # CORRECTION: Limiter la largeur du spinbox
        self.spinSampling.setMaximumWidth(80)
        self.spinSampling.setMinimumWidth(60)

        self.chkTrajectory = QCheckBox("Trajectory mode (phantoms)")
        self.btnClearPhantoms = QPushButton("Clear")
        # CORRECTION: Limiter la largeur du bouton
        self.btnClearPhantoms.setMaximumWidth(120)

        tg.addWidget(QLabel("Max Phantoms:"), 0, 0)
        tg.addWidget(self.spinMaxPhantoms, 0, 1)
        tg.addWidget(QLabel("Sampling Rate:"), 1, 0)
        tg.addWidget(self.spinSampling, 1, 1)

        # Move "Trajectory mode" next to "Clear Phantoms" to save vertical space
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.btnClearPhantoms)
        row.addSpacing(8)
        row.addWidget(self.chkTrajectory)
        row.addStretch()  # CORRECTION: Ajouter un stretch pour empêcher l'expansion
        tg.addLayout(row, 2, 0, 1, 3)
        
        # CORRECTION: Empêcher l'expansion des colonnes
        tg.setColumnStretch(2, 1)  # La colonne 2 prend l'espace supplémentaire
        
        self.chkTrajectory.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.btnClearPhantoms.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        root.addWidget(trajGroup)

        # ───────────────────────────────────── Drawing Library ─────────────────────────────────────
        libGroup = QGroupBox("Drawing Library")
        libLayout = QVBoxLayout(libGroup)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_list_context_menu)
        self.list.itemDoubleClicked.connect(lambda *_: self._do_load())

        libLayout.addWidget(self.list)
        root.addWidget(libGroup)

        # ───────────────────────────────────────── Wiring ──────────────────────────────────────────
        self.btnClear.clicked.connect(self._do_new)
        self.btnSave.clicked.connect(self._do_save)

        self.chkDraw.toggled.connect(self._set_drawing_enabled)

        self.chkTrajectory.toggled.connect(self._on_traj_toggled)
        self.spinMaxPhantoms.valueChanged.connect(self._apply_traj_limits)
        self.spinSampling.valueChanged.connect(self._apply_traj_limits)
        self.btnClearPhantoms.clicked.connect(
            lambda: (self._overlay and self._overlay.clear_phantoms_only())
        )
        # Permettre la désélection en cliquant dans une zone vide
        self.list.mousePressEvent = self._list_mouse_press_event
        # Réagir aux changements de sélection pour vider le canvas si besoin
        self.list.itemSelectionChanged.connect(self._on_selection_changed)

        # Initial list load
        self._refresh_list()
    
    def _on_selection_changed(self):
        """Réagir aux changements de sélection - vider le canvas si rien n'est sélectionné."""
        if not self.list.selectedItems():
            # Aucun élément sélectionné -> vider le canvas pour permettre un nouveau dessin
            if self._overlay and hasattr(self._overlay, "clear"):
                self._overlay.clear()

    # ───────────────────────────────────────── Public API ─────────────────────────────────────────
    def set_overlay_active(self, active: bool):
        """
        Called when switching tabs.
        Keep the overlay visible across tabs so previews/playback can render.
        Only grab the mouse when this tab is active AND Draw mode is on.
        """
        if not self._overlay:
            return
        self._overlay.setVisible(True)  # always visible
        self._overlay.set_mouse_passthrough(not (active and self.chkDraw.isChecked()))

    def bind_controls(self, gui: 'HapticPatternGUI'):
        """Mirror phantom renderer + gain from the Waveform Lab controls."""
        self._gui = gui
        if self._overlay:
            self._overlay.set_phantom_mode(gui.strokeModeCombo.currentText())
            self._overlay.set_phantom_gain(gui.intensitySlider.value())

        def _apply():
            if self._overlay:
                self._overlay.set_phantom_mode(gui.strokeModeCombo.currentText())
                self._overlay.set_phantom_gain(gui.intensitySlider.value())

        gui.strokeModeCombo.currentTextChanged.connect(lambda *_: _apply())
        gui.intensitySlider.valueChanged.connect(lambda *_: _apply())

    def attach_canvas_selector(self, sel: MultiCanvasSelector):
        self.canvas_selector = sel
        try:
            sel.canvasCombo.currentIndexChanged.connect(lambda *_: self._ensure_overlay_on_current_canvas())
        except Exception:
            pass
        self._ensure_overlay_on_current_canvas()

    # ───────────────────────────────────────── Internals ──────────────────────────────────────────
    def _on_list_context_menu(self, pos):
        # Ensure we have a selection; if none, select the item under the cursor
        if not self.list.selectedItems():
            it = self.list.itemAt(pos)
            if it:
                it.setSelected(True)
        if not self.list.selectedItems():
            return

        menu = QMenu(self)
        act_delete = menu.addAction("Delete")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen == act_delete:
            self._do_delete()

    def _on_traj_toggled(self, on: bool):
        if self._overlay:
            self._overlay.enable_trajectory(on)
            self._overlay.set_traj_limits(self.spinMaxPhantoms.value(), self.spinSampling.value())
            # Reset current trajectory if overlay supports it
            if hasattr(self._overlay, "reset_trajectory"):
                self._overlay.reset_trajectory()
            # Mouse capture: capture when either Draw or Trajectory mode is ON (except Designer page)
            is_designer = (self.canvas_selector and self.canvas_selector.stack.currentIndex() == 0)
            self._overlay.set_mouse_passthrough(True if is_designer else not (self.chkDraw.isChecked() or on))

    def _ensure_overlay_on_current_canvas(self):
        """
        (Re)attach the drawing overlay to the currently active canvas widget,
        push all UI state (modes, limits), and set mouse-capture policy.
        """
        if self.canvas_selector is None:
            return

        host = self.canvas_selector.get_active_canvas_widget()
        if host is None:
            return

        # Reuse the overlay if already targeting the same host; otherwise recreate it
        if self._overlay and self._overlay.parent() is host:
            self._overlay.setGeometry(host.rect())
        else:
            # Dispose previous overlay if any
            if self._overlay:
                try:
                    self._overlay.setParent(None)
                    self._overlay.deleteLater()
                except Exception:
                    pass
                self._overlay = None

            # Create a fresh overlay bound to the active canvas
            self._overlay = DrawingCanvasOverlay(parent=host)
            self._overlay.set_overlay_mode(True)
            # Default pen width (since Pen UI was removed)
            try:
                self._overlay.set_pen_width(4)
            except Exception:
                pass

            # Mirror phantom renderer/gain from Waveform Lab, if available
            if hasattr(self, "_gui") and self._gui:
                try:
                    self._overlay.set_phantom_mode(self._gui.strokeModeCombo.currentText())
                    self._overlay.set_phantom_gain(self._gui.intensitySlider.value())
                except Exception:
                    pass

            # Keep the overlay sized with the host
            try:
                host.installEventFilter(self)
            except Exception:
                pass

        # Always visible; mouse capture handled separately
        self._overlay.setVisible(True)
        self._overlay.setGeometry(host.rect())
        self._overlay.raise_()

        # Update actuator anchors used for phantom computation
        try:
            self._overlay.set_nodes(self.canvas_selector.current_nodes())
        except Exception:
            pass

        # Push runtime modes & limits from the Drawing tab
        draw_on = bool(self.chkDraw.isChecked())
        traj_on = bool(self.chkTrajectory.isChecked())

        try:
            self._overlay.set_draw_enabled(draw_on)
        except Exception:
            pass
        try:
            self._overlay.enable_trajectory(traj_on)
        except Exception:
            pass
        try:
            self._overlay.set_traj_limits(self.spinMaxPhantoms.value(), self.spinSampling.value())
            if hasattr(self._overlay, "reset_trajectory"):
                self._overlay.reset_trajectory()
        except Exception:
            pass

        # Mouse capture policy
        is_designer = (self.canvas_selector.stack.currentIndex() == 0)
        try:
            if is_designer:
                # Designer page: never intercept (so you can place actuators)
                self._overlay.set_mouse_passthrough(True)
            else:
                # Capture when either Draw or Trajectory mode is ON
                self._overlay.set_mouse_passthrough(not (draw_on or traj_on))
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if self._overlay and ev.type() == QEvent.Type.Resize:
            self._overlay.setGeometry(obj.rect())
        return super().eventFilter(obj, ev)

    # ───────────────────────────────────────── Library ops ─────────────────────────────────────────
    def _refresh_list(self):
        self.list.clear()
        for name in self.lib.list():
            self.list.addItem(name)

    def _current_name(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None

    def _do_new(self):
        if self._overlay and hasattr(self._overlay, "clear"):
            self._overlay.clear()

    def _do_save(self):
        """
        Save does both jobs:
        - If a drawing is selected in the list → overwrite it.
        - Otherwise → prompt for a new name (formerly 'Save As…').
        """
        name = self._current_name()
        if not name:
            self._do_save_as()
            return
        self._save_named(name)
        self._refresh_list()

    # Internal helper (kept, no visible button)
    def _do_save_as(self):
        name, ok = QInputDialog.getText(self, "Save Drawing", "Name:")
        if not ok or not name.strip():
            return
        self._save_named(name.strip())
        self._refresh_list()

    def _save_named(self, name: str):
        if not self._overlay:
            QMessageBox.warning(self, "Save", "No overlay available.")
            return
        if hasattr(self._overlay, "to_json"):
            data = self._overlay.to_json()
            ok = self.lib.save_json(name, data)
            if ok:
                QMessageBox.information(self, "Saved", f"Drawing '{name}' saved.")
            else:
                QMessageBox.critical(self, "Error", "Failed to save drawing.")

    def _do_load(self):
        if not self._overlay:
            QMessageBox.warning(self, "Load", "No overlay available.")
            return
        items = self.list.selectedItems()
        if not items:
            return
        names = [it.text() for it in items]
        datas = [self.lib.load_json(n) for n in names]
        datas = [d for d in datas if d]

        if hasattr(self._overlay, "clear"):
            self._overlay.clear()
        for d in datas:
            self._overlay.append_json(d)
        
    def _list_mouse_press_event(self, event):
        """Gérer les clics de souris sur la liste pour permettre la désélection."""
        # Appeler d'abord le comportement normal
        from PyQt6.QtWidgets import QListWidget
        QListWidget.mousePressEvent(self.list, event)
        
        # Si on a cliqué dans une zone vide, désélectionner tout
        item_at_pos = self.list.itemAt(event.position().toPoint())
        if item_at_pos is None:
            self.list.clearSelection()
            self.list.setCurrentItem(None) 

    def _do_delete(self):
        items = self.list.selectedItems()
        if not items:
            return
        names = [it.text() for it in items]
        if QMessageBox.question(
            self, "Delete", f"Delete {len(names)} drawing(s)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        for n in names:
            self.lib.delete(n)
        self._refresh_list()

    # ───────────────────────────────────────── Modes/limits ────────────────────────────────────────
    def _apply_traj_limits(self, *_):
        if self._overlay:
            self._overlay.set_traj_limits(self.spinMaxPhantoms.value(), self.spinSampling.value())

    def _set_drawing_enabled(self, on: bool):
        if self._overlay:
            self._overlay.set_draw_enabled(on)
            # Capture mouse when Draw or Trajectory is ON (except Designer)
            is_designer = (self.canvas_selector and self.canvas_selector.stack.currentIndex() == 0)
            self._overlay.set_mouse_passthrough(True if is_designer else not (on or self.chkTrajectory.isChecked()))

class PatternVisualizationWidget(QWidget):
    """Clean library view with search, info panel, and primary actions."""
    pattern_selected = pyqtSignal(dict)
    pattern_deleted = pyqtSignal(str)

    def __init__(self, pattern_manager):
        super().__init__()
        self.pattern_manager = pattern_manager
        self._all: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._build_ui()
        self.refresh_patterns()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # header
        header = QHBoxLayout()
        ttl = QLabel("Your Pattern Library")
        ttl.setStyleSheet("font-weight:600;")
        header.addWidget(ttl); header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMaximumWidth(90)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # search
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter patterns…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        # list
        self.pattern_list = QListWidget()
        self.pattern_list.setUniformItemSizes(True)
        self.pattern_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pattern_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self.pattern_list, 1)

        # info
        self.info_label = QLabel("Select a pattern to view details")
        self.info_label.setObjectName("patternDescLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # actions
        row = QHBoxLayout()
        self.load_button = QPushButton("Load Pattern")
        self.load_button.setObjectName("loadSelectedBtn")
        self.load_button.setEnabled(False)
        self.delete_button = QPushButton("Delete")
        row.addWidget(self.load_button)
        row.addWidget(self.delete_button)
        row.addStretch()
        layout.addLayout(row)

        # wire
        self.refresh_button.clicked.connect(self.refresh_patterns)
        self.search.textChanged.connect(self._rebuild)
        self.pattern_list.itemSelectionChanged.connect(self._on_clicked)
        self.pattern_list.itemDoubleClicked.connect(lambda *_: self.load_selected_pattern())
        self.load_button.clicked.connect(self.load_selected_pattern)
        self.delete_button.clicked.connect(self._delete_current)

    # data ops
    def refresh_patterns(self):
        self._all = self.pattern_manager.get_all_patterns()
        self._by_name = {k: v for k, v in self._all.items()}
        self._rebuild()

    def _rebuild(self):
        q = self.search.text().strip().lower()
        self.pattern_list.clear()
        for name in sorted(self._by_name.keys()):
            if q and q not in name.lower():
                continue
            info = self._by_name[name]
            it = QListWidgetItem(name)
            cfg = info.get("config", {})
            it.setToolTip(f"{cfg.get('pattern_type','?')} • {len(cfg.get('actuators',[]))} actuator(s)")
            it.setSizeHint(QSize(it.sizeHint().width(), 30))
            self.pattern_list.addItem(it)
        self.info_label.setText(
            "No patterns found" if self.pattern_list.count()==0 else "Select a pattern to view details"
        )
        self.load_button.setEnabled(False)

    def _on_clicked(self):
        it = self.pattern_list.currentItem()
        if not it:
            self.load_button.setEnabled(False)
            self.info_label.setText("Select a pattern to view details")
            return
        self.load_button.setEnabled(True)
        info = self.pattern_manager.get_pattern_info(it.text())
        if not info:
            self.info_label.setText("Error loading pattern information")
            return
        cfg = info["config"]
        lines = [
            f"<b>{info.get('name', it.text())}</b>",
            f"<i>{info.get('description','')}</i>" if info.get('description') else "",
            f"<b>Type:</b> {cfg.get('pattern_type','?')}",
            f"<b>Actuators:</b> {cfg.get('actuators',[])}",
            f"<b>Intensity:</b> {cfg.get('intensity',0)}",
            f"<b>Frequency:</b> {cfg.get('frequency',0)}"
        ]
        wf = cfg.get("waveform", {})
        if wf: lines.append(f"<b>Waveform:</b> {wf.get('name','?')} ({wf.get('source','?')})")
        sp = cfg.get("specific_parameters", {})
        if sp:
            lines.append("<b>Specific Parameters:</b>")
            for k,v in sp.items(): lines.append(f"&nbsp;&nbsp;{k}: {v}")
        if info.get('timestamp'): lines.append(f"<br><small>Created: {info['timestamp']}</small>")
        self.info_label.setText("<br>".join([s for s in lines if s]))

    def load_selected_pattern(self):
        it = self.pattern_list.currentItem()
        if not it: return
        info = self.pattern_manager.get_pattern_info(it.text())
        if info:
            self.pattern_selected.emit(info)

    def _delete_current(self):
        it = self.pattern_list.currentItem()
        if not it: return
        name = it.text()
        if QMessageBox.question(self, "Delete Pattern",
                                f"Delete '{name}'?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                               ) != QMessageBox.StandardButton.Yes:
            return
        if self.pattern_manager.delete_pattern(name):
            self.pattern_deleted.emit(name)
            self.refresh_patterns()

class PatternWorker(QThread):
    """Worker thread for running patterns"""
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)
    
    def __init__(self, pattern, params):
        super().__init__()
        self.pattern = pattern
        self.params = params
    
    def run(self):
        try:
            result = self.pattern.execute(**self.params)
            message = "Pattern completed successfully" if result else "Pattern execution failed"
            self.log_message.emit(message)
            self.finished.emit(result, message)
        except Exception as e:
            error_msg = f"Pattern execution error: {e}"
            self.log_message.emit(error_msg)
            self.finished.emit(False, error_msg)

class StrokePlaybackWorker(QThread):
    """Schedule and play a stroke schedule on hardware with explicit offs."""
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)
    step_started = pyqtSignal(int, list, tuple)

    def __init__(self, api, schedule, freq_code:int):
        super().__init__()
        self.api = api
        self.schedule = list(sorted(schedule, key=lambda s: s["t_on"]))
        self.freq_code = int(max(0, min(7, freq_code)))
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        """Play the precomputed schedule on the device and emit UI updates.

        Emits:
            - step_started(int index, list bursts, tuple pt): just before sending ON commands
            - log_message(str): on hardware errors
            - finished(bool ok, str message): at end or on error
        """
        try:
            t0 = time.perf_counter()
            off_events = []  # list of {"t_off": ms_from_start, "addr": int}
            active_addrs = set()

            for i, step in enumerate(self.schedule):
                if self._stop_flag:
                    break

                # Wait until the absolute onset time (in ms from t0)
                while not self._stop_flag and (time.perf_counter() - t0) * 1000.0 < step["t_on"]:
                    time.sleep(0.0005)

                # Notify UI about the step that is starting
                try:
                    self.step_started.emit(i, step["bursts"], step.get("pt", (0.5, 0.5)))
                except Exception:
                    pass  # never break playback because of UI issues

                # Send ON commands for this step
                for addr, inten in step["bursts"]:
                    try:
                        self.api.send_command(int(addr), int(inten), self.freq_code, 1)
                        active_addrs.add(int(addr))
                    except Exception as e:
                        self.log_message.emit(f"HW error @on: {e}")

                # Schedule OFF commands for this step
                for addr, _ in step["bursts"]:
                    off_events.append({
                        "t_off": step["t_on"] + step["dur_ms"],
                        "addr": int(addr)
                    })

                # Send any OFFs that are due by now
                now_ms = (time.perf_counter() - t0) * 1000.0
                due = [o for o in off_events if o["t_off"] <= now_ms]
                for off in due:
                    try:
                        self.api.send_command(off["addr"], 0, 0, 0)
                        active_addrs.discard(off["addr"])
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")
                    off_events.remove(off)

            # Drain remaining OFFs
            if self._stop_flag:
                # On stop, turn everything off immediately (no more waiting)
                for off in off_events:
                    try:
                        self.api.send_command(off["addr"], 0, 0, 0)
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")
            else:
                # Normal end: wait until each OFF time then send it
                for off in off_events:
                    while (time.perf_counter() - t0) * 1000.0 < off["t_off"]:
                        time.sleep(0.0005)
                    try:
                        self.api.send_command(off["addr"], 0, 0, 0)
                    except Exception as e:
                        self.log_message.emit(f"HW error @off: {e}")

            self.finished.emit(not self._stop_flag,
                            "Stroke playback done" if not self._stop_flag else "Stopped")

        except Exception as e:
            self.finished.emit(False, f"Stroke worker error: {e}")

    @staticmethod
    def _resample_polyline(points_xy: list[tuple[float,float]], n_samples: int) -> list[tuple[float,float]]:

        """Arc-length resample of a polyline in [0..1]×[0..1]."""
        if n_samples <= 1 or len(points_xy) < 2:
            return points_xy[:1] * max(1, n_samples)
        # cumulative distances
        d = [0.0]
        for a,b in zip(points_xy, points_xy[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            d.append(d[-1] + math.hypot(dx, dy))
        length = d[-1] if d[-1] > 0 else 1e-9
        targets = [i*length/(n_samples-1) for i in range(n_samples)]
        out = []
        j = 0
        for t in targets:
            while j+1 < len(d) and d[j+1] < t:
                j += 1
            if j+1 >= len(d):
                out.append(points_xy[-1]); continue
            # local interpolation between j and j+1
            seg = d[j+1] - d[j]
            alpha = 0.0 if seg <= 0 else (t - d[j]) / seg
            x = points_xy[j][0] + alpha * (points_xy[j+1][0]-points_xy[j][0])
            y = points_xy[j][1] + alpha * (points_xy[j+1][1]-points_xy[j][1])
            out.append((x,y))
        return out

    @staticmethod
    def _nearest_n(point_xy: tuple[float,float], id_to_xy: dict[int,tuple[float,float]], n:int) -> list[tuple[int,float]]:
        """Return list of (id, distance) for n nearest nodes to the point."""
        items = []
        for aid, (x,y) in id_to_xy.items():
            items.append((aid, math.hypot(point_xy[0]-x, point_xy[1]-y)))
        items.sort(key=lambda t: t[1])
        return items[:max(1,n)]

    @staticmethod
    def _phantom_intensities_2act(d1: float, d2: float, Av: int) -> tuple[int,int]:
        """Eq. (2) from Park et al. (Av in device units 1..15)."""
        d1 = max(d1, 1e-6); d2 = max(d2, 1e-6)
        A1 = math.sqrt(d2/(d1+d2)) * Av
        A2 = math.sqrt(d1/(d1+d2)) * Av
        return (max(1, min(15, round(A1))), max(1, min(15, round(A2))))

    @staticmethod
    def _phantom_intensities_3act(d1: float, d2: float, d3: float, Av: int) -> tuple[int,int,int]:
        """Eq. (10) from Park et al. — energy-based 3‑actuator phantom."""
        d1 = max(d1, 1e-6); d2 = max(d2, 1e-6); d3 = max(d3, 1e-6)
        inv = [1.0/d1, 1.0/d2, 1.0/d3]
        s = sum(inv)
        # Ai = sqrt((1/di)/sum(1/dj)) * Av
        A = [math.sqrt(v/s) * Av for v in inv]
        A = [max(1, min(15, round(a))) for a in A]
        return (A[0], A[1], A[2])

class SavePatternDialog(QDialog):
    """Dialog pour sauvegarder un pattern"""
    
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.current_config = current_config
        self.setWindowTitle("Save Pattern Configuration")
        self.setModal(True)
        self.resize(400, 300)
        
        layout = QVBoxLayout(self)
        
        # Nom du pattern
        form_layout = QFormLayout()
        self.nameEdit = QLineEdit()
        self.nameEdit.setPlaceholderText("Enter pattern name...")
        form_layout.addRow("Pattern Name:", self.nameEdit)
        
        self.descriptionEdit = QTextEdit()
        self.descriptionEdit.setPlaceholderText("Optional description...")
        self.descriptionEdit.setMaximumHeight(80)
        form_layout.addRow("Description:", self.descriptionEdit)
        
        layout.addLayout(form_layout)
        
        # Aperçu de la configuration
        preview_group = QGroupBox("Configuration Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.previewText = QTextEdit()
        self.previewText.setReadOnly(True)
        self.previewText.setMaximumHeight(120)
        self._update_preview()
        preview_layout.addWidget(self.previewText)
        
        layout.addWidget(preview_group)
        
        # Boutons
        button_layout = QHBoxLayout()
        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.clicked.connect(self.reject)
        self.saveButton = QPushButton("Save")
        self.saveButton.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancelButton)
        button_layout.addWidget(self.saveButton)
        layout.addLayout(button_layout)
        
        # Validation
        self.nameEdit.textChanged.connect(self._validate_input)
        self._validate_input()
    
    def _update_preview(self):
        """Mettre à jour l'aperçu de la configuration"""
        config_text = f"Pattern Type: {self.current_config.get('pattern_type', 'N/A')}\n"
        config_text += f"Actuators: {self.current_config.get('actuators', [])}\n"
        config_text += f"Intensity: {self.current_config.get('intensity', 0)}\n"
        config_text += f"Frequency: {self.current_config.get('frequency', 0)}\n"
        wd = self.current_config.get('waveform_duration', None)
        if wd is not None:
            config_text += f"Waveform Duration: {wd:.2f}s\n"
        
        # Waveform info
        waveform_info = self.current_config.get('waveform', {})
        if waveform_info:
            config_text += f"Waveform: {waveform_info.get('name', 'N/A')} ({waveform_info.get('source', 'N/A')})\n"
        
        # Paramètres spécifiques
        specific_params = self.current_config.get('specific_parameters', {})
        if specific_params:
            config_text += "Specific Parameters:\n"
            for key, value in specific_params.items():
                config_text += f"  {key}: {value}\n"
        
        self.previewText.setPlainText(config_text)
    
    def _validate_input(self):
        """Valider l'entrée utilisateur"""
        name = self.nameEdit.text().strip()
        self.saveButton.setEnabled(len(name) > 0)
    
    def get_save_data(self):
        """Récupérer les données de sauvegarde"""
        return {
            'name': self.nameEdit.text().strip(),
            'description': self.descriptionEdit.toPlainText().strip(),
            'timestamp': datetime.now().isoformat(),
            'config': self.current_config
        }

class CompactActuatorSelector(QWidget):
    """Version compacte du sélecteur d'actuateurs pour l'intégration"""
    
    selection_changed = pyqtSignal(list)
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Titre simple
        title_label = QLabel("Select actuators (click to select, right-click to delete)")
        title_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(title_label)
        
        # Créer le sélecteur flexible
        self.selector = FlexibleActuatorSelector()
        self.selector.selection_changed.connect(self.selection_changed.emit)
        self.selector.setMinimumHeight(350)
        layout.addWidget(self.selector)
    
    def get_selected_actuators(self):
        return self.selector.get_selected_actuators()
    
    def load_actuator_configuration(self, actuators):
        """
        Recharge une liste d'IDs sur le canvas.
        - Si le canvas est vide ou insuffisant, on (re)crée une chaîne 0..N-1
          pour couvrir le plus grand ID.
        """
        # Rien à charger → on nettoie juste la sélection
        if not actuators:
            self.selector.select_none()
            try:
                self.selector.canvas.on_actuator_selection_changed()
            except Exception:
                pass
            return

        max_id = max(actuators)
        canvas = self.selector.canvas
        current = getattr(canvas, "actuators", [])

        # Assurer qu'on a au moins max_id+1 actuateurs sur le canvas
        if len(current) <= max_id:
            # Essayer l'API "create_chain" du sélecteur (bouton "Create Chain")
            try:
                # On repart proprement si possible
                if hasattr(self.selector, "clear_canvas"):
                    self.selector.clear_canvas()
                elif hasattr(canvas, "clear"):
                    canvas.clear()

                # Crée une chaîne 0..max_id (type par défaut, ex. LRA)
                self.selector.create_chain(max_id + 1)
                current = getattr(canvas, "actuators", [])
            except Exception:
                # Fallback: ajouter un par un si dispo
                try:
                    needed = (max_id + 1) - len(current)
                    for _ in range(max(0, needed)):
                        if hasattr(canvas, "add_actuator"):
                            # type par défaut
                            canvas.add_actuator("LRA")
                    current = getattr(canvas, "actuators", [])
                except Exception:
                    pass

        # Appliquer la sélection
        try:
            self.selector.select_none()
        except Exception:
            pass

        for a in getattr(canvas, "actuators", []):
            try:
                a.set_selected_state(a.actuator_id in actuators)
            except Exception:
                pass

        try:
            canvas.on_actuator_selection_changed()
        except Exception:
            pass

# Add to imports if missing:
# from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu

class UnifiedPatternLibraryWidget(QWidget):
    """
    Single Pattern Library view with two categories:
      - Pre-made (from PREMADE_PATTERNS)
      - Custom (from PatternLibraryManager)

    Signals (unchanged):
      - template_selected(dict)  → premade preset
      - pattern_selected(dict)   → custom pattern_info
      - pattern_deleted(str)     → emitted after successful delete of a custom pattern

    Changes:
      - Multi-select enabled (ExtendedSelection).
      - Load/Delete buttons removed; use right-click context menu.
      - Double-click loads ALL currently selected items.
    """
    template_selected = pyqtSignal(dict)
    pattern_selected = pyqtSignal(dict)
    pattern_deleted = pyqtSignal(str)

    def __init__(self, pattern_manager, premade_list: list[dict], parent=None):
        super().__init__(parent)
        self.pattern_manager = pattern_manager
        self._premade = list(premade_list)      # [{name, description, config}]
        self._custom_index: dict[str, dict] = {}  # name -> data

        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        ttl = QLabel("Pattern Library")
        ttl.setStyleSheet("font-weight:600;")
        header.addWidget(ttl)
        header.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMaximumWidth(90)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        # Search
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter patterns…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        # Tree (multi-select)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(18)
        self.tree.setObjectName("patternTree")
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.tree, 1)

        # Info (no bottom buttons anymore)
        self.info_label = QLabel("Select a pattern to view details")
        self.info_label.setObjectName("patternDescLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Category roots
        self._premade_root = QTreeWidgetItem(self.tree, ["Pre-made"])
        self._custom_root  = QTreeWidgetItem(self.tree, ["Custom Patterns"])
        self._premade_root.setExpanded(True)
        self._custom_root.setExpanded(True)
        self._style_category_item(self._premade_root)
        self._style_category_item(self._custom_root)

        # Wiring
        self.refresh_button.clicked.connect(self.refresh_patterns)
        self.search.textChanged.connect(self._rebuild_tree)
        self.tree.itemSelectionChanged.connect(self._on_select_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._act_load_selected())
        self.tree.customContextMenuRequested.connect(self._context_menu)

        self.refresh_patterns()

    # ---------- Public API (compat) ----------
    def refresh_patterns(self):
        """Re-scan custom patterns and rebuild the tree."""
        all_custom = self.pattern_manager.get_all_patterns()  # {name: pattern_data}
        self._custom_index = {name: data for name, data in all_custom.items()}
        self._rebuild_tree()

    # ---------- Internals ----------
    def _style_category_item(self, it: QTreeWidgetItem) -> None:
        """Bold, highlighted, non-selectable category row."""
        f = it.font(0); f.setBold(True); it.setFont(0, f)
        flags = it.flags()
        flags &= ~Qt.ItemFlag.ItemIsSelectable
        flags |= Qt.ItemFlag.ItemIsEnabled
        it.setFlags(flags)
        it.setFirstColumnSpanned(True)
        it.setSizeHint(0, QSize(0, 26))
        it.setBackground(0, QBrush(QColor("#EAF2FF")))
        it.setForeground(0, QBrush(QColor("#111827")))

    def _rebuild_tree(self):
        premade_open = self._premade_root.isExpanded()
        custom_open  = self._custom_root.isExpanded()

        self._premade_root.takeChildren()
        self._custom_root.takeChildren()

        query = (self.search.text() or "").strip().lower()

        # Premade
        for p in self._premade:
            name = p.get("name", "Preset")
            if query and query not in name.lower():
                continue
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.ItemDataRole.UserRole, ("premade", p))
            self._premade_root.addChild(it)

        # Custom
        for name, info in sorted(self._custom_index.items()):
            if query and query not in name.lower():
                continue
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.ItemDataRole.UserRole, ("custom", name))
            self._custom_root.addChild(it)

        self._premade_root.setExpanded(premade_open)
        self._custom_root.setExpanded(custom_open)

        total_leaves = self._premade_root.childCount() + self._custom_root.childCount()
        self.info_label.setText("No patterns found" if total_leaves == 0
                                else "Select a pattern to view details")

    def _is_leaf(self, it: QTreeWidgetItem | None) -> bool:
        return bool(it and it.parent() in (self._premade_root, self._custom_root))

    def _payload_for_item(self, it: QTreeWidgetItem):
        return it.data(0, Qt.ItemDataRole.UserRole)  # ("premade", preset) or ("custom", name)

    def _selected_leaves(self):
        out = []
        for it in self.tree.selectedItems():
            if self._is_leaf(it):
                out.append(self._payload_for_item(it))
        return out  # list of tuples

    def _on_select_changed(self):
        sels = self._selected_leaves()
        if len(sels) == 1:
            kind, payload = sels[0]
            if kind == "premade":
                p = payload; cfg = p.get("config", {})
                lines = [
                    f"<b>{p.get('name','Preset')}</b>",
                    f"<i>{p.get('description','')}</i>" if p.get("description") else "",
                    f"<b>Type:</b> {cfg.get('pattern_type','?')}",
                    f"<b>Actuators:</b> {cfg.get('actuators',[])}",
                    f"<b>Intensity:</b> {cfg.get('intensity','')}",
                    f"<b>Frequency:</b> {cfg.get('frequency','')}",
                ]
                wf = cfg.get("waveform", {})
                if wf: lines.append(f"<b>Waveform:</b> {wf.get('name','?')}")
                sp = cfg.get("specific_parameters", {})
                if sp:
                    lines.append("<b>Specific Parameters:</b>")
                    for k, v in sp.items():
                        lines.append(f"&nbsp;&nbsp;{k}: {v}")
                self.info_label.setText("<br>".join([s for s in lines if s]))
            else:  # custom
                name = payload
                info = self.pattern_manager.get_pattern_info(name) or {"config": {}}
                cfg = info.get("config", {})
                lines = [
                    f"<b>{info.get('name', name)}</b>",
                    f"<i>{info.get('description','')}</i>" if info.get("description") else "",
                    f"<b>Type:</b> {cfg.get('pattern_type','?')}",
                    f"<b>Actuators:</b> {cfg.get('actuators',[])}",
                    f"<b>Intensity:</b> {cfg.get('intensity','')}",
                    f"<b>Frequency:</b> {cfg.get('frequency','')}",
                ]
                wf = cfg.get("waveform", {})
                if wf: lines.append(f"<b>Waveform:</b> {wf.get('name','?')}")
                sp = cfg.get("specific_parameters", {})
                if sp:
                    lines.append("<b>Specific Parameters:</b>")
                    for k, v in sp.items():
                        lines.append(f"&nbsp;&nbsp;{k}: {v}")
                if info.get('timestamp'):
                    lines.append(f"<br><small>Created: {info['timestamp']}</small>")
                self.info_label.setText("<br>".join([s for s in lines if s]))
        elif len(sels) > 1:
            # Mixed selection summary
            n_premade = sum(1 for k, _ in sels if k == "premade")
            n_custom  = sum(1 for k, _ in sels if k == "custom")
            self.info_label.setText(f"{len(sels)} patterns selected "
                                    f"({n_premade} pre-made, {n_custom} custom).")
        else:
            self.info_label.setText("Select a pattern to view details")

    # ---------- Actions ----------
    def _act_load_selected(self):
        sels = self._selected_leaves()
        if not sels:
            return
        # Emit load signals for all selected
        for kind, payload in sels:
            if kind == "premade":
                self.template_selected.emit(payload)  # preset dict
            else:
                name = payload
                info = self.pattern_manager.get_pattern_info(name)
                if info:
                    self.pattern_selected.emit(info)

    def _act_delete_selected(self):
        sels = self._selected_leaves()
        # Keep only custom items
        names = [payload for kind, payload in sels if kind == "custom"]
        if not names:
            return
        if QMessageBox.question(
            self, "Delete Patterns", f"Delete {len(names)} custom pattern(s)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        deleted_any = False
        for n in names:
            if self.pattern_manager.delete_pattern(n):
                self.pattern_deleted.emit(n)
                deleted_any = True
        if deleted_any:
            self.refresh_patterns()

    def _context_menu(self, pos):
        sels = self._selected_leaves()
        if not sels:
            # If no selection, try the item under the cursor (single)
            it = self.tree.itemAt(pos)
            if not self._is_leaf(it):
                return
            it.setSelected(True)
            sels = self._selected_leaves()
            if not sels:
                return

        has_custom = any(kind == "custom" for kind, _ in sels)

        menu = QMenu(self)
        act_load = menu.addAction("Load selected")
        if has_custom:
            act_del = menu.addAction("Delete selected (custom only)")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_load:
            self._act_load_selected()
        elif has_custom and chosen.text().startswith("Delete selected"):
            self._act_delete_selected()

class HapticPatternGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Initialize API and patterns
        self.api = python_serial_api()
        self.current_pattern = None
        self.pattern_worker = None
        self.is_running = False
        
        # Initialize library managers
        self.pattern_manager = PatternLibraryManager()
        self.event_manager = EventLibraryManager()
        self.wf_manager = WaveformLibraryManager()
        
        # Current waveform tracking
        self.current_waveform_source = "Built-in Oscillators"
        self.current_waveform_name = "Sine"
        self.current_event = None

        # --- [PHANTOMS] state holders ---
        self.phantom_engine: Optional[PhantomEngine] = None
        self.preview_bundle: Optional[PreviewBundle] = None
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(25)  # used only for device playback timing if needed
        self._device_queue = []  # (at, actuator_id, intensity, duration_ms)
        self._device_start_ms = None
        # Available patterns
        self.patterns = {
            "Single Pulse": SinglePulsePattern(),
            "Wave": WavePattern(),
            "Pulse Train": PulseTrainPattern(),
            "Fade": FadePattern(),
            "Circular": CircularPattern(),
            "Random": RandomPattern(),
            "Sine Wave": SineWavePattern()
        }
        
        # Set API for all patterns
        for pattern in self.patterns.values():
            pattern.set_api(self.api)
        
        self._create_ui()
        self._name_widgets_for_qss()
        self.setup_connection_menu()     # build the Connection menu
        self.setup_waveform_menu()
        self._scan_ports_menu()          # preload menu with ports
        if hasattr(self, "connectionGroup"):
            self.connectionGroup.hide()  # keep widgets for signals, but hide the top bar
        self._connect_signals()
        self.scan_ports()
        self.preview_driver = PatternPreviewDriver(self.canvas_selector, self)
        self._stroke_worker = None
        self._stroke_preview_timer = QTimer(self)
        self._stroke_preview_timer.setInterval(30)  # ~33 FPS
        self._stroke_preview_timer.timeout.connect(self._on_stroke_preview_tick)
        self._stroke_preview_state = None  # dict with schedule, t0, id_to_xy, idx
    
    def _preview_drawn_stroke(self):
        """Construit le même schedule que pour le hardware, mais l'anime en UI uniquement."""
        if self._stroke_preview_timer.isActive():
            self._stroke_preview_timer.stop()
            self.canvas_selector.clear_preview()
            try:
                ov = getattr(self.drawing_tab, "_overlay", None)
                if ov and hasattr(ov, "clear_preview_marker"):
                    ov.clear_preview_marker()
            except Exception:
                pass
            self._log_info("Drawing preview: stopped")
            return

        data = self._get_overlay_json()
        if not data:
            QMessageBox.information(self, "Drawing", "No drawing found. Use the Drawing Studio overlay.")
            return
        poly = self._extract_last_polyline(data)
        if len(poly) < 2:
            QMessageBox.information(self, "Drawing", "Need at least 2 points. Draw a stroke on the overlay.")
            return
        id_to_xy = self._get_actuator_positions_for_overlay(data)
        if not id_to_xy:
            QMessageBox.warning(self, "Nodes", "No actuator anchors available. Use 3×3 Grid or Back Layout.")
            return

        mode = self.strokeModeCombo.currentText()
        step_ms = int(self.strokeStepMs.value())
        Av = int(max(1, min(15, self.intensitySlider.value())))
        total_time_s = float(self.durationSpinBox.value())
        schedule = self._build_stroke_schedule(poly, id_to_xy, step_ms, total_time_s, mode, Av)
        if not schedule:
            QMessageBox.information(self, "Preview", "Failed to build a schedule from the drawing.")
            return

        self._stroke_preview_state = {
            "schedule": schedule,
            "t0": time.perf_counter(),
            "id_to_xy": id_to_xy,
            "idx": -1
        }
        ov = getattr(self.drawing_tab, "_overlay", None)
        if ov:
            ov.setVisible(True)
            ov.raise_()
        self._stroke_preview_timer.start()
        self._log_info(f"Drawing preview: {len(schedule)} steps")
    
    def load_premade_template(self, preset: dict):
        """
        Apply a premade pattern to the Waveform Lab so the existing
        Control section (Preview/Start/Stop/Emergency) can be used.
        """
        try:
            cfg = dict(preset.get("config", {}))

            # 1) Go to Waveform Lab (tab index 0 in this app)
            QTimer.singleShot(0, lambda: self.tab_widget.setCurrentIndex(0))

            # 2) Pattern type first → rebuild specific params UI
            pt = cfg.get("pattern_type", "Single Pulse")
            self.patternComboBox.setCurrentText(pt)
            QApplication.processEvents()
            self._create_pattern_specific_params()

            # 3) Global parameters (these drive both Preview & device playback)
            self.intensitySlider.setValue(int(cfg.get("intensity", self.intensitySlider.value())))
            # Device frequency code lives in Global Parameters in this app
            try:
                self.strokeFreqCode.setValue(int(cfg.get("frequency", self.strokeFreqCode.value())))
            except Exception:
                pass  # in case strokeFreqCode isn't available in your build

            # 4) Waveform suggestion (optional). If the waveform isn't present,
            #    we keep the current selection and just log a note.
            wf = cfg.get("waveform", {})
            if isinstance(wf, dict) and wf.get("name"):
                before = self.waveformComboBox.currentText()
                self._apply_loaded_waveform(wf)
                after = self.waveformComboBox.currentText()
                if before == after and (before or after):
                    self._log_info(f"Premade '{preset['name']}': waveform '{wf.get('name')}' not found, keeping '{after}'")

            # 5) Pattern-specific fields
            sp = cfg.get("specific_parameters", {})
            for key, widget in getattr(self, "pattern_specific_widgets", {}).items():
                if key in sp:
                    try:
                        widget.setValue(sp[key])
                    except Exception:
                        pass

            # 6) Actuators → the MultiCanvasSelector helper auto-creates chains if needed
            acts = list(cfg.get("actuators", []))
            if acts and hasattr(self, "canvas_selector"):
                self.canvas_selector.load_actuator_configuration(acts)

            self._log_info(f"Premade pattern loaded: {preset.get('name', 'Unnamed')}")
            QMessageBox.information(self, "Premade Pattern",
                                    f"Loaded '{preset.get('name','Preset')}'.\n"
                                    f"Use Preview/Start in the Waveform Lab → Control section.")
        except Exception as e:
            self._log_info(f"Error applying premade: {e}")
            QMessageBox.critical(self, "Error", f"Failed to apply premade pattern:\n{e}")
    
    def _create_global_parameters_section(self, layout: QVBoxLayout):
        """
        Global Parameters shared by both Timeline playback and Drawn-stroke phantoms:
        - Intensity (gain)        → self.intensitySlider (+ self.intensityValueLabel)
        - Device freq code (0..7) → self.strokeFreqCode (QSlider) + self.freqCodeValueLabel
        """
        group = QGroupBox("Global Parameters")
        form = QFormLayout(group)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(6)

        # ── Intensity (gain) [0..15]
        self.intensitySlider = QSlider(Qt.Orientation.Horizontal)
        self.intensitySlider.setRange(0, 15)
        self.intensitySlider.setValue(7)

        self.intensityValueLabel = QLabel(str(self.intensitySlider.value()))
        intensityWrap = QWidget()
        iw = QHBoxLayout(intensityWrap)
        iw.setContentsMargins(0, 0, 0, 0)
        iw.addWidget(self.intensitySlider)
        iw.addWidget(self.intensityValueLabel)
        form.addRow("Intensity (gain):", intensityWrap)

        # ── Device frequency code [0..7] — now a slider for consistency
        self.strokeFreqCode = QSlider(Qt.Orientation.Horizontal)
        self.strokeFreqCode.setRange(0, 7)
        self.strokeFreqCode.setSingleStep(1)
        self.strokeFreqCode.setPageStep(1)
        self.strokeFreqCode.setValue(4)
        self.strokeFreqCode.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.strokeFreqCode.setTickInterval(1)
        self.strokeFreqCode.setToolTip(
            "Hardware 'device frequency' index (0..7). Used by Timeline playback and drawn-stroke phantoms."
        )

        self.freqCodeValueLabel = QLabel(str(self.strokeFreqCode.value()))
        self.strokeFreqCode.valueChanged.connect(
            lambda v: self.freqCodeValueLabel.setText(str(v))
        )

        freqWrap = QWidget()
        fw = QHBoxLayout(freqWrap)
        fw.setContentsMargins(0, 0, 0, 0)
        fw.addWidget(self.strokeFreqCode)
        fw.addWidget(self.freqCodeValueLabel)
        form.addRow("Device freq code:", freqWrap)

        layout.addWidget(group)
    
    def _create_timeline_panel(self, parent_layout: QVBoxLayout):
        """Create the timeline panel as a full-width horizontal section."""
        self.timeline_panel = TimelinePanel(self)
        # Reduce minimum height and set fixed height for more compact timeline
        self.timeline_panel.setMinimumHeight(200)
        self.timeline_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)  # Change to Fixed
        
        if hasattr(self, 'canvas_selector'):
            self.timeline_panel.attach_canvas_selector(self.canvas_selector)
        
        parent_layout.addWidget(self.timeline_panel)

    def _on_stroke_preview_tick(self):
        st = self._stroke_preview_state
        if not st:
            self._stroke_preview_timer.stop(); return
        elapsed_ms = (time.perf_counter() - st["t0"]) * 1000.0
        # avancer tant que des steps sont dus
        advanced = False
        while st["idx"] + 1 < len(st["schedule"]) and st["schedule"][st["idx"] + 1]["t_on"] <= elapsed_ms:
            st["idx"] += 1
            advanced = True
        if not advanced:
            return
        # afficher l'état courant
        step = st["schedule"][st["idx"]]
        active_ids = [aid for (aid, _inten) in step["bursts"]]
        try:
            self.canvas_selector.set_preview_active(active_ids)
        except Exception:
            pass
        try:
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "show_preview_marker"):
                ov.show_preview_marker(step.get("pt", (0.5,0.5)), st["id_to_xy"], step["bursts"])
        except Exception:
            pass
        # arrêt si fini
        if st["idx"] >= len(st["schedule"]) - 1:
            self._stroke_preview_timer.stop()
            self._log_info("Drawing preview: done")
    
    def _get_overlay_json(self) -> dict | None:
        """Grab the current overlay JSON from the Drawing Studio tab."""
        try:
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "to_json"):
                return ov.to_json()
        except Exception as e:
            self._log_info(f"Overlay read error: {e}")
        return None


    def _extract_last_polyline(self, data: dict) -> list[tuple[float,float]]:
        """
        Return a list of normalized (x,y) in [0..1] from the most recent stroke.
        Fallback: concatenate all strokes.
        """
        strokes = data.get("strokes", [])
        if not strokes:
            return []
        # pick the last stroke with points
        for s in reversed(strokes):
            pts = s.get("points") or []
            if len(pts) >= 2:
                return [(float(x), float(y)) for (x,y) in pts]
        # fallback: concat everything
        pts_all = []
        for s in strokes:
            pts = s.get("points") or []
            pts_all.extend([(float(x), float(y)) for (x,y) in pts])
        return pts_all


    def _get_actuator_positions_for_overlay(self, overlay_json: dict) -> dict[int, tuple[float,float]]:
        """
        Build id->(x,y) normalized map. Prefer nodes stored with the drawing;
        else use current fixed canvas nodes.
        """
        # 1) nodes serialized by overlay (best)
        nodes = overlay_json.get("nodes") or []
        m = {}
        for n in nodes:
            try:
                m[int(n["id"])] = (float(n["x"]), float(n["y"]))
            except Exception:
                pass
        if m:
            return m

        # 2) current fixed canvas nodes
        try:
            cur = self.canvas_selector.current_nodes() or []
            for (aid, xn, yn) in cur:
                m[int(aid)] = (float(xn), float(yn))
        except Exception:
            pass
        return m


    def _build_stroke_schedule(self, poly_xy: list[tuple[float,float]], id_to_xy: dict[int,tuple[float,float]],
                            duration_ms: int, total_time_s: float, mode: str, Av: int) -> list[dict]:
        """
        Return a list of steps: [{t_on, dur_ms, bursts=[(addr,intensity), ...]}].
        SOA is computed from Eq.(1): SOA_ms = 0.32*duration + 47.3.
        No overlap guaranteed if duration ≤ 69 ms (Eq.(11)).
        """
        if len(poly_xy) < 2 or not id_to_xy:
            return []

        duration_ms = int(max(20, min(69, duration_ms)))
        soa_ms = 0.32 * duration_ms + 47.3  # Eq. (1), ms domain
        n_samples = max(2, int((total_time_s * 1000.0) / soa_ms))
        samples = StrokePlaybackWorker._resample_polyline(poly_xy, n_samples)

        schedule = []
        t = 0.0
        for p in samples:
            neigh   = StrokePlaybackWorker._nearest_n(p, id_to_xy, 3)
            if mode.startswith("Physical"):
                # nearest 1
                addr = neigh[0][0]
                bursts = [(addr, Av)]
            elif "2-Act" in mode:
                (a1,d1),(a2,d2) = neigh[:2]
                A1,A2   = StrokePlaybackWorker._phantom_intensities_2act(d1,d2,Av)
                bursts = [(a1,A1),(a2,A2)]
            else:
                (a1,d1),(a2,d2),(a3,d3) = neigh[:3]
                A1,A2,A3= StrokePlaybackWorker._phantom_intensities_3act(d1,d2,d3,Av)
                bursts = [(a1,A1),(a2,A2),(a3,A3)]

            schedule.append({
                "t_on": t,
                "dur_ms": duration_ms,
                "bursts": bursts,
                "pt": p
            })
            t += soa_ms

        return schedule


    def _play_drawn_stroke(self):
        """Entry point when user clicks 'Play Drawing'."""
        if self.is_running:
            QMessageBox.warning(self, "Busy", "A pattern is currently running. Stop it first.")
            return
        if not self.api or not self.api.connected:
            QMessageBox.warning(self, "Hardware", "Please connect to a device first.")
            return

        data = self._get_overlay_json()
        if not data:
            QMessageBox.information(self, "Drawing", "No drawing found. Use the Drawing Studio overlay.")
            return

        poly = self._extract_last_polyline(data)
        if len(poly) < 2:
            QMessageBox.information(self, "Drawing", "Need at least 2 points. Draw a stroke on the overlay.")
            return

        id_to_xy = self._get_actuator_positions_for_overlay(data)
        if not id_to_xy:
            QMessageBox.warning(self, "Nodes", "No actuator anchors available. Use 3×3 Grid or Back Layout.")
            return

        mode = self.strokeModeCombo.currentText()
        step_ms = int(self.strokeStepMs.value())
        Av = int(max(1, min(15, self.intensitySlider.value())))
        total_time_s = float(self.durationSpinBox.value())
        schedule = self._build_stroke_schedule(poly, id_to_xy, step_ms, total_time_s, mode, Av)
        if not schedule:
            QMessageBox.information(self, "Schedule", "Failed to build a schedule from the drawing.")
            return

        # stop any preview and start worker
        try:
            self.preview_driver.stop()
        except Exception:
            pass

        self._log_info(f"Playing drawn stroke → mode='{mode}', steps={len(schedule)}, step={step_ms}ms, total≈{total_time_s:.2f}s")
        self._stroke_worker = StrokePlaybackWorker(self.api, schedule, self.strokeFreqCode.value())
        self._stroke_worker.log_message.connect(self._log_info)
        self._stroke_worker.finished.connect(self._on_stroke_finished)
        self._stroke_worker.start()
        self._stroke_worker.step_started.connect(self._on_stroke_step_started)
    
    def _on_stroke_step_started(self, idx: int, bursts: list, pt: tuple):
        ov = getattr(self.drawing_tab, "_overlay", None)
        if ov:
            ov.setVisible(True)
            ov.raise_()
        active = [aid for (aid, _i) in bursts]
        try:
            self.canvas_selector.set_preview_active(active)
        except Exception:
            pass
        try:
            ov = getattr(self.drawing_tab, "_overlay", None)
            if ov and hasattr(ov, "show_preview_marker"):
                # id_to_xy vient du dernier build; si besoin, recalculer depuis overlay
                data = self._get_overlay_json() or {}
                id_to_xy = self._get_actuator_positions_for_overlay(data)
                ov.show_preview_marker(pt, id_to_xy, bursts)
        except Exception:
            pass


    def _stop_drawn_stroke(self):
        if self._stroke_worker and self._stroke_worker.isRunning():
            self._stroke_worker.stop()
            self._stroke_worker.wait(1000)
            # ensure everything is off
            try:
                for aid in range(128):
                    self.api.send_command(aid, 0, 0, 0)
            except Exception:
                pass
            try:
                self._stroke_preview_timer.stop()
                self.canvas_selector.clear_preview()
                ov = getattr(self.drawing_tab, "_overlay", None)
                if ov and hasattr(ov, "clear_preview_marker"):
                    ov.clear_preview_marker()
            except Exception:
                pass
            self._log_info("Drawn stroke: stop requested")


    def _on_stroke_finished(self, ok: bool, msg: str):
        self._stroke_worker = None
        # safety: stop selected actuators (same behavior as patterns)
        self._force_stop_selected_actuators()
        self._log_info(f"Drawn stroke finished → {msg}")

    def _name_widgets_for_qss(self):
        # buttons
        self.startButton.setObjectName("startButton")
        self.stopButton.setObjectName("stopButton")
        #self.saveButton.setObjectName("saveButton")
        # info boxes
        self.waveformInfoLabel.setObjectName("waveformInfoLabel")
        self.patternDescLabel.setObjectName("patternDescLabel")

    def setup_waveform_menu(self):
        mb = self.menuBar()
        self.menu_waveform = mb.addMenu("&Waveform")

        self.act_open_designer = QAction("Open Waveform Designer…", self)
        self.act_open_designer.triggered.connect(self._open_waveform_designer)
        self.menu_waveform.addAction(self.act_open_designer)

        self.menu_waveform.addSeparator()

        self.act_refresh_library = QAction("Refresh Library", self)
        self.act_refresh_library.setShortcut("Ctrl+Shift+R")
        self.act_refresh_library.triggered.connect(self.refresh_waveforms)
        self.menu_waveform.addAction(self.act_refresh_library)

    def _open_waveform_designer(self):
        here = os.path.dirname(os.path.abspath(__file__))  # gui/
        pattern_generator = os.path.dirname(here)          # pattern_generator/
        main_gui = os.path.dirname(pattern_generator)      # Main_GUI/

        # We will launch the designer as a MODULE so that relative imports work
        module_path = ["-m", "waveform_designer.event_designer.main"]

        # Prepare process
        self._designer_proc = QProcess(self)
        self._designer_proc.finished.connect(lambda *_: self.refresh_waveforms())

        # 1) Ensure the working directory is Main_GUI so resources/paths resolve
        self._designer_proc.setWorkingDirectory(main_gui)

        # 2) Ensure PYTHONPATH contains Main_GUI (so absolute imports work even from IDE)
        env = self._designer_proc.processEnvironment()
        if env is None:
            from PyQt6.QtCore import QProcessEnvironment
            env = QProcessEnvironment.systemEnvironment()
        existing = env.value("PYTHONPATH", "")
        if existing:
            env.insert("PYTHONPATH", f"{main_gui}{os.pathsep}{existing}")
        else:
            env.insert("PYTHONPATH", main_gui)
        self._designer_proc.setProcessEnvironment(env)

        # Optional: capture logs to your info panel
        try:
            self._designer_proc.readyReadStandardError.connect(
                lambda: self._log_info(self._designer_proc.readAllStandardError().data().decode(errors='ignore'))
            )
            self._designer_proc.readyReadStandardOutput.connect(
                lambda: self._log_info(self._designer_proc.readAllStandardOutput().data().decode(errors='ignore'))
            )
        except Exception:
            pass

        # Start using current Python interpreter and run as module
        self._designer_proc.start(sys.executable, module_path)
        if not self._designer_proc.waitForStarted(3000):
            QMessageBox.critical(self, "Waveform Designer", "Failed to start Universal Event Designer.")
            return

    def setup_connection_menu(self):
        """Build 'Connection' menu and move controls from the top bar into it."""
        self.is_connected = False
        self.selected_port = None
        self._ports_actions = {}
        self.ports_group = QActionGroup(self)
        self.ports_group.setExclusive(True)

        mb = self.menuBar()
        self.menu_connection = mb.addMenu("&Connection")

        # Scan
        self.act_scan = QAction("Scan Ports", self)
        self.act_scan.setShortcut("Ctrl+R")
        self.act_scan.triggered.connect(self._scan_ports_menu)
        self.menu_connection.addAction(self.act_scan)

        # Dynamic Ports submenu
        self.menu_ports = QMenu("Ports", self)
        self.menu_connection.addMenu(self.menu_ports)
        self._refresh_ports_menu([])

        self.menu_connection.addSeparator()

        # Connect / Disconnect
        self.act_connect = QAction("Connect", self)
        self.act_connect.setShortcut("Ctrl+Shift+C")
        self.act_connect.triggered.connect(self._do_connect)
        self.menu_connection.addAction(self.act_connect)

        self.act_disconnect = QAction("Disconnect", self)
        self.act_disconnect.setShortcut("Ctrl+Shift+D")
        self.act_disconnect.triggered.connect(self._do_disconnect)
        self.menu_connection.addAction(self.act_disconnect)

        # Initial state
        self._update_connection_actions()
        # Optional: show status in the status bar (bottom)
        if not self.statusBar():
            self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Status: Disconnected")

    def _scan_ports_menu(self):
        ports = self._scan_available_ports()
        self._refresh_ports_menu(ports)
        # keep legacy combo in sync (even if hidden)
        if hasattr(self, "portComboBox"):
            self.portComboBox.clear()
            self.portComboBox.addItems(ports)
        self.statusBar().showMessage(f"Found {len(ports)} port(s)")
        self._log_info(f"Found {len(ports)} port(s)" if ports else "No ports found")
    
    def setup_view_menu(self):
        mb = self.menuBar()
        self.menu_view = mb.addMenu("&View")

        # Checkable action to show/hide the bottom log
        self.act_show_log = QAction("Show Log", self, checkable=True)
        self.act_show_log.setShortcut("Ctrl+L")
        self.act_show_log.setChecked(True)
        self.act_show_log.toggled.connect(self._set_log_visible)
        self.menu_view.addAction(self.act_show_log)

    def _set_log_visible(self, visible: bool):
        if hasattr(self, "infoGroup"):
            self.infoGroup.setVisible(visible)
        if visible and hasattr(self, "infoTextEdit"):
            from PyQt6.QtGui import QTextCursor
            # Qt6: enums are namespaced
            self.infoTextEdit.moveCursor(QTextCursor.MoveOperation.End)
            self.infoTextEdit.ensureCursorVisible()

    def _refresh_ports_menu(self, ports: list[str]):
        self.menu_ports.clear()
        self._ports_actions.clear()
        for p in ports:
            act = QAction(p, self, checkable=True)
            self.ports_group.addAction(act)
            self.menu_ports.addAction(act)
            act.triggered.connect(lambda checked, port=p: self._select_port(port))
            self._ports_actions[p] = act

        # Keep previous selection if still available; else preselect first
        if ports:
            sel = self.selected_port if self.selected_port in ports else ports[0]
            self._ports_actions[sel].setChecked(True)
            self._select_port(sel)

    def _select_port(self, port: str):
        self.selected_port = port
        self.statusBar().showMessage(f"Port selected: {port}")

    def _do_connect(self):
        # fallback to legacy combo if no menu selection yet
        if not self.selected_port and hasattr(self, "portComboBox"):
            self._select_port(self.portComboBox.currentText() or None)
        if not self.selected_port:
            QMessageBox.information(self, "Connect", "Select a port first.")
            return
        try:
            ok = bool(self.api.connect_serial_device(self.selected_port))
            self.is_connected = ok
        except Exception as e:
            self.is_connected = False
            QMessageBox.warning(self, "Connect", str(e))
        self._update_connection_actions()
        self.statusBar().showMessage(
            f"Status: Connected ({self.selected_port})" if self.is_connected else "Status: Disconnected"
        )
        if hasattr(self, "statusLabel"):
            self.statusLabel.setText("Status: Connected" if self.is_connected else "Status: Disconnected")
        

    def _do_disconnect(self):
        try:
            self.api.disconnect_serial_device()
        except Exception as e:
            QMessageBox.warning(self, "Disconnect", str(e))
        self.is_connected = False
        self._update_connection_actions()
        self.statusBar().showMessage("Status: Disconnected")
        if hasattr(self, "statusLabel"):
            self.statusLabel.setText("Status: Disconnected")

    def _update_connection_actions(self):
        self.act_connect.setEnabled(not self.is_connected)
        self.act_disconnect.setEnabled(self.is_connected)
        self.menu_ports.setEnabled(not self.is_connected)
        self.act_scan.setEnabled(not self.is_connected)

    def _scan_available_ports(self) -> list[str]:
        """Use existing serial API to enumerate ports."""
        try:
            return list(self.api.get_serial_devices())
        except Exception:
            return []
    
    def _create_ui(self):
        """Create the complete UI programmatically"""
        self.setWindowTitle("Haptic Vibration Pattern Controller")
        
        # Rendre la fenêtre redimensionnable et commencer plus petit
        self.setGeometry(100, 100, 1200, 900)
        self.setMinimumSize(1000, 700)  # Taille minimum
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(6)  # Plus d'espace entre sections
        
        # Connection group
        self._create_connection_group(layout)
        
        # Main layout with two columns
        main_layout = QHBoxLayout()
        
        # Left column - Tabbed interface
        self._create_left_column(main_layout)
        
        # Right column - Actuator selection  
        self._create_right_column(main_layout)
        
        # AFTER
        layout.addLayout(main_layout)
        self._create_timeline_panel(layout)

        # No bottom "Information" panel anymore (frees ~80px)

        # Give timeline 1/3 of vertical space: workspace ≈ 66%, timeline ≈ 33%
        layout.setStretch(0, 0)  # connection bar
        layout.setStretch(1, 2)  # main workspace (left + right) - 2/3
        layout.setStretch(2, 1)  # timeline - 1/3

        self.showMaximized()
    
    def _create_connection_group(self, layout):
        """Legacy top bar (now hidden)."""
        self.connectionGroup = QGroupBox("Connection")
        connectionLayout = QHBoxLayout(self.connectionGroup)

        self.scanPortsButton = QPushButton("Scan Ports")
        self.portComboBox = QComboBox()
        self.connectButton = QPushButton("Connect")
        self.disconnectButton = QPushButton("Disconnect")
        self.statusLabel = QLabel("Status: Disconnected")

        connectionLayout.addWidget(self.scanPortsButton)
        connectionLayout.addWidget(self.portComboBox)
        connectionLayout.addWidget(self.connectButton)
        connectionLayout.addWidget(self.disconnectButton)
        connectionLayout.addStretch()
        connectionLayout.addWidget(self.statusLabel)

        layout.addWidget(self.connectionGroup)
    
    def _create_left_column(self, main_layout):
        """Create left column with tabbed interface"""
        leftColumn = QWidget()
        leftColumn.setMaximumWidth(520)
        leftColumnLayout = QVBoxLayout(leftColumn)
        
        # Create tab widget for Waveform Lab and Pattern Library
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ccc;
            }
            QTabBar::tab {
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                border: 1px solid #ccc;
                background-color: #f5f5f5;
            }
            QTabBar::tab:selected {
                background-color: white;
                border-bottom: 1px solid white;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background-color: #eeeeee;
            }
        """)
        
        # Create Waveform Lab tab
        waveform_scroll = QScrollArea()
        waveform_scroll.setWidgetResizable(True)
        waveform_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        waveform_scroll.setFrameShape(QFrame.Shape.NoFrame)

        waveform_page = QWidget()
        waveform_page_layout = QVBoxLayout(waveform_page)
        waveform_page_layout.setContentsMargins(8, 8, 8, 8)
        waveform_page_layout.setSpacing(8)

        self._create_waveform_lab_content(waveform_page_layout)
        waveform_page_layout.addStretch()

        waveform_scroll.setWidget(waveform_page)
        
        # Create Pattern Library tab
        pattern_library_tab = QWidget()
        pattern_library_tab_layout = QVBoxLayout(pattern_library_tab)
        self._create_pattern_library_content(pattern_library_tab_layout)
        
        # Add tabs
        self.tab_widget.addTab(waveform_scroll, "Waveform Lab")
        self.tab_widget.addTab(pattern_library_tab, "Pattern Library")

        self.drawing_tab = DrawingStudioTab()
        self.tab_widget.addTab(self.drawing_tab, "Drawing Studio")

        if hasattr(self, "drawnStrokeGroup") and self.drawnStrokeGroup:
            gb = self.drawnStrokeGroup
            # detach from its old parent/layout
            old_parent = gb.parentWidget()
            if old_parent and old_parent.layout():
                old_parent.layout().removeWidget(gb)
            gb.setParent(self.drawing_tab)
            # append at the bottom of Drawing Studio content
            self.drawing_tab.layout().addWidget(gb)
        centralize_drawn_stroke_playback_in_drawing(self)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.drawing_tab.bind_controls(self)
        
        leftColumnLayout.addWidget(self.tab_widget)
        main_layout.addWidget(leftColumn)


    def _on_tab_changed(self, idx: int):
        try:
            is_drawing = (idx == self.tab_widget.indexOf(self.drawing_tab))
            if hasattr(self.drawing_tab, "set_overlay_active"):
                self.drawing_tab.set_overlay_active(is_drawing)
        except Exception:
            pass

    def _create_headless_frequency_controls(self):
        """Create hidden frequency widgets so existing signal hookups don't break."""
        self.lblFrequency = QLabel("Frequency:")
        self.frequencySlider = QSlider(Qt.Orientation.Horizontal)
        self.frequencySlider.setRange(0, 7)
        self.frequencySlider.setValue(2)
        self.frequencyValueLabel = QLabel("2")
        # keep them hidden; patterns that use waveform data will ignore frequency
        self.lblFrequency.setVisible(False)
        self.frequencySlider.setVisible(False)
        self.frequencyValueLabel.setVisible(False)

    def _create_waveform_lab_content(self, layout):
        # Waveform Selection — keep
        self._create_waveform_selection_section(layout)

        # NEW: Global Parameters shared by Timeline & Phantoms
        self._create_global_parameters_section(layout)

        # These 3 sections exist but are hidden:
        self._create_pattern_selection_section(layout)
        self._create_basic_parameters_section(layout)
        self._create_specific_parameters_section(layout)

        # Drawn stroke, Save, Control — keep
        self._create_drawn_stroke_section(layout)
        #self._create_save_pattern_section(layout)
        self._create_control_section(layout)

        # <<< keep these hidden >>>
        if hasattr(self, "grpPatternSelection"):
            self.grpPatternSelection.setVisible(False)
        if hasattr(self, "grpBasicParameters"):
            self.grpBasicParameters.setVisible(False)
        if hasattr(self, "specificParamsGroup"):
            self.specificParamsGroup.setVisible(False)

        layout.addStretch()

    
    def _create_drawn_stroke_section(self, layout):
        group = QGroupBox("Drawn Stroke Playback")
        group.setObjectName("DrawnStrokePlaybackGroup")
        self.drawnStrokeGroup = group  
        v = QVBoxLayout(group)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(6)

        # Row 1: renderer
        top = QHBoxLayout()
        top.addWidget(QLabel("Renderer:"))
        self.strokeModeCombo = QComboBox()
        self.strokeModeCombo.addItems([
            "Physical (nearest 1)",
            "Phantom (2-Act)",
            "Phantom (3-Act)"
        ])
        self.strokeModeCombo.setCurrentIndex(2)
        # Limiter la largeur du combobox
        self.strokeModeCombo.setMaximumWidth(200)
        top.addWidget(self.strokeModeCombo)
        top.addStretch()
        v.addLayout(top)

        # Row 2: controls avec layout grid pour un meilleur contrôle
        controls_layout = QGridLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setHorizontalSpacing(8)
        controls_layout.setVerticalSpacing(6)

        # Total time applies only to drawn-stroke playback (preview/device)
        self.durationSpinBox = QDoubleSpinBox()
        self.durationSpinBox.setRange(0.1, 600.0)
        self.durationSpinBox.setValue(2.0)
        self.durationSpinBox.setDecimals(2)
        self.durationSpinBox.setSuffix(" s")
        # CORRECTION: Limiter la largeur du spinbox
        self.durationSpinBox.setMaximumWidth(100)
        self.durationSpinBox.setMinimumWidth(80)
        
        controls_layout.addWidget(QLabel("Total time (drawn stroke):"), 0, 0)
        controls_layout.addWidget(self.durationSpinBox, 0, 1)

        # Step duration (≤69 ms) — SOA depends on this; overlap-free if ≤ 69 ms
        self.strokeStepMs = QSpinBox()
        self.strokeStepMs.setRange(20, 69)
        self.strokeStepMs.setValue(60)
        self.strokeStepMs.setSuffix(" ms")
        # CORRECTION: Limiter la largeur du spinbox
        self.strokeStepMs.setMaximumWidth(100)
        self.strokeStepMs.setMinimumWidth(80)
        
        controls_layout.addWidget(QLabel("Step duration (≤69 ms):"), 1, 0)
        controls_layout.addWidget(self.strokeStepMs, 1, 1)

        # Ajouter un stretch à droite pour éviter l'expansion
        controls_layout.setColumnStretch(2, 1)
        
        v.addLayout(controls_layout)

        # Buttons
        btns = QHBoxLayout()
        self.previewDrawingBtn = QPushButton("Preview (no device)")
        btns.addWidget(self.previewDrawingBtn)
        self.playDrawingBtn = QPushButton("Play Drawing")
        self.stopDrawingBtn = QPushButton("Stop")
        btns.addWidget(self.playDrawingBtn)
        btns.addWidget(self.stopDrawingBtn)
        btns.addStretch()
        v.addLayout(btns)

        layout.addWidget(group)

    def _create_pattern_library_content(self, layout):
        """Single Pattern Library with two categories (Pre-made / Custom)."""
        self.pattern_visualization = UnifiedPatternLibraryWidget(self.pattern_manager, PREMADE_PATTERNS)
        # Wire like before (no behavior change)
        self.pattern_visualization.template_selected.connect(self.load_premade_template)
        self.pattern_visualization.pattern_selected.connect(self.load_pattern_from_library)
        self.pattern_visualization.pattern_deleted.connect(self.on_pattern_deleted)
        layout.addWidget(self.pattern_visualization)
    
    def _create_waveform_selection_section(self, layout):
        group = QGroupBox("Waveform Selection")
        v = QVBoxLayout(group); v.setSpacing(5); v.setContentsMargins(8, 5, 8, 5)

        # Top row: Refresh / New…
        row = QHBoxLayout(); row.setSpacing(6)
        title = QLabel("Waveform Library"); title.setStyleSheet("font-weight:600;")
        row.addWidget(title); row.addStretch()
        self.refreshWaveformsButton = QPushButton("Refresh"); self.refreshWaveformsButton.setMaximumWidth(70)
        row.addWidget(self.refreshWaveformsButton)
        self.newWaveformButton = QPushButton("New…"); self.newWaveformButton.setMaximumWidth(70)
        self.newWaveformButton.clicked.connect(self._open_waveform_designer)
        row.addWidget(self.newWaveformButton)
        v.addLayout(row)

        # Waveform picker
        pick = QHBoxLayout(); pick.setSpacing(6)
        pick.addWidget(QLabel("Waveform:"))
        self.waveformComboBox = QComboBox()
        pick.addWidget(self.waveformComboBox)
        v.addLayout(pick)

        # Info
        self.waveformInfoLabel = QLabel("Select a waveform from the library")
        self.waveformInfoLabel.setWordWrap(True)
        self.waveformInfoLabel.setStyleSheet(
            "padding:4px;border:1px solid #ddd;border-radius:3px;"
            "background:#f9f9f9;font-style:italic;font-size:10px;"
        )
        self.waveformInfoLabel.setMaximumHeight(40)
        v.addWidget(self.waveformInfoLabel)

        layout.addWidget(group)
    
    def _create_pattern_selection_section(self, layout):
        """Create pattern selection - COMPACT"""
        patternGroup = QGroupBox("Pattern Selection")
        self.grpPatternSelection = patternGroup
        patternLayout = QVBoxLayout(patternGroup)
        patternLayout.setSpacing(3)
        patternLayout.setContentsMargins(8, 5, 8, 5)
        
        self.patternComboBox = QComboBox()
        self.patternComboBox.addItems([
            "Single Pulse", "Wave", "Pulse Train", "Fade", 
            "Circular", "Random", "Sine Wave"
        ])
        patternLayout.addWidget(self.patternComboBox)
        
        self.patternDescLabel = QLabel("Single vibration pulse on selected actuators")
        self.patternDescLabel.setWordWrap(True)
        self.patternDescLabel.setStyleSheet("font-style: italic; padding: 2px; color: #666; font-size: 10px;")
        self.patternDescLabel.setMaximumHeight(25)  # Plus petit
        patternLayout.addWidget(self.patternDescLabel)
        
        layout.addWidget(patternGroup)
    
    def _create_basic_parameters_section(self, layout):
        """
        Minimal 'Basic Parameters' (kept hidden). We NO LONGER create intensity here.
        We keep Duration here for legacy patterns, and create headless frequency
        widgets to satisfy existing signal hookups without showing them.
        """
        group = QGroupBox("Basic Parameters")
        self.grpBasicParameters = group
        g = QGridLayout(group)
        g.setSpacing(4)
        g.setContentsMargins(8, 5, 8, 5)

        # Duration (legacy/placeholder; waveform-driven patterns may ignore it)
        g.addWidget(QLabel("Duration:"), 0, 0)
        self.durationSpinBox = QDoubleSpinBox()
        self.durationSpinBox.setRange(0.1, 600.0)
        self.durationSpinBox.setValue(2.0)
        self.durationSpinBox.setDecimals(2)
        self.durationSpinBox.setSuffix(" s")
        g.addWidget(self.durationSpinBox, 0, 1, 1, 2)

        layout.addWidget(group)

        # Create hidden 'legacy' frequency widgets so existing code paths stay safe.
        self._create_headless_frequency_controls()
    
    def _create_specific_parameters_section(self, layout):
        """Create the Pattern-Specific Parameters section (auto-size)."""
        self.specificParamsGroup = QGroupBox("Pattern-Specific Parameters")

        # Let the group grow/shrink as needed (no fixed max height)
        self.specificParamsGroup.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )

        # Prepare an inner container layout once; we'll repopulate its contents later
        container = QVBoxLayout(self.specificParamsGroup)
        container.setContentsMargins(8, 6, 8, 6)
        container.setSpacing(6)

        # Keep handle to the container so we can clear & refill it
        self._specific_params_container = container
        self.pattern_specific_widgets = {}

        # First build based on the current pattern
        self._create_pattern_specific_params()

        layout.addWidget(self.specificParamsGroup)
    
    # def _create_save_pattern_section(self, layout):
    #     """Create save pattern section - COMPACT"""
    #     saveGroup = QGroupBox("Save Pattern")
    #     saveLayout = QVBoxLayout(saveGroup)
    #     saveLayout.setContentsMargins(8, 5, 8, 5)
        
    #     self.saveButton = QPushButton("Save Current Pattern")
    #     saveLayout.addWidget(self.saveButton)
        
    #     layout.addWidget(saveGroup)
    
    def _create_control_section(self, layout):
        """Create control section - COMPACT"""
        controlGroup = QGroupBox("Control")
        controlLayout = QVBoxLayout(controlGroup)
        controlLayout.setSpacing(5)
        controlLayout.setContentsMargins(8, 5, 8, 5)
        
        # Start/Stop buttons - ligne compacte
        buttonLayout = QHBoxLayout()
        buttonLayout.setSpacing(5)
        
        self.startButton = QPushButton("Start")
        self.stopButton = QPushButton("Pause")
        self.previewButton = QPushButton("Preview")
        self.previewButton.setCheckable(True)
        buttonLayout.addWidget(self.previewButton)
        
        buttonLayout.addWidget(self.startButton)
        buttonLayout.addWidget(self.stopButton)
        controlLayout.addLayout(buttonLayout)
        
        layout.addWidget(controlGroup)
    
    def _create_pattern_library_section(self, layout):
        """Create pattern library section"""
        # No group box here since it's already in a tab
        self.pattern_visualization = PatternVisualizationWidget(self.pattern_manager)
        self.pattern_visualization.pattern_selected.connect(self.load_pattern_from_library)
        self.pattern_visualization.pattern_deleted.connect(self.on_pattern_deleted)
        layout.addWidget(self.pattern_visualization)
    
    def _create_right_column(self, main_layout):
        """Create right column with actuator selection"""
        rightColumn = QWidget()
        rightColumnLayout = QVBoxLayout(rightColumn)
        rightColumnLayout.setContentsMargins(0, 0, 0, 0)
        rightColumnLayout.setSpacing(6)

        actuatorGroup = QGroupBox("Actuator Selection & Design")
        actuatorGroup.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        actuatorLayout = QVBoxLayout(actuatorGroup)
        actuatorLayout.setContentsMargins(6, 0, 6, 6)   # was default (bigger on some styles)
        actuatorLayout.setSpacing(6)

        self.canvas_selector = MultiCanvasSelector()
        self.canvas_selector.selection_changed.connect(self.on_actuator_selection_changed)
        self.canvas_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        actuatorLayout.addWidget(self.canvas_selector, 1)

        try:
            if hasattr(self, "drawing_tab") and self.drawing_tab is not None:
                self.drawing_tab.attach_canvas_selector(self.canvas_selector)
        except Exception:
            pass

        rightColumnLayout.addWidget(actuatorGroup, 1)
        main_layout.addWidget(rightColumn, 1)
    
    def _create_info_section(self, layout):
        """Create info section - ALWAYS VISIBLE but compact"""
        self.infoGroup = QGroupBox("Information")        
        self.infoGroup.setFixedHeight(80)
        infoLayout = QVBoxLayout(self.infoGroup)
        infoLayout.setContentsMargins(5, 5, 5, 5)

        self.infoTextEdit = QTextEdit()
        self.infoTextEdit.setReadOnly(True)
        self.infoTextEdit.setStyleSheet(
            "QTextEdit { "
            "font-family: 'Consolas', 'Monaco', monospace; "
            "font-size: 10px; "
            "padding: 5px; "
            "border: 1px solid #999; "
            "background-color: #f8f8f8; "
            "line-height: 1.2; "
            "}"
        )
        infoLayout.addWidget(self.infoTextEdit)

        layout.addWidget(self.infoGroup)
    
    def _connect_signals(self):
        """Connect signals to slots"""
        # Connection buttons
        self.scanPortsButton.clicked.connect(self._scan_ports_menu)
        self.connectButton.clicked.connect(self._do_connect)
        self.disconnectButton.clicked.connect(self._do_disconnect)
        self.previewButton.toggled.connect(self._on_preview_toggled)
        self.previewDrawingBtn.clicked.connect(self._preview_drawn_stroke)

        
        # Waveform controls
        self.waveformComboBox.currentTextChanged.connect(self.on_waveform_changed)
        self.refreshWaveformsButton.clicked.connect(self.refresh_waveforms)
        
        # Pattern controls
        self.patternComboBox.currentTextChanged.connect(self._on_pattern_change)
        
        # Basic parameter sliders
        self.intensitySlider.valueChanged.connect(
            lambda v: self.intensityValueLabel.setText(str(v))
        )
        self.frequencySlider.valueChanged.connect(
            lambda v: self.frequencyValueLabel.setText(str(v))
        )
        
        # Control buttons
        self.startButton.clicked.connect(self.start_pattern)
        self.stopButton.clicked.connect(self.stop_pattern)
        #self.saveButton.clicked.connect(self.save_pattern)
        
        # Initialize waveform controls
        self.refresh_waveforms()
        self.update_waveform_info()

        self.playDrawingBtn.clicked.connect(self._play_drawn_stroke)
        self.stopDrawingBtn.clicked.connect(self._stop_drawn_stroke)
    
    def refresh_waveforms(self):
        self.waveformComboBox.clear()
        self._wf_entries = self.wf_manager.list_entries()
        self._wf_by_display = {e["display"]: e for e in self._wf_entries}
        if self._wf_entries:
            self.waveformComboBox.addItems([e["display"] for e in self._wf_entries])
            self._log_info(f"Waveform Library → {self.wf_manager.lib_root}/customized "
                        f"→ {len(self._wf_entries)} file(s)")
        else:
            self.waveformComboBox.addItem("No waveforms found")
            self._log_info(f"Waveform Library → {self.wf_manager.lib_root}/customized → 0 file")
        if self.waveformComboBox.count() > 0:
            self.update_waveform_info()
        
    def _on_preview_toggled(self, checked: bool):
        if checked:
            actuators = self._get_selected_actuators()
            if not actuators:
                QMessageBox.warning(self, "Preview", "Please select at least one actuator")
                self.previewButton.setChecked(False)
                return
            
            wf = self.current_event
            wf_duration = 0.0
            try:
                wf_duration = float(wf.waveform_data.duration or 0.0) if (wf and wf.waveform_data) else 0.0
            except Exception:
                wf_duration = 0.0

            params = {
                'actuators': actuators,
                'intensity': self.intensitySlider.value(),
                'frequency': self.frequencySlider.value(),  # ignored by waveform-driven patterns
                'duration': wf_duration if wf_duration > 0 else 2.0,  # fall back just in case
                'playback_rate': 1.0,
                'repeat': 1,
                'start_offset': 0.0,
            }

            for name, w in self.pattern_specific_widgets.items():
                params[name] = w.value()
            self.preview_driver.stop()
            self.preview_driver.start(self.patternComboBox.currentText(), params)
            self._log_info("Preview started (UI-only)")
            self.previewButton.setText("Stop Preview")
        else:
            self.preview_driver.stop()
            self._log_info("Preview stopped")
            self.previewButton.setText("Preview")
    
    def on_waveform_source_changed(self):
        self.current_waveform_source = self.waveformSourceComboBox.currentText()
        self.refresh_waveforms()
        self._log_info(f"Waveform source: {self.current_waveform_source}")

    def on_waveform_changed(self):
        self.current_waveform_name = self.waveformComboBox.currentText()
        self.update_waveform_info()
        self._log_info(f"Waveform: {self.current_waveform_name}")
        
    def update_waveform_info(self):
        name = self.waveformComboBox.currentText()
        if not self._wf_entries or name == "No waveforms found":
            self.waveformInfoLabel.setText("No waveforms available.")
            self.current_event = None
            return
        entry = self._wf_by_display.get(name)
        ev = self.wf_manager.load_event(entry) if entry else None
        self.current_event = ev
        if ev and ev.waveform_data:
            dur = ev.waveform_data.duration or 0.0
            sr  = ev.waveform_data.sample_rate or 0.0
            md  = ev.metadata.name if ev.metadata else entry["name"]
            self.waveformInfoLabel.setText(f"<b>{md}</b><br>Duration: {dur:.2f}s • Sample Rate: {sr:g}Hz")
            # (removed) offsetSpinBox.setMaximum(...)
        else:
            self.waveformInfoLabel.setText("Failed to load waveform.")
    
    def get_current_waveform_info(self):
        return {"source": "Waveform Library", "name": self.waveformComboBox.currentText(), "event": self.current_event}
    
    def _create_pattern_specific_params(self):
        """(Re)build the content of the Pattern-Specific Parameters panel."""
        # Clear previous widgets from the container
        container = getattr(self, "_specific_params_container", None)
        if container is None:
            return
        self._clear_layout(container)

        pattern_name = self.patternComboBox.currentText()
        self.pattern_specific_widgets = {}

        pattern_config = PATTERN_PARAMETERS.get(pattern_name, {})
        parameters = pattern_config.get("parameters", [])

        if not parameters:
            # Show a small hint instead of an empty box
            hint = QLabel("No additional parameters for this pattern.")
            hint.setStyleSheet("font-style: italic; color: #666;")
            container.addWidget(hint)
        else:
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(8)

            for param in parameters:
                label = QLabel(param["label"])
                label.setToolTip(param.get("description", ""))

                if param["type"] == "float":
                    editor = QDoubleSpinBox()
                    editor.setRange(*param["range"])
                    editor.setSingleStep(param["step"])
                    editor.setValue(param["default"])
                    if param.get("suffix"):
                        editor.setSuffix(param["suffix"])
                else:  # "int"
                    editor = QSpinBox()
                    editor.setRange(*param["range"])
                    editor.setSingleStep(param["step"])
                    editor.setValue(param["default"])
                    if param.get("suffix"):
                        editor.setSuffix(param["suffix"])

                editor.setToolTip(param.get("description", ""))
                form.addRow(label, editor)
                self.pattern_specific_widgets[param["name"]] = editor

            container.addLayout(form)

        # Make sure geometry updates immediately
        self.specificParamsGroup.adjustSize()
        self.specificParamsGroup.updateGeometry()
    
    def _clear_layout(self, layout):
        """Clear all widgets from layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
    
    def _on_pattern_change(self):
        """Handle pattern selection change"""
        pattern_name = self.patternComboBox.currentText()
        if pattern_name in self.patterns:
            self.patternDescLabel.setText(self.patterns[pattern_name].description)
        self._create_pattern_specific_params()
    
    def scan_ports(self):
        """Scan for available serial ports"""
        try:
            ports = self.api.get_serial_devices()
            self.portComboBox.clear()
            self.portComboBox.addItems(ports)
            self._log_info(f"Found {len(ports)} ports" if ports else "No ports found")
        except Exception as e:
            self._log_info(f"Error scanning ports: {e}")
    
    def connect(self):
        """Connect to selected serial port"""
        port = self.portComboBox.currentText()
        if not port:
            QMessageBox.warning(self, "Error", "Please select a port")
            return
        
        try:
            success = self.api.connect_serial_device(port)
            status = "Connected" if success else "Connection Failed"
            self.statusLabel.setText(f"Status: {status}")
            self._log_info(f"{'Connected to' if success else 'Failed to connect to'} {port}")
        except Exception as e:
            self.statusLabel.setText("Status: Connection Error")
            self._log_info(f"Connection error: {e}")
    
    def disconnect(self):
        """Disconnect from serial port"""
        try:
            if self.api.disconnect_serial_device():
                self.statusLabel.setText("Status: Disconnected")
                self._log_info("Disconnected")
        except Exception as e:
            self._log_info(f"Disconnect error: {e}")
    
    def save_pattern(self):
        """Save current configuration into the pattern library"""
        actuators = self._get_selected_actuators()
        if not actuators:
            QMessageBox.warning(self, "Warning", "Please select at least one actuator before saving.")
            return

        waveform_info = self.get_current_waveform_info()

        current_config = {
            'pattern_type': self.patternComboBox.currentText(),
            'actuators': actuators,
            'intensity': self.intensitySlider.value(),
            'frequency': self.frequencySlider.value(),
            # no 'duration' — waveform is the source of truth
            'waveform': {
                'source': wf_info['source'],
                'name': wf_info['name']
            },
            'waveform_duration': wf_dur if wf_dur > 0 else None,
            'specific_parameters': {}
        }

        for param_name, widget in self.pattern_specific_widgets.items():
            current_config['specific_parameters'][param_name] = widget.value()

        dialog = SavePatternDialog(current_config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            save_data = dialog.get_save_data()
            pattern_name = save_data['name']
            existing = self.pattern_manager.get_all_patterns()
            if pattern_name in existing:
                reply = QMessageBox.question(
                    self, "Overwrite Pattern",
                    f"Pattern '{pattern_name}' already exists in the library. Overwrite?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            if self.pattern_manager.save_pattern(pattern_name, save_data):
                self.pattern_visualization.refresh_patterns()
                self._log_info(f"Pattern '{pattern_name}' saved to pattern library")
                QMessageBox.information(self, "Success", f"Pattern '{pattern_name}' saved to pattern library!")
            else:
                QMessageBox.critical(self, "Error", "Failed to save pattern to library.")

    def _apply_loaded_waveform(self, waveform_info: dict | None):
        """Select a waveform from the library; robust if file naming differs."""
        if not waveform_info:
            return
        name = str(waveform_info.get("name", "")).strip()
        # We only have Waveform Library now.
        self.refresh_waveforms()  # repopulates self.waveformComboBox & self._wf_by_display

        # Try exact display text first
        idx = self.waveformComboBox.findText(name)
        # If saved name was a base name (without bucket suffix), try to match by base
        if idx < 0 and hasattr(self, "_wf_by_display"):
            base = name.split(" [", 1)[0]
            for display in self._wf_by_display.keys():
                if display.split(" [", 1)[0] == base:
                    idx = self.waveformComboBox.findText(display)
                    if idx >= 0:
                        break

        if idx >= 0:
            self.waveformComboBox.setCurrentIndex(idx)
            self.update_waveform_info()
        else:
            self._log_info(f"Waveform '{name}' not found in library.")


    def _set_rate_combo(self, rate_value: float):
        """Helper to restore playback rate on a QComboBox if you have one."""
        try:
            # try by userData first
            for i in range(self.rateCombo.count()):
                data = self.rateCombo.itemData(i)
                if isinstance(data, (int, float)) and abs(float(data) - float(rate_value)) < 1e-6:
                    self.rateCombo.setCurrentIndex(i)
                    return
            # fallback: match by text like "1.00x"
            txt = f"{float(rate_value):.2f}x"
            ix = self.rateCombo.findText(txt)
            if ix >= 0:
                self.rateCombo.setCurrentIndex(ix)
        except Exception:
            pass


    def load_pattern_from_library(self, pattern_info):
        try:
            config = pattern_info["config"]
            if config.get("pattern_type") == "Timeline":
                try:
                    # switch left column visible and ensure Designer page
                    if hasattr(self, "timeline_panel") and self.timeline_panel:
                        self.timeline_panel.load_from_config(config)
                    if hasattr(self, "canvas_selector"):
                        self.canvas_selector.canvasCombo.setCurrentIndex(0)  # Designer
                    self._log_info(f"Timeline '{pattern_info['name']}' loaded")
                    QMessageBox.information(self, "Timeline", f"Timeline '{pattern_info['name']}' loaded.")
                    return
                except Exception as e:
                    self._log_info(f"Timeline load error: {e}")
                    QMessageBox.critical(self, "Error", f"Failed to load timeline: {e}")
                    return
            QTimer.singleShot(0, lambda: self.tab_widget.setCurrentIndex(0))

            # 1) Pattern type first
            self.patternComboBox.setCurrentText(config.get("pattern_type", "Single Pulse"))
            QApplication.processEvents()
            self._create_pattern_specific_params()

            # 2) Basic parameters
            self.intensitySlider.setValue(int(config.get("intensity", 7)))
            self.durationSpinBox.setValue(float(config.get("duration", 2.0)))
            if hasattr(self, "frequencySlider"):
                self.frequencySlider.setValue(int(config.get("frequency", 0)))

            # 3) Waveform from library
            self._apply_loaded_waveform(config.get("waveform", {}))

            # 4) Pattern-specific params
            sp = config.get("specific_parameters", {})
            for key, widget in getattr(self, "pattern_specific_widgets", {}).items():
                if key in sp:
                    try:
                        widget.setValue(sp[key])
                    except Exception:
                        pass

            # (removed) restore playbackRateSpinBox/repeatSpinBox/offsetSpinBox — section deleted

            # 6) Actuators
            if "actuators" in config and hasattr(self, "canvas_selector"):
                self.canvas_selector.load_actuator_configuration(config.get("actuators", []))

            self._log_info(f"Pattern '{pattern_info['name']}' loaded from library")
            QMessageBox.information(self, "Success",
                                    f"Pattern '{pattern_info['name']}' loaded successfully!")
        except Exception as e:
            self._log_info(f"Error loading pattern: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load pattern: {e}")
    
    def on_pattern_deleted(self, pattern_name):
        """Appelé quand un pattern est supprimé de la bibliothèque"""
        self._log_info(f"Pattern '{pattern_name}' deleted from library")
    
    def on_actuator_selection_changed(self, selected_ids):
        """Appelé quand la sélection d'actuateurs change"""
        if selected_ids:
            self._log_info(f"Selected actuators: {selected_ids}")
        else:
            self._log_info("No actuators selected")
    
    def _get_selected_actuators(self):
        """Return the list of selected actuators from the current canvas."""
        return self.canvas_selector.get_selected_actuators()
    
    def start_pattern(self):
        """Start the selected pattern"""
        if self.is_running:
            QMessageBox.warning(self, "Warning", "Pattern is already running")
            return
        if not self.api.connected:
            QMessageBox.warning(self, "Error", "Please connect to a device first")
            return

        actuators = self._get_selected_actuators()
        if not actuators:
            QMessageBox.warning(self, "Error", "Please select at least one actuator")
            return

        pattern_name = self.patternComboBox.currentText()
        if pattern_name not in self.patterns:
            QMessageBox.warning(self, "Error", "Invalid pattern selected")
            return

        waveform_info = self.get_current_waveform_info()
        if waveform_info['source'] == 'Waveform Library' and not waveform_info['event']:
            QMessageBox.warning(self, "Waveform", "Please select a waveform from the library.")
            return


        base_intensity = self.intensitySlider.value()
        base_frequency = self.frequencySlider.value()

        if waveform_info['source'] == 'Built-in Oscillators':
            intensity, frequency = self._apply_builtin_waveform_modulation(
                waveform_info['name'], base_intensity, base_frequency
            )
        else:
            intensity, frequency = base_intensity, base_frequency

        # Duration comes from the selected waveform if available
        wf_duration = 0.0
        if waveform_info['source'] == 'Waveform Library' and waveform_info['event'] and getattr(waveform_info['event'], 'waveform_data', None):
            try:
                wf_duration = float(waveform_info['event'].waveform_data.duration or 0.0)
            except Exception:
                wf_duration = 0.0

        params = {
            'actuators': actuators,
            'intensity': intensity,         # keep intensity
            'frequency': frequency,         # patterns using waveform_data may ignore this
            'duration': wf_duration if wf_duration > 0 else 2.0,
            'playback_rate': 1.0,
            'repeat': 1,
            'start_offset': 0.0,
        }
        for param_name, widget in self.pattern_specific_widgets.items():
            params[param_name] = widget.value()

        self.current_pattern = self.patterns[pattern_name]
        if waveform_info['source'] == 'Waveform Library' and waveform_info['event']:
            if hasattr(self.current_pattern, 'set_waveform_data'):
                self.current_pattern.set_waveform_data(waveform_info['event'])
        else:
            # Clear previous waveform if pattern supports it (avoid stale state)
            if hasattr(self.current_pattern, 'set_waveform_data'):
                self.current_pattern.set_waveform_data(None)

        self.current_pattern.stop_flag = False
        self.is_running = True

        self.pattern_worker = PatternWorker(self.current_pattern, params)
        self.pattern_worker.finished.connect(self._on_pattern_finished)
        self.pattern_worker.log_message.connect(self._log_info)
        self.pattern_worker.start()

        try:
            self.preview_driver.stop()
            self.preview_driver.start(pattern_name, params)
        except Exception:
            pass

        waveform_desc = f" with {waveform_info['name']} waveform" if waveform_info['name'] else ""
        self._log_info(f"Started {pattern_name} pattern{waveform_desc} on actuators {actuators} (I:{intensity}, F:{frequency})")
    
    def _apply_builtin_waveform_modulation(self, waveform_name, base_intensity, base_frequency):
        """Apply waveform-specific modifications to basic parameters"""
        
        # Different waveforms can modify intensity and frequency differently
        waveform_modifications = {
            "Sine": (base_intensity, base_frequency),
            "Square": (min(15, base_intensity + 2), base_frequency),
            "Saw": (base_intensity, min(7, base_frequency + 1)),
            "Triangle": (max(1, base_intensity - 1), base_frequency),
            "Chirp": (base_intensity, min(7, base_frequency + 2)),
            "FM": (base_intensity, max(0, base_frequency - 1)),
            "PWM": (min(15, base_intensity + 1), base_frequency),
            "Noise": (max(1, min(15, base_intensity + random.randint(-2, 2))), 
                     max(0, min(7, base_frequency + random.randint(-1, 1))))
        }
        
        intensity, frequency = waveform_modifications.get(waveform_name, (base_intensity, base_frequency))
        
        self._log_info(f"Waveform '{waveform_name}' modified parameters: {base_intensity}->{intensity}, {base_frequency}->{frequency}")
        
        return intensity, frequency
    
    def stop_pattern(self):
        """Stop the current pattern"""
        self._stop_drawn_stroke()
        if self.current_pattern:
            self.current_pattern.stop()
            self._log_info("Pattern stop requested")
        
        if self.pattern_worker and self.pattern_worker.isRunning():
            self.pattern_worker.wait(1000)
        try:
            self.preview_driver.stop()
        except Exception:
            pass
        self._force_stop_selected_actuators()
        self.is_running = False
        self._log_info("Pattern stopped")
        
    
    def _force_stop_selected_actuators(self):
        """Force stop all selected actuators"""
        try:
            actuators = self._get_selected_actuators()
            if actuators:
                for addr in actuators:
                    self.api.send_command(addr, 0, 0, 0)
                self._log_info(f"Force stopped actuators: {actuators}")
        except Exception as e:
            self._log_info(f"Error force stopping actuators: {e}")
    
    def emergency_stop(self):
        """Emergency stop - stops pattern and all actuators"""
        self._stop_drawn_stroke()
        self.stop_pattern()
        try:
            for i in range(128):
                self.api.send_command(i, 0, 0, 0)
            self._log_info("Emergency stop executed - all actuators (0-127) stopped")
        except Exception as e:
            self._log_info(f"Emergency stop error: {e}")
    
    def _on_pattern_finished(self, success, message):
        """Handle pattern completion"""
        self._force_stop_selected_actuators()
        self.is_running = False
        self._log_info("Pattern completed")
    
    def closeEvent(self, event):
        """Handle window closing"""
        self.emergency_stop()
        if self.api.connected:
            self.api.disconnect_serial_device()
        try:
            if hasattr(self, "timeline_panel") and self.timeline_panel:
                self.timeline_panel.stop_all()
        except Exception:
            pass
        event.accept()
    
    def _log_info(self, message):
        """Lightweight logger: status bar + stdout (text panel may not exist)."""
        timestamp = time.strftime('%H:%M:%S')
        log_message = f"{timestamp} - {message}"

        # Show brief status
        try:
            if not self.statusBar():
                self.setStatusBar(QStatusBar(self))
            self.statusBar().showMessage(message, 4000)
        except Exception:
            pass

        # Only append if the panel exists
        if hasattr(self, "infoTextEdit") and self.infoTextEdit is not None:
            self.infoTextEdit.append(log_message)

        print(log_message)

def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))

    # High DPI scaling policy (PyQt6 handles scaling automatically)
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Palette claire pour éviter les champs foncés qui mangent le texte
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,       QColor("#F6F7F9"))
    pal.setColor(QPalette.ColorRole.Base,         QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase,QColor("#F3F4F6"))
    pal.setColor(QPalette.ColorRole.Text,         QColor("#111827"))
    pal.setColor(QPalette.ColorRole.WindowText,   QColor("#111827"))
    pal.setColor(QPalette.ColorRole.Button,       QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText,   QColor("#111827"))
    pal.setColor(QPalette.ColorRole.ToolTipBase,  QColor("#111827"))
    pal.setColor(QPalette.ColorRole.ToolTipText,  QColor("#F9FAFB"))
    pal.setColor(QPalette.ColorRole.Highlight,    QColor("#3B82F6"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)

    # Charger la feuille de style
    qss_path = os.path.join(os.path.dirname(__file__), "haptic_pro.qss")
    if os.path.exists(qss_path):
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = HapticPatternGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
