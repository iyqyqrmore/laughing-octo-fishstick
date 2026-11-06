"""Private opportunity/venue evidence; independent of the fast arithmetic window."""
from decimal import Decimal as D
import tkinter as tk
from tkinter import ttk

from coincat_assumed_ui import table,number,native
from coincat_opportunity_policy import OpportunityConfig
from coincat_watchlist import WATCH_ASSETS,WATCH_PAIRS

class OpportunityWindow:
    def __init__(self,app):
        self.app=app;self.root=tk.Toplevel(app.root);self.root.title('CoinCat v1.04 · Opportunity shadow · No automatic real orders')
        self.root.geometry('1360x880');self.root.minsize(1040,740)
        shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='Opportunity-driven portfolio shadow · 168 valid hours',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='Unvalidated forecast · Conditional maker-fill model · Automatic real-money trading disabled',foreground='#eab86b').pack(anchor='w',pady=4)
        ttk.Label(shell,text='Independent $100 per watched coin. HOLD unless projected portfolio advantage remains positive after entry costs, estimated future exit costs, risk and uncertainty.',wraplength=1280).pack(anchor='w')
        controls=ttk.Frame(shell);controls.pack(fill='x',pady=7)
        ttk.Button(controls,text='Start / resume opportunity shadow',command=self.start).pack(side='left')
        ttk.Button(controls,text='Pause / cancel owned shadow order',command=app.pause_opportunity).pack(side='left',padx=5)
        ttk.Button(controls,text='Save private evidence',command=app.save_opportunity_report).pack(side='left',padx=5)
        ttk.Button(controls,text='Import simulated receipt…',command=app.opportunity_replay_dialog).pack(side='right')
        self.summary=tk.StringVar();ttk.Label(shell,textvariable=self.summary,wraplength=1280).pack(anchor='w')
        self.bar=ttk.Progressbar(shell,maximum=100);self.bar.pack(fill='x',pady=5)
        self.footer=ttk.Label(shell,text='BID/ASK touch never guarantees a fill. Public trade-through, queue and participation assumptions are not exchange execution proof. Future exit costs are estimates, not paid fees.',wraplength=1280,style='Muted.TLabel')
        self.footer.pack(side='bottom',fill='x')
        self.tabs=ttk.Notebook(shell);self.tabs.pack(fill='both',expand=True)
        decisions=ttk.Frame(self.tabs);orders=ttk.Frame(self.tabs);results=ttk.Frame(self.tabs,padding=7);settings=ttk.Frame(self.tabs,padding=10)
        for page,label in ((decisions,'14 directions'),(orders,'Resting orders'),(results,'Portfolio / evidence'),(settings,'Fixed policy')):self.tabs.add(page,text=label)
        self.decisions=table(decisions,(('pair','Market',90),('side','Side',60),('state','Decision',90),('size','Base quantity',100),('price','Native limit',185),
            ('gain','Projected edge USD',170),('exit','Future exit USD',160),('uncertainty','Uncertainty USD',140),('reason','Reason',320)),14)
        self.orders=table(orders,(('id','Shadow order ID',280),('pair','Market',90),('side','Side',65),('state','State',125),('price','Native limit',185),
            ('size','Original quantity',120),('filled','Filled quantity',120),('age','Age / lifetime seconds',145),('reason','Reason',320)),12)
        self.performance=tk.StringVar();ttk.Label(results,textvariable=self.performance,wraplength=1260,justify='left').pack(anchor='w',pady=4)
        self.holdings=table(results,(('asset','Asset',90),('hold','Original HOLD quantity',230),('current','Current modeled quantity',230),('fees','Paid modeled native fees',230)),5)
        self.evidence=tk.Text(results,height=9,wrap='word',background='#10151b',foreground='#e3e8ee');self.evidence.pack(fill='both',expand=True,pady=5)
        self.fields={};self.settings_inputs=[];config=OpportunityConfig(**app.opportunity.state()['config']) if app.opportunity.state() else OpportunityConfig()
        readonly=app.opportunity.state() is not None
        ttk.Label(settings,text='Frozen on first Start. No dollar gain floor or forced ETH return. BUY BID / SELL ASK, LIMIT GTC Post Only.',wraplength=1240).grid(row=0,column=0,columnspan=4,sticky='w',pady=8)
        for i,(key,title) in enumerate((('order_lifetime_s','Maximum child-order lifetime · seconds'),('campaign_lifetime_s','Original opportunity lifetime · seconds'),('retry_budget','Maximum replacement attempts')),1):
            ttk.Label(settings,text=title).grid(row=i,column=0,sticky='w',pady=5)
            value=tk.StringVar(value=str(getattr(config,key)));self.fields[key]=value
            entry=ttk.Entry(settings,textvariable=value,width=12,state='readonly' if readonly else 'normal');entry.grid(row=i,column=1,sticky='w',padx=10);self.settings_inputs.append(entry)
        self.provider=tk.StringVar(value=config.provider)
        ttk.Label(settings,text='Shadow fill provider').grid(row=4,column=0,sticky='w',pady=5)
        self.provider_box=ttk.Combobox(settings,textvariable=self.provider,values=('TRADE_THROUGH_QUEUE_V1','NO_FILL_OBSERVATION_V1'),width=34,state='disabled' if readonly else 'readonly')
        self.provider_box.grid(row=4,column=1,columnspan=2,sticky='w',padx=10)
        ttk.Label(settings,text='30-second reviews · 120-second competitiveness reassessment · 20-interval prospective warmup · Forecast confidence is unvalidated',wraplength=1240).grid(row=5,column=0,columnspan=4,sticky='w',pady=9)
        self.sizing={}
        for i,pair in enumerate(WATCH_PAIRS,6):
            ttk.Label(settings,text=pair+' · size above native minimum (0) toward available inventory (100%)').grid(row=i,column=0,sticky='w',pady=4)
            value=tk.StringVar(value=str(config.size_percent[pair]));self.sizing[pair]=value
            entry=ttk.Entry(settings,textvariable=value,width=12,state='readonly' if readonly else 'normal');entry.grid(row=i,column=1,sticky='w',padx=10);self.settings_inputs.append(entry)
        self.last=None;self.render()
    def start(self):
        try:
            if self.app.opportunity.state():config=OpportunityConfig(**self.app.opportunity.state()['config'])
            else:config=OpportunityConfig(**{k:int(v.get()) for k,v in self.fields.items()},provider=self.provider.get(),size_percent={p:D(v.get()) for p,v in self.sizing.items()}).checked()
            self.app.start_opportunity(config)
        except (ValueError,ArithmeticError):self.app.status.set('Check the finite opportunity lifetimes, replacement budget and sizing percentages.')
    def render(self):
        engine=self.app.opportunity;view=engine.view();public=engine.public();s=view['state'];p=engine.progress();perf=view['performance'] or {}
        o=view['active_order'];fresh=engine.last_frame is not None and 0<=self.app.clock()-engine.last_frame['at']<=30
        self.summary.set(public['state']+' · '+str(public['reviews'])+' reviews / '+str(public['direction_checks'])+' direction checks · '+str(public['opportunity_episodes'])+' qualifying episodes\n'+
            str(public['orders'])+' orders · '+str(public['fill_events'])+' conditional fill events · '+str(public['nonfills'])+' terminal nonfills · '+view['reason'].replace('_',' ')+
            ('' if p is None else f"\n{p['valid_seconds']/3600:.3f} / 168 valid h · {p['coverage_percent']:.1f}% coverage · {p['restart_count']} restarts")+('' if fresh else ' · quotes unobserved / stale'))
        self.bar['value']=0 if p is None else p['completion_percent']
        marker=(view,public,fresh)
        if marker==self.last:return
        self.last=marker
        for tree in (self.decisions,self.orders,self.holdings):
            for row in tree.get_children():tree.delete(row)
        for row in view['rows']:
            uncertainty=None if row.get('forecast_uncertainty_usd') is None else row['forecast_uncertainty_usd']+row['execution_uncertainty_usd']
            self.decisions.insert('','end',values=(row['pair'],row['side'],row['state'],native(row.get('size')),native(row.get('price'))+' '+row['pair'].split('-')[1],
                number(row.get('projected_advantage_usd')),number(row.get('estimated_future_exit_cost_usd')),number(uncertainty),row['reason'].replace('_',' ')))
        for row in reversed(view['orders']):
            self.orders.insert('','end',values=(row['reference'],row['pair'],row['side'],row['state'],native(row['price'])+' '+row['pair'].split('-')[1],
                native(row['size']),native(row['filled']),str(round(row['age_s']))+' / '+str(round(row['expires_at']-row['created_at'])),row['reason'].replace('_',' ')))
        if s is None:
            self.performance.set('Start a new independent opportunity shadow trial. The fast arithmetic test and previous records remain unchanged.');return
        for widget in self.settings_inputs:widget.configure(state='readonly')
        self.provider_box.configure(state='disabled')
        for asset in WATCH_ASSETS:self.holdings.insert('','end',values=(asset,native(s['original'][asset]),native(s['wallet'][asset]),native(s['fees_native'][asset])))
        m=s['metrics'];known=bool(perf and (fresh or public['state']=='COMPLETE'))
        self.performance.set('Cumulative modeled portfolio USD: '+number(perf.get('portfolio_usd') if known else None)+
            ' · original HOLD USD: '+number(perf.get('hold_usd') if known else None)+' · net USD advantage vs HOLD: '+number(perf.get('advantage_usd') if known else None)+
            '\nLatest fill mark change USD: '+number(m['last_fill_change_usd'])+' · known fees valued at fill USD: '+number(m['fees_usd_at_fill'])+
            ' · unpriced fill marks: '+str(m['unknown_fill_marks'])+' · maximum marked drawdown: '+number(s['max_drawdown']*100)+'%'+
            '\nPortfolio value already includes paid modeled fees. Estimated future exit costs have not been deducted as executions.')
        lines=['Forecast and public-trade queue model remain UNVALIDATED; observed quotes/prints do not prove our hypothetical order filled.',
            'Qualified checks '+str(m['qualified_checks'])+' · rejected checks '+str(m['rejected_checks'])+' · replacements '+str(m['replacements'])+
            ' · trade-window gaps '+str(m['gaps'])+' · unknown outcomes '+str(m['unknown_events']),
            'Rejected reasons: '+str(m['rejections'])]
        if o is not None:
            projection=o.get('latest_projection',o['projection'])
            lines+=['Active '+o['reference']+' · '+o['state']+' · reserved '+native(o['reserved'])+' '+o['source'],
                'Admission projected advantage USD '+number(o['projection']['projected_advantage_usd'])+' · latest '+number(projection.get('projected_advantage_usd')),
                'Future exit estimate USD '+number(projection.get('estimated_future_exit_cost_usd'))+' (not booked) · fee unit '+str(projection.get('fee_currency')),
                'Venue evidence: '+('awaiting acknowledged model state' if not o.get('venue') else
                    o['venue']['data_state']+' · strict-through prints '+str(o['venue']['through_count'])+' · assumed queue remaining '+native(o['venue']['queue_left']))]
        self.evidence.configure(state='normal');self.evidence.delete('1.0','end');self.evidence.insert('1.0','\n'.join(lines));self.evidence.configure(state='disabled')
