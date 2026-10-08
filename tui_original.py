"""Terminal UI for the F1 tracker. Reuses the data layer in server.py.

    python tui.py                                   # replay latest finished race
    MODE=live OPENF1_USER=.. OPENF1_PASS=.. python tui.py

Keys: up/down select driver, esc deselect, space pause, 1/2/5 speed, b/f jump -/+1 min, q quit.
Needs a terminal of at least ~110x32.
"""
import time

import httpx
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Static

import server
from server import S

BITS = {(0, 0): 1, (0, 1): 2, (0, 2): 4, (1, 0): 8, (1, 1): 16, (1, 2): 32, (0, 3): 64, (1, 3): 128}
TYRE = {"S": "red", "M": "yellow", "H": "white", "I": "green", "W": "dodger_blue1"}
SEL_BG = "#36425a"


def clock(s):
    s = max(0, int(s))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def lap_time(s):
    return "-" if s is None else f"{int(s // 60)}:{s % 60:06.3f}"


def num(v):
    return f"+{v:.3f}" if isinstance(v, (int, float)) else (v or "")


def bar(v, w=20):
    n = round(max(0, min(100, v)) / 100 * w)
    return "█" * n + "░" * (w - n)


def spark(vals):
    out = ""
    for v in vals[-40:]:
        out += " " if v is None else "▁▂▃▄▅▆▇█"[min(7, int(v / 360 * 8))]
    return out


