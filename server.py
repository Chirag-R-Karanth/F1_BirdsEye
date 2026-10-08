from __future__ import annotations
import asyncio, os, time
from collections import defaultdict
from datetime import datetime, timezone
from f1.api import OpenF1Client, OpenF1Error
from f1.cache import Cache
from f1.models import Driver, SessionInfo
from f1.replay import ReplayEngine, ts

client=OpenF1Client(); READY=asyncio.Event(); LIVE=os.getenv('MODE','replay').lower()=='live'; DELAY=float(os.getenv('OPENF1_DELAY','8'))
class State:
    def __init__(self):
        self.session={}; self.clock=0.; self.start=0.; self.end=0.; self.speed=1; self.paused=False; self.loaded=0.; self.epoch=0; self.outline=[]; self.engine=None; self.snapshot=None; self.status=None
S=State()

async def fetch_cached(cache,name,endpoint,params,auth=False):
    data=cache.load(name)
    if data is not None:return data
    data=await client.get(endpoint,params,auth=auth); cache.save(name,data); return data

async def fetch_driver_stream(cache,name,endpoint,drivers):
    out=[]
    for n in drivers:
        key=f'{name}_d{n}_full'; data=cache.load(key)
        if data is None:
            try:data=await client.get(endpoint,{'session_key':int(cache.root.name),'driver_number':n})
            except Exception as e:
                # One broken driver's stream must never erase everyone else's map/telemetry.
                data=[]
            cache.save(key,data)
        out.extend(data or [])
    return out

async def latest_race():
    rows=await client.get('sessions',{'session_name':'Race','year':datetime.now(timezone.utc).year})
    races=[r for r in rows if not r.get('is_cancelled') and r.get('date_end')]
    if not races:
        rows=await client.get('sessions',{'session_name':'Race'}); races=[r for r in rows if not r.get('is_cancelled') and r.get('date_end')]
    if not races:raise OpenF1Error('No completed race session found')
    now=datetime.now(timezone.utc).timestamp(); finished=[r for r in races if ts(r['date_end'])<now]
    return max(finished or races,key=lambda r:ts(r['date_end']))

async def load_session(session_key=None):
    s=await latest_race() if session_key is None else (await client.get('sessions',{'session_key':session_key}))[0]
    key=int(s['session_key']); cache=Cache(key)
    raw=await fetch_cached(cache,'drivers','drivers',{'session_key':key})
    drivers={int(r['driver_number']):Driver(int(r['driver_number']),r.get('name_acronym','???'),r.get('full_name',r.get('broadcast_name','')),r.get('team_name',''),r.get('team_colour','FFFFFF')) for r in raw}
    start,end=ts(s['date_start']),ts(s['date_end']); nums=sorted(drivers)
    async def low(name):
        try:return name,await fetch_cached(cache,name,name,{'session_key':key})
        except Exception:return name,[]
    results=await asyncio.gather(
        fetch_driver_stream(cache,'location','location',nums),
        fetch_driver_stream(cache,'car_data','car_data',nums),
        *[low(x) for x in ('position','intervals','stints','laps','race_control','weather','pit','overtakes')]
    )
    data={'location':results[0],'car_data':results[1]}; data.update(dict(results[2:]))
    sr=await fetch_cached(cache,'session_result','session_result',{'session_key':key})
    total=max((int(r.get('number_of_laps',0)) for r in sr),default=0) or None
    info=SessionInfo(key,int(s.get('meeting_key',0)),int(s.get('year',0)),s.get('circuit_short_name',''),s.get('meeting_name',''),s.get('session_name','Race'),s.get('session_type','Race'),start,end,total)
    S.session=s; S.start=start; S.end=end; S.clock=start; S.loaded=start; S.engine=ReplayEngine(info,drivers,data); S.outline=S.engine.track_outline(); S.snapshot=S.engine.snapshot(start); READY.set()

async def init():
    try:
        k=os.getenv('SESSION_KEY'); await load_session(int(k) if k else None)
    except Exception as e:
        S.session={'error':str(e)}; READY.set(); raise

async def feeder():
    if not LIVE:return
    await READY.wait()
    while True:
        try:
            S.clock=time.time()-DELAY
            if S.engine:S.snapshot=S.engine.snapshot(S.clock)
        except Exception:pass
        await asyncio.sleep(1)

def snapshot(clock=None):
    if S.engine is None:return None
    if LIVE: return S.snapshot
    S.snapshot=S.engine.snapshot(S.clock if clock is None else clock); return S.snapshot

if __name__=='__main__':
    from tui import Tracker
    Tracker().run()
