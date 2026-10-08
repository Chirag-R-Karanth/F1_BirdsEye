from __future__ import annotations
import time
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Static
import server
from server import S
BITS={(0,0):1,(0,1):2,(0,2):4,(1,0):8,(1,1):16,(1,2):32,(0,3):64,(1,3):128}
TYRE={'S':'red','M':'yellow','H':'white','I':'green','W':'dodger_blue1'}

def clock(s):
 s=max(0,int(s)); h,m,sec=s//3600,s%3600//60,s%60; return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'
def lap_time(s): return '-' if s is None else f'{int(s//60)}:{s%60:06.3f}'
def num(v): return f'+{v:.3f}' if isinstance(v,(int,float)) else (v or '')
def bar(v,w=18): v=max(0,min(100,float(v or 0))); n=round(v/100*w); return '█'*n+'░'*(w-n)
def spark(vals):
 chars='▁▂▃▄▅▆▇█'; clean=[v for v in vals[-90:] if isinstance(v,(int,float))]; scale=max(1,max(clean,default=360)); return ''.join(' ' if v is None else chars[min(7,max(0,int(v/scale*8)-1))] for v in vals[-90:])

class MapView(Static):
 def __init__(self,**kw): super().__init__(**kw); self.outline=[]; self.hitboxes={}; self._cache=None
 def draw(self,cars,sel):
  W,H=self.size.width,self.size.height
  if W<20 or H<8:return
  pts=self.outline or [(c.x,c.y) for c in cars if c.x is not None and c.y is not None]
  if len(pts)<2:self.update(Text('MAP DATA UNAVAILABLE\nWaiting for location telemetry…',style='dim')); return
  xs,ys=zip(*pts); x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys); DW,DH=W*2,H*4; pad=4; scale=min((DW-2*pad)/max(1,x1-x0),(DH-2*pad)/max(1,y1-y0)); ox=(DW-(x1-x0)*scale)/2; oy=(DH-(y1-y0)*scale)/2
  def P(x,y):return ox+(x-x0)*scale,DH-1-(oy+(y-y0)*scale)
  key=(W,H,len(self.outline),self.outline[0] if self.outline else None)
  if not self._cache or self._cache[0]!=key:
   mask={}
   def dot(px,py):
    px,py=int(px),int(py)
    if 0<=px<DW and 0<=py<DH:
     cell=(px//2,py//4); mask[cell]=mask.get(cell,0)|BITS[(px%2,py%4)]
   if self.outline:
    prev=P(*self.outline[-1])
    for point in self.outline:
     q=P(*point); n=int(max(abs(q[0]-prev[0]),abs(q[1]-prev[1])))+1
     for i in range(n+1):dot(prev[0]+(q[0]-prev[0])*i/n,prev[1]+(q[1]-prev[1])*i/n)
     prev=q
   self._cache=(key,mask)
  labels={}; self.hitboxes={}
  for c in sorted([c for c in cars if c.x is not None and c.y is not None],key=lambda c:(c.number!=sel,c.pos or 99)):
   px,py=P(c.x,c.y); cx=min(max(int(px)//2,0),W-5); cy=min(max(int(py)//4,0),H-1); self.hitboxes[c.number]=(cx,cy); on=c.number==sel; labels[(cx,cy)]=('●',Style(color=c.color,bold=True));
   for dy in (0,-1,1,-2,2):
    yy=cy+dy
    if 0<=yy<H and all((cx+1+i,yy) not in labels for i in range(len(c.code))):
     st=Style(color='black',bgcolor='white',bold=True) if on else Style(color='white',bold=True)
     for i,ch in enumerate(c.code):labels[(cx+1+i,yy)]=(ch,st)
     break
  out=Text(no_wrap=True)
  mask=self._cache[1]
  for y in range(H):
   for x in range(W):
    if (x,y) in labels:out.append(*labels[(x,y)])
    elif (x,y) in mask:out.append(chr(0x2800+mask[(x,y)]),'grey50')
    else:out.append(' ')
   if y<H-1:out.append('\n')
  self.update(out)
 def on_click(self,event):
  if not self.hitboxes:return
  n=min(self.hitboxes,key=lambda n:(self.hitboxes[n][0]-event.x)**2+(self.hitboxes[n][1]-event.y)**2)
  if (self.hitboxes[n][0]-event.x)**2+(self.hitboxes[n][1]-event.y)**2<=36:self.app.select_driver(n)

class DriverRow(Static):
 def __init__(self,number,**kw):super().__init__(**kw);self.number=number
 def on_click(self):self.app.select_driver(self.number)

class Tracker(App):
 CSS='''
 Screen{background:#0d1117;color:#d7dde8} #top{height:2;padding:0 1;background:#171d27;border-bottom:solid #303a4a} #body{height:1fr} #map{width:1fr;border-right:solid #303a4a} #side{width:55} #board{height:1fr;padding:0 1;overflow-y:auto} #tele{height:14;border-top:solid #303a4a;padding:0 1} #bottom{height:7;border-top:solid #303a4a;padding:0 1} Footer{height:1}
 '''
 BINDINGS=[Binding('q','quit','Quit'),Binding('space','pause','Pause'),Binding('up','move(-1)','Prev'),Binding('down','move(1)','Next'),Binding('enter','select','Select'),Binding('escape','clear','Clear'),Binding('1','speed(1)','1x'),Binding('2','speed(2)','2x'),Binding('5','speed(5)','5x'),Binding('b','jump(-60)','-1m'),Binding('f','jump(60)','+1m'),Binding('home','home','Start'),Binding('end','end','End')]
 def compose(self)->ComposeResult:
  yield Static('Loading…',id='top')
  with Horizontal(id='body'):
   yield MapView(id='map')
   with Vertical(id='side'):yield Static(id='board');yield Static(id='tele')
  yield Static(id='bottom');yield Footer()
 def on_mount(self):
  self.last=time.monotonic();self.sel=None;self.hist={};self.snap=None;self.run_worker(self.start(),exclusive=True);self.set_interval(1,self.tick)
 async def start(self):
  try:
   await server.init()
   if server.LIVE:self.run_worker(server.feeder())
  except Exception as e:self.query_one('#top').update(Text(f'OpenF1 ERROR  {e}',style='bold red'))
 def tick(self):
  if not server.READY.is_set() or not S.engine:return
  now=time.monotonic();dt=now-self.last;self.last=now
  if server.LIVE:S.clock=time.time()-server.DELAY
  elif not S.paused:S.clock=min(S.end,S.clock+dt*S.speed)
  s=server.snapshot(S.clock)
  if not s:return
  self.snap=s;m=self.query_one(MapView);m.outline=S.outline
  for c in s.cars:self.hist.setdefault(c.number,[]).append(c.speed);self.hist[c.number]=self.hist[c.number][-90:]
  self.refresh_ui()
 def refresh_ui(self):
  s=self.snap;se=S.session;mode='LIVE ● +8s' if server.LIVE else f'REPLAY {S.speed}×'+(' PAUSED' if S.paused else '');status=s.status or '—'; title=f"{se.get('circuit_short_name','')} {se.get('year','')}  {se.get('session_name','RACE')}   LAP {s.lap or '-'} / {s.total_laps or '-'}   {clock(s.elapsed)}   {status}   {mode}"
  self.query_one('#top').update(title);self.query_one(MapView).draw(s.cars,self.sel);self.query_one('#board').update(self.board(s.cars));self.query_one('#tele').update(self.tele(s.cars));self.query_one('#bottom').update(self.events(s.cars))
 def board(self,cars):
  t=Text();t.append(' P  DRV        GAP       INT   TYRE AGE\n','bold dim')
  for c in cars:
   bg='#29364d' if c.number==self.sel else None;st=lambda **kw:Style(bgcolor=bg,**kw);gap='LEADER' if c.pos==1 else num(c.gap) or '-';iv='' if c.pos==1 else num(c.interval) or '-';t.append('▌',st(color=c.color));t.append(f'{c.pos or "-":>2} ',st());t.append(f'{c.code:<4}',st(bold=True));t.append(f'{gap:>9}{iv:>9}  ',st(color='grey70'));t.append(c.tyre or ' ',st(bold=True,color=TYRE.get(c.tyre)));t.append(f'{c.age if c.age is not None else "-":>3}',st(color='grey70'));t.append('\n')
  return t
 def tele(self,cars):
  c=next((x for x in cars if x.number==self.sel),None)
  if not c:return Text('↑/↓ or click a car/row to select a driver',style='dim')
  gear='N' if c.gear==0 else '-' if c.gear is None else str(c.gear);drs='OPEN' if c.drs in (10,12,14) else 'CLOSED';thr=c.throttle or 0;brk=c.brake or 0
  t=Text();t.append(c.name or c.code,Style(bold=True,color=c.color));t.append(f'  {c.team}\n','dim');t.append(f'SPD {c.speed if c.speed is not None else "-":>3} km/h   GEAR {gear}   DRS {drs}\n',Style(bold=True));t.append(f'THR {bar(thr)} {thr:3.0f}%\n','green');t.append(f'BRK {bar(brk)} {brk:3.0f}%\n','red');t.append(f'RPM {c.rpm or "-":>5}   LAP {c.lap or "-":>2}   LAST {lap_time(c.last_lap)}\n');t.append('SPEED  '+spark(self.hist.get(c.number,[])),Style(color=c.color));return t
 def events(self,cars):
  # Race-control backlog: the latest events already loaded by the server.
  rows=server.S.engine.data.get('race_control',[]) if S.engine else []; rows=rows[-3:]
  t=Text();t.append('RACE CONTROL  ','bold');
  if not rows:t.append('no events loaded','dim');return t
  for r in rows:
   flag=r.get('flag') or r.get('category') or '';msg=r.get('message','');t.append(f'  {flag} {msg[:90]}','grey70')
  return t
 def select_driver(self,n):self.sel=n;self.refresh_ui()
 def action_move(self,d):
  if not self.snap:return
  ns=[c.number for c in self.snap.cars];i=ns.index(self.sel) if self.sel in ns else (-1 if d>0 else 0);self.sel=ns[(i+d)%len(ns)];self.refresh_ui()
 def action_select(self):
  if not self.sel:self.action_move(1)
 def action_clear(self):self.sel=None;self.refresh_ui()
 def action_pause(self):
  if not server.LIVE:S.paused=not S.paused;self.refresh_ui()
 def action_speed(self,n):
  if not server.LIVE:S.speed=n;self.refresh_ui()
 def action_jump(self,v):
  if not server.LIVE:S.clock=max(S.start,min(S.end,S.clock+v));self.refresh_ui()
 def action_home(self):
  if not server.LIVE:S.clock=S.start;self.refresh_ui()
 def action_end(self):
  if not server.LIVE:S.clock=S.end;self.refresh_ui()

if __name__=='__main__':Tracker().run()