class MapView(Static):
    """Track drawn in braille dots, cars as colored dots with driver codes."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.outline, self.extra, self._cache = [], [], None

    def draw(self, cars, sel):
        W, H = self.size.width, self.size.height
        if W < 12 or H < 6:
            return
        track = self.outline or self.extra
        pts = track or [(c["x"], c["y"]) for c in cars if "x" in c]
        if not pts:
            self.update("Waiting for positions…")
            return
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        DW, DH, pad = W * 2, H * 4, 6
        s = min((DW - 2 * pad) / ((x1 - x0) or 1), (DH - 2 * pad) / ((y1 - y0) or 1))
        ox, oy = (DW - (x1 - x0) * s) / 2, (DH - (y1 - y0) * s) / 2

        def P(x, y):
            return ox + (x - x0) * s, DH - 1 - (oy + (y - y0) * s)

        key = (W, H, len(track), bool(self.outline))
        if self._cache is None or self._cache[0] != key:
            mask = {}

            def dot(px, py):
                px, py = int(px), int(py)
                if 0 <= px < DW and 0 <= py < DH:
                    c = (px // 2, py // 4)
                    mask[c] = mask.get(c, 0) | BITS[(px % 2, py % 4)]

            if self.outline:
                prev = None
                for x, y in self.outline + [self.outline[0]]:
                    q = P(x, y)
                    if prev:
                        n = int(max(abs(q[0] - prev[0]), abs(q[1] - prev[1]))) + 1
                        for i in range(n + 1):
                            dot(prev[0] + (q[0] - prev[0]) * i / n, prev[1] + (q[1] - prev[1]) * i / n)
                    prev = q
            else:
                for x, y in self.extra:
                    dot(*P(x, y))
            self._cache = (key, mask)
        mask = self._cache[1]

        labels = {}
        order = sorted((c for c in cars if "x" in c), key=lambda c: (c["n"] != sel, c["pos"] or 99))
        for c in order:
            px, py = P(c["x"], c["y"])
            cx = min(max(int(px) // 2, 0), W - 5)
            cy = min(max(int(py) // 4, 0), H - 1)
            on = c["n"] == sel
            labels.setdefault((cx, cy), ("●", Style(color=c["color"], bold=True)))
            code = c["code"]
            for dy in (0, -1, 1, -2, 2):
                y = cy + dy
                if 0 <= y < H and all((cx + 1 + i, y) not in labels for i in range(len(code))):
                    style = Style(color="black", bgcolor="white", bold=True) if on else Style(color="white", bold=True)
                    for i, ch in enumerate(code):
                        labels[(cx + 1 + i, y)] = (ch, style)
                    break

        out = Text(no_wrap=True)
        for y in range(H):
            for x in range(W):
                if (x, y) in labels:
                    out.append(*labels[(x, y)])
                elif (x, y) in mask:
                    out.append(chr(0x2800 + mask[(x, y)]), "grey50")
                else:
                    out.append(" ")
            if y < H - 1:
                out.append("\n")
        self.update(out)


class Tracker(App):
    CSS = """
    #top { height: 1; padding: 0 1; background: #222a3a; }
    #body { height: 1fr; }
    #map { width: 1fr; }
    #side { width: 46; border-left: solid #324058; }
    #board { height: 1fr; padding: 0 1; }
    #tele { height: 9; border-top: solid #324058; padding: 0 1; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("space", "pause", "Pause"),
        Binding("up", "move(-1)", "Prev"),
        Binding("down", "move(1)", "Next"),
        Binding("escape", "clear", "Deselect"),
        Binding("1", "speed(1)", "1x"),
        Binding("2", "speed(2)", "2x"),
        Binding("5", "speed(5)", "5x"),
        Binding("b", "jump(-60)", "-1 min"),
        Binding("f", "jump(60)", "+1 min"),
    ]

    sel = None
    snap = None
    hist: dict = {}

    def compose(self) -> ComposeResult:
        yield Static("Loading session…", id="top")
        with Horizontal(id="body"):
            yield MapView(id="map")
            with Vertical(id="side"):
                yield Static(id="board")
                yield Static(id="tele")
        yield Footer()

    def on_mount(self):
        server.client = httpx.AsyncClient(timeout=30)
        self.run_worker(server.init())
        self.run_worker(server.feeder())
        self.last = time.time()
        self.set_interval(1, self.tick)

    def tick(self):
        if not server.READY.is_set():
            return
        now = time.time()
        dt, self.last = now - self.last, now
        if server.LIVE:
            S.clock = now - server.DELAY
        elif not S.paused and S.loaded > S.clock + 1:  # wait for data instead of racing ahead
            S.clock += dt * S.speed
        self.snap = server.snapshot(S.clock)
        m = self.query_one(MapView)
        m.outline = S.outline
        for c in self.snap["cars"]:
            h = self.hist.setdefault(c["n"], [])
            h.append(c.get("speed"))
            del h[:-90]
            if not m.outline and "x" in c and len(m.extra) < 6000:
                m.extra.append((c["x"], c["y"]))
        self.refresh_ui()

    def refresh_ui(self):
        s = self.snap
        if not s:
            return
        cars = s["cars"]
        se = S.session
        mode = "live" if server.LIVE else f"replay {S.speed}x" + (" paused" if S.paused else "")
        title = f"{se.get('circuit_short_name', '')} {se.get('year', '')} {se.get('session_name', '')}"
        self.query_one("#top").update(Text(f"{title}   Lap {s['lap'] or '-'}   {clock(s['elapsed'])}   {mode}"))
        self.query_one(MapView).draw(cars, self.sel)
        self.query_one("#board").update(self.board(cars))
        self.query_one("#tele").update(self.tele(cars))

    def board(self, cars):
        t = Text()
        t.append(" P  Drv        Gap     Int  Tyre\n", "dim")
        for c in cars:
            bg = SEL_BG if c["n"] == self.sel else None

            def st(**kw):
                return Style(bgcolor=bg, **kw)

            gap = "Leader" if c["pos"] == 1 else (num(c.get("gap")) or "-")
            itv = "" if c["pos"] == 1 else (num(c.get("int")) or "-")
            t.append("▌", st(color=c["color"]))
            t.append(f"{c['pos'] or '-':>2} ", st())
            t.append(f"{c['code']:<4}", st(bold=True))
            t.append(f"{gap:>8}{itv:>8}  ", st(color="grey70"))
            tyre = c.get("tyre")
            t.append(tyre[0] if tyre else " ", st(bold=True, color=TYRE.get(tyre[0]) if tyre else None))
            t.append(f"{c.get('age') if c.get('age') is not None else '':>3}", st(color="grey70"))
            t.append("\n")
        return t

    def tele(self, cars):
        c = next((c for c in cars if c["n"] == self.sel), None)
        if not c:
            return Text("Up/down to select a driver", style="dim")
        thr, brk, gear = c.get("thr") or 0, c.get("brk") or 0, c.get("gear")
        t = Text()
        t.append(c["name"] or c["code"], Style(bold=True, color=c["color"]))
        t.append(f"  {c['team']}\n", "dim")
        t.append(f"{c.get('speed', '-')} km/h", "bold")
        t.append(f"   gear {'N' if gear == 0 else '-' if gear is None else gear}")
        t.append(f"   DRS {'open' if c.get('drs') in (10, 12, 14) else 'closed'}\n")
        t.append("Throttle ")
        t.append(bar(thr), "green")
        t.append(f" {thr:>3}%\nBrake    ")
        t.append(bar(brk), "red")
        t.append(f" {brk:>3}%\n")
        t.append(f"RPM {c.get('rpm', '-')}   Lap {c['lap'] or '-'}   Last {lap_time(c['last'])}\n")
        t.append(spark(self.hist.get(c["n"], [])), Style(color=c["color"]))
        return t

    def action_move(self, d: int):
        if not self.snap or not self.snap["cars"]:
            return
        ns = [c["n"] for c in self.snap["cars"]]
        i = ns.index(self.sel) if self.sel in ns else (-1 if d > 0 else 0)
        self.sel = ns[(i + d) % len(ns)]
        self.refresh_ui()

    def action_clear(self):
        self.sel = None
        self.refresh_ui()

    def action_pause(self):
        S.paused = not S.paused
        self.refresh_ui()

    def action_speed(self, n: int):
        S.speed = n
        self.refresh_ui()

    def action_jump(self, v: int):
        if server.LIVE or not server.READY.is_set():
            return
        S.clock = max(S.start, S.clock + v)
        S.loaded, S.epoch = S.clock, S.epoch + 1
        S.loc, S.car, S.ivl = server.Series(), server.Series(), server.Series()


if __name__ == "__main__":
    Tracker().run()