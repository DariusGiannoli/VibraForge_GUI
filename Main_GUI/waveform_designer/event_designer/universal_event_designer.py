# universal_event_designer.py
"""
Universal Waveform Designer - Ultra Clean Professional Interface
- Waveform Library (Oscillators / Customized / Imported) with drag & drop
- Context menu Delete on Customized/Imported
- CSV import in Waveform Design (plus .haptic)
- Drop proxy over the editor to compose by multiplication
- Safe math generator and utilities
"""

import sys, os, time, json, ast, shutil
from math import gcd
import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal, QFileSystemWatcher, QTimer, QByteArray, QMimeData
from PyQt6.QtGui import QAction, QActionGroup, QPalette, QColor, QDrag
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox, QLabel, QLineEdit,
    QTextEdit, QComboBox, QPushButton, QFileDialog, QMessageBox, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QGridLayout, QDoubleSpinBox, QMenu, QWidgetAction,
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QScrollArea  # ← added QScrollArea
)
from PyQt6.QtWidgets import QToolButton, QSizePolicy, QFrame

# ---------- Optional SciPy ----------
try:
    from scipy import signal as _sig
    from scipy.signal import resample_poly as _resample_poly
except Exception:
    _sig = None
    _resample_poly = None

# ---------- MIME ----------
MIME_WAVEFORM = "application/x-waveform"

# ---------- utils ----------
def common_time_grid(duration: float, sr: float) -> np.ndarray:
    n = max(1, int(round(duration * sr)))
    return np.arange(n, dtype=float) / sr

