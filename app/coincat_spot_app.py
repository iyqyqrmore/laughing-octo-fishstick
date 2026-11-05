"""Coinbase-style manual spot workspace. Every new order requires one click."""
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
from queue import Queue,Empty
import sqlite3
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk,filedialog
import uuid

from coinbase_account import parse_key_json,save_encrypted,load_encrypted
from coincat_beta_controller import protect_sdk_logs
from coincat_beta_store import BetaBlocked,unpack
from coincat_live import client_from_credentials
from coincat_live_beta import LiveLimits
from coincat_manual_trade import ManualTradeStore,identity
from coincat_monitor import MonitorPublisher
from coincat_order_book import BookView,display_levels
from coincat_spot_execution import ManualExecution,TERMINAL
from coincat_spot_market import SpotReader
from coincat_state_v50 import data_root
from coincat_statement_math import read_statement,corroborate_many
from coincat_theme import apply_theme,BG,EDGE,TEXT,MUTED,GREEN,RED
from coincat_v80_immediate import exact
from coincat_version import DISPLAY
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS
from coincat_v701_transport import BUDGET


def fmt(value):return '—' if value is None else format(value,'f')


def legacy_pending(data):
    """Read a pre-existing auto journal without initializing its controller."""
    path=Path(data)/'research_data'/'live_beta'/'active.sqlite3'
    if not path.exists():return False
    try:
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size>32*1024*1024:return True
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            if db.execute('PRAGMA application_id').fetchone()[0]!=0x43434C42:return True
            raw,sha=db.execute('SELECT payload,digest FROM beta_state WHERE id=1').fetchone()
        if hashlib.sha256(raw.encode()).hexdigest()!=sha:return True
        state=unpack(raw)
        return any(o.get('state') not in TERMINAL or o.get('reconciliation_unknown') is True for o in state['orders'].values())
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):return True


class Unconnected:
    def __getattr__(self,name):raise BetaBlocked('CONNECT_FIRST')


