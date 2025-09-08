# test_stroke_worker.py
import sys, time
from collections import defaultdict

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

# ⬇️ ADAPT THIS IMPORT to your package/module path
# from your_module import StrokePlaybackWorker
from your_module_file import StrokePlaybackWorker  # e.g., from Main_GUI.Pattern_Generator import StrokePlaybackWorker

TOL_MS_ON  = 20   # acceptable jitter for ON relative to step_started
TOL_MS_OFF = 25   # acceptable jitter for OFF relative to (step_started + dur_ms)

class FakeAPI:
    """Minimal fake device API that records all send_command calls with timestamps."""
    def __init__(self):
        self.calls = []  # list of dict(ts_ms, addr, inten, freq, mode)

    def send_command(self, addr, intensity, freq_code, mode):
        self.calls.append({
            "ts_ms": time.perf_counter() * 1000.0,
            "addr": int(addr),
            "inten": int(intensity),
            "freq": int(freq_code),
            "mode": int(mode),  # 1 = ON burst, 0 = OFF in our usage
        })

def run_worker_and_wait(worker, timeout_ms=5000):
    loop = QEventLoop()
    done = {"ok": None, "msg": None}
    worker.finished.connect(lambda ok, msg: (done.update(ok=ok, msg=msg), loop.quit()))
    worker.start()
    # hard timeout to avoid hanging tests
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    if worker.isRunning():
        worker.stop()
        worker.wait(1500)
    return done

def pick_event_after(events, predicate, not_before_ms, used):
    for i, ev in enumerate(events):
        if i in used:
            continue
        if ev["ts_ms"] >= not_before_ms and predicate(ev):
            used.add(i)
            return ev
    return None

def test_normal_run():
    print("\n=== test_normal_run ===")
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    # Simple schedule: three steps, some multi-actuator bursts
    schedule = [
        {"t_on": 0,   "dur_ms": 50, "bursts": [(0, 10), (1, 8)],   "pt": (0.1, 0.1)},
        {"t_on": 60,  "dur_ms": 50, "bursts": [(1, 10)],           "pt": (0.3, 0.2)},
        {"t_on": 120, "dur_ms": 50, "bursts": [(2, 10), (0, 4)],   "pt": (0.6, 0.4)},
    ]

    api = FakeAPI()
    worker = StrokePlaybackWorker(api, schedule, freq_code=4)

    step_ts = {}
    worker.step_started.connect(lambda i, bursts, pt:
                                step_ts.setdefault(i, time.perf_counter() * 1000.0))

    result = run_worker_and_wait(worker)
    print("finished:", result)

    # Split recorded calls into ON and OFF lists
    ons  = [ev for ev in api.calls if ev["inten"] > 0]
    offs = [ev for ev in api.calls if ev["inten"] == 0]

    # For matching, keep track of used indices
    used_on_idx  = set()
    used_off_idx = set()
    errors = []

    # Validate ON near step_started, and OFF near step_started + dur_ms
    for i, step in enumerate(schedule):
        if i not in step_ts:
            errors.append(f"Missing step_started for step {i}")
            continue
        t0 = step_ts[i]
        dur = step["dur_ms"]

        for addr, inten in step["bursts"]:
            # Find the ON for this addr right after step_started
            on_ev = pick_event_after(
                ons,
                predicate=lambda e, a=addr, it=inten: e["addr"] == a and e["inten"] == it,
                not_before_ms=t0 - 5,  # tiny leeway
                used=used_on_idx
            )
            if not on_ev:
                errors.append(f"[STEP {i}] Missing ON for addr {addr} inten {inten}")
            else:
                delta_on = on_ev["ts_ms"] - t0
                if abs(delta_on) > TOL_MS_ON:
                    errors.append(f"[STEP {i}] ON timing off for addr {addr}: "
                                  f"{delta_on:.1f} ms (tol ±{TOL_MS_ON} ms)")

            # Find the OFF for this addr near t0+dur
            target_off = t0 + dur
            off_ev = pick_event_after(
                offs,
                predicate=lambda e, a=addr: e["addr"] == a,
                not_before_ms=t0 + 1,  # after step start
                used=used_off_idx
            )
            if not off_ev:
                errors.append(f"[STEP {i}] Missing OFF for addr {addr}")
            else:
                delta_off = off_ev["ts_ms"] - target_off
                if abs(delta_off) > TOL_MS_OFF:
                    errors.append(f"[STEP {i}] OFF timing off for addr {addr}: "
                                  f"{delta_off:.1f} ms (tol ±{TOL_MS_OFF} ms)")

    if errors:
        print("❌ FAIL")
        for e in errors:
            print("   -", e)
        return False

    print("✅ PASS (normal run)")
    return True

def test_stop_path():
    print("\n=== test_stop_path ===")
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    # Longer schedule so we can stop mid-way
    schedule = []
    t = 0
    for k in range(20):
        schedule.append({"t_on": t, "dur_ms": 60, "bursts": [(k % 3, 12)], "pt": (0.2, 0.2)})
        t += 70

    api = FakeAPI()
    worker = StrokePlaybackWorker(api, schedule, freq_code=4)

    # Stop after ~150 ms
    QTimer.singleShot(150, worker.stop)

    result = run_worker_and_wait(worker, timeout_ms=4000)
    print("finished:", result)

    # For each address that ever received ON, ensure its last event is an OFF
    last_by_addr = defaultdict(lambda: None)
    for ev in api.calls:
        last_by_addr[ev["addr"]] = ev

    addrs_with_on = {ev["addr"] for ev in api.calls if ev["inten"] > 0}
    errors = []
    for addr in addrs_with_on:
        last = last_by_addr.get(addr)
        if last is None or last["inten"] != 0:
            errors.append(f"Last event for addr {addr} is not OFF after stop")

    if errors:
        print("❌ FAIL")
        for e in errors:
            print("   -", e)
        return False

    print("✅ PASS (stop path flushes OFFs)")
    return True

if __name__ == "__main__":
    ok1 = test_normal_run()
    ok2 = test_stop_path()
    sys.exit(0 if (ok1 and ok2) else 1)