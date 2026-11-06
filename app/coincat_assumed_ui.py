"""Private native-price assumed-fill dashboard; never an actual order ticket."""
from datetime import datetime,timezone
from decimal import Decimal as D
import tkinter as tk
from tkinter import ttk
from coincat_watchlist import WATCH_ASSETS
from coincat_watchlist import WATCH_PAIRS
from coincat_assumed_math import plan

def number(value):return '—' if value is None else format(value,'.12g')
def native(value):return '—' if value is None else format(value,'f')

def table(parent,columns,height):
    frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=5);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    tree=ttk.Treeview(frame,columns=tuple(k for k,_,_ in columns),show='headings',height=height)
    for key,title,width in columns:tree.heading(key,text=title);tree.column(key,width=width,minwidth=65)
    tree.grid(row=0,column=0,sticky='nsew')
    vertical=ttk.Scrollbar(frame,command=tree.yview);vertical.grid(row=0,column=1,sticky='ns')
    horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set);return tree

class AssumedWindow:
    def __init__(self,app):
        self.app=app;self.root=tk.Toplevel(app.root);self.root.title('CoinCat v1.04 · Native one-leg trial · Assumed fills')
        self.root.geometry('1240x850');self.root.minsize(920,720)
        shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='168-hour native one-leg trial · Assumed fills',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='ASSUMED FILLS · Arithmetic demonstration · Not realistic fill or profit evidence',foreground='#eab86b').pack(anchor='w',pady=4)
        ttk.Label(shell,text='$100 initially in each of ETH, BTC, ADA, LINK and SOL · One shared fictional portfolio · No USD spending, turnover or attempt caps',wraplength=1150).pack(anchor='w')
        ttk.Label(shell,text='Each order is one independent leg: exact native book price, one maker/taker fee, zero added slippage. SELL uses ASK; BUY can use ASK (taker estimate) or BID (maker estimate).',wraplength=1150).pack(anchor='w',pady=4)
        controls=ttk.Frame(shell);controls.pack(fill='x',pady=5)
        ttk.Label(controls,text='BUY price').pack(side='left');self.buy_price=tk.StringVar(value=app.assumed.buy_price)
        self.buy_box=ttk.Combobox(controls,textvariable=self.buy_price,values=('ASK','BID'),width=5,state='readonly');self.buy_box.pack(side='left',padx=5)
        ttk.Button(controls,text='Start / resume assumed fills',command=lambda:app.start_assumed(self.buy_price.get())).pack(side='left')
        ttk.Button(controls,text='Pause assumed fills',command=app.pause_assumed).pack(side='left',padx=6)
        ttk.Button(controls,text='Previous trial…',command=app.open_trial).pack(side='right')
        self.summary=tk.StringVar();ttk.Label(shell,textvariable=self.summary,wraplength=1150).pack(anchor='w',pady=3)
        self.bar=ttk.Progressbar(shell,maximum=100);self.bar.pack(fill='x',pady=3)
        self.footer=ttk.Label(shell,text='One proportional fee in the quote coin; exchange fee precision remains unverified. No round-trip charge or added slippage. Maker/taker rates are authenticated; exchange minimums, ticks and simulated funding still apply.',wraplength=1150,style='Muted.TLabel')
        self.footer.pack(side='bottom',fill='x')
        self.tabs=ttk.Notebook(shell);self.tabs.pack(fill='both',expand=True)
        market_page=ttk.Frame(self.tabs);self.portfolio_page=ttk.Frame(self.tabs);self.sizing_page=ttk.Frame(self.tabs,padding=10)
        for page,title in ((market_page,'Native markets'),(self.portfolio_page,'Simulated portfolio / orders'),(self.sizing_page,'Order sizing')):self.tabs.add(page,text=title)
        self.markets=table(market_page,(('pair','Market',75),('side','Side / fee',100),('bid','BID',90),('ask','ASK',90),
            ('size','Base amount',90),('limit','Native limit',125),('fee','Native fee',185),('rate','Rate',60),('total','Cost / proceeds',185),('reason','Result / missing input',245)),7)
        self.holdings=table(self.portfolio_page,(('asset','Simulated asset',120),('initial','Original HOLD units',190),('current','Current simulated units',210),('fee','Cumulative fee in this coin',220)),5)
        self.performance=tk.StringVar();ttk.Label(self.portfolio_page,textvariable=self.performance,wraplength=1150).pack(anchor='w',pady=4)
        ttk.Label(self.portfolio_page,text='Recent assumed orders · SIM IDs are local only; no Coinbase order is submitted',style='Muted.TLabel').pack(anchor='w')
        self.orders=table(self.portfolio_page,(('id','Simulated order ID',290),('market','Market',90),('side','Side',70),('size','Base quantity',105),
            ('price','Native price',115),('fee','Native commission / class',190),('fill','Assumption',240)),7)
        ttk.Label(self.sizing_page,text='0 = exchange minimum. Move toward 100% to use more of the available simulated source coin. Fees are separate from the base order quantity.',wraplength=1100).grid(row=0,column=0,columnspan=4,sticky='w',pady=8)
        self.sizing_vars={};self.sizing_labels={};self.dirty=False;self.applied_version=None
        for i,pair in enumerate(WATCH_PAIRS,1):
            ttk.Label(self.sizing_page,text=pair).grid(row=i,column=0,sticky='w',padx=(0,12),pady=9)
            value=tk.DoubleVar(value=float(app.assumed.pending_sizing[pair]));self.sizing_vars[pair]=value
            ttk.Scale(self.sizing_page,from_=0,to=100,variable=value,command=self.slider_changed).grid(row=i,column=1,sticky='ew',padx=8)
            label=ttk.Label(self.sizing_page,wraplength=500);label.grid(row=i,column=2,sticky='w',padx=12);self.sizing_labels[pair]=label
        self.sizing_page.columnconfigure(1,weight=1)
        ttk.Button(self.sizing_page,text='Apply sizes to future simulated orders',command=self.apply_sizes).grid(row=8,column=0,columnspan=3,sticky='w',pady=12)
        self.settings_note=tk.StringVar();ttk.Label(self.sizing_page,textvariable=self.settings_note,wraplength=1100).grid(row=9,column=0,columnspan=3,sticky='w')
        ttk.Label(self.sizing_page,text='AI sizing control OFF. Applying a slider changes future assumed orders only.',style='Muted.TLabel').grid(row=10,column=0,columnspan=3,sticky='w',pady=6)
        self.last=None;self.render()
    def values(self):return {p:D(str(round(v.get(),1))) for p,v in self.sizing_vars.items()}
    def slider_changed(self,value=None):self.dirty=True;self.preview_sizes()
    def apply_sizes(self):
        if self.app.apply_assumed_sizing(self.values()):self.dirty=False
    def preview_sizes(self):
        state=self.app.assumed.view()['state'];frame=self.app.assumed.last_frame
        for pair,percent in self.values().items():
            note='Minimum' if percent==0 else format(percent,'g')+'% available'
            try:
                if state is None or frame is None:raise ValueError()
                side=state['pairs'][pair]['next_side'];ticket=plan(pair,side,frame,state['buy_price'],wallet=state['wallet'],percent=percent,settings_version=state['settings_version'])
                note+=' · '+side+' '+native(ticket['size'])+' '+pair.split('-')[0]+' + fee '+native(ticket['commission'])+' '+ticket['fee_currency']
            except (ValueError,TypeError,KeyError,ArithmeticError):note+=' · waiting for an eligible native size'
            self.sizing_labels[pair].configure(text=note)
        self.settings_note.set(('Draft sizing — press Apply.' if self.dirty else 'Applied sizing')+' · '+('not started' if state is None else 'version '+str(state['settings_version'])))
    def render(self):
        view=self.app.assumed.view();public=self.app.assumed.public();state=view['state'];frame_at=(self.app.assumed.last_frame or {}).get('at')
        fresh=frame_at is not None and 0<=self.app.clock()-frame_at<=30
        progress=self.app.assumed.progress()
        stamp='waiting for native books' if frame_at is None else datetime.fromtimestamp(frame_at,timezone.utc).strftime('%H:%M:%S UTC')+('' if fresh else ' · STALE')
        self.summary.set(public['state']+' · '+str(public['orders'])+' assumed fills / '+str(public['waves'])+' waves · '+str(public['maker_orders'])+' maker / '+str(public['taker_orders'])+' taker\n'+stamp+' · '+view['reason'].replace('_',' ')+
            ('' if progress is None else f"\n{progress['valid_seconds']/3600:.3f} / 168 valid h · {progress['coverage_percent']:.1f}% market coverage · {progress['restart_count']} restarts"))
        self.bar['value']=0 if progress is None else progress['completion_percent']
        marker=(view,public,fresh)
        if marker==self.last:return
        self.last=marker
        if state is not None and self.applied_version!=state['settings_version']:
            if not self.dirty:
                for p,v in state['sizing'].items():self.sizing_vars[p].set(float(v))
            self.applied_version=state['settings_version']
        self.preview_sizes()
        self.buy_box.configure(state='disabled' if state is not None or self.app.assumed.running else 'readonly')
        for tree in (self.markets,self.holdings,self.orders):
            for row in tree.get_children():tree.delete(row)
        for row in view['rows']:
            quote=row['pair'].split('-')[1]
            self.markets.insert('','end',values=(row['pair'],row.get('side','—')+' '+row.get('fee_kind','').lower(),native(row.get('bid')),native(row.get('ask')),
                native(row.get('size')),native(row.get('price'))+' '+quote,native(row.get('commission'))+' '+quote,
                '—' if row.get('fee_rate') is None else number(row['fee_rate']*100)+'%',native(row.get('quote_total'))+' '+quote,row['reason'].replace('_',' ')))
        if state:
            for asset in WATCH_ASSETS:self.holdings.insert('','end',values=(asset,number(state['original'][asset]),number(state['wallet'][asset]),number(state['fees_native'][asset])))
        perf=view['performance'] if fresh or public['state']=='COMPLETE' else None
        self.performance.set('Conditional midpoint USD before exit costs: '+('UNKNOWN / stale valuations' if perf is None else
            'simulated $'+number(perf['portfolio_usd'])+' · original HOLD $'+number(perf['hold_usd'])+' · difference $'+number(perf['difference_usd']))+
            '\nAssumed fills cannot demonstrate an executable advantage. Prior trial records remain separate and unchanged.')
        for row in reversed(view['orders']):self.orders.insert('','end',values=(row['order_id'],row['pair'],row['side'],number(row['size']),
            native(row['price']),native(row['commission'])+' '+row['fee_currency']+' '+row['fee_kind'],'ASSUMED AT BOOK'))
