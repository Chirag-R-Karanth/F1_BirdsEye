from __future__ import annotations
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from .models import CarState, Driver, SessionInfo, Snapshot, parse_float


def ts(v: str) -> float:
    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()


def norm_compound(v: str | None) -> str | None:
    if not v: return None
    return {"SOFT":"S", "MEDIUM":"M", "HARD":"H", "INTERMEDIATE":"I", "WET":"W"}.get(v.upper(), v[:1].upper())

class ReplayEngine:
    def __init__(self, session: SessionInfo, drivers: dict[int, Driver], data: dict[str, Any]):
        self.session = session
        self.drivers = drivers
        self.data = data
        self._indexes: dict[str, dict[int, list[dict[str, Any]]]] = {}
        for key in ("location", "car_data", "position", "intervals", "stints", "laps", "race_control"):
            grouped = defaultdict(list)
            for row in data.get(key, []):
                n = row.get("driver_number")
                if n is not None and "date" in row:
                    grouped[int(n)].append(row)
            for rows in grouped.values():
                rows.sort(key=lambda r: ts(r["date"]))
            self._indexes[key] = dict(grouped)

    def _at(self, kind: str, number: int, when: float) -> dict[str, Any] | None:
        rows = self._indexes.get(kind, {}).get(number, [])
        if not rows: return None
        dates = [ts(r["date"]) for r in rows]
        i = bisect_right(dates, when) - 1
        return rows[i] if i >= 0 else None

    def _location(self, number: int, when: float):
        r = self._at("location", number, when)
        return (r.get("x"), r.get("y")) if r else (None, None)

    def _stint(self, number: int, lap: int | None):
        if lap is None: return None
        rows = self.data.get("stints", [])
        best = None
        for r in rows:
            if int(r.get("driver_number", -1)) != number: continue
            if int(r.get("lap_start", 10**9)) <= lap <= int(r.get("lap_end", -1)):
                best = r
        return best

    def _last_lap(self, number: int, lap: int | None):
        if lap is None: return None
        rows = [r for r in self.data.get("laps", []) if int(r.get("driver_number", -1)) == number and int(r.get("lap_number", -1)) < lap]
        if not rows: return None
        return rows[-1].get("lap_duration")

    def snapshot(self, clock: float) -> Snapshot:
        elapsed = max(0.0, min(clock - self.session.start, self.session.end - self.session.start))
        when = self.session.start + elapsed
        cars = []
        for number, d in self.drivers.items():
            posr = self._at("position", number, when)
            intr = self._at("intervals", number, when)
            tele = self._at("car_data", number, when)
            locx, locy = self._location(number, when)
            lapr = None
            for r in self.data.get("laps", []):
                if int(r.get("driver_number", -1)) == number and r.get("date_start") and ts(r["date_start"]) <= when:
                    if lapr is None or int(r.get("lap_number", 0)) > int(lapr.get("lap_number", 0)): lapr = r
            lap = int(lapr["lap_number"]) if lapr else None
            stint = self._stint(number, lap)
            age = None
            tyre = None
            if stint:
                tyre = norm_compound(stint.get("compound"))
                age = int(stint.get("tyre_age_at_start") or 0) + max(0, (lap or 0) - int(stint.get("lap_start") or 0))
            gap = intr.get("gap_to_leader") if intr else None
            interval = intr.get("interval") if intr else None
            if isinstance(gap, str): gapv = gap
            else: gapv = parse_float(gap)
            cars.append(CarState(number, d.code, d.name, d.team, f"#{d.color}",
                int(posr["position"]) if posr and posr.get("position") is not None else None,
                gapv, parse_float(interval), tyre, age,
                parse_float(locx), parse_float(locy),
                parse_float(tele.get("speed")) if tele else None,
                int(tele["n_gear"]) if tele and tele.get("n_gear") is not None else None,
                parse_float(tele.get("throttle")) if tele else None,
                parse_float(tele.get("brake")) if tele else None,
                int(tele["drs"]) if tele and tele.get("drs") is not None else None,
                int(tele["rpm"]) if tele and tele.get("rpm") is not None else None,
                lap, parse_float(self._last_lap(number, lap))))
        cars.sort(key=lambda c: c.pos if c.pos is not None else 999)
        current_lap = max((c.lap or 0 for c in cars), default=0) or None
        status = self._status(when)
        return Snapshot(current_lap, self.session.total_laps, elapsed, status, cars)

    def _status(self, when: float) -> str | None:
        rows = [r for r in self.data.get("race_control", []) if r.get("date") and ts(r["date"]) <= when]
        if not rows: return None
        r = rows[-1]
        flag = r.get("flag")
        if flag in {"RED", "YELLOW", "DOUBLE YELLOW", "GREEN", "CHEQUERED"}: return flag
        msg = str(r.get("message", ""))
        if "VIRTUAL SAFETY CAR" in msg.upper(): return "VSC"
        if "SAFETY CAR" in msg.upper(): return "SC"
        return None

    def track_outline(self):
        # Prefer a clean non-pit-out lap from the first driver with usable lap metadata.
        laps = [r for r in self.data.get("laps", []) if not r.get("is_pit_out_lap") and r.get("date_start") and r.get("lap_duration")]
        if not laps: return []
        laps.sort(key=lambda r: float(r.get("lap_duration") or 10**9))
        chosen = laps[len(laps)//3]
        number = int(chosen["driver_number"])
        start = ts(chosen["date_start"])
        end = start + float(chosen["lap_duration"])
        pts = [(float(r["x"]), float(r["y"])) for r in self.data.get("location", [])
               if int(r.get("driver_number", -1)) == number and r.get("date") and start <= ts(r["date"]) <= end and r.get("x") is not None and r.get("y") is not None]
        if len(pts) < 20:
            return []
        # Downsample while preserving the shape.
        step = max(1, len(pts) // 700)
        return pts[::step]
