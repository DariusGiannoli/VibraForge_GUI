# timeline_widget.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Callable
import time, json
from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal, QObject
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QGraphicsView, QGraphicsScene, QGraphicsRectItem,
                             QGraphicsSimpleTextItem, QFileDialog)
from PyQt6.QtGui import QColor, QBrush, QPen, QPainter

@dataclass
class TimelineEvent:
    start: float
    duration: float
    pattern: str
    params: Dict[str, Any]
    actuators: List[int]
    id: int = field(default_factory=lambda: int(time.time() * 1000))
    @property
    def end(self) -> float: return self.start + self.duration

class TimelineModel(QObject):
    changed = pyqtSignal()
    def __init__(self): super().__init__(); self.events: List[TimelineEvent] = []; self.length: float = 10.0
    def add(self, ev: TimelineEvent):
        self.events.append(ev); self.events.sort(key=lambda e: e.start)
        self.length = max(self.length, ev.end); self.changed.emit()
    def clear(self): self.events.clear(); self.length = 10.0; self.changed.emit()
    def remove_by_id(self, ev_id: int): self.events = [e for e in self.events if e.id != ev_id]; self.changed.emit()
    def to_dict(self) -> Dict[str, Any]: return {"length": self.length, "events": [e.__dict__ for e in self.events]}
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TimelineModel":
        m = TimelineModel(); m.length = d.get("length", 10.0)
        for e in d.get("events", []): m.events.append(TimelineEvent(**e))
        m.changed.emit(); return m

class TimelineView(QGraphicsView):
    event_double_clicked = pyqtSignal(int)
    def __init__(self, model: TimelineModel, px_per_s: float = 100.0):
        super().__init__(); self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.model = model; self.px_per_s = px_per_s
        self.scene = QGraphicsScene(self); self.setScene(self.scene)
        self.model.changed.connect(self._rebuild); self._rebuild()
    def _x(self, t: float) -> float: return t * self.px_per_s
    def _rebuild(self):
        self.scene.clear(); h = 60
        self.scene.addRect(QRectF(0, 0, self._x(self.model.length), h),
                           QPen(QColor(210,210,210)), QBrush(QColor(245,245,245)))
        for s in range(int(self.model.length)+1):
            x = self._x(s); self.scene.addLine(x, 0, x, h, QPen(QColor(200,200,200)))
            tick = QGraphicsSimpleTextItem(f"{s}s"); tick.setPos(x+2, h-18); self.scene.addItem(tick)
        for ev in self.model.events:
            x = self._x(ev.start); w = max(4.0, self._x(ev.duration))
            rect = QGraphicsRectItem(x, 10, w, 40)
            rect.setBrush(QBrush(QColor(170,200,255))); rect.setPen(QPen(QColor(60,90,160)))
            rect.setData(0, ev.id); self.scene.addItem(rect)
            label = QGraphicsSimpleTextItem(f"{ev.pattern} ({','.join(map(str, ev.actuators))})")
            label.setPos(x+6, 14); self.scene.addItem(label)
    def mouseDoubleClickEvent(self, e):
        item = self.itemAt(e.pos())
        if isinstance(item, QGraphicsRectItem):
            ev_id = item.data(0); 
            if ev_id: self.event_double_clicked.emit(int(ev_id))
        super().mouseDoubleClickEvent(e)

class TimelinePlayer(QObject):
    started = pyqtSignal(); stopped = pyqtSignal(); position_changed = pyqtSignal(float)
    def __init__(self, model: TimelineModel, start_cb: Callable[[TimelineEvent], None]):
        super().__init__(); self.model = model; self.start_cb = start_cb
        self.timer = QTimer(self); self.timer.setInterval(10); self.timer.timeout.connect(self._tick)
        self.t0 = 0.0; self.t = 0.0; self._started_ids: set[int] = set()
    def play(self): self.t0 = time.perf_counter() - self.t; self.timer.start(); self.started.emit()
    def pause(self): self.timer.stop(); self.stopped.emit()
    def stop(self): self.timer.stop(); self.t = 0.0; self._started_ids.clear(); self.position_changed.emit(self.t); self.stopped.emit()
    def _tick(self):
        self.t = max(0.0, time.perf_counter() - self.t0)
        for ev in self.model.events:
            if ev.id in self._started_ids: continue
            if self.t >= ev.start:
                self._started_ids.add(ev.id); self.start_cb(ev)
        if self.t >= self.model.length: self.stop()
        self.position_changed.emit(self.t)

class TimelineWidget(QWidget):
    def __init__(self, start_cb: Callable[[TimelineEvent], None]):
        super().__init__(); self.model = TimelineModel()
        self.view = TimelineView(self.model); self.player = TimelinePlayer(self.model, start_cb)
        btns = QHBoxLayout()
        self.playBtn, self.pauseBtn, self.stopBtn = QPushButton("Play"), QPushButton("Pause"), QPushButton("Stop")
        self.saveBtn, self.loadBtn = QPushButton("Save Timeline"), QPushButton("Load Timeline")
        for b in (self.playBtn,self.pauseBtn,self.stopBtn): btns.addWidget(b)
        btns.addStretch(1); btns.addWidget(self.saveBtn); btns.addWidget(self.loadBtn)
        layout = QVBoxLayout(self); layout.addWidget(self.view); layout.addLayout(btns)
        self.playBtn.clicked.connect(self.player.play); self.pauseBtn.clicked.connect(self.player.pause); self.stopBtn.clicked.connect(self.player.stop)
        self.saveBtn.clicked.connect(self._save); self.loadBtn.clicked.connect(self._load)
    def add_event(self, ev: TimelineEvent): self.model.add(ev)
    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Timeline", "", "Timeline (*.timeline.json)")
        if not path: return
        with open(path, "w", encoding="utf-8") as f: json.dump(self.model.to_dict(), f, indent=2)
    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Timeline", "", "Timeline (*.timeline.json)")
        if not path: return
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        self.model = TimelineModel.from_dict(data)
        self.view.model = self.model; self.view.model.changed.connect(self.view._rebuild); self.view._rebuild()
