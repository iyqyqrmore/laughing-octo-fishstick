"""Read-only quote-history candles. Display-only; never a strategy price source."""
from calendar import monthrange
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from queue import Queue,Empty
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import ttk

from coincat_cross_quote import split_spot
from coincat_v6010_registry import STABLE_AND_FIAT
from coincat_hover import Hover

INTERVALS={'1s':1,'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400,
           '1 month':2629800,'1 year':31557600}
RANGES=('1 minute','1 hour','1 day','1 month','1 year','All stored')


def range_start(end,span):
    if span=='1 minute':return end-60
    if span=='1 hour':return end-3600
    if span=='1 day':return end-86400
    if span=='All stored':return None
    dt=datetime.fromtimestamp(end,timezone.utc)
    year,month=(dt.year-1,dt.month) if span=='1 year' else (dt.year-1,12) if dt.month==1 else (dt.year,dt.month-1)
    return dt.replace(year=year,month=month,day=min(dt.day,monthrange(year,month)[1])).timestamp()


def read_history(path,pair=None,*,interval='1m',span='1 day',end=None,cancel=None,max_candles=500,
                 allowed_products=None,native=False):
    """Aggregate stored midpoint samples into bounded display OHLC via read-only SQL.

    No interpolation, API requests, new schemas, pruning or financial database.
    SQLite REAL values are chart coordinates only, never native receipt inputs.
    Coarser calendar/clock buckets are explicit when needed to fit a wide range.
    """
    if interval not in INTERVALS or span not in RANGES or not 10<=max_candles<=1000:
        raise ValueError('INVALID_CHART_RANGE')
    if allowed_products is not None and pair is not None and pair not in allowed_products:
        return dict(state='OUTSIDE_APPROVED_WATCHLIST',pair=pair,products=[],candles=[])
    deadline=time.monotonic()+20
    stopped=lambda:(cancel is not None and cancel.is_set()) or time.monotonic()>deadline
    if stopped():return {'state':'CANCELLED','candles':[]}
    path=Path(path)
    if not path.is_file():return {'state':'NO_STORED_QUOTES','candles':[],'products':[]}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.execute('PRAGMA query_only=ON');db.set_progress_handler(lambda:int(stopped()),1000)
        try:
            products=[]
            scope='' if allowed_products is None else ' WHERE pair IN ('+','.join('?' for _ in allowed_products)+')'
            for (product,) in db.execute('SELECT DISTINCT pair FROM market_quotes'+scope,tuple(allowed_products or ())):
                try:
                    base,quote=split_spot(product)
                    companion=base if quote=='ETH' else quote if base=='ETH' else None
                    if native or (companion and companion!='ETH' and companion not in STABLE_AND_FIAT):products.append(product)
                except (ValueError,TypeError):continue
            products.sort()
            if pair is None:pair=next(iter(products),None)
            if pair not in products:return dict(state='NO_STORED_QUOTES',pair=pair,products=products,candles=[])
            base,quote=split_spot(pair)
            clock=time.time() if end is None else float(end)
            oldest,newest,count=db.execute('SELECT MIN(at_utc),MAX(at_utc),COUNT(*) FROM market_quotes WHERE pair=? AND at_utc<=?',(pair,time.time())).fetchone()
            if not count:return dict(state='NO_STORED_QUOTES',products=products,candles=[],pair=pair)
            start=range_start(clock,span)
            if start is None:
                start=oldest
                if end is None:clock=max(oldest+1,newest+1)
            duration=max(1,clock-start);effective=interval
            options=list(INTERVALS);index=options.index(interval)
            while duration/INTERVALS[effective]>max_candles-2 and index<len(options)-1:
                index+=1;effective=options[index]
            if duration/INTERVALS[effective]>max_candles-2:
                return dict(state='RANGE_TOO_LARGE',candles=[],products=products,pair=pair)
            if effective=='1 month':
                bucket="CAST(strftime('%s',datetime(at_utc,'unixepoch','start of month')) AS INTEGER)"
            elif effective=='1 year':
                bucket="CAST(strftime('%s',datetime(at_utc,'unixepoch','start of year')) AS INTEGER)"
            else:
                size=INTERVALS[effective];bucket=f'(at_utc/{size})*{size}'
            raw_bid='CAST(bid AS REAL)';raw_ask='CAST(ask AS REAL)'
            price=f'({raw_bid}+{raw_ask})/2.0' if native or quote=='ETH' else f'(1.0/{raw_ask}+1.0/{raw_bid})/2.0'
            valid=f'{raw_bid}>=1e-100 AND {raw_ask}>={raw_bid} AND {raw_ask}<1e100'
            query=f'''WITH grouped AS (
                SELECT {bucket} bucket,MIN(at_utc) first_at,MAX(at_utc) last_at,
                       MIN({price}) low,MAX({price}) high,COUNT(*) samples
                FROM market_quotes WHERE pair=? AND at_utc>=? AND at_utc<=? AND {valid}
                GROUP BY bucket)
                SELECT bucket,first_at,last_at,low,high,samples,
                    (SELECT {price} FROM market_quotes WHERE pair=? AND at_utc=g.first_at),
                    (SELECT {price} FROM market_quotes WHERE pair=? AND at_utc=g.last_at)
                FROM grouped g ORDER BY bucket'''
            candles=[dict(at=row[0],first_at=row[1],last_at=row[2],low=row[3],high=row[4],
                          samples=row[5],open=row[6],close=row[7])
                     for row in db.execute(query,(pair,start,min(clock,time.time()),pair,pair))]
            if stopped():return {'state':'CANCELLED','candles':[]}
            return dict(state='QUOTE_CANDLES' if candles else 'NO_QUOTES_IN_RANGE',pair=pair,products=products,
                candles=candles,oldest=oldest,newest=newest,stored_samples=count,
                start=start,end=clock,requested_interval=interval,interval=effective,span=span,
                price_unit=quote+'_PER_'+base if native else 'ETH_PER_COIN',basis='STORED_BID_ASK_MIDPOINT_SAMPLES_NOT_TRADE_OHLC')
        except sqlite3.OperationalError:
            if cancel is not None and cancel.is_set():return {'state':'CANCELLED','candles':[]}
            return {'state':'HISTORY_READ_BUSY_OR_LIMITED','candles':[],'products':[]}