def resample_to(y: np.ndarray, sr_in: float, sr_out: float) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    if sr_in == sr_out or y.size == 0:
        return y
    if _resample_poly is None:
        t_in = np.arange(y.size) / float(sr_in)
        n_out = int(round((y.size / float(sr_in)) * float(sr_out)))
        t_out = np.arange(n_out) / float(sr_out)
        return np.interp(t_out, t_in, y).astype(float, copy=False)
    up = int(round(sr_out)); down = int(round(sr_in)); g = gcd(up, down) or 1
    return _resample_poly(y, up // g, down // g).astype(float, copy=False)

def load_csv_waveform(path: str, default_sr: float = 1000.0) -> tuple[np.ndarray, np.ndarray, float]:
    arr = np.loadtxt(path, delimiter=",")
    if arr.ndim == 1:
        y = np.asarray(arr, dtype=float); sr = float(default_sr)
        t = common_time_grid(y.size / sr, sr); return t, y, sr
    if arr.shape[1] < 2:
        raise ValueError("CSV must have 1 (y) or 2 (t,y) columns.")
    t = np.asarray(arr[:, 0], dtype=float); y = np.asarray(arr[:, 1], dtype=float)
    dt = np.median(np.diff(t)) if t.size > 1 else 0.0
    sr = 1.0 / dt if dt > 0 else float(default_sr)
    return t, y, sr

def safe_eval_equation(expr: str, local_vars: dict) -> np.ndarray:
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("Equation is empty.")
    t = local_vars.get("t"); f = local_vars.get("f")
    if t is None or f is None:
        raise ValueError("Missing required variables: t and f.")
    allowed = {
        "t": t, "f": f, "A": local_vars.get("A", 1.0), "phi": local_vars.get("phi", 0.0),
        "pi": np.pi, "np": np,
        "sin": np.sin, "cos": np.cos, "tan": np.tan, "exp": np.exp, "log": np.log,
        "sqrt": np.sqrt, "abs": np.abs, "clip": np.clip, "arctan": np.arctan,
        "arcsin": np.arcsin, "arccos": np.arccos, "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    }
    if _sig is not None:
        allowed.update({"square": _sig.square, "sawtooth": _sig.sawtooth})
    node = ast.parse(expr, mode="eval")
    for sub in ast.walk(node):
        if isinstance(sub, (
            ast.Expression, ast.Call, ast.Attribute, ast.Name, ast.Load,
            ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
            ast.Subscript, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
            ast.USub, ast.UAdd, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        )):
            continue
        raise ValueError("Disallowed construct in equation.")
    y = eval(compile(node, "<equation>", "eval"), {"__builtins__": {}}, allowed)
    y = np.asarray(y, dtype=float)
    if y.ndim == 0:
        y = np.full_like(t, float(y), dtype=float)
    if y.ndim != 1:
        raise ValueError("Equation must produce a 1D vector.")
    if y.size != t.size:
        if y.size == 1:
            y = np.full_like(t, float(y), dtype=float)
        else:
            raise ValueError("Signal length does not match time base.")
    if not np.isfinite(y).all():
        raise ValueError("Signal contains NaN/Inf.")
    return y

def normalize_signal(y: np.ndarray) -> np.ndarray:
    m = float(np.max(np.abs(y))) if y.size else 1.0
    return (y / m) if m > 1e-12 else y

def generate_builtin_waveform(
    kind: str, *, frequency: float, amplitude: float, duration: float, sample_rate: float,
    f0: float | None = None, f1: float | None = None, fm: float | None = None, beta: float | None = None, duty: float | None = None
) -> tuple[np.ndarray, np.ndarray, float]:
    t = common_time_grid(duration, sample_rate); k = (kind or "Sine").lower()
    if k in ("sine", "sin"):
        y = amplitude * np.sin(2 * np.pi * frequency * t)
    elif k == "square":
        if _sig is None: raise RuntimeError("SciPy is required for square().")
        y = amplitude * _sig.square(2 * np.pi * frequency * t, duty=duty if duty is not None else 0.5)
    elif k == "saw":
        if _sig is None: raise RuntimeError("SciPy is required for sawtooth().")
        y = amplitude * _sig.sawtooth(2 * np.pi * frequency * t, 1.0)
    elif k == "triangle":
        if _sig is None: raise RuntimeError("SciPy is required for sawtooth().")
        y = amplitude * _sig.sawtooth(2 * np.pi * frequency * t, 0.5)
    elif k == "chirp":
        if _sig is None or not hasattr(_sig, "chirp"):
            f0_ = f0 if f0 is not None else frequency; f1_ = f1 if f1 is not None else max(1.0, frequency * 2.0)
            k_ = (f1_ - f0_) / max(1e-9, duration)
            phase = 2 * np.pi * (f0_ * t + 0.5 * k_ * t * t); y = amplitude * np.sin(phase)
        else:
            y = amplitude * _sig.chirp(t, f0=(f0 if f0 is not None else frequency),
                                       f1=(f1 if f1 is not None else max(1.0, frequency * 2.0)),
                                       t1=duration, method="linear")
    elif k == "fm":
        fc = frequency; fm_hz = fm if fm is not None else 5.0; beta_ = beta if beta is not None else 1.0
        y = amplitude * np.sin(2 * np.pi * fc * t + beta_ * np.sin(2 * np.pi * fm_hz * t))
    elif k == "pwm":
        if _sig is None: raise RuntimeError("SciPy is required for square().")
        y = amplitude * _sig.square(2 * np.pi * frequency * t, duty=duty if duty is not None else 0.5)
    elif k == "noise":
        rng = np.random.default_rng(); y = amplitude * rng.uniform(-1.0, 1.0, size=t.size)
    else:
        raise ValueError(f"Unknown oscillator: {kind}")
    return t, y.astype(float, copy=False), float(sample_rate)

# ---------- your models/widgets ----------
# --- imports that work both as a package (-m) and as a script ---
try:
    # When run as a package:  python -m waveform_designer.event_designer.universal_event_designer
    from .event_data_model import HapticEvent, EventCategory, WaveformData
except ImportError:
    # Fallback when run directly from the folder (not recommended but handy)
    from event_data_model import HapticEvent, EventCategory, WaveformData

try:
    # Package-relative import to the sibling package
    from ..waveform_widget.waveform_editor_widget import WaveformEditorWidget
except ImportError:
    # Fallback when run directly
    from waveform_widget.waveform_editor_widget import WaveformEditorWidget
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from communication import python_serial_api

# ---------- theme ----------
def apply_ultra_clean_theme(app: QApplication) -> None:
    try: app.setStyle("Fusion")
    except Exception: pass
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#FAFBFC"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F8F9FA"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1A202C"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1A202C"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1A202C"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#A0AEC0"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#4299E1"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.BrightText, QColor("#E53E3E"))
    app.setPalette(pal)

def load_ultra_clean_qss(app: QApplication) -> None:
    qss = """
    QWidget { font-size: 12.5pt; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif; }
    QGroupBox { border: 1px solid #E2E8F0; border-radius: 10px; margin-top: 14px; padding: 12px; background: #FFFFFF; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; color: #2D3748; font-weight: 700; font-size: 13pt; background: #FFFFFF; }
    QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
        height: 34px; border: 1px solid #E2E8F0; border-radius: 8px; padding: 0 10px; background: #FFFFFF; color: #1A202C; font-size: 12pt; font-weight: 500;
    }
    QPushButton { font-weight: 600; }
    QPushButton:hover { background: #F7FAFC; border-color: #4299E1; }
    QPushButton:pressed { background: #EDF2F7; }
    QLabel { color: #4A5568; font-weight: 500; font-size: 11.5pt; }
    QListWidget, QTreeWidget, QTextEdit { border: 1px solid #E2E8F0; border-radius: 8px; background: #FFFFFF; padding: 8px; }
    QTabWidget::pane { border: 1px solid #E2E8F0; border-radius: 10px; background: #FFFFFF; }
    QTabBar::tab { padding: 10px 16px; background: #F7FAFC; color: #4A5568; border: 1px solid #E2E8F0; border-bottom: none;
                   border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }
    QTabBar::tab:selected { background: #FFFFFF; color: #2D3748; font-weight: 600; }
    QSplitter::handle { background: #E2E8F0; width: 4px; border-radius: 2px; }
    """
    app.setStyleSheet(qss)

class CollapsibleSection(QWidget):
    """Header + content container. Can be collapsible or forced always-open."""
    def __init__(self, title: str, content_widget: QWidget, *,
                 collapsed: bool = False, always_expanded: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)

        self._always_expanded = bool(always_expanded)

        self.toggle_btn = QToolButton(self)
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True if self._always_expanded else (not collapsed))
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.toggle_btn.setStyleSheet("""
            QToolButton {
                border: none;
                font-weight: 700;
                color: #2D3748;
                padding: 6px 4px;
                text-align: left;
            }
            QToolButton:hover { color: #1A202C; }
        """)

        # Content container
        self.content_area = QFrame(self)
        self.content_area.setFrameShape(QFrame.Shape.NoFrame)
        self.content_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay_content = QVBoxLayout(self.content_area)
        lay_content.setContentsMargins(8, 4, 8, 8)
        lay_content.setSpacing(8)
        lay_content.addWidget(content_widget)

        # If always expanded, keep visible and disable toggling.
        if self._always_expanded:
            self.content_area.setVisible(True)
            self.toggle_btn.setCheckable(False)  # ← important: no collapse possible
        else:
            self.content_area.setVisible(not collapsed)
            self.toggle_btn.toggled.connect(self._on_toggled)

        # Main layout
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        main_lay.addWidget(self.toggle_btn)
        main_lay.addWidget(self.content_area)

    def _on_toggled(self, checked: bool):
        if self._always_expanded:
            self.toggle_btn.setChecked(True)
            self.content_area.setVisible(True)
            self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
            return
        self.content_area.setVisible(checked)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

# ---------- Library (left) ----------
class LibraryTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
    def startDrag(self, actions):
        item = self.currentItem()
        if not item or item.parent() is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        mime = QMimeData()
        mime.setData(MIME_WAVEFORM, QByteArray(json.dumps(payload).encode("utf-8")))
        drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.DropAction.CopyAction)

