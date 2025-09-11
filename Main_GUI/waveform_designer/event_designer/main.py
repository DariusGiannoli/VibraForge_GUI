# main.py
"""
Main application file for the Universal Haptic Waveform Designer
"""

import sys
import os
import time
import shutil
import numpy as np
from PyQt6.QtCore import Qt, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QGroupBox, QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton, 
    QFileDialog, QMessageBox, QTabWidget, QGridLayout, QDoubleSpinBox, 
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QScrollArea,
    QWidgetAction, QFrame
)

# Import our custom modules
from .core import (
    safe_eval_equation, normalize_signal, load_csv_waveform, 
    resample_to, generate_builtin_waveform, common_time_grid
)
from .ui import (
    apply_ultra_clean_theme, load_ultra_clean_qss,
    CollapsibleSection, EventLibraryWidget, EditorDropProxy, EventLibraryManager
)

# Import event data model
from .core import HapticEvent, EventCategory, WaveformData

# Import communication API
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from communication import python_serial_api

class UniversalEventDesigner(QMainWindow):
    """Main application window for the Universal Haptic Waveform Designer."""
    
    def __init__(self):
        super().__init__()
        self.current_event: HapticEvent | None = None
        self.current_file_path: str | None = None
        self.event_manager = EventLibraryManager()
        self.serial_api = python_serial_api()
        self.logs_visible = True
        self.export_watch_dir: str | None = None
        self.export_start_mtime: float = 0.0
        
        # File system watcher for Meta Haptics Studio integration
        self.dir_watcher = QFileSystemWatcher(self)
        self.dir_watcher.directoryChanged.connect(self._dir_changed)
        
        # Build UI
        self._build_menubar()
        self._build_ui()
        self.new_event()
        
        # Set placeholder text for math equation
        self.math_equation.setPlaceholderText(
            "Examples: sin(2*pi*f*t) | square(2*pi*f*t) | sawtooth(2*pi*f*t) | 0.5*sin(2*pi*f*t)+0.5*sin(4*pi*f*t)"
        )

    def _build_menubar(self):
        """Build the application menu bar."""
        mb = self.menuBar()
        
        # Device menu
        device_menu = mb.addMenu("Device")
        self.act_device_test = QAction("Device Test…", self)
        device_menu.addSeparator()
        device_menu.addAction(self.act_device_test)

        def _open_device_test():
            dlg = QDialog(self)
            dlg.setWindowTitle("Device Test")
            lay = QFormLayout(dlg)
            sp = QSpinBox(dlg)
            sp.setRange(0, 127)
            sp.setValue(0)
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
        
        # Port selection widget
        port_row = QWidget(self)
        lay = QHBoxLayout(port_row)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Port:", port_row))
        self.device_combo = QComboBox(port_row)
        self.device_combo.setMinimumWidth(260)
        lay.addWidget(self.device_combo, 1)
        port_action = QWidgetAction(self)
        port_action.setDefaultWidget(port_row)
        device_menu.addAction(port_action)
        
        # Device actions
        self.scan_action = QAction("Scan Ports", self)
        self.scan_action.triggered.connect(self.scan_devices)
        device_menu.addAction(self.scan_action)
        device_menu.addSeparator()
        self.connect_action = QAction("Connect", self)
        self.connect_action.triggered.connect(self.toggle_connection)
        device_menu.addAction(self.connect_action)
        
        # View menu
        view_menu = mb.addMenu("View")
        
        # Plot mode selection
        self.plot_mode_group = QActionGroup(self)
        self.plot_mode_group.setExclusive(True)

        act_amp = QAction("Amplitude", self, checkable=True)
        act_freq = QAction("Frequency", self, checkable=True)
        act_both = QAction("Both", self, checkable=True)

        for a in (act_amp, act_freq, act_both):
            self.plot_mode_group.addAction(a)
            view_menu.addAction(a)

        act_amp.setChecked(True)

        def _apply_plot_mode(action: QAction):
            if not hasattr(self, "drop_proxy"): 
                return
            mode = action.text()
            self.drop_proxy.editor.set_view_mode(mode)
            
        self.plot_mode_group.triggered.connect(_apply_plot_mode)

        view_menu.addSeparator()

        # View actions
        self.act_clear = QAction("Clear Plot", self)
        self.act_save = QAction("Save Signal (CSV)", self)
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
        
        # Initial device scan
        QTimer.singleShot(100, self.scan_devices)

    def _build_ui(self):
        """Build the main user interface."""
        self.setWindowTitle("Universal Haptic Waveform Designer")
        self.setGeometry(100, 100, 1350, 800)
        self.setMinimumSize(1200, 700)
        
        self.setCentralWidget(QWidget())
        main = QHBoxLayout(self.centralWidget())
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(12)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(splitter)
        
        splitter.addWidget(self._build_left_panel())
        self.drop_proxy = EditorDropProxy(self)
        splitter.addWidget(self.drop_proxy)
        splitter.setSizes([320, 980])

    def _build_left_panel(self) -> QWidget:
        """Build the left panel with tabs."""
        tabs = QTabWidget()

        # Waveform Design tab (wrapped in scroll area)
        meta_tab = QWidget()
        meta_layout = QVBoxLayout(meta_tab)
        meta_layout.setSpacing(16)

        # Action buttons
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        btn_new = QPushButton("New")
        btn_new.clicked.connect(self.new_event)
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.save_event)
        buttons.addWidget(btn_new)
        buttons.addWidget(btn_save)
        meta_layout.addLayout(buttons)

        # Waveform Information section (always expanded)
        self.metadata_widget = self._build_metadata_widget()
        info_section = CollapsibleSection(
            "Waveform Information",
            self.metadata_widget,
            collapsed=False,
            always_expanded=True
        )
        meta_layout.addWidget(info_section)

        # Haptic File group
        group_file = QGroupBox("Haptic File")
        file_layout = QVBoxLayout(group_file)
        file_layout.setSpacing(8)
        btn_import_hapt = QPushButton("Import .haptic File")
        btn_import_hapt.clicked.connect(self.import_haptic_file)
        btn_import_csv = QPushButton("Import CSV Waveform")
        btn_import_csv.clicked.connect(self.import_csv_waveform)
        btn_create = QPushButton("Create with Meta Haptics Studio")
        btn_create.clicked.connect(self.create_with_meta_studio)
        self.file_info_label = QLabel("No file loaded")
        self.file_info_label.setStyleSheet("color:#A0AEC0; font-style:italic; font-size:10.5pt;")
        self.file_info_label.setMaximumHeight(20)
        file_layout.addWidget(btn_import_csv)
        file_layout.addWidget(btn_import_hapt)
        file_layout.addWidget(btn_create)
        file_layout.addWidget(self.file_info_label)
        meta_layout.addWidget(group_file)

        # Mathematical Generator section (always expanded)
        math_content = QWidget()
        math_layout = QVBoxLayout(math_content)
        math_layout.setSpacing(10)

        eq_row = QHBoxLayout()
        eq_row.setSpacing(8)
        eq_row.addWidget(QLabel("Equation:"))
        self.math_equation = QLineEdit("np.sin(2 * np.pi * f * t)")
        eq_row.addWidget(self.math_equation, 1)
        math_layout.addLayout(eq_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.addWidget(QLabel("Frequency (Hz):"), 0, 0)
        self.math_freq = QDoubleSpinBox()
        self.math_freq.setRange(0.1, 5000.0)
        self.math_freq.setValue(100.0)
        self.math_freq.setSingleStep(1.0)
        grid.addWidget(self.math_freq, 0, 1)

        grid.addWidget(QLabel("Duration (s):"), 1, 0)
        self.math_dur = QDoubleSpinBox()
        self.math_dur.setRange(0.05, 30.0)
        self.math_dur.setValue(1.0)
        self.math_dur.setSingleStep(0.1)
        grid.addWidget(self.math_dur, 1, 1)

        grid.addWidget(QLabel("Sample Rate:"), 2, 0)
        self.math_sr = QDoubleSpinBox()
        self.math_sr.setRange(200.0, 50000.0)
        self.math_sr.setValue(1000.0)
        self.math_sr.setSingleStep(100.0)
        grid.addWidget(self.math_sr, 2, 1)
        math_layout.addLayout(grid)

        btn_gen = QPushButton("Generate Waveform")
        btn_gen.clicked.connect(self.generate_from_math)
        math_layout.addWidget(btn_gen)

        math_section = CollapsibleSection(
            "Mathematical Generator",
            math_content,
            collapsed=False,
            always_expanded=True
        )
        meta_layout.addWidget(math_section)

        # System logs section
        self.logs_group = QGroupBox("System Log")
        logs_layout = QVBoxLayout(self.logs_group)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(70)
        self.info_text.setMinimumHeight(50)
        self.info_text.setStyleSheet(
            "QTextEdit{background:#FFFFFF;border:1px solid #E2E8F0;color:#2D3748;"
            "font-family:'SF Mono','Consolas','Monaco',monospace;font-size:10pt;border-radius:8px;padding:6px;}"
        )
        logs_layout.addWidget(self.info_text)
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.clear_log)
        logs_layout.addWidget(clear_btn)
        self.logs_group.setVisible(self.logs_visible)
        meta_layout.addWidget(self.logs_group)

        meta_layout.addStretch()

        # Wrap in scroll area
        scroll = QScrollArea()
        scroll.setWidget(meta_tab)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tabs.addTab(scroll, "Waveform Design")

        # Library tab
        self.library_widget = EventLibraryWidget()
        self.library_widget.event_selected.connect(
            lambda payload: self.handle_library_payload(payload, compose=False)
        )
        tabs.addTab(self.library_widget, "Waveform Library")
        
        return tabs

    def _build_metadata_widget(self) -> QWidget:
        """Build the metadata editing widget."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        
        # Name field
        row = QHBoxLayout()
        row.addWidget(QLabel("Waveform Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_name_changed)
        row.addWidget(self.name_edit)
        lay.addLayout(row)
        
        # Category field
        row = QHBoxLayout()
        row.addWidget(QLabel("Category:"))

        # Editable combobox
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)

        # Base categories
        self._base_categories = [c.value for c in EventCategory]
        self.category_combo.clear()
        self.category_combo.addItems(self._base_categories)

        # Placeholder text
        self.category_combo.lineEdit().setPlaceholderText(
            "crash, isolation, embodiment, alert, custom … or type your own"
        )

        # Connect signals
        self.category_combo.currentIndexChanged.connect(self._on_category_base_index_changed)
        self.category_combo.lineEdit().editingFinished.connect(self._on_category_free_text_committed)
        row.addWidget(self.category_combo)
        lay.addLayout(row)
        
        # Description field
        lay.addWidget(QLabel("Description:"))
        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(85)
        self.description_edit.setMinimumHeight(60)
        self.description_edit.textChanged.connect(self._on_description_changed)
        lay.addWidget(self.description_edit)
        
        return w

    # Metadata handlers
    def _on_category_base_index_changed(self, index: int):
        """Handle selection of base category from dropdown."""
        if index is None or index < 0 or not hasattr(self, "category_combo"):
            return
        text = self.category_combo.itemText(index)
        self._on_category_base_selected(text)

    def _on_category_base_selected(self, text: str):
        """Handle selection of built-in category."""
        if not self.current_event:
            return
        try:
            self.current_event.metadata.category = EventCategory(text)
        except Exception:
            self.current_event.metadata.category = EventCategory.CUSTOM

        # Remove any previous free-text tag
        tags = self.current_event.metadata.tags or []
        self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]

    def _on_category_free_text_committed(self):
        """Handle commit of free-text category."""
        if not self.current_event:
            return
        text = (self.category_combo.currentText() or "").strip()
        if not text:
            self.current_event.metadata.category = EventCategory.CUSTOM
            tags = self.current_event.metadata.tags or []
            self.current_event.metadata.tags = [t for t in tags if not t.startswith("category_name=")]
            return

        # Check if it's a base category
        if text in getattr(self, "_base_categories", []):
            self._on_category_base_selected(text)
            return

        # Store as custom category with label in tags
        self.current_event.metadata.category = EventCategory.CUSTOM
        tags = self.current_event.metadata.tags or []
        tags = [t for t in tags if not t.startswith("category_name=")]
        tags.append(f"category_name={text}")
        self.current_event.metadata.tags = tags

    def _on_name_changed(self, text: str):
        """Handle name field changes."""
        if self.current_event: 
            self.current_event.metadata.name = text

    def _on_description_changed(self):
        """Handle description field changes."""
        if self.current_event: 
            self.current_event.metadata.description = self.description_edit.toPlainText()

    # Library payload handling
    def handle_library_payload(self, payload, *, compose: bool):
        """Handle payload from library (double-click or drop)."""
        try:
            if isinstance(payload, dict):
                kind = payload.get("kind")
                if kind == "osc":
                    self._handle_oscillator_payload(payload.get("name", "Sine"), compose=compose)
                    return
                if kind == "file":
                    self._handle_file_payload(payload.get("path"), compose=compose)
                    return
            elif isinstance(payload, str):
                if payload.startswith("oscillator::"):
                    self._handle_oscillator_payload(payload.split("::", 1)[1], compose=compose)
                else:
                    self._handle_file_payload(payload, compose=compose)
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))

    def _handle_oscillator_payload(self, osc_name: str, *, compose: bool):
        """Handle oscillator payload from library."""
        freq, amp, dur, sr = 100.0, 1.0, 1.0, 1000.0
        
        if compose and self.current_event and self.current_event.waveform_data:
            sr = float(self.current_event.waveform_data.sample_rate)
            dur = float(self.current_event.waveform_data.duration)
        
        t2, y2, sr2 = generate_builtin_waveform(
            osc_name, frequency=freq, amplitude=amp, duration=dur, sample_rate=sr
        )
        
        if compose and self.current_event and self.current_event.waveform_data:
            # Composition mode - multiply with existing waveform
            wf = self.current_event.waveform_data
            y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
            sr1 = float(wf.sample_rate)
            y2r = resample_to(y2, sr2, sr1)
            n = min(y1.size, y2r.size)
            if n == 0: 
                return
            y1[:n] *= y2r[:n]
            t1 = np.arange(y1.size) / sr1
            wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
            wf.duration = float(y1.size / sr1)
            self.update_ui()
            self.log_info_message(f"Composed {osc_name} (multiply)")
        else:
            # Create new waveform
            amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
            freq_pts = [{"time": 0.0, "frequency": freq}, {"time": float(dur), "frequency": freq}]
            evt = HapticEvent(name=f"{osc_name} Oscillator")
            evt.waveform_data = WaveformData(
                amplitude=amp_pts, frequency=freq_pts, duration=float(dur), sample_rate=float(sr)
            )
            self.current_event = evt
            self.current_file_path = None
            self.update_ui()
            self.log_info_message(f"New {osc_name} oscillator created")

    def _handle_file_payload(self, path: str | None, *, compose: bool):
        """Handle file payload from library."""
        if not path or not os.path.isfile(path): 
            raise FileNotFoundError("File not found.")
        
        if path.lower().endswith(".csv"):
            t2, y2, sr2 = load_csv_waveform(path)
            if compose and self.current_event and self.current_event.waveform_data:
                # Composition mode
                wf = self.current_event.waveform_data
                y1 = np.array([p["amplitude"] for p in wf.amplitude], dtype=float)
                sr1 = float(wf.sample_rate)
                y2r = resample_to(y2, sr2, sr1)
                n = min(y1.size, y2r.size)
                if n == 0: 
                    return
                y1[:n] *= y2r[:n]
                t1 = np.arange(y1.size) / sr1
                wf.amplitude = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t1, y1)]
                wf.duration = float(y1.size / sr1)
                self.update_ui()
                self.log_info_message("Composed CSV waveform (multiply)")
            else:
                # New waveform
                dur = float(t2[-1] - t2[0]) if t2.size > 1 else (y2.size / sr2)
                amp_pts = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t2, y2)]
                freq_pts = [{"time": 0.0, "frequency": 0.0}, {"time": float(dur), "frequency": 0.0}]
                evt = HapticEvent(name=os.path.splitext(os.path.basename(path))[0])
                evt.waveform_data = WaveformData(
                    amplitude=amp_pts, frequency=freq_pts, duration=float(dur), sample_rate=float(sr2)
                )
                self.current_event = evt
                self.current_file_path = None
                self.update_ui()
                self.log_info_message(f"Loaded CSV: {os.path.basename(path)}")
        else:
            # Load haptic event file
            evt = HapticEvent.load_from_file(path)
            self.current_event = evt
            self.current_file_path = path
            self.update_ui()
            self.log_info_message(f"Loaded: {os.path.basename(path)}")

    # Device management
    def toggle_logs_visibility(self):
        """Toggle the visibility of the logs section."""
        self.logs_visible = not self.logs_visible
        self.logs_group.setVisible(self.logs_visible)
        self.toggle_logs_action.setText("Hide Logs" if self.logs_visible else "Show Logs")
        self.update()

    def clear_log(self):
        """Clear the log text."""
        self.info_text.clear()

    def scan_devices(self):
        """Scan for available serial devices."""
        try:
            devices = self.serial_api.get_serial_devices()
            self.device_combo.clear()
            self.device_combo.addItems(devices)
            self.log_info_message(f"Found {len(devices)} devices")
        except Exception as e:
            self.log_info_message(f"Error scanning devices: {e}")

    def toggle_connection(self):
        """Toggle serial device connection."""
        if self.serial_api.connected:
            ok = self.serial_api.disconnect_serial_device()
            if ok:
                self.connect_action.setText("Connect")
                self.log_info_message("Disconnected from device")
            else:
                self.log_info_message("Failed to disconnect")
            return
        
        port = self.device_combo.currentText()
        if port and self.serial_api.connect_serial_device(port):
            self.connect_action.setText("Disconnect")
            self.log_info_message(f"Connected on {port}")
        else:
            self.log_info_message("Failed to connect to device")

    def log_info_message(self, message: str):
        """Log an informational message."""
        ts = time.strftime("%H:%M:%S")
        self.info_text.append(f"<span style='color:#A0AEC0;'>[{ts}]</span> {message}")
        self.info_text.verticalScrollBar().setValue(self.info_text.verticalScrollBar().maximum())

    # Meta Haptics Studio integration
    def create_with_meta_studio(self):
        """Launch Meta Haptics Studio and watch for exported files."""
        watch_dir = QFileDialog.getExistingDirectory(
            self, "Choose the folder where you will export your .haptic file"
        )
        if not watch_dir: 
            return
        
        if self.export_watch_dir: 
            self.dir_watcher.removePath(self.export_watch_dir)
        
        self.export_watch_dir = watch_dir
        self.export_start_mtime = time.time()
        self.dir_watcher.addPath(watch_dir)
        
        # Try to launch Meta Haptics Studio
        try:
            if sys.platform.startswith("darwin"): 
                os.system("open -a 'Meta Haptics Studio'")
            elif sys.platform.startswith("win"): 
                os.startfile(r"C:\Program Files\Meta Haptic Studio\MetaHapticStudio.exe")  # type: ignore
            else: 
                os.system("/opt/meta-haptic-studio/MetaHapticStudio &")
        except Exception: 
            pass
        
        self.log_info_message(f"Meta Haptics Studio launched – waiting for .haptic in \"{watch_dir}\"…")

    def _dir_changed(self, path: str):
        """Handle directory change events from file watcher."""
        if path != self.export_watch_dir: 
            return
        
        candidates = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".haptic")]
        if not candidates: 
            return
        
        latest = max(candidates, key=os.path.getmtime)
        if os.path.getmtime(latest) < self.export_start_mtime: 
            return
        
        self.dir_watcher.removePath(path)
        self.export_watch_dir = None
        
        if self.current_event and self.current_event.load_from_haptic_file(latest):
            self.update_ui()
            self.file_info_label.setText(f"Loaded: {os.path.basename(latest)}")
            self.log_info_message(f"File imported: {os.path.basename(latest)}")
        else:
            QMessageBox.critical(self, "Error", f"Could not import \"{os.path.basename(latest)}\".")

    # File operations
    def new_event(self):
        """Create a new haptic event."""
        self.current_event = HapticEvent()
        self.current_file_path = None
        self.update_ui()
        self.log_info_message("New waveform created")

    def save_event(self):
        """Save the current event."""
        if self.current_event is None: 
            return
        
        if self.current_file_path:
            if self.current_event.save_to_file(self.current_file_path):
                self.log_info_message(f"Saved: {os.path.basename(self.current_file_path)}")
                if hasattr(self, "library_widget"):
                    if hasattr(self.library_widget, "refresh"): 
                        self.library_widget.refresh()
            else: 
                QMessageBox.critical(self, "Error", "Save failed")
        else:
            self.save_event_as()

    def save_event_as(self):
        """Save the current event with a new filename."""
        if self.current_event is None: 
            return
        
        lib_dir = self.event_manager.get_events_directory("customized")
        suggested = (self.current_event.metadata.name or "untitled").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Waveform As",
            os.path.join(lib_dir, f"{suggested}.json"),
            "Waveform Files (*.json);;All Files (*)"
        )
        if not path: 
            return
        
        if self.current_event.save_to_file(path):
            self.current_file_path = path
            self.log_info_message(f"Saved: {os.path.basename(path)}")
            
            # Copy to library if not already there
            custom_dir = os.path.abspath(lib_dir)
            if os.path.dirname(os.path.abspath(path)) != custom_dir:
                dst = os.path.join(custom_dir, os.path.basename(path))
                try: 
                    shutil.copy2(path, dst)
                    self.log_info_message(f"Copied to library/customized: {os.path.basename(dst)}")
                except Exception as e: 
                    self.log_info_message(f"Failed to copy into library/customized: {e}")
            
            if hasattr(self, "library_widget"):
                if hasattr(self.library_widget, "refresh"): 
                    self.library_widget.refresh()
        else:
            QMessageBox.critical(self, "Error", "Save failed")

    def import_haptic_file(self):
        """Import a .haptic file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import .haptic file", "", "Haptic Files (*.haptic);;All Files (*)"
        )
        if not path: 
            return
        
        if self.current_event and self.current_event.load_from_haptic_file(path):
            self.update_ui()
            self.file_info_label.setText(f"Loaded: {os.path.basename(path)}")
            self.log_info_message(f"File imported: {os.path.basename(path)}")
        else:
            QMessageBox.critical(self, "Error", f"Could not import \"{os.path.basename(path)}\".")

    def import_csv_waveform(self):
        """Import a CSV waveform."""
        if self.current_event is None: 
            self.current_event = HapticEvent()
        
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV waveform", "", "CSV (*.csv)")
        if not path: 
            return
        
        try:
            t, y, sr = load_csv_waveform(path)
            dur = float(t[-1]) if t.size else (len(y) / sr if sr > 0 else 0.0)
            amp = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq = (self.current_event.waveform_data.frequency
                    if self.current_event.waveform_data and self.current_event.waveform_data.frequency
                    else [{"time": 0.0, "frequency": 0.0}, {"time": dur, "frequency": 0.0}])
            self.current_event.waveform_data = WaveformData(amp, freq, dur, sr)
            tags = self.current_event.metadata.tags or []
            if "imported-csv" not in tags: 
                self.current_event.metadata.tags = tags + ["imported-csv"]
            self.update_ui()
            self.log_info_message(f"CSV imported: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def generate_from_math(self):
        """Generate waveform from mathematical equation."""
        if not self.current_event: 
            return
        
        try:
            f = float(self.math_freq.value())
            dur = float(self.math_dur.value())
            sr = float(self.math_sr.value())
            
            # Clamp values
            f = max(0.01, min(f, 5000.0))
            dur = max(0.05, min(dur, 30.0))
            sr = max(200.0, min(sr, 50000.0))
            
            n = int(round(sr * dur))
            t = np.arange(n, dtype=float) / sr
            expr = self.math_equation.text().strip()
            
            if not expr: 
                raise ValueError("Equation is empty.")
            
            y = safe_eval_equation(expr, {"t": t, "f": f, "A": 1.0, "phi": 0.0})
            y = normalize_signal(y)
            
            if not np.isfinite(y).all(): 
                raise ValueError("Signal contains NaN/Inf.")
            
            amp = [{"time": float(tt), "amplitude": float(yy)} for tt, yy in zip(t, y)]
            freq = [{"time": 0.0, "frequency": f}, {"time": dur, "frequency": f}]
            self.current_event.waveform_data = WaveformData(amp, freq, dur, sr)
            
            tags = getattr(self.current_event.metadata, "tags", None) or []
            if "generated" not in tags: 
                tags.append("generated")
            self.current_event.metadata.tags = tags
            
            self.update_ui()
            self.log_info_message("Waveform generated from equation")
        except Exception as e:
            self.log_info_message(f"Equation error: {e}")

    def update_ui(self):
        """Update the UI to reflect the current event."""
        if not self.current_event:
            self.setWindowTitle("Universal Haptic Waveform Designer")
            return

        # Block signals while updating
        if hasattr(self, "name_edit"):
            self.name_edit.blockSignals(True)
        if hasattr(self, "description_edit"):
            self.description_edit.blockSignals(True)
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(True)

        # Update name
        if hasattr(self, "name_edit"):
            self.name_edit.setText(self.current_event.metadata.name)

        # Update category
        cat_text = self.current_event.metadata.category.value
        tags = self.current_event.metadata.tags or []
        for t in tags:
            if t.startswith("category_name="):
                cat_text = t.split("=", 1)[1]
                break

        base_list = getattr(self, "_base_categories", None)
        if base_list is None:
            base_list = [c.value for c in EventCategory]
            self._base_categories = base_list

        if hasattr(self, "category_combo"):
            idx = self.category_combo.findText(cat_text)
            if cat_text in base_list and idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            else:
                self.category_combo.setEditText(cat_text)

        # Update description
        if hasattr(self, "description_edit"):
            self.description_edit.setPlainText(self.current_event.metadata.description)

        # Unblock signals
        if hasattr(self, "name_edit"):
            self.name_edit.blockSignals(False)
        if hasattr(self, "description_edit"):
            self.description_edit.blockSignals(False)
        if hasattr(self, "category_combo"):
            self.category_combo.blockSignals(False)

        # Update editor
        if hasattr(self, "drop_proxy") and hasattr(self.drop_proxy, "set_event"):
            self.drop_proxy.set_event(self.current_event)

        # Update file label
        if hasattr(self, "file_info_label"):
            if self.current_event.original_haptic_file:
                self.file_info_label.setText(
                    f"Loaded: {os.path.basename(self.current_event.original_haptic_file)}"
                )
            else:
                self.file_info_label.setText("No file loaded")

        # Update window title
        title = self.current_event.metadata.name or "Untitled"
        self.setWindowTitle(f"Universal Haptic Waveform Designer – {title}")

    def closeEvent(self, event):
        """Handle application close."""
        if self.export_watch_dir: 
            self.dir_watcher.removePath(self.export_watch_dir)
        if self.serial_api.connected: 
            self.serial_api.disconnect_serial_device()
        event.accept()

def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    apply_ultra_clean_theme(app)
    load_ultra_clean_qss(app)
    
    app.setApplicationName("Universal Haptic Waveform Designer")
    app.setApplicationVersion("2.3")
    app.setOrganizationName("Haptic Systems")
    
    window = UniversalEventDesigner()
    window.show()
    window.log_info_message("Application ready - Ultra Clean Interface")
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()