class QuoteChart(ttk.LabelFrame):
    def __init__(self,parent,path,allowed_products=None):
        super().__init__(parent,text='Price chart · Recorded quotes',padding=5)
        self.allowed_products=None if allowed_products is None else tuple(allowed_products)
        self.path=Path(path);self.result={};self.closed=False;self.busy=False;self.generation=0
        self.cancel=threading.Event();self.jobs=Queue();self.pending=None;self.last_live=0
        self.poll_after=None;self.cursor_candle=None;self.reader=None
        self.pair=tk.StringVar();self.interval=tk.StringVar(value='1m');self.span=tk.StringVar(value='1 day')
        self.end=None;self.summary=tk.StringVar(value='Recorded quotes only · No imported trade candles')
        controls=ttk.Frame(self);controls.pack(fill='x')
        navigation=ttk.Frame(controls);navigation.pack(fill='x')
        ranges=ttk.Frame(controls);ranges.pack(fill='x',pady=(4,0))
        self.product=ttk.Combobox(navigation,textvariable=self.pair,state='readonly',width=13,values=self.allowed_products or ())
        self.product.pack(side='left',padx=(0,6));self.product.bind('<<ComboboxSelected>>',lambda e:self.refresh())
        Hover(self.product,'Historical chart product only; it does not change funding or research selection. Only approved markets are shown. Prices use the product’s actual quote currency.')
        for label,var,values,tip in (
            ('Candle',self.interval,tuple(INTERVALS),'Candle interval: aggregate only recorded quote midpoints. 1s does not add ticks between scans. Months and years use calendar UTC boundaries. Wide history may explicitly use coarser candles to fit the screen.'),
            ('History',self.span,RANGES,'Visible history range. All stored reaches the oldest quote retained in this database. Previous/next moves the time window. Missing intervals stay empty; no backfill or interpolation.')):
            ttk.Label(ranges,text=label).pack(side='left',padx=(0,3))
            box=ttk.Combobox(ranges,textvariable=var,values=values,state='readonly',width=10)
            box.pack(side='left',padx=(0,7));box.bind('<<ComboboxSelected>>',lambda e:self.refresh());Hover(box,tip)
        for text,command,tip in (
            ('Prev',lambda:self.pan(-1),'Previous history window; no new data is downloaded.'),
            ('Next',lambda:self.pan(1),'Next history window.'),
            ('Latest',self.latest,'Return to the latest time window.'),
            ('Refresh',self.refresh,'Read the existing public quote journal again. No exchange or financial requests.')):
            button=ttk.Button(navigation,text=text,command=command,width=7)
            button.pack(side='left',padx=(0,3));Hover(button,tip)
        self.canvas=tk.Canvas(self,height=220,background='#0b0e12',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,pady=(5,0))
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<Motion>',self.inspect)
        self.canvas.bind('<MouseWheel>',self.zoom);self.canvas.bind('<Button-4>',lambda e:self.zoom(e,-1))
        self.canvas.bind('<Button-5>',lambda e:self.zoom(e,1))
        Hover(self.canvas,self.candle_help)
        self.canvas.bind('<Leave>',lambda e:self.canvas.delete('crosshair'),add='+')
        caption=ttk.Label(self,textvariable=self.summary,wraplength=1040);caption.pack(anchor='w',pady=(3,0))
        Hover(caption,'Sampled bid/ask-midpoint OHLC, not executed trades or exchange OHLC. Gaps are missing stored observations. '
            'No trade volume is available. Chart prices never feed strategy calculations. History reads are bounded, cancellable and read-only.')
        self.bind('<Destroy>',self._destroy,add='+')
        self.poll_after=self.after(100,self.poll)

    def set_products(self,products):
        known=set(self.product['values'])|set(products)
        if self.allowed_products is not None:known.intersection_update(self.allowed_products)
        self.product.configure(values=tuple(sorted(known)))
        if not self.pair.get() and known:self.pair.set(next((p for p in products if p in known),sorted(known)[0]))

    def refresh(self,*,live=False):
        if self.closed:return
        if live and time.monotonic()-self.last_live<10:return
        self.last_live=time.monotonic();self.generation+=1;self.cancel.set()
        self.pending=(self.generation,self.pair.get() or None,self.interval.get(),self.span.get(),self.end)
        self.summary.set('Reading stored quote history...')
        if not self.busy:self._launch()

    def _launch(self):
        if self.pending is None or self.closed:return
        generation,pair,interval,span,end=self.pending;self.pending=None
        self.busy=True;self.cancel=threading.Event();cancel=self.cancel;path=self.path
        def work():
            try:result=read_history(path,pair,interval=interval,span=span,end=end,cancel=cancel,
                allowed_products=self.allowed_products,native=self.allowed_products is not None)
            except Exception:result={'state':'HISTORY_UNAVAILABLE','candles':[]}
            self.jobs.put((generation,result))
        self.reader=threading.Thread(target=work,daemon=True);self.reader.start()

    def poll(self):
        if self.closed:return
        if self.poll_after is not None:
            try:self.after_cancel(self.poll_after)
            except tk.TclError:pass
            self.poll_after=None
        try:
            while True:
                generation,result=self.jobs.get_nowait();self.busy=False
                if generation==self.generation and result['state']!='CANCELLED':
                    self.result=result;self.set_products(result.get('products',[]))
                    if result.get('pair'):self.pair.set(result['pair'])
                    self.draw()
                self._launch()
        except Empty:pass
        self.poll_after=self.after(100,self.poll)

    def cancel_pending(self):
        self.generation+=1;self.cancel.set();self.pending=None
        if self.busy and not self.closed:self.summary.set('History read stopped · Display retained')

    def diagnostics(self):
        return {key:self.result.get(key,'UNOBSERVED') for key in
                ('state','pair','interval','requested_interval','span','oldest','newest','stored_samples','basis')}

    def latest(self):
        self.end=None;self.refresh()

    def pan(self,direction):
        if self.span.get()=='All stored':return
        end=self.end if self.end is not None else time.time()
        duration=end-range_start(end,self.span.get())
        self.end=min(time.time(),end+direction*duration);self.refresh()

    def zoom(self,event,direction=None):
        direction=direction if direction is not None else (-1 if event.delta>0 else 1)
        options=list(INTERVALS);i=options.index(self.interval.get())
        self.interval.set(options[max(0,min(len(options)-1,i+direction))]);self.refresh();return 'break'

    def draw(self):
        if self.closed:return
        c=self.canvas;c.delete('all');self.cursor_candle=None
        width,height=max(300,c.winfo_width()),max(100,c.winfo_height())
        left,right,top,bottom=12,width-106,14,height-32
        rows=self.result.get('candles',[])
        if not rows:
            state=self.result.get('state','NO_STORED_QUOTES')
            message=('History read busy or too large — try Refresh or a shorter range' if state=='HISTORY_READ_BUSY_OR_LIMITED'
                else 'History unavailable — try Refresh' if state=='HISTORY_UNAVAILABLE'
                else 'No recorded quotes in this time window')
            c.create_text(width/2,height/2,text=message,fill='#b7c6d6')
            if self.result.get('oldest') is not None:
                first=datetime.fromtimestamp(self.result['oldest'],timezone.utc).strftime('%Y-%m-%d')
                last=datetime.fromtimestamp(self.result['newest'],timezone.utc).strftime('%Y-%m-%d')
                self.summary.set(f'Stored {first} → {last} UTC · Choose All stored to see available history')
            else:self.summary.set('Recorded quotes only · Choose a stored product or start read-only observations')
            return
        start,end=self.result['start'],self.result['end'];end=max(end,start+1)
        low=min(r['low'] for r in rows);high=max(r['high'] for r in rows)
        pad=max((high-low)*.12,abs(high)*.0001,1e-18);low-=pad;high+=pad
        px=lambda stamp:left+(stamp-start)/(end-start)*(right-left)
        py=lambda price:bottom-(price-low)/(high-low)*(bottom-top)
        self.axes=(left,right,top,bottom,start,end,px,py)
        for i in range(5):
            y=top+(bottom-top)*i/4;p=high-(high-low)*i/4
            c.create_line(left,y,right,y,fill='#283544');c.create_text(right+8,y,text=f'{p:.6g}',anchor='w',fill='#aebed0')
            stamp=start+(end-start)*i/4;x=px(stamp)
            c.create_line(x,top,x,bottom,fill='#1e2a37')
            fmt='%H:%M:%S' if end-start<=3600 else '%m-%d %H:%M' if end-start<=604800 else '%Y-%m-%d'
            c.create_text(x,bottom+16,text=datetime.fromtimestamp(stamp,timezone.utc).strftime(fmt),fill='#aebed0',anchor='w' if i==0 else 'e' if i==4 else 'center')
        candle_width=max(1,min(14,(right-left)*INTERVALS[self.result['interval']]/(end-start)*.72))
        for row in rows:
            # The first retained bucket may begin before the selected range.
            stamp=max(start,row['at']);x=px(stamp)
            color='#3fce98' if row['close']>=row['open'] else '#ee6f79'
            c.create_line(x,py(row['high']),x,py(row['low']),fill=color)
            y1,y2=py(row['open']),py(row['close'])
            if abs(y2-y1)<1:c.create_line(x-candle_width/2,y1,x+candle_width/2,y1,fill=color,width=2)
            else:c.create_rectangle(x-candle_width/2,min(y1,y2),x+candle_width/2,max(y1,y2),fill=color,outline=color)
        oldest=datetime.fromtimestamp(self.result['oldest'],timezone.utc).strftime('%Y-%m-%d')
        newest=datetime.fromtimestamp(self.result['newest'],timezone.utc).strftime('%Y-%m-%d')
        fitted=(' (fitted from '+self.result['requested_interval']+')' if self.result['interval']!=self.result['requested_interval'] else '')
        unit=self.result.get('price_unit','ETH_PER_COIN').replace('_PER_',' / ')
        self.summary.set(f"{self.result['pair']} · {unit} · {self.result['interval']}{fitted} · UTC · {oldest} → {newest}")

    def inspect(self,event):
        self.canvas.delete('crosshair')
        if not self.result.get('candles') or not hasattr(self,'axes'):return
        left,right,top,bottom,start,end,px,py=self.axes
        if not left<=event.x<=right or not top<=event.y<=bottom:return
        stamp=start+(event.x-left)/(right-left)*(end-start)
        self.cursor_candle=min(self.result['candles'],key=lambda r:abs(r['at']-stamp))
        if abs(self.cursor_candle['at']-stamp)>INTERVALS[self.result['interval']]:self.cursor_candle=None
        self.canvas.create_line(event.x,top,event.x,bottom,fill='#6e839a',dash=(2,3),tags='crosshair')
        self.canvas.create_line(left,event.y,right,event.y,fill='#6e839a',dash=(2,3),tags='crosshair')

    def candle_help(self):
        row=self.cursor_candle
        if row is None:return 'Recorded quote midpoint candles in the actual product’s quote currency. Move over a candle for OHLC and sample count. Empty intervals are gaps, not unchanged prices. Wheel changes candle interval; history controls and arrows browse stored time.'
        return (datetime.fromtimestamp(row['at'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')+
            f"\nOpen {row['open']:.10g} · High {row['high']:.10g}\nLow {row['low']:.10g} · Close {row['close']:.10g} "+self.result.get('price_unit','ETH_PER_COIN').replace('_PER_',' / ')+'\n'+
            f"{row['samples']} recorded bid/ask observations. No executed trades, fill evidence or volume inferred.")

    def _destroy(self,event):
        if event.widget is not self:return
        self.closed=True;self.cancel_pending()
        if self.poll_after is not None:
            try:self.after_cancel(self.poll_after)
            except tk.TclError:pass
        if self.reader is not None:
            self.reader.join(timeout=2)
            if self.reader.is_alive():raise RuntimeError('Public history reader did not close after cancellation')