class EventLibraryManager:

    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))  # .../Main_GUI/waveform_designer
        main_gui = os.path.dirname(current_dir)                  # .../Main_GUI
        project_root = os.path.dirname(main_gui)                 # .../VibraForge_GUI
        
        # Vérification que c'est bien la racine
        indicators = ['requirements.txt', 'pyproject.toml', '.git', 'README.md']
        if not any(os.path.exists(os.path.join(project_root, i)) for i in indicators):
            print(f"Warning: Project root indicators not found in {project_root}")
        self.lib_root   = os.path.join(project_root, "waveform_library")
        self.custom_dir = os.path.join(self.lib_root, "customized")
        self.import_dir = os.path.join(self.lib_root, "imported")
        for d in (self.lib_root, self.custom_dir, self.import_dir):
            os.makedirs(d, exist_ok=True)
        print(f"Library root   : {self.lib_root}")
        print(f"Customized dir : {self.custom_dir}")
        print(f"Imported dir   : {self.import_dir}")
        init_file = os.path.join(self.lib_root, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w", encoding="utf-8") as f:
                f.write("# Waveform Library\n")

    def get_events_directory(self, bucket: str = "customized"):
        if bucket == "imported": return self.import_dir
        if bucket == "root": return self.lib_root
        return self.custom_dir

class EventLibraryWidget(QWidget):
    """Waveform Library with 3 sections; emits payload on double-click."""
    event_selected = pyqtSignal(object)
    BUILTIN_OSC = ["Sine", "Square", "Saw", "Triangle", "Chirp", "FM", "PWM", "Noise"]
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = EventLibraryManager()
        self.custom_dir = self.manager.custom_dir
        self.import_dir = self.manager.import_dir
        v = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("Waveform Library"); head.addWidget(title); head.addStretch(1)
        #self.btn_refresh = QPushButton("🔄 Refresh"); head.addWidget(self.btn_refresh)
        v.addLayout(head)
        self.tree = LibraryTree(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_ctx_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        v.addWidget(self.tree)
        #self.btn_refresh.clicked.connect(self.refresh)
        self.refresh()
    def refresh(self):
        self.tree.clear()
        # Oscillators
        osc_root = QTreeWidgetItem(["Oscillators"]); self.tree.addTopLevelItem(osc_root)
        for name in self.BUILTIN_OSC:
            child = QTreeWidgetItem([name])
            child.setData(0, Qt.ItemDataRole.UserRole, {"kind": "osc", "name": name})
            osc_root.addChild(child)
        # Customized
        cust_root = QTreeWidgetItem(["Customized Signals"]); self.tree.addTopLevelItem(cust_root)
        for fn in sorted(os.listdir(self.custom_dir)):
            if fn.endswith((".json", ".csv")):
                p = os.path.join(self.custom_dir, fn)
                child = QTreeWidgetItem([os.path.splitext(fn)[0]])
                child.setData(0, Qt.ItemDataRole.UserRole, {"kind": "file", "path": p})
                cust_root.addChild(child)
        self.tree.expandAll()
    def _on_double_clicked(self, item, _col):
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload: self.event_selected.emit(payload)
    def _on_ctx_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item or item.parent() is None: return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload or payload.get("kind") != "file": return
        menu = QMenu(self); act_del = menu.addAction("Delete")
        act = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if act == act_del:
            try:
                os.remove(payload["path"]); self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Delete failed", str(e))

# ---------- Drop proxy ----------
class EditorDropProxy(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.editor = WaveformEditorWidget(self)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.editor)
        self._current_event: HapticEvent | None = None
    def set_event(self, evt: HapticEvent) -> None:
        self._current_event = evt; self.editor.set_event(evt)
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_WAVEFORM): e.acceptProposedAction()
        else: e.ignore()
    def dropEvent(self, e):
        try:
            payload = json.loads(bytes(e.mimeData().data(MIME_WAVEFORM)).decode("utf-8"))
        except Exception:
            e.ignore(); return
        self.parent().handle_library_payload(payload, compose=True)
        e.acceptProposedAction()

# ---------- Main Window ----------
class UniversalEventDesigner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_event: HapticEvent | None = None
        self.current_file_path: str | None = None
        self.event_manager = EventLibraryManager()
        self.serial_api = python_serial_api()
        self.logs_visible = True
        self.export_watch_dir: str | None = None
        self.export_start_mtime: float = 0.0
        self.dir_watcher = QFileSystemWatcher(self)
        self.dir_watcher.directoryChanged.connect(self._dir_changed)
        self._build_menubar()
        self._build_ui()
        self.new_event()
        self.math_equation.setPlaceholderText(
            "Examples: sin(2*pi*f*t) | square(2*pi*f*t) | sawtooth(2*pi*f*t) | 0.5*sin(2*pi*f*t)+0.5*sin(4*pi*f*t)"
        )

    # --- UI ---
    def _build_menubar(self):
        mb = self.menuBar()
        # Device
        device_menu = mb.addMenu("Device")
        self.act_device_test = QAction("Device Test…", self)
        device_menu.addSeparator()
        device_menu.addAction(self.act_device_test)

        def _open_device_test():
            dlg = QDialog(self)
            dlg.setWindowTitle("Device Test")
            lay = QFormLayout(dlg)
            sp = QSpinBox(dlg); sp.setRange(0, 127); sp.setValue(0)
            lay.addRow("Actuator #:", sp)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok, parent=dlg)
            lay.addRow(bb)
            def _ok():
                try:
                    self.drop_proxy.editor.device_test_requested.emit(int(sp.value()))
                finally:
                    dlg.accept()
            bb.accepted.connect(_ok)
            bb.rejected.connect(dlg.reject)
            dlg.exec()

        self.act_device_test.triggered.connect(_open_device_test)
        port_row = QWidget(self); lay = QHBoxLayout(port_row)
        lay.setContentsMargins(12, 6, 12, 6); lay.setSpacing(8)
        lay.addWidget(QLabel("Port:", port_row))
        self.device_combo = QComboBox(port_row); self.device_combo.setMinimumWidth(260)
        lay.addWidget(self.device_combo, 1)
        port_action = QWidgetAction(self)
        port_action.setDefaultWidget(port_row)
        device_menu.addAction(port_action)
        self.scan_action = QAction("Scan Ports", self); self.scan_action.triggered.connect(self.scan_devices)
        device_menu.addAction(self.scan_action); device_menu.addSeparator()
        self.connect_action = QAction("Connect", self); self.connect_action.triggered.connect(self.toggle_connection)
        device_menu.addAction(self.connect_action)
        # View
        view_menu = mb.addMenu("View")
        # Plot Mode (Amplitude/Frequency/Both)
        self.plot_mode_group = QActionGroup(self)
        self.plot_mode_group.setExclusive(True)

        act_amp  = QAction("Amplitude", self, checkable=True)
        act_freq = QAction("Frequency", self, checkable=True)
        act_both = QAction("Both", self, checkable=True)

        for a in (act_amp, act_freq, act_both):
            self.plot_mode_group.addAction(a)
            view_menu.addAction(a)

        act_amp.setChecked(True)

        def _apply_plot_mode(action: QAction):
            if not hasattr(self, "drop_proxy"): return
            mode = action.text()
            self.drop_proxy.editor.set_view_mode(mode)
        self.plot_mode_group.triggered.connect(_apply_plot_mode)

        view_menu.addSeparator()

        self.act_clear = QAction("Clear Plot", self)
        self.act_save  = QAction("Save Signal (CSV)", self)
        view_menu.addAction(self.act_clear)
        view_menu.addAction(self.act_save)

        self.act_clear.triggered.connect(lambda: self.drop_proxy.editor.clear_plot())
        self.act_save.triggered.connect(lambda: self.drop_proxy.editor.save_csv())

        view_menu.addSeparator()

        self.act_modifiers = QAction("Modifiers…", self)
        view_menu.addAction(self.act_modifiers)
        self.act_modifiers.triggered.connect(lambda: self.drop_proxy.editor.open_modifiers_dialog())
        self.toggle_logs_action = QAction("Hide Logs", self)
        self.toggle_logs_action.triggered.connect(self.toggle_logs_visibility)
        view_menu.addAction(self.toggle_logs_action)
        QTimer.singleShot(100, self.scan_devices)

    def _build_ui(self):
        self.setWindowTitle("Universal Haptic Waveform Designer")
        self.setGeometry(100, 100, 1350, 800); self.setMinimumSize(1200, 700)
        self.setCentralWidget(QWidget()); main = QHBoxLayout(self.centralWidget())
        main.setContentsMargins(12, 12, 12, 12); main.setSpacing(12)
        splitter = QSplitter(Qt.Orientation.Horizontal); main.addWidget(splitter)
        splitter.addWidget(self._build_left_panel())
        self.drop_proxy = EditorDropProxy(self); splitter.addWidget(self.drop_proxy)
        splitter.setSizes([320, 980])

    def _build_left_panel(self) -> QWidget:
        tabs = QTabWidget()

        # --- Waveform Design (wrapped in a scroll area for vertical scrolling)
        meta_tab = QWidget()
        meta_layout = QVBoxLayout(meta_tab); meta_layout.setSpacing(16)

        buttons = QHBoxLayout(); buttons.setSpacing(8)
        btn_new = QPushButton("🆕 New"); btn_new.clicked.connect(self.new_event)
        btn_save = QPushButton("💾 Save"); btn_save.clicked.connect(self.save_event)
        buttons.addWidget(btn_new); buttons.addWidget(btn_save); meta_layout.addLayout(buttons)

        # Waveform Information — ALWAYS EXPANDED
        self.metadata_widget = self._build_metadata_widget()
        info_section = CollapsibleSection(
            "📝 Waveform Information",
            self.metadata_widget,
            collapsed=False,
            always_expanded=True  # ← key: cannot be folded
        )
        meta_layout.addWidget(info_section)

        # Haptic File group
        group_file = QGroupBox("📁 Haptic File"); file_layout = QVBoxLayout(group_file); file_layout.setSpacing(8)
        btn_import_hapt = QPushButton("📥 Import .haptic File"); btn_import_hapt.clicked.connect(self.import_haptic_file)
        btn_import_csv = QPushButton("📥 Import CSV Waveform"); btn_import_csv.clicked.connect(self.import_csv_waveform)
        btn_create = QPushButton("🎨 Create with Meta Haptics Studio"); btn_create.clicked.connect(self.create_with_meta_studio)
        self.file_info_label = QLabel("No file loaded"); self.file_info_label.setStyleSheet("color:#A0AEC0; font-style:italic; font-size:10.5pt;")
        self.file_info_label.setMaximumHeight(20)
        file_layout.addWidget(btn_import_csv); file_layout.addWidget(btn_import_hapt)
        file_layout.addWidget(btn_create); file_layout.addWidget(self.file_info_label)
        meta_layout.addWidget(group_file)

        # Mathematical Generator — ALWAYS EXPANDED
        math_content = QWidget()
        math_layout = QVBoxLayout(math_content); math_layout.setSpacing(10)

        eq_row = QHBoxLayout(); eq_row.setSpacing(8)
        eq_row.addWidget(QLabel("Equation:"))
        self.math_equation = QLineEdit("np.sin(2 * np.pi * f * t)")
        eq_row.addWidget(self.math_equation, 1)
        math_layout.addLayout(eq_row)

        grid = QGridLayout(); grid.setSpacing(8)
        grid.addWidget(QLabel("Frequency (Hz):"), 0, 0)
        self.math_freq = QDoubleSpinBox(); self.math_freq.setRange(0.1, 5000.0); self.math_freq.setValue(100.0); self.math_freq.setSingleStep(1.0)
        grid.addWidget(self.math_freq, 0, 1)

        grid.addWidget(QLabel("Duration (s):"), 1, 0)
        self.math_dur = QDoubleSpinBox(); self.math_dur.setRange(0.05, 30.0); self.math_dur.setValue(1.0); self.math_dur.setSingleStep(0.1)
        grid.addWidget(self.math_dur, 1, 1)

        grid.addWidget(QLabel("Sample Rate:"), 2, 0)
        self.math_sr = QDoubleSpinBox(); self.math_sr.setRange(200.0, 50000.0); self.math_sr.setValue(1000.0); self.math_sr.setSingleStep(100.0)
        grid.addWidget(self.math_sr, 2, 1)
        math_layout.addLayout(grid)

        btn_gen = QPushButton("⚡ Generate Waveform"); btn_gen.clicked.connect(self.generate_from_math)
        math_layout.addWidget(btn_gen)

        math_section = CollapsibleSection(
            "🧮 Mathematical Generator",
            math_content,
            collapsed=False,
            always_expanded=True  # ← key: cannot be folded
        )
        meta_layout.addWidget(math_section)

        # Logs (show/hide; scroll area will let you reach content below)
        self.logs_group = QGroupBox("📊 System Log")
        logs_layout = QVBoxLayout(self.logs_group)
        self.info_text = QTextEdit(); self.info_text.setReadOnly(True)
        # Keep compact height; overall tab is scrollable
        self.info_text.setMaximumHeight(70); self.info_text.setMinimumHeight(50)
        self.info_text.setStyleSheet(
            "QTextEdit{background:#FFFFFF;border:1px solid #E2E8F0;color:#2D3748;"
            "font-family:'SF Mono','Consolas','Monaco',monospace;font-size:10pt;border-radius:8px;padding:6px;}"
        )
        logs_layout.addWidget(self.info_text)
        clear_btn = QPushButton("🗑️ Clear Log"); clear_btn.clicked.connect(self.clear_log)
        logs_layout.addWidget(clear_btn)
        self.logs_group.setVisible(self.logs_visible)
        meta_layout.addWidget(self.logs_group)

        meta_layout.addStretch()

        # IMPORTANT: wrap the whole Waveform Design tab in a scroll area so it stays readable when logs are shown
        scroll = QScrollArea()
        scroll.setWidget(meta_tab)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tabs.addTab(scroll, "🎛️ Waveform Design")

        # --- Library
        self.library_widget = EventLibraryWidget()
        self.library_widget.event_selected.connect(lambda payload: self.handle_library_payload(payload, compose=False))
        tabs.addTab(self.library_widget, "📚 Waveform Library")
        return tabs

    def _build_metadata_widget(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w); lay.setSpacing(12)
        row = QHBoxLayout(); row.addWidget(QLabel("Waveform Name:")); self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed); row.addWidget(self.name_edit); lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Category:"))

        # Editable combobox – base items only
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)  # ← do not auto-insert typed text

        # Keep the canonical base list once (to test membership fast)
        self._base_categories = [c.value for c in EventCategory]  # ["crash","isolation","embodiment","alert","custom"]
        self.category_combo.clear()
        self.category_combo.addItems(self._base_categories)

        # UX hint
        self.category_combo.lineEdit().setPlaceholderText("crash, isolation, embodiment, alert, custom … or type your own")

        # Signals:
        self.category_combo.currentIndexChanged.connect(self._on_category_base_index_changed)
        # commit typed free text (Enter or focus out)
        self.category_combo.lineEdit().editingFinished.connect(self._on_category_free_text_committed)
        row.addWidget(self.category_combo)
        lay.addLayout(row)
        lay.addWidget(QLabel("Description:")); self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(85); self.description_edit.setMinimumHeight(60); self.description_edit.textChanged.connect(self._on_description_changed)
        lay.addWidget(self.description_edit); return w
    
    def _on_category_base_index_changed(self, index: int):
        """Triggered when user selects a base item from the dropdown."""
        if index is None or index < 0 or not hasattr(self, "category_combo"):
            return
        text = self.category_combo.itemText(index)
        self._on_category_base_selected(text)

    def _on_category_text_changed(self):
        """Accept base categories (enum) or free-text; store free-text in tags."""
        if not self.current_event:
            return

        # Read text from combo if present, else from the legacy edit
        if hasattr(self, "category_combo"):
            text = (self.category_combo.currentText() or "").strip()
        elif hasattr(self, "category_edit"):
            text = (self.category_edit.text() or "").strip()
        else:
            return

        if not text:
            # Empty → reset to CUSTOM and clear freeform tag
            self.current_event.metadata.category = EventCategory.CUSTOM
            tags = self.current_event.metadata.tags or []
            self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]
            return

        # Try to map to known enum values (crash/isolation/embodiment/alert/custom)
        try:
            self.current_event.metadata.category = EventCategory(text)
            # Remove any freeform tag if a base enum is used
            tags = self.current_event.metadata.tags or []
            self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]
        except Exception:
            # Free text → keep enum CUSTOM, store label in tags
            self.current_event.metadata.category = EventCategory.CUSTOM
            tags = self.current_event.metadata.tags or []
            tags = [t for t in tags if not t.startswith("category_name=")]
            tags.append(f"category_name={text}")
            self.current_event.metadata.tags = tags
    
    def _on_category_base_selected(self, text: str):
        """User picked a built-in category from the dropdown."""
        if not self.current_event:
            return
        try:
            self.current_event.metadata.category = EventCategory(text)
        except Exception:
            # If somehow not a valid enum, fall back to CUSTOM
            self.current_event.metadata.category = EventCategory.CUSTOM

        # Drop any previous free-text tag
        tags = self.current_event.metadata.tags or []
        self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]

    def _on_category_free_text_committed(self):
        """User typed a value and pressed Enter or left the field."""
        if not self.current_event:
            return
        text = (self.category_combo.currentText() or "").strip()
        if not text:
            # Empty → reset to CUSTOM and clear the free-text tag
            self.current_event.metadata.category = EventCategory.CUSTOM
            tags = self.current_event.metadata.tags or []
            self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]
            return

        # If the committed text matches a base category, treat as base
        if text in getattr(self, "_base_categories", []):
            self._on_category_base_selected(text)
            return

        # Otherwise: store as CUSTOM + keep the label in tags (do NOT add to list)
        self.current_event.metadata.category = EventCategory.CUSTOM
        tags = self.current_event.metadata.tags or []
        tags = [t for t in tags if not t.startswith("category_name=")]
        tags.append(f"category_name={text}")
        self.current_event.metadata.tags = tags

        # Keep the dropdown pristine: no insertion of "text" into items list.
        # (Leave the list as only base categories.)

    # --- Library payload handling (double-click or drop) ---
    def handle_library_payload(self, payload, *, compose: bool):
        try:
            if isinstance(payload, dict):
                kind = payload.get("kind")
                if kind == "osc":
                    self._handle_oscillator_payload(payload.get("name", "Sine"), compose=compose); return
                if kind == "file":
                    self._handle_file_payload(payload.get("path"), compose=compose); return
            elif isinstance(payload, str):
                if payload.startswith("oscillator::"):
                    self._handle_oscillator_payload(payload.split("::", 1)[1], compose=compose)
                else:
                    self._handle_file_payload(payload, compose=compose)
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))

    def _handle_oscillator_payload(self, osc_name: str, *, compose: bool):
        freq, amp, dur, sr = 100.0, 1.0, 1.0, 1000.0
        if compose and self.current_event and self.current_event.waveform_data:
            sr = float(self.current_event.waveform_data.sample_rate)
            dur = float(self.current_event.waveform_data.duration)
        t2, y2, sr2 = generate_builtin_waveform(osc_name, frequency=freq, amplitude=amp, duration=dur, sample_rate=sr)
        if compose and self.current_event and self.current_event.waveform_data:
            wf = self.current_event.waveform_data
            y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
            sr1 = float(wf.sample_rate); y2r = resample_to(y2, sr2, sr1)
            n = min(y1.size, y2r.size); 
            if n == 0: return
            y1[:n] *= y2r[:n]; t1 = np.arange(y1.size) / sr1
            wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
            wf.duration = float(y1.size / sr1); self.update_ui(); self.log_info_message(f"✚ Composed {osc_name} (multiply)")
        else:
            amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
            freq_pts = [{"time": 0.0, "frequency": freq}, {"time": float(dur), "frequency": freq}]
            evt = HapticEvent(name=f"{osc_name} Oscillator")
            evt.waveform_data = WaveformData(amplitude=amp_pts, frequency=freq_pts, duration=float(dur), sample_rate=float(sr))
            self.current_event = evt; self.current_file_path = None; self.update_ui(); self.log_info_message(f"🌊 New {osc_name} oscillator created")

    def _handle_file_payload(self, path: str | None, *, compose: bool):
        if not path or not os.path.isfile(path): raise FileNotFoundError("File not found.")
        if path.lower().endswith(".csv"):
            t2, y2, sr2 = load_csv_waveform(path)
            if compose and self.current_event and self.current_event.waveform_data:
                wf = self.current_event.waveform_data
                y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
                sr1 = float(wf.sample_rate); y2r = resample_to(y2, sr2, sr1)
                n = min(y1.size, y2r.size); 
                if n == 0: return
                y1[:n] *= y2r[:n]; t1 = np.arange(y1.size) / sr1
                wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
                wf.duration = float(y1.size / sr1); self.update_ui(); self.log_info_message("✚ Composed CSV waveform (multiply)")
            else:
                dur = float(t2[-1] - t2[0]) if t2.size > 1 else (y2.size / sr2)
                amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
                freq_pts = [{"time": 0.0, "frequency": 0.0}, {"time": float(dur), "frequency": 0.0}]
                evt = HapticEvent(name=os.path.splitext(os.path.basename(path))[0])
                evt.waveform_data = WaveformData(amplitude=amp_pts, frequency=freq_pts, duration=float(dur), sample_rate=float(sr2))
                self.current_event = evt; self.current_file_path = None; self.update_ui(); self.log_info_message(f"📂 Loaded CSV: {os.path.basename(path)}")
        else:
            evt = HapticEvent.load_from_file(path)
            self.current_event = evt; self.current_file_path = path; self.update_ui(); self.log_info_message(f"📂 Loaded: {os.path.basename(path)}")

    # --- metadata wiring ---
    def _on_name_changed(self, text: str):
        if self.current_event: self.current_event.metadata.name = text
    def _on_category_changed(self, text: str):
        if self.current_event: self.current_event.metadata.category = EventCategory(text)
    def _on_description_changed(self):
        if self.current_event: self.current_event.metadata.description = self.description_edit.toPlainText()

    # --- device & logs ---
    def toggle_logs_visibility(self):
        self.logs_visible = not self.logs_visible
        self.logs_group.setVisible(self.logs_visible)
        self.toggle_logs_action.setText("Hide Logs" if self.logs_visible else "Show Logs")
        self.update()
    def clear_log(self): self.info_text.clear()
    def scan_devices(self):
        try:
            devices = self.serial_api.get_serial_devices()
            self.device_combo.clear(); self.device_combo.addItems(devices)
            self.log_info_message(f"🔍 Found {len(devices)} devices")
        except Exception as e:
            self.log_info_message(f"❌ Error scanning devices: {e}")
    def toggle_connection(self):
        if self.serial_api.connected:
            ok = self.serial_api.disconnect_serial_device()
            if ok: self.connect_action.setText("Connect"); self.log_info_message("🔌 Disconnected from device")
            else: self.log_info_message("❌ Failed to disconnect")
            return
        port = self.device_combo.currentText()
        if port and self.serial_api.connect_serial_device(port):
            self.connect_action.setText("Disconnect"); self.log_info_message(f"🔗 Connected on {port}")
        else:
            self.log_info_message("❌ Failed to connect to device")
    def log_info_message(self, message: str):
        ts = time.strftime("%H:%M:%S")
        self.info_text.append(f"<span style='color:#A0AEC0;'>[{ts}]</span> {message}")
        self.info_text.verticalScrollBar().setValue(self.info_text.verticalScrollBar().maximum())

    # --- Meta Haptics Studio workflow ---
    def create_with_meta_studio(self):
        watch_dir = QFileDialog.getExistingDirectory(self, "Choose the folder where you will export your .haptic file")
        if not watch_dir: return
        if self.export_watch_dir: self.dir_watcher.removePath(self.export_watch_dir)
        self.export_watch_dir = watch_dir; self.export_start_mtime = time.time(); self.dir_watcher.addPath(watch_dir)
        try:
            if sys.platform.startswith("darwin"): os.system("open -a 'Meta Haptics Studio'")
            elif sys.platform.startswith("win"): os.startfile(r"C:\Program Files\Meta Haptic Studio\MetaHapticStudio.exe")  # type: ignore
            else: os.system("/opt/meta-haptic-studio/MetaHapticStudio &")
        except Exception: pass
        self.log_info_message(f"🎨 Meta Haptics Studio launched – waiting for .haptic in \"{watch_dir}\"…")
    def _dir_changed(self, path: str):
        if path != self.export_watch_dir: return
        candidates = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".haptic")]
        if not candidates: return
        latest = max(candidates, key=os.path.getmtime)
        if os.path.getmtime(latest) < self.export_start_mtime: return
        self.dir_watcher.removePath(path); self.export_watch_dir = None
        if self.current_event and self.current_event.load_from_haptic_file(latest):
            self.update_ui(); self.file_info_label.setText(f"✅ Loaded: {os.path.basename(latest)}")
            self.log_info_message(f"📥 File imported: {os.path.basename(latest)}")
        else:
            QMessageBox.critical(self, "Error", f"Could not import \"{os.path.basename(latest)}\".")

    # --- file ops ---
    def new_event(self):
        self.current_event = HapticEvent(); self.current_file_path = None
        self.update_ui(); self.log_info_message("🆕 New waveform created")
    def save_event(self):
        if self.current_event is None: return
        if self.current_file_path:
            if self.current_event.save_to_file(self.current_file_path):
                self.log_info_message(f"💾 Saved: {os.path.basename(self.current_file_path)}")
                if hasattr(self, "library_widget"):
                    if hasattr(self.library_widget, "refresh"): self.library_widget.refresh()
            else: QMessageBox.critical(self, "Error", "Save failed")
        else:
            self.save_event_as()
    def save_event_as(self):
        if self.current_event is None: return
        lib_dir = self.event_manager.get_events_directory("customized")
        suggested = (self.current_event.metadata.name or "untitled").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(self, "Save Waveform As",
                                              os.path.join(lib_dir, f"{suggested}.json"),
                                              "Waveform Files (*.json);;All Files (*)")
        if not path: return
        if self.current_event.save_to_file(path):
            self.current_file_path = path; self.log_info_message(f"💾 Saved: {os.path.basename(path)}")
            custom_dir = os.path.abspath(lib_dir)
            if os.path.dirname(os.path.abspath(path)) != custom_dir:
                dst = os.path.join(custom_dir, os.path.basename(path))
                try: shutil.copy2(path, dst); self.log_info_message(f"📚 Copied to library/customized: {os.path.basename(dst)}")
                except Exception as e: self.log_info_message(f"❌ Failed to copy into library/customized: {e}")
            if hasattr(self, "library_widget"):
                if hasattr(self.library_widget, "refresh"): self.library_widget.refresh()
        else:
            QMessageBox.critical(self, "Error", "Save failed")
    def import_haptic_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import .haptic file", "", "Haptic Files (*.haptic);;All Files (*)")
        if not path: return
        if self.current_event and self.current_event.load_from_haptic_file(path):
            self.update_ui(); self.file_info_label.setText(f"✅ Loaded: {os.path.basename(path)}")
            self.log_info_message(f"📥 File imported: {os.path.basename(path)}")
        else:
            QMessageBox.critical(self, "Error", f"Could not import \"{os.path.basename(path)}\".")
    # --- UI sync ---
    def update_ui(self):
        """Refresh left-panel fields and push the event to the editor."""
        if not self.current_event:
            self.setWindowTitle("Universal Haptic Waveform Designer")
            return

        # ---------- block signals while filling ----------
        if hasattr(self, "name_edit"):
            self.name_edit.blockSignals(True)
        if hasattr(self, "description_edit"):
            self.description_edit.blockSignals(True)
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(True)
        elif hasattr(self, "category_edit"):
            self.category_edit.blockSignals(True)

        # ---------- name ----------
        if hasattr(self, "name_edit"):
            self.name_edit.setText(self.current_event.metadata.name)

        # ---------- category (base enum or free-text in tags) ----------
        cat_text = self.current_event.metadata.category.value
        tags = self.current_event.metadata.tags or []
        for t in tags:
            if t.startswith("category_name="):
                cat_text = t.split("=", 1)[1]
                break

        # Ensure we have the canonical base list cached (used below)
        base_list = getattr(self, "_base_categories", None)
        if base_list is None:
            base_list = [c.value for c in EventCategory]
            self._base_categories = base_list

        if hasattr(self, "category_combo"):
            # If it's a base category, select it; else only show in the edit line
            idx = self.category_combo.findText(cat_text)
            if cat_text in base_list and idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            else:
                # show custom text but do NOT add it to the items
                self.category_combo.setEditText(cat_text)
        elif hasattr(self, "category_edit"):
            # Legacy fallback (free-text QLineEdit)
            self.category_edit.setText(cat_text)

        # ---------- description ----------
        if hasattr(self, "description_edit"):
            self.description_edit.setPlainText(self.current_event.metadata.description)

        # ---------- unblock signals ----------
        if hasattr(self, "name_edit"):
            self.name_edit.blockSignals(False)
        if hasattr(self, "description_edit"):
            self.description_edit.blockSignals(False)
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(False)
        elif hasattr(self, "category_edit"):
            self.category_edit.blockSignals(False)

        # ---------- push event to the right pane editor ----------
        if hasattr(self, "drop_proxy") and hasattr(self.drop_proxy, "set_event"):
            self.drop_proxy.set_event(self.current_event)

        # ---------- file label ----------
        if hasattr(self, "file_info_label"):
            if self.current_event.original_haptic_file:
                self.file_info_label.setText(
                    f"✅ Loaded: {os.path.basename(self.current_event.original_haptic_file)}"
                )
            else:
                self.file_info_label.setText("📁 No file loaded")

        # ---------- window title ----------
        title = self.current_event.metadata.name or "Untitled"
        self.setWindowTitle(f"Universal Haptic Waveform Designer – {title}")
    # --- CSV import ---
    def import_csv_waveform(self):
        if self.current_event is None: self.current_event = HapticEvent()
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV waveform", "", "CSV (*.csv)")
        if not path: return
        try:
            t, y, sr = load_csv_waveform(path)
            dur = float(t[-1]) if t.size else (len(y) / sr if sr > 0 else 0.0)
            amp = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq = (self.current_event.waveform_data.frequency
                    if self.current_event.waveform_data and self.current_event.waveform_data.frequency
                    else [{"time": 0.0, "frequency": 0.0}, {"time": dur, "frequency": 0.0}])
            self.current_event.waveform_data = WaveformData(amp, freq, dur, sr)
            tags = self.current_event.metadata.tags or []
            if "imported-csv" not in tags: self.current_event.metadata.tags = tags + ["imported-csv"]
            self.update_ui(); self.log_info_message(f"📥 CSV imported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))
    # --- Math generator ---
    def generate_from_math(self):
        if not self.current_event: return
        try:
            f = float(self.math_freq.value()); dur = float(self.math_dur.value()); sr = float(self.math_sr.value())
            f = max(0.01, min(f, 5000.0)); dur = max(0.05, min(dur, 30.0)); sr = max(200.0, min(sr, 50000.0))
            n = int(round(sr * dur)); t = np.arange(n, dtype=float) / sr
            expr = self.math_equation.text().strip()
            if not expr: raise ValueError("Equation is empty.")
            y = safe_eval_equation(expr, {"t": t, "f": f, "A": 1.0, "phi": 0.0})
            y = normalize_signal(y)
            if not np.isfinite(y).all(): raise ValueError("Signal contains NaN/Inf.")
            amp = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq = [{"time": 0.0, "frequency": f}, {"time": dur, "frequency": f}]
            self.current_event.waveform_data = WaveformData(amp, freq, dur, sr)
            tags = getattr(self.current_event.metadata, "tags", None) or []
            if "generated" not in tags: tags.append("generated")
            self.current_event.metadata.tags = tags
            self.update_ui(); self.log_info_message("⚡ Waveform generated from equation")
        except Exception as e:
            self.log_info_message(f"❌ Equation error: {e}")
    # --- Close ---
    def closeEvent(self, event):
        if self.export_watch_dir: self.dir_watcher.removePath(self.export_watch_dir)
        if self.serial_api.connected: self.serial_api.disconnect_serial_device()
        event.accept()

# ---------- entry point ----------
def main():
    app = QApplication(sys.argv)
    apply_ultra_clean_theme(app); load_ultra_clean_qss(app)
    app.setApplicationName("Universal Haptic Waveform Designer")
    app.setApplicationVersion("2.3"); app.setOrganizationName("Haptic Systems")
    window = UniversalEventDesigner(); window.show()
    window.log_info_message("🚀 Application ready - Ultra Clean Interface")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()