from __future__ import annotations
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from typing import Any
from .models import CarState, Driver, SessionInfo, Snapshot, parse_float


def ts(v: str) -> float:
    return datetime.fromisoformat(v.replace('Z', '+00:00')).timestamp()


def norm_compound(v: str | None) -> str | None:
    if not v: return None
    return {'SOFT':'S','MEDIUM':'M','HARD':'H','INTERMEDIATE':'I','WET':'W'}.get(v.upper(), v[:1].upper())


class ReplayEngine:
    def __init__(self, session: SessionInfo, drivers: dict[int, Driver], data: dict[str, Any]):
        self.session = session
        self.drivers = drivers
        self.data = data
        self._indexes: dict[str, dict[int, list[dict[str, Any]]]] = {}
        for key in ('location','car_data','position','intervals','stints','laps'):
            grouped = defaultdict(list)
            for row in data.get(key, []):
                n = row.get('driver_number')
                date = row.get('date')
                if n is not None and date:
                    grouped[int(n)].append(row)
            for rows in grouped.values(): rows.sort(key=lambda r: ts(r['date']))
            self._indexes[key] = dict(grouped)
        self._dates = {k: {n:[ts(r['date']) for r in rows] for n,rows in groups.items()} for k,groups in self._indexes.items()}

    def _at(self, kind: str, number: int, when: float):
        rows = self._indexes.get(kind, {}).get(number, [])
        if not rows: return None
        dates = self._dates[kind][number]
        i = bisect_right(dates, when) - 1
        return rows[i] if i >= 0 else None

    def _location(self, number, when):
        r = self._at('location', number, when)
        return (parse_float(r.get('x')), parse_float(r.get('y'))) if r else (None,None)

    def _stint(self, number, lap):
        if lap is None: return None
        best=None
        for r in self.data.get('stints',[]):
            if int(r.get('driver_number',-1)) == number and int(r.get('lap_start',10**9)) <= lap <= int(r.get('lap_end',-1)):
                best=r
        return best

    def _last_lap(self, number, lap):
        if lap is None:return None
        rows=[r for r in self.data.get('laps',[]) if int(r.get('driver_number',-1))==number and int(r.get('lap_number',-1)) < lap]
        rows.sort(key=lambda r:int(r.get('lap_number',0)))
        return parse_float(rows[-1].get('lap_duration')) if rows else None

    def _lap_row(self, number, when):
        best=None
        for r in self.data.get('laps',[]):
            if int(r.get('driver_number',-1)) != number: continue
            ds=r.get('date_start')
            if ds and ts(ds) <= when and (best is None or int(r.get('lap_number',0)) > int(best.get('lap_number',0))): best=r
        return best

    def _status(self, when):
        rows=[r for r in self.data.get('race_control',[]) if r.get('date') and ts(r['date'])<=when]
        if not rows:return None
        r=rows[-1]; flag=r.get('flag')
        if flag in {'RED','YELLOW','DOUBLE YELLOW','GREEN','CHEQUERED','BLUE'}: return flag
        msg=str(r.get('message','')).upper()
        if 'VIRTUAL SAFETY CAR' in msg:return 'VSC'
        if 'SAFETY CAR' in msg:return 'SC'
        return None

    def _event_log(self, when, limit=10):
        rows=[r for r in self.data.get('race_control',[]) if r.get('date') and ts(r['date'])<=when]
        return rows[-limit:]

    def snapshot(self, clock: float) -> Snapshot:
        elapsed=max(0.0,min(clock-self.session.start,self.session.end-self.session.start))
        when=self.session.start+elapsed
        cars=[]
        for number,d in self.drivers.items():
            posr=self._at('position',number,when); intr=self._at('intervals',number,when); tele=self._at('car_data',number,when)
            x,y=self._location(number,when); lapr=self._lap_row(number,when)
            lap=int(lapr['lap_number']) if lapr else None
            stint=self._stint(number,lap); tyre=None; age=None
            if stint:
                tyre=norm_compound(stint.get('compound'))
                age=int(stint.get('tyre_age_at_start') or 0)+max(0,(lap or 0)-int(stint.get('lap_start') or 0))
            gap=intr.get('gap_to_leader') if intr else None
            gap=parse_float(gap) if not isinstance(gap,str) else gap
            cars.append(CarState(number,d.code,d.name,d.team,f'#{d.color}',
                int(posr['position']) if posr and posr.get('position') is not None else None,
                gap,parse_float(intr.get('interval')) if intr else None,tyre,age,x,y,
                parse_float(tele.get('speed')) if tele else None,
                int(tele['n_gear']) if tele and tele.get('n_gear') is not None else None,
                parse_float(tele.get('throttle')) if tele else None,
                parse_float(tele.get('brake')) if tele else None,
                int(tele['drs']) if tele and tele.get('drs') is not None else None,
                int(tele['rpm']) if tele and tele.get('rpm') is not None else None,
                lap,self._last_lap(number,lap)))
        cars.sort(key=lambda c:c.pos if c.pos is not None else 999)
        current=max((c.lap or 0 for c in cars),default=0) or None
        return Snapshot(current,self.session.total_laps,elapsed,self._status(when),cars)

    def track_outline(self):
        laps=[r for r in self.data.get('laps',[]) if not r.get('is_pit_out_lap') and r.get('date_start') and r.get('lap_duration')]
        laps.sort(key=lambda r:float(r.get('lap_duration') or 10**9))
        # Try several representative clean laps; don't assume the fastest driver's location feed survived.
        for chosen in laps[:min(12,len(laps))]:
            number=int(chosen['driver_number']); start=ts(chosen['date_start']); end=start+float(chosen['lap_duration'])
            pts=[]
            for r in self.data.get('location',[]):
                if int(r.get('driver_number',-1))==number and r.get('date') and start<=ts(r['date'])<=end and r.get('x') is not None and r.get('y') is not None:
                    pts.append((float(r['x']),float(r['y'])))
            if len(pts)>=20:
                step=max(1,len(pts)//900)
                return pts[::step]
        # Fallback: use all location samples, ordered by driver/date, and form a cloud.
        pts=[(float(r['x']),float(r['y'])) for r in self.data.get('location',[]) if r.get('x') is not None and r.get('y') is not None]
        if len(pts)>=20:
            return pts[::max(1,len(pts)//1200)]
        return []
