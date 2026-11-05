"""Private local shadow dashboard; these amounts never enter monitor exports."""
from decimal import Decimal
import tkinter as tk
from tkinter import ttk
from coincat_portfolio_policy import PortfolioConfig,DIRECTIONS

def fmt(v):return 'UNKNOWN' if v is None else format(v,'f')
def hours(v):return 'UNKNOWN' if v is None else f'{v/3600:.3f} h'

class TrialWindow:
    def __init__(self,app):
        self.app=app;self.root=tk.Toplevel(app.root);self.root.title('CoinCat v1.04 · Resumable shadow trial');self.root.geometry('1080x800')
        self.root.minsize(800,620);shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='Resumable Trial — 168 Valid Hours',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='Shadow research · No automatic live authority · No quote-touch fills · Forecast unvalidated').pack(anchor='w',pady=5)
        self.summary=tk.StringVar();ttk.Label(shell,textvariable=self.summary,wraplength=1000).pack(anchor='w')
        self.bar=ttk.Progressbar(shell,maximum=100);self.bar.pack(fill='x',pady=6)
        settings=ttk.LabelFrame(shell,text='Frozen on first Start · one shared hypothetical portfolio',padding=6);settings.pack(fill='x')
        self.fields={};config=PortfolioConfig(**app.shadow.state()['config']) if app.shadow.state() else PortfolioConfig()
        for i,(key,label) in enumerate((('max_order_usd','USD / order'),('max_turnover_usd','Lifetime turnover USD'),('max_orders','Lifetime attempts'),('source_fraction','Source fraction (≤ 0.5)'))):
            ttk.Label(settings,text=label).grid(row=0,column=i*2,padx=4);v=tk.StringVar(value=str(getattr(config,key)));self.fields[key]=v
            ttk.Entry(settings,textvariable=v,width=9,state='readonly' if app.shadow.state() else 'normal').grid(row=0,column=i*2+1)
        controls=ttk.Frame(shell);controls.pack(fill='x',pady=8)
        ttk.Button(controls,text='Start / resume shadow trial',command=self.start).pack(side='left')
        ttk.Button(controls,text='Pause shadow',command=app.pause_trial).pack(side='left',padx=6)
        ttk.Button(controls,text='Save private summary',command=app.save_trial_report).pack(side='left')
        ttk.Button(controls,text='November 4 fee audit…',command=app.fee_audit_dialog).pack(side='right')
        self.table=ttk.Treeview(shell,columns=('pair','side','state','reason'),show='headings',height=9)
        for k,t,w in (('pair','Market',95),('side','Direction',65),('state','Decision',155),('reason','Reason',620)):
            self.table.heading(k,text=t);self.table.column(k,width=w,minwidth=60)
        self.table.pack(fill='both',expand=True)
        frame=ttk.LabelFrame(shell,text='Private inventory, orders and performance',padding=5);frame.pack(fill='both',expand=True,pady=(8,0))
        self.details=tk.Text(frame,height=15,wrap='word',background='#10151b',foreground='#e3e8ee',insertbackground='white')
        scroll=ttk.Scrollbar(frame,command=self.details.yview);self.details.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.details.pack(fill='both',expand=True);self.render()
    def start(self):
        try:
            if self.app.shadow.state():config=PortfolioConfig(**self.app.shadow.state()['config'])
            else:
                values={k:(int(v.get()) if k=='max_orders' else Decimal(v.get())) for k,v in self.fields.items()};config=PortfolioConfig(**values).checked()
            self.app.start_trial(config)
        except (ValueError,ArithmeticError):self.app.status.set('Check the shadow USD limits, attempt limit and source fraction.')
    def render(self):
        if not self.root.winfo_exists():return
        e=self.app.shadow;s=e.state();p=e.progress();public=e.public()
        self.summary.set(public['state']+(' · '+hours(p['valid_seconds'])+' valid / 168 h · '+hours(p['remaining_seconds'])+' remaining\nCalendar '+hours(p['calendar_elapsed_s'])+' · offline / suspended '+hours(p['downtime_s'])+' · paused '+hours(p['paused_s'])+' · disconnected '+hours(p['disconnected_s'])+' · partial '+hours(p['partial_s'])+'\nRestarts '+str(p['restart_count'])+' · coverage '+f"{p['coverage_percent']:.2f}%" if p else ' · Start once to freeze this trial and original HOLD portfolio.'))
        self.bar['value']=0 if p is None else p['completion_percent']
        for row in self.table.get_children():self.table.delete(row)
        for row in e.rows or [dict(**d,state='HOLD',reason='WAIT_FOR_VALIDATED_OBSERVATIONS') for d in DIRECTIONS]:
            self.table.insert('','end',values=(row['pair'],row['side'],row['state'],row['reason']))
        lines=['No observed quote, candle or downtime interval creates a fill. Explicit replay receipts model fills only.']
        if s:
            perf=s['last_performance'] or {};orders=list(s['orders'].values());fees={}
            for record in self.app.history_store.records():
                for raw in record['fills']:
                    from coincat_manual_trade import explicit_fee_currency
                    try:
                        asset=explicit_fee_currency(raw)
                        if asset is None:fees['UNKNOWN']='UNKNOWN (not summed across currencies)';continue
                        if fees.get(asset)!='UNKNOWN':fees[asset]=fees.get(asset,Decimal(0))+Decimal(raw['commission'])
                    except (ValueError,ArithmeticError):fees['UNKNOWN']='UNKNOWN'
            lines+=['Trial '+s['trial_id']+' · '+s['strategy'],s['reason'],
                'Hypothetical inventory: '+', '.join(a+' '+fmt(q) for a,q in s['wallet'].items()),
                'Original HOLD quantities: '+', '.join(a+' '+fmt(q) for a,q in s['original'].items()),
                'Starting marked USD: '+fmt(s['initial_usd'])+' · Current marked USD: '+fmt(perf.get('portfolio_usd')),
                'Change USD: '+fmt(perf.get('change_usd'))+' ('+fmt(perf.get('change_percent'))+'%)',
                'Original HOLD USD: '+fmt(perf.get('hold_original_usd'))+' · Difference: '+fmt(perf.get('outperformance_usd'))+' ('+fmt(perf.get('outperformance_percent'))+'%)',
                'Estimated liquidation USD: '+fmt(perf.get('liquidation_usd'))+' · '+perf.get('liquidation_status','AWAIT_VALIDATION'),
                'Open inventory P/L: '+fmt(perf.get('unrealized_pnl_usd'))+' · '+perf.get('unrealized_pnl_status','AWAIT_VALIDATION'),
                'Max marked drawdown: '+fmt(s['max_drawdown']*100)+'% · Marked exposures: '+str(perf.get('exposure_usd','UNKNOWN')),
                'Hypothetical native fees: '+str(perf.get('hypothetical_fees_native','UNKNOWN')),
                'Actual imported API commissions (separate; units may be UNKNOWN): '+str(fees),
                'External actual-account changes excluded: '+str(len(s['external_changes']))+' · Actual realized profit NOT ASSESSED',
                'Proposals '+str(len(orders))+' · replay fills '+str(sum(f['settled'] for f in s['fills'].values()))+' · unfilled '+str(sum(o['filled']==0 for o in orders))+' · canceled '+str(sum(o['state']=='CANCELED' for o in orders)),
                'Full USD liquidation / open lot P/L remain UNKNOWN where native exits, fee units or basis are unverified.']
            for o in orders:
                market=(e.last_frame or {}).get('books',{}).get(o['pair'],{})
                lines.append(o['pair']+' '+o['side']+' '+o['state']+' · limit '+fmt(o['price'])+' · BID '+fmt(market.get('bid'))+' / ASK '+fmt(market.get('ask'))+' · base '+fmt(o['size'])+' · filled '+fmt(o['filled'])+' · reserved '+fmt(o['reserved'])+' '+o['source'])
        self.details.configure(state='normal');self.details.delete('1.0','end');self.details.insert('1.0','\n'.join(lines));self.details.configure(state='disabled')