class MarketPanel(ttk.Frame):
    def __init__(self,parent,app,pair):
        super().__init__(parent,padding=6);self.app=app;self.pair=pair;self.snap=None;self.chart_data=None;self.replaces=None
        self.base,self.quote=pair.split('-');self.side=tk.StringVar(value='SELL');self.price=tk.StringVar();self.size=tk.StringVar()
        self.post=tk.BooleanVar(value=False);self.interval=tk.StringVar(value='5m');self.group=tk.StringVar(value='1')
        self.amount_unit=tk.StringVar(value=self.base);self.summary=tk.StringVar(value='Connect to read this native market.')
        self.available=tk.StringVar(value='Available: —');self.estimate=tk.StringVar(value='Subtotal / estimated fee / total: —')
        self.columnconfigure(0,weight=6,minsize=360);self.columnconfigure(1,weight=3,minsize=225);self.columnconfigure(2,weight=0,minsize=280)
        self.rowconfigure(1,weight=1)
        ttk.Label(self,textvariable=self.summary,style='Metric.TLabel').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,7))
        chart=ttk.LabelFrame(self,text='Price chart · exchange trade candles',padding=5);chart.grid(row=1,column=0,sticky='nsew',padx=(0,6))
        bar=ttk.Frame(chart);bar.pack(fill='x')
        ttk.Label(bar,text='Candle').pack(side='left');box=ttk.Combobox(bar,textvariable=self.interval,values=('1m','5m','15m','1h'),state='readonly',width=5)
        box.pack(side='left',padx=5)
        def interval_changed(event=None):
            self.chart_data=None;self.draw_chart();app.refresh_due=0;app.refresh(candles=True)
        box.bind('<<ComboboxSelected>>',interval_changed)
        ttk.Label(bar,text='UTC · actual traded OHLC and volume',style='Muted.TLabel').pack(side='left')
        self.canvas=tk.Canvas(chart,background=BG,highlightthickness=0,height=310);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw_chart())
        self.chart_note=ttk.Label(chart,text='No exchange candles received.',style='Muted.TLabel');self.chart_note.pack(anchor='w')
        book=ttk.LabelFrame(self,text='Order book · REST snapshots',padding=5);book.grid(row=1,column=1,sticky='nsew',padx=(0,6))
        opts=ttk.Frame(book);opts.pack(fill='x')
        ttk.Label(opts,text='Tick ×').pack(side='left')
        for variable,values,width in ((self.group,('1','2','5','10','25','50','100'),4),(self.amount_unit,(self.base,self.quote),5)):
            cb=ttk.Combobox(opts,textvariable=variable,values=values,state='readonly',width=width);cb.pack(side='left',padx=3)
            cb.bind('<<ComboboxSelected>>',lambda e:self.draw_book())
        self.book_tree=ttk.Treeview(book,columns=('price','size','total'),show='headings',height=17,style='Book.Treeview')
        for k,label,width in (('price','Price ('+self.quote+')',90),('size','Amount',80),('total','Total',80)):
            self.book_tree.heading(k,text=label);self.book_tree.column(k,width=width,minwidth=60,anchor='e')
        self.book_tree.tag_configure('ask',foreground=RED);self.book_tree.tag_configure('bid',foreground=GREEN)
        self.book_tree.pack(fill='both',expand=True,pady=(5,0));self.book_tree.bind('<Double-1>',self.book_price)
        self.book_note=ttk.Label(book,text='No current book.',style='Muted.TLabel',wraplength=260);self.book_note.pack(anchor='w')
        ticket_panel=ttk.LabelFrame(self,text='Order form · manual LIMIT GTC',padding=6);ticket_panel.grid(row=1,column=2,sticky='nsew')
        ticket_panel.rowconfigure(0,weight=1);ticket_panel.columnconfigure(0,weight=1)
        viewport=tk.Canvas(ticket_panel,background=BG,highlightthickness=0,width=260,height=150)
        viewport.grid(row=0,column=0,sticky='nsew');scroll=ttk.Scrollbar(ticket_panel,command=viewport.yview);scroll.grid(row=0,column=1,sticky='ns')
        viewport.configure(yscrollcommand=scroll.set);ticket=ttk.Frame(viewport);item=viewport.create_window(0,0,window=ticket,anchor='nw')
        ticket.bind('<Configure>',lambda e:viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>',lambda e:viewport.itemconfigure(item,width=e.width))
        self.ticket_viewport=viewport
        sides=ttk.Frame(ticket);sides.pack(fill='x',pady=(0,6))
        for side in ('BUY','SELL'):
            ttk.Radiobutton(sides,text=side.title(),variable=self.side,value=side,command=self.changed_side).pack(side='left',expand=True,fill='x')
        ttk.Label(ticket,textvariable=self.available,wraplength=260).pack(anchor='w',pady=5)
        ttk.Label(ticket,text='Limit price · '+self.quote+' per '+self.base).pack(anchor='w')
        self.price_entry=ttk.Entry(ticket,textvariable=self.price,width=23);self.price_entry.pack(fill='x',pady=(3,5))
        prices=ttk.Frame(ticket);prices.pack(fill='x')
        for choice in ('BID','MID','ASK'):
            ttk.Button(prices,text=choice,width=4,command=lambda c=choice:self.use_price(c)).pack(side='left',expand=True,fill='x')
        ttk.Label(ticket,text='Amount · '+self.base).pack(anchor='w',pady=(9,3))
        self.size_entry=ttk.Entry(ticket,textvariable=self.size,width=23);self.size_entry.pack(fill='x')
        ttk.Checkbutton(ticket,text='Post Only',variable=self.post,command=self.estimate_ticket).pack(anchor='w',pady=(8,2))
        ttk.Label(ticket,text='OFF: a limit BUY at ASK can take liquidity.\nON: use BID to buy, ASK to sell.',style='Muted.TLabel',wraplength=255).pack(anchor='w')
        ttk.Label(ticket,textvariable=self.estimate,wraplength=255,justify='left').pack(anchor='w',pady=9)
        footer=ttk.Frame(ticket_panel);footer.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(5,0))
        footer.columnconfigure(0,weight=1)
        self.trade_button=ttk.Button(footer,text='Sell '+self.base,command=lambda:app.place(self),style='Accent.TButton')
        self.trade_button.grid(row=0,column=0,sticky='ew',padx=(0,3))
        ttk.Button(footer,text='Caps…',command=app.limits_dialog).grid(row=0,column=1)
        ttk.Label(footer,text='Live block OFF: your click sends a real order. Automation OFF.',wraplength=255,style='Muted.TLabel').grid(row=1,column=0,columnspan=2,sticky='w',pady=(3,0))
        for var in (self.price,self.size):var.trace_add('write',lambda *args:self.estimate_ticket())
        def wheel(event):
            direction=-1 if getattr(event,'num',None)==4 or getattr(event,'delta',0)>0 else 1
            viewport.yview_scroll(direction,'units');return 'break'
        def bind_wheel(widget):
            for event in ('<MouseWheel>','<Button-4>','<Button-5>'):widget.bind(event,wheel)
            for child in widget.winfo_children():bind_wheel(child)
        bind_wheel(ticket)
        self.changed_side();self.draw_chart()

    def current(self):return self.app.connected and self.snap is not None and 0<=self.app.clock()-self.snap['book']['at']<=30
    def changed_side(self):
        self.replaces=None;self.trade_button.configure(text=self.side.get().title()+' '+self.base);self.estimate_ticket()
    def use_price(self,choice):
        if not self.current():self.app.status.set('Refresh this market before choosing a price.');return
        b=self.snap['book'];value=b['bid'] if choice=='BID' else b['ask'] if choice=='ASK' else (b['bid']+b['ask'])/2
        tick=exact(self.snap['rules'].get('price_increment',self.snap['rules']['quote_increment']))
        value=(value//tick)*tick;self.price.set(fmt(value))
    def book_price(self,event):
        row=self.book_tree.identify_row(event.y)
        if row and row!='spread' and self.current():self.price.set(str(self.book_tree.item(row,'values')[0]))
    def accept(self,snap):
        self.snap=deepcopy(snap)
        if snap.get('chart') is not None and snap['chart']['interval']==self.interval.get():self.chart_data=deepcopy(snap['chart'])
        if not self.price.get():self.use_price('BID' if self.side.get()=='BUY' and self.post.get() else 'ASK')
        self.summary.set(self.pair+'   Bid '+fmt(snap['book']['bid'])+'   Ask '+fmt(snap['book']['ask'])+' '+self.quote)
        self.draw_book();self.draw_chart();self.estimate_ticket()
    def draw_book(self):
        for row in self.book_tree.get_children():self.book_tree.delete(row)
        if not self.current():self.book_note.configure(text='Book stale or unavailable · refresh.');return
        b=self.snap['book'];tick=exact(self.snap['rules'].get('price_increment',self.snap['rules']['quote_increment']))
        view=BookView(self.pair,0,0,b['bids'],b['asks'],b['at'],b['at'],'HEALTHY','REST_SNAPSHOT')
        rows=display_levels(view,tick=tick,multiple=int(self.group.get()),quote_amount=self.amount_unit.get()==self.quote,limit=8)
        for side,tag in (('asks','ask'),('bids','bid')):
            if side=='bids':self.book_tree.insert('','end',iid='spread',values=('Spread',fmt(b['ask']-b['bid']),''))
            for i,row in enumerate(rows[side]):self.book_tree.insert('','end',iid=side+str(i),values=tuple(fmt(v) for v in row),tags=(tag,))
        self.book_note.configure(text='Amount / total in '+self.amount_unit.get()+'. Snapshot '+datetime.fromtimestamp(b['at'],timezone.utc).strftime('%H:%M:%S UTC'))
    def estimate_ticket(self):
        source=self.base if self.side.get()=='SELL' else self.quote
        account=self.app.account or {};q=(account.get('available') or {}).get(source)
        self.available.set('Available: '+fmt(q)+' '+source)
        self.trade_button.configure(state='normal' if self.current() and not self.app.busy and not self.app.blocked.get() else 'disabled')
        try:
            price,size=exact(self.price.get()),exact(self.size.get());tier=(self.snap or {}).get('tier')
            if price<=0 or size<=0 or not tier:raise ValueError()
            rate=tier['maker'] if self.post.get() else max(tier['maker'],tier['taker']);gross=price*size;fee=gross*rate
            total=gross-fee if self.side.get()=='SELL' else gross+fee
            self.estimate.set('Subtotal: '+fmt(gross)+' '+self.quote+'\nEstimated '+('maker' if self.post.get() else 'taker / maximum tier')+' fee ('+fmt(rate*100)+'%): '+fmt(fee)+' '+self.quote+
                '\nEstimated '+('receive' if self.side.get()=='SELL' else 'cost')+': '+fmt(total)+' '+self.quote+'\nQuote-fee estimate; actual fill units shown in history.')
        except (ValueError,TypeError,KeyError,ArithmeticError):self.estimate.set('Enter an amount and native limit price. Fees are estimates until filled.')
    def draw_chart(self):
        c=self.canvas;c.delete('all');w=max(150,c.winfo_width());h=max(120,c.winfo_height());chart=self.chart_data
        if not chart or not chart['candles']:
            c.create_text(w/2,h/2,text='Connect for exchange candles',fill=MUTED);return
        rows=chart['candles'][-90:];low=min(r['low'] for r in rows);high=max(r['high'] for r in rows);span=high-low or high*D('.001')
        left,right,top,bottom=8,w-75,12,h-65;cw=max(1,(right-left)/len(rows));max_volume=max((r['volume'] for r in rows),default=D(1)) or D(1)
        def y(v):return bottom-float((v-low)/span)*(bottom-top)
        for i in range(5):
            value=low+span*i/4;yy=y(value);c.create_line(left,yy,right,yy,fill=EDGE)
            c.create_text(right+4,yy,text=format(value,'.7g'),fill=MUTED,anchor='w',font=('Segoe UI',8))
        for i,r in enumerate(rows):
            x=left+cw*(i+.5);color=GREEN if r['close']>=r['open'] else RED
            c.create_line(x,y(r['low']),x,y(r['high']),fill=color)
            c.create_rectangle(x-cw*.32,y(max(r['open'],r['close'])),x+cw*.32,max(y(min(r['open'],r['close'])),y(max(r['open'],r['close']))+1),fill=color,outline=color)
            volume_h=float(r['volume']/max_volume)*28;c.create_rectangle(x-cw*.32,h-28-volume_h,x+cw*.32,h-28,fill=color,outline='')
            if i in (0,len(rows)//2,len(rows)-1):c.create_text(x,h-11,text=datetime.fromtimestamp(r['at'],timezone.utc).strftime('%H:%M'),fill=MUTED,font=('Segoe UI',8))
        self.chart_note.configure(text=chart['interval']+' · '+self.quote+' per '+self.base+' · candles fetched '+datetime.fromtimestamp(chart['at'],timezone.utc).strftime('%H:%M:%S UTC'))


class SpotApp:
    manual_workspace=True
    def __init__(self,root,*,data=None,client=None,clock=time.time):
        self.root=root;self.data=Path(data) if data is not None else data_root();self.clock=clock;self.client=client
        self.reader=SpotReader(client or Unconnected(),clock=clock,budget=None if client is not None else BUDGET)
        self.engine=ManualExecution(self.data/'research_data'/'spot_manual'/'active.sqlite3',self.reader,clock=clock,legacy_pending=lambda:legacy_pending(self.data))
        self.history_store=ManualTradeStore(self.data/'research_data'/'manual_trade_lab'/'observations.sqlite3')
        self.account=None;self.connected=False;self.busy=False;self.closed=False;self.closing=False;self.jobs=Queue();self.worker=None
        self.status=tk.StringVar(value='Connect / refresh to read markets and balances. Automation is OFF.')
        self.market=tk.StringVar(value='ETH-BTC');self.blocked=tk.BooleanVar(value=True);self.monitor_on=tk.BooleanVar(value=False)
        self.publisher=MonitorPublisher();self.last_read_at=None;self.last_error=False;self.reads=0;self.history={};self.favorites=set()
        self.manual_public=self.engine.public();self._after=None;self.refresh_due=0;self.poll_due=0;self.stop_requested=False
        self._ui();self._load_favorites();self.refresh_local();root.protocol('WM_DELETE_WINDOW',self.close)
        self._after=root.after(100,self.tick)

    def _ui(self):
        root=self.root;root.title(DISPLAY+' · Manual Spot · Live blocked');root.geometry('1450x920');root.minsize(1040,780);apply_theme(root)
        style=ttk.Style(root);style.configure('Book.Treeview',rowheight=21);style.configure('Book.Treeview.Heading',font=('Segoe UI',9))
        if sys.platform=='win32':root.iconbitmap(str(Path(__file__).with_name('CoinCat50.ico')))
        shell=ttk.Frame(root,padding=8);shell.pack(fill='both',expand=True);shell.rowconfigure(2,weight=3,minsize=350);shell.rowconfigure(3,weight=1,minsize=185);shell.columnconfigure(0,weight=1)
        head=ttk.Frame(shell);head.grid(row=0,column=0,sticky='ew');head.columnconfigure(0,weight=1)
        ttk.Label(head,text=DISPLAY+' / Manual Spot',style='Title.TLabel').grid(row=0,column=0,sticky='w')
        self.badge=ttk.Label(head,text='LIVE BLOCK ON · Automation OFF',foreground='#eab86b');self.badge.grid(row=1,column=0,sticky='w',pady=3)
        source=tk.PhotoImage(file=str(Path(__file__).with_name('coincat_logo_transparent.png')))
        self.logo_source=tk.PhotoImage(width=source.width(),height=445)
        self.logo_source.tk.call(self.logo_source,'copy',source,'-from',0,145,source.width(),590)
        self.logo=self.logo_source.subsample(8);self.logo_label=ttk.Label(head,image=self.logo);self.logo_label.grid(row=0,column=1,rowspan=2,sticky='e',padx=10)
        toolbar=ttk.Frame(shell);toolbar.grid(row=1,column=0,sticky='ew',pady=(4,7))
        self.market_box=ttk.Combobox(toolbar,textvariable=self.market,values=WATCH_PAIRS,state='readonly',width=12);self.market_box.pack(side='left')
        self.market_box.bind('<<ComboboxSelected>>',lambda e:self.select_market(self.market.get()))
        self.star=ttk.Button(toolbar,text='☆',width=2,command=self.toggle_favorite);self.star.pack(side='left',padx=(3,9))
        for text,action in (('Connect / refresh',self.connect),('Import key',self.import_key),('Diagnostics',self.export),('Trade details / CSV',self.history_dialog)):
            ttk.Button(toolbar,text=text,command=action).pack(side='left',padx=3)
        ttk.Checkbutton(toolbar,text='Local monitor',variable=self.monitor_on,command=self.toggle_monitor).pack(side='right')
        ttk.Checkbutton(toolbar,text='Live orders blocked',variable=self.blocked,command=self.toggle_block).pack(side='right',padx=5)
        self.tabs=ttk.Notebook(shell);self.tabs.grid(row=2,column=0,sticky='nsew')
        self.panels={}
        for pair in WATCH_PAIRS:
            panel=MarketPanel(self.tabs,self,pair);self.panels[pair]=panel;self.tabs.add(panel,text=pair)
        self.tabs.select(self.panels['ETH-BTC']);self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed)
        lower=ttk.Frame(shell);lower.grid(row=3,column=0,sticky='nsew',pady=(7,0));lower.columnconfigure(0,weight=1);lower.columnconfigure(1,minsize=275);lower.rowconfigure(0,weight=1)
        self.tables=ttk.Notebook(lower);self.tables.grid(row=0,column=0,sticky='nsew',padx=(0,6));self.trees={}
        columns=('pair','side','price','size','filled','status','id')
        for label in ('Open orders','Order history','Trade history'):
            frame=ttk.Frame(self.tables);self.tables.add(frame,text=label);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
            tree=ttk.Treeview(frame,columns=columns,show='headings',height=5)
            for key,title,width in zip(columns,('Market','Side','Limit / price','Amount','Filled','Status','Order ID'),(95,55,110,105,90,145,100)):
                tree.heading(key,text=title);tree.column(key,width=width,minwidth=45,stretch=True)
            tree.grid(row=0,column=0,sticky='nsew');scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);scroll.grid(row=0,column=1,sticky='ns');tree.configure(yscrollcommand=scroll.set)
            tree.bind('<Double-1>',lambda e:self.history_dialog());self.trees[label]=tree
        actions=ttk.Frame(self.trees['Open orders'].master);actions.grid(row=1,column=0,sticky='w',pady=4)
        ttk.Button(actions,text='Cancel selected',command=lambda:self.cancel_selected(False)).pack(side='left')
        ttk.Button(actions,text='Cancel & refresh ticket',command=lambda:self.cancel_selected(True)).pack(side='left',padx=5)
        ttk.Label(actions,text='Owned CoinCat orders only · replacement waits for your click.',style='Muted.TLabel').pack(side='left')
        balances=ttk.LabelFrame(lower,text='Balances · available excludes holds',padding=6);balances.grid(row=0,column=1,sticky='nsew')
        balances.rowconfigure(0,weight=1);balances.columnconfigure(0,weight=1)
        self.balance_tree=ttk.Treeview(balances,columns=('asset','available','hold'),show='headings',height=2)
        for key,title,width in (('asset','Asset',45),('available','Available',125),('hold','Held',90)):
            self.balance_tree.heading(key,text=title);self.balance_tree.column(key,width=width,minwidth=40,anchor='e')
        self.balance_tree.grid(row=0,column=0,sticky='nsew');balance_scroll=ttk.Scrollbar(balances,command=self.balance_tree.yview);balance_scroll.grid(row=0,column=1,sticky='ns');self.balance_tree.configure(yscrollcommand=balance_scroll.set)
        self.cap_text=tk.StringVar();ttk.Label(balances,textvariable=self.cap_text,wraplength=270,style='Muted.TLabel').grid(row=1,column=0,columnspan=2,sticky='w',pady=4)
        ttk.Button(balances,text='New session · archive completed',command=self.new_session).grid(row=2,column=0,columnspan=2,sticky='ew')
        ttk.Label(shell,textvariable=self.status,wraplength=1350).grid(row=4,column=0,sticky='w',pady=(7,0))

    def panel(self):return self.panels[self.market.get()]
    def _load_favorites(self):
        path=self.data/'research_data'/'spot_manual'/'favorites.json'
        try:
            if not path.is_symlink() and path.stat().st_size<4096:
                rows=json.loads(path.read_text());self.favorites=set(rows) if isinstance(rows,list) and set(rows)<=set(WATCH_PAIRS) else set()
        except (OSError,ValueError,TypeError):pass
        self.star.configure(text='★' if self.market.get() in self.favorites else '☆')
    def toggle_favorite(self):
        pair=self.market.get()
        if pair in self.favorites:self.favorites.remove(pair)
        else:self.favorites.add(pair)
        path=self.data/'research_data'/'spot_manual'/'favorites.json'
        try:
            if path.is_symlink() or path.with_suffix('.tmp').is_symlink():raise ValueError()
            path.with_suffix('.tmp').write_text(json.dumps(sorted(self.favorites)),encoding='utf-8');path.with_suffix('.tmp').replace(path)
        except (OSError,ValueError):self.status.set('Favorite could not be saved. Trading settings are unchanged.')
        self.star.configure(text='★' if pair in self.favorites else '☆')
    def select_market(self,pair):
        self.tabs.select(self.panels[pair]);self.market.set(pair);self.star.configure(text='★' if pair in self.favorites else '☆')
    def tab_changed(self,event=None):
        selected=self.tabs.select()
        for pair,panel in self.panels.items():
            if str(panel)==selected:self.market.set(pair);break
        self.star.configure(text='★' if self.market.get() in self.favorites else '☆')
        self.refresh_due=0

    def work(self,kind,task):
        if self.busy or self.closed:return False
        self.busy=True;self.refresh_controls()
        def run():
            try:self.jobs.put((kind,task(),None))
            except Exception as exc:
                # A raw SDK response may contain private data. Show controlled
                # local validation codes only; never format arbitrary errors.
                code=str(exc) if isinstance(exc,BetaBlocked) and str(exc).isascii() and all(c.isupper() or c.isdigit() or c=='_' for c in str(exc)) else 'REQUEST_FAILED_REFRESH_OR_EXPORT_DIAGNOSTICS'
                self.jobs.put((kind,None,code))
        self.worker=threading.Thread(target=run,name='CoinCat-manual-worker',daemon=False);self.worker.start();return True
    def connect(self):
        if self.busy:self.status.set('A bounded request is finishing.');return
        if self.client is None:
            try:credentials=load_encrypted()
            except Exception:credentials=None
            if not credentials:self.status.set('Import your key JSON locally, then Connect / refresh.');return
            protect_sdk_logs();self.client=client_from_credentials(credentials);self.reader.client=self.client;self.engine.client=self.client
        self.refresh(candles=True,account=True,history=True)
    def refresh(self,*,candles=False,account=False,history=False):
        if self.client is None:return
        pair=self.market.get();interval=self.panels[pair].interval.get()
        def read():
            snap=self.reader.snapshot(pair,account=account,candles=candles,interval=interval,history=history)
            scope=self.engine.state()['portfolio']
            if scope is not None and snap['account']['portfolio']!=scope:
                self.engine.set_blocked(True);raise BetaBlocked('MANUAL_SESSION_PORTFOLIO_CHANGED')
            return snap
        if self.work('refresh',read):
            self.refresh_due=self.clock()+8
            self.status.set('Reading '+pair+' · balances / REST book'+(' / candles' if candles else '')+'…')
    def import_key(self):
        if self.busy or self.engine.public()['unresolved']:
            self.status.set('Finish the current request and reconcile owned orders before changing keys.');return
        path=filedialog.askopenfilename(parent=self.root,title='Choose local Coinbase CDP JSON key',filetypes=[('JSON','*.json')])
        if not path:return
        try:
            p=Path(path)
            if p.is_symlink() or p.stat().st_size>32768:raise ValueError()
            save_encrypted(parse_key_json(p.read_text(encoding='utf-8')))
            self.engine.set_blocked(True);self.blocked.set(True);self.connected=False;self.client=None
            self.reader=SpotReader(Unconnected(),clock=self.clock);self.engine.reader=self.reader;self.engine.client=self.reader.client
            self.account=None
            for panel in self.panels.values():panel.snap=None;panel.draw_book()
            self.status.set('Key saved with Windows DPAPI. Connect to refresh. Live block is ON.')
        except Exception:self.status.set('Key import failed. Key contents remain private.')
        self.refresh_controls()
    def toggle_block(self):
        if self.closing:
            self.engine.set_blocked(True);self.blocked.set(True);return
        try:self.engine.set_blocked(self.blocked.get())
        except BetaBlocked as exc:self.blocked.set(True);self.status.set(str(exc))
        if self.blocked.get():self.stop_requested=True;self.status.set('Live block ON · canceling owned resting orders; no liquidation.')
        else:self.status.set('Live block OFF · only your explicit Buy/Sell clicks can place orders. Automation OFF.')
        self.refresh_controls()
    def place(self,panel):
        if self.closing or self.busy:return
        try:
            ticket=dict(pair=panel.pair,side=panel.side.get(),size=exact(panel.size.get()),price=exact(panel.price.get()),post_only=panel.post.get())
            if ticket['size']<=0 or ticket['price']<=0:raise ValueError()
            if panel.replaces:ticket['replaces']=panel.replaces
        except (ValueError,TypeError,ArithmeticError):self.status.set('Enter a positive native amount and limit price.');return
        click=uuid.uuid4().hex
        if self.work('place',lambda:self.engine.submit(ticket,click)):self.status.set('Checking funds, exchange rules, fees and preview before sending your manual limit…')
    def selected_owned(self):
        tree=self.trees['Open orders'];choice=tree.selection()
        if not choice or not choice[0].startswith('owned_'):raise BetaBlocked('SELECT_AN_OWNED_COINCAT_ORDER_TO_CANCEL')
        return choice[0][6:]
    def cancel_selected(self,replace=False):
        if self.busy:return
        try:cid=self.selected_owned()
        except BetaBlocked as exc:self.status.set(str(exc));return
        def cancel():
            order=self.engine.cancel(cid)
            return dict(order=order,draft=self.engine.remaining_ticket(cid) if replace and order['state']=='CANCELED' and order['filled']<order['size'] else None)
        if self.work('cancel',cancel):self.status.set('Cancel requested · waiting for terminal state and all reported fills…')
    def refresh_controls(self):
        if self.engine.expired():self.engine.set_blocked(True)
        self.manual_public=self.engine.public();self.blocked.set(self.manual_public['blocked'])
        self.badge.configure(text='LIVE BLOCK '+('ON' if self.blocked.get() else 'OFF')+' · Automation OFF · '+self.manual_public['state'])
        self.root.title(DISPLAY+' · Manual Spot · Live '+('blocked' if self.blocked.get() else 'enabled for manual clicks'))
        limits=self.engine.state()['limits'];self.cap_text.set('Session caps: $'+fmt(limits['max_order_usd'])+' / order · '+str(limits['max_orders'])+' orders\n'+fmt(limits['max_eth'])+' ETH equivalent · '+str(limits['duration_s']//60)+' minutes')
        for panel in self.panels.values():panel.estimate_ticket()
    def refresh_local(self):
        self.refresh_controls()
        for tree in self.trees.values():
            for row in tree.get_children():tree.delete(row)
        state=self.engine.state();owned_ids=set();self.records=self.history_store.records()
        for cid,o in state['orders'].items():
            if o['order_id']:owned_ids.add(o['order_id'])
            values=(o['pair'],o['side'],fmt(o['price']),fmt(o['size']),fmt(o['filled']),o['state'],(o['order_id'] or o['cid'])[:8]+'…')
            self.trees['Order history'].insert('','end',iid='owned_'+cid,values=values)
            if o['state'] not in TERMINAL:self.trees['Open orders'].insert('','end',iid='owned_'+cid,values=values)
            for f in o['fills']:
                self.trees['Trade history'].insert('','end',values=(o['pair'],o['side'],f['price'],f['size'],f['size'],'EXCHANGE FILL',f['order_id'][:8]+'…'))
        for oid,o in self.history.items():
            if oid in owned_ids:continue
            conf=(o.get('order_configuration') or {}).get('limit_limit_gtc') or {}
            values=(o.get('product_id'),o.get('side'),conf.get('limit_price','—'),conf.get('base_size','—'),o.get('filled_size','—'),str(o.get('status','UNKNOWN'))+' · external',oid[:8]+'…')
            self.trees['Order history'].insert('','end',iid='external_'+oid,values=values)
            if o.get('status') in ('OPEN','PENDING','ACTIVE'):
                self.trees['Open orders'].insert('','end',iid='external_'+oid,values=values)
        for record in self.records:
            order=record['order'];oid=order['order_id']
            if oid in owned_ids:continue
            r=record['report']
            if oid not in self.history:
                conf=(order.get('order_configuration') or {}).get('limit_limit_gtc') or {}
                self.trees['Order history'].insert('','end',iid='external_'+oid,values=(r['pair'],r['side'],
                    conf.get('limit_price','—'),conf.get('base_size','—'),fmt(r['base_qty']),r['state']+' · imported',oid[:8]+'…'))
            for fill in record['fills']:
                self.trees['Trade history'].insert('','end',values=(r['pair'],r['side'],fill.get('price','—'),fill.get('size','—'),
                    'quote' if fill.get('size_in_quote') is True else 'base','IMPORTED FILL',oid[:8]+'…'))
        for row in self.balance_tree.get_children():self.balance_tree.delete(row)
        for asset in WATCH_ASSETS:
            self.balance_tree.insert('','end',values=(asset,fmt((self.account or {}).get('available',{}).get(asset)),fmt((self.account or {}).get('holds',{}).get(asset))))

    def limits_dialog(self):
        if self.engine.state()['orders']:self.status.set('Session caps are frozen after the first submission and survive restart.');return
        win=tk.Toplevel(self.root);win.title('Manual beta session caps');body=ttk.Frame(win,padding=15);body.pack(fill='both',expand=True)
        fields={};limits=asdict(LiveLimits(**self.engine.state()['limits']))
        for i,(key,label) in enumerate((('max_order_usd','Maximum USD equivalent per order'),('max_eth','Maximum session ETH-equivalent turnover'),('max_orders','Maximum submitted orders'),('duration_s','Session duration · seconds'),('max_fee_fraction','Fee buffer / ceiling · fraction'))):
            ttk.Label(body,text=label).grid(row=i,column=0,sticky='w',pady=4);fields[key]=tk.StringVar(value=str(limits[key]));ttk.Entry(body,textvariable=fields[key]).grid(row=i,column=1,padx=8)
        def save():
            if self.busy:self.status.set('Finish the current request before changing caps.');return
            try:
                values={k:int(v.get()) if k in ('max_orders','duration_s') else exact(v.get()) for k,v in fields.items()}
                self.engine.configure(LiveLimits(**values));self.refresh_controls();win.destroy()
            except (ValueError,TypeError,ArithmeticError):self.status.set('Caps invalid or session already started.')
        ttk.Label(body,text='Caps are separate from trade profits. They cannot be reset by reconnecting or restarting.',wraplength=460).grid(row=5,column=0,columnspan=2,pady=8)
        ttk.Button(body,text='Apply session caps',command=save).grid(row=6,column=1,sticky='e')

    def new_session(self):
        if self.busy:return
        self.engine.set_blocked(True);self.blocked.set(True)
        def archive():
            state=self.engine.state()
            if any(o['state'] not in TERMINAL for o in state['orders'].values()):raise BetaBlocked('RECONCILE_ALL_ORDERS_BEFORE_NEW_SESSION')
            records=[o['record'] for o in state['orders'].values() if o.get('record')]
            if records:self.history_store.append(dict(records=records,complete=True,reason='COMPLETED_MANUAL_SESSION_ARCHIVE',portfolio=state['portfolio'],at=self.clock()))
            self.engine.new_session()
        if self.work('archive',archive):self.status.set('Archiving the completed manual journal. New session starts blocked with the same caps.')

    def history_dialog(self):
        win=tk.Toplevel(self.root);win.title('Native order settlement · read-only');win.geometry('1050x650')
        body=ttk.Frame(win,padding=10);body.pack(fill='both',expand=True);bar=ttk.Frame(body);bar.pack(fill='x')
        selected_id=''
        for tree in self.trees.values():
            selection=tree.selection()
            if selection and selection[0].startswith('owned_'):
                selected_id=self.engine.state()['orders'].get(selection[0][6:],{}).get('order_id') or '';break
            if selection and selection[0].startswith('external_'):selected_id=selection[0][9:];break
        oid=tk.StringVar(value=selected_id);ttk.Label(bar,text='Full order ID').pack(side='left');ttk.Entry(bar,textvariable=oid,width=39).pack(side='left',padx=5)
        ttk.Button(bar,text='Read order & fills',command=lambda:self.import_history(oid.get())).pack(side='left')
        ttk.Button(bar,text='Cross-check statement CSV',command=self.import_statement).pack(side='left',padx=5)
        text=tk.Text(body,background=BG,foreground=TEXT,wrap='word',font=('Consolas',10));text.pack(fill='both',expand=True,pady=8)
        records=self.history_store.records()+[o['record'] for o in self.engine.state()['orders'].values() if o.get('record')]
        text.insert('1.0','Private local view. API fee units are never invented. CSV matches are corroboration by native fields and UTC second, not order-ID or account reconciliation.\n\n'+json.dumps(records,default=str,indent=2));text.configure(state='disabled')
        ttk.Label(body,text='Close and reopen after a read/cross-check to see the saved report revision. No settings change or order is placed.',style='Muted.TLabel').pack(anchor='w')
    def import_history(self,oid):
        if self.client is None:self.status.set('Connect first to read this order.');return
        try:oid=identity(oid)
        except BetaBlocked as exc:self.status.set(str(exc));return
        def read():
            self.reader.begin();scope=self.reader.scope();record=self.engine._history(oid,scope)
            run=dict(records=[record],complete=record['complete'],reason='MANUAL_READ_ONLY_ORDER',portfolio=scope,at=self.clock())
            self.history_store.append(run);return record['report']['native_settlement']
        if self.work('history',read):self.status.set('Reading exact native order and fill evidence…')
    def import_statement(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self.root,title='Cross-check local Coinbase statement',filetypes=[('CSV','*.csv')])
        if not path:return
        def crosscheck():
            statement=read_statement(path);records=self.history_store.records()
            records.extend(o['record'] for o in self.engine.state()['orders'].values() if o.get('record'))
            unique={r['report']['portfolio']+'_'+r['report']['order_id']:r for r in records};matched=0
            by_scope={}
            for result in corroborate_many(list(unique.values()),statement):
                if result['report'].get('statement_corroboration')=='UNIQUE_NATIVE_FIELDS_AND_UTC_SECOND_MATCH':matched+=1
                by_scope.setdefault(result['report']['portfolio'],[]).append(result)
            for scope,rows in by_scope.items():
                self.history_store.append(dict(records=rows,complete=all(r['complete'] for r in rows),
                    reason='OWNER_STATEMENT_CORROBORATION_API_RECORDS_PRESERVED',portfolio=scope,at=self.clock()))
            return matched
        if self.work('statement',crosscheck):self.status.set('Matching CSV native fields to saved API fills; no orders or fee settings change…')
    def export(self):
        from coincat_spot_public import diagnostic
        path=filedialog.asksaveasfilename(parent=self.root,initialfile='CoinCat_v1.03beta_Manual_Diagnostics.txt',defaultextension='.txt')
        if not path:return
        try:Path(path).write_text(diagnostic(self),encoding='utf-8');self.status.set('Eight redacted manual-workspace diagnostic sections exported.')
        except (ValueError,OSError):self.status.set('Diagnostic export failed.')
    def toggle_monitor(self):
        if self.monitor_on.get():
            if not self.publisher.start():self.monitor_on.set(False)
        else:self.publisher.stop(self.publisher.sample(self,lifecycle='DISABLED'))

    def tick(self):
        if self.closed:return
        try:
            while True:
                kind,result,error=self.jobs.get_nowait();self.busy=False
                if self.worker is not None:self.worker.join();self.worker=None
                if error:
                    if kind in ('refresh','reconcile'):self.last_error=True
                    if kind=='refresh':self.connected=False
                    if kind=='reconcile':self.engine.set_blocked(True)
                    self.blocked.set(self.engine.block.is_set())
                    self.status.set(error.replace('_',' ')+' · Live block '+('ON' if self.blocked.get() else 'OFF')+'.')
                elif kind=='refresh':
                    self.last_error=False;self.connected=True;self.account=result['account'];self.last_read_at=self.clock();self.reads+=1
                    self.panels[result['pair']].accept(result)
                    if result.get('history') is not None:
                        self.history={o['order_id']:o for o in result['history']['orders']};self.history_at=self.clock()
                    self.status.set(result['pair']+' refreshed. '+('History: first 50 only; more may exist. ' if (result.get('history') or {}).get('more') else '')+
                        ('Optional data unavailable: '+', '.join(result['errors']) if result['errors'] else 'Automation OFF. Choose BID / ASK and enter an amount.'))
                elif kind=='place':self.poll_due=0;self.status.set('Exchange '+result['state']+' · refresh monitors real fills. No automatic replacement.');self.panels[result['pair']].replaces=None
                elif kind=='cancel':
                    draft=result['draft'];self.status.set('Order '+result['order']['state']+' reconciled. '+('Only the unfilled remainder is in the refreshed ticket; review and click to submit.' if draft else 'No replacement was sent.'))
                    if draft:
                        self.select_market(draft['pair']);p=self.panels[draft['pair']];p.side.set(draft['side']);p.post.set(draft['post_only'])
                        p.price.set(fmt(draft['price']));p.size.set(fmt(draft['size']));p.replaces=draft['replaces'];p.trade_button.configure(text=draft['side'].title()+' '+p.base)
                    self.refresh_due=0
                elif kind=='history':self.status.set('Native order saved locally: '+result+'. Reopen trade details to inspect.')
                elif kind=='statement':self.status.set(str(result)+' saved order(s) uniquely corroborated by CSV. Raw API fills and future fee settings preserved.')
                elif kind=='archive':
                    self.status.set('Completed journal preserved. New manual session is blocked with the same caps. Refresh before placing an order.')
                    for panel in self.panels.values():panel.replaces=None
                self.refresh_local()
        except Empty:pass
        now=self.clock()
        if not self.busy:
            active=self.engine.public()['unresolved']
            if self.stop_requested:
                self.stop_requested=False
                if active:self.work('reconcile',self.engine.poll)
            elif active and not self.closing and now>=self.poll_due and self.client is not None:
                self.poll_due=now+10;self.work('reconcile',self.engine.poll)
            elif self.connected and not self.closing and now>=self.refresh_due:
                self.refresh_due=now+8;p=self.panel();self.refresh(candles=p.chart_data is None or now-p.chart_data['at']>=60,history=now-(getattr(self,'history_at',0))>=60)
        for panel in self.panels.values():
            if panel.snap is not None and not panel.current():panel.draw_book();panel.summary.set(panel.pair+' · displayed quote is stale');panel.estimate_ticket()
        self.refresh_controls()
        if self.publisher.enabled and now-getattr(self,'monitor_at',0)>=3:
            self.monitor_at=now;self.publisher.publish(self.publisher.sample(self))
        if self.closing and not self.busy:
            self.closed=True
            if self.publisher.enabled:self.publisher.stop(self.publisher.sample(self,lifecycle='CLOSED'))
            if self.client is not None and hasattr(self.client,'session'):
                try:self.client.session.close()
                except OSError:pass
            self.root.destroy();return
        self._after=self.root.after(100,self.tick)
    def close(self):
        if self.closing:return
        self.closing=True;self.engine.set_blocked(True);self.blocked.set(True);self.stop_requested=True
        self.status.set('Closing · live block ON; waiting for the bounded worker and owned-order reconciliation.')


def main():
    from coincat_single_instance import SingleInstance
    from coincat_state_v50 import state_status
    data=data_root();state_status(data)
    with SingleInstance(data):
        root=tk.Tk();SpotApp(root,data=data);root.mainloop()


if __name__=='__main__':main()
