"""Private v1.05 forecasts, native intents and modeled performance evidence."""
from dataclasses import replace
from decimal import Decimal as D
import tkinter as tk
from tkinter import ttk
from coincat_ui_tables import table,number,native
from coincat_intelligent_policy import IntelligentConfig
from coincat_version import DISPLAY
from coincat_theme import BG,EDGE,MUTED,GREEN,RED,TEXT
from coincat_watchlist import WATCH_ASSETS

class IntelligentWindow:
    def __init__(self,app):
        self.app=app;self.root=tk.Toplevel(app.root);self.root.title(DISPLAY+' · Intelligent 24-hour shadow trader')
        self.root.geometry('1360x900');self.root.minsize(1040,740)
        shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=DISPLAY+' · Intelligent 24-hour one-leg portfolio shadow',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='Unvalidated forecast · Conditional maker fills · No automatic real-money authority',foreground='#eab86b').pack(anchor='w',pady=4)
        self.metric=tk.StringVar();self.metric_label=ttk.Label(shell,textvariable=self.metric,style='Title.TLabel');self.metric_label.pack(anchor='w',pady=5)
        self.status=tk.StringVar();ttk.Label(shell,textvariable=self.status,wraplength=1280).pack(anchor='w')
        self.bar=ttk.Progressbar(shell,maximum=100);self.bar.pack(fill='x',pady=5)
        controls=ttk.Frame(shell);controls.pack(fill='x',pady=5)
        self.start_button=ttk.Button(controls,text='Start / resume intelligent shadow',command=self.start);self.start_button.pack(side='left')
        ttk.Button(controls,text='Pause / cancel shadow order',command=app.pause_intelligent).pack(side='left',padx=5)
        ttk.Button(controls,text='Save private report',command=app.save_intelligent_report).pack(side='left',padx=5)
        ttk.Button(controls,text='Import simulated receipt…',command=app.intelligent_replay_dialog).pack(side='right')
        self.tabs=ttk.Notebook(shell);self.tabs.pack(fill='both',expand=True)
        best=ttk.Frame(self.tabs,padding=10);decisions=ttk.Frame(self.tabs);orders=ttk.Frame(self.tabs);perf=ttk.Frame(self.tabs,padding=8);settings=ttk.Frame(self.tabs,padding=10);evidence=ttk.Frame(self.tabs,padding=8)
        for page,label in ((best,'Best opportunity'),(decisions,'14 directions'),(orders,'Orders'),(perf,'Portfolio / evidence'),(settings,'Frozen settings'),(evidence,'Forecast / rejections')):self.tabs.add(page,text=label)
        self.best=tk.StringVar();ttk.Label(best,textvariable=self.best,wraplength=1260,justify='left',style='Metric.TLabel').pack(anchor='w',pady=8)
        self.model=tk.StringVar();ttk.Label(best,textvariable=self.model,wraplength=1260,justify='left').pack(anchor='w',pady=12)
        self.decisions=table(decisions,(('rank','Rank',65),('pair','Market',90),('side','Side',65),('source','Funding → destination',160),
            ('state','Decision',90),('size','Base quantity',120),('price','Native maker limit',190),('gain','24h net risk-adjusted USD',190),('reason','Reason',350)),14)
        self.orders=table(orders,(('id','Conditional order ID',290),('pair','Market',90),('side','Side',60),('state','State',125),('price','Native limit',180),
            ('q','Original quantity',140),('filled','Filled',140),('age','Age / lifetime s',140),('remaining','Remaining child / campaign s',220),('reason','Reconciliation / replacement',350)),12)
        self.details=tk.StringVar();ttk.Label(perf,textvariable=self.details,wraplength=1260,justify='left').pack(anchor='w')
        self.canvas=tk.Canvas(perf,height=120,background=BG,highlightthickness=0);self.canvas.pack(fill='x',pady=7);self.canvas.bind('<Configure>',lambda e:self.draw_trend())
        self.holdings=table(perf,(('a','Asset',90),('original','Original HOLD quantity',250),('current','Modeled inventory',250),('fees','Paid modeled native commissions',270)),5)
        self.notes=tk.Text(evidence,height=6,wrap='word',background='#10151b',foreground=TEXT);self.notes.pack(side='left',fill='both',expand=True)
        evidence_scroll=ttk.Scrollbar(evidence,command=self.notes.yview);evidence_scroll.pack(side='right',fill='y');self.notes.configure(yscrollcommand=evidence_scroll.set)
        config=app.intelligent.pending_config;self.funding=tk.StringVar(value=config.funding_mode)
        ttk.Label(settings,text='First Start freezes the baseline and risk/model settings. Existing v1.04 records are preserved in the read-only archive.',wraplength=1200).grid(row=0,column=0,columnspan=3,sticky='w',pady=8)
        ttk.Label(settings,text='Initial shadow portfolio').grid(row=1,column=0,sticky='w')
        self.funding_box=ttk.Combobox(settings,textvariable=self.funding,values=('ACCOUNT_AVAILABLE','FICTIONAL_100_EACH'),width=30,state='readonly');self.funding_box.grid(row=1,column=1,sticky='w',padx=10)
        self.inputs=[];self.fields={}
        for i,(key,label,value) in enumerate((('max_source_fraction','Maximum source fraction (0–0.5)',config.max_source_fraction),
                ('max_asset_weight','Maximum asset weight (0.2–1)',config.max_asset_weight),('risk_aversion','Volatility risk weight',config.risk_aversion),
                ('uncertainty_z','Uncertainty multiplier (1–5)',config.uncertainty_z),('concentration_penalty','Concentration penalty (0–0.1)',config.concentration_penalty)),2):
            ttk.Label(settings,text=label).grid(row=i,column=0,sticky='w',pady=7);v=tk.StringVar(value=str(value));self.fields[key]=v
            w=ttk.Entry(settings,textvariable=v,width=15);w.grid(row=i,column=1,sticky='w',padx=10);self.inputs.append(w)
        self.provider=tk.StringVar(value=config.provider)
        ttk.Label(settings,text='Conditional fill provider').grid(row=7,column=0,sticky='w',pady=7)
        self.provider_box=ttk.Combobox(settings,textvariable=self.provider,values=('TRADE_THROUGH_QUEUE_V1','NO_FILL_OBSERVATION_V1'),width=30,state='readonly');self.provider_box.grid(row=7,column=1,sticky='w',padx=10)
        ttk.Label(settings,text='100 days of closed hourly USD reference history · direct 24h labels · 40 minimum training days · 12 analogs · 14 validation + 14 holdout days.\n30s reviews / 120s competitiveness / 600s child / 1800s campaign / 3 replacements. Acquired assets have no mandatory holding deadline.\nNo fixed dollar profit floor, forced ETH return, compulsory future exit fee, counterparty fee or automatic taker fallback.\nUSD historical products are read-only forecast references; only the seven native pairs can receive orders. Native fees are modeled quote commissions until explicit settlement evidence exists.',wraplength=1180).grid(row=8,column=0,columnspan=3,sticky='w',pady=15)
        self.footer=ttk.Label(shell,text='Closing CoinCat exits safely. Tray/minimize integration is removed. Marked/model results are not realized profit or exchange execution proof.',wraplength=1280,style='Muted.TLabel')
        self.footer.pack(side='bottom',anchor='w',pady=3,before=self.tabs)
        def fit(event):
            if event.widget is self.root:
                def wrap(widget):
                    if isinstance(widget,ttk.Label) and int(widget.cget('wraplength') or 0)>0:widget.configure(wraplength=max(400,event.width-65))
                    for child in widget.winfo_children():wrap(child)
                wrap(shell)
        self.root.bind('<Configure>',fit,add='+')
        self.render()
    def start(self):
        try:
            e=self.app.intelligent
            config=e.pending_config if e.store is not None else replace(IntelligentConfig(),funding_mode=self.funding.get(),provider=self.provider.get(),**{k:D(v.get()) for k,v in self.fields.items()}).checked()
            self.app.start_intelligent(config)
        except (ValueError,ArithmeticError):self.app.status.set('Check the shadow portfolio and finite risk settings.')
    def render(self):
        e=self.app.intelligent;v=e.view();s=v['state'];public=e.public();p=e.progress();perf=v['performance'] or {}
        self.start_button.configure(state='disabled' if self.app.busy or e.running or public['state'] in ('COMPLETE','REVIEW_REQUIRED') else 'normal')
        frozen=s is not None or e.running
        self.funding_box.configure(state='disabled' if frozen else 'readonly');self.provider_box.configure(state='disabled' if frozen else 'readonly')
        for widget in self.inputs:widget.configure(state='readonly' if frozen else 'normal')
        fresh=e.last_frame is not None and 0<=self.app.clock()-e.last_frame['at']<=30;known=bool(perf and (fresh or public['state']=='COMPLETE'))
        edge=perf.get('advantage_usd') if known else None
        self.metric.set('Net modeled USD advantage vs original HOLD: '+number(edge)+('' if not known else '  ('+number(perf.get('advantage_percent'))+'%)'))
        self.metric_label.configure(foreground=MUTED if edge is None else GREEN if edge>=0 else RED)
        self.status.set(public['state']+' · '+public['data_state']+' inputs · '+public['history_state']+' history '+str(public['history_observations'])+'/'+str(public['history_required'])+' aligned hours\n'+
            str(public['reviews'])+' reviews / '+str(public['direction_checks'])+' direction checks · '+str(public['qualified_checks'])+' qualified · '+str(public['orders'])+' orders · '+str(public['fill_events'])+' conditional fill events'+
            ('' if p is None else f" · {p['valid_seconds']/3600:.3f} / 168 valid h · {p['restart_count']} restarts"))
        self.bar['value']=0 if p is None else p['completion_percent']
        for tree in (self.decisions,self.orders,self.holdings):
            for key in tree.get_children():tree.delete(key)
        rows=sorted(v['rows'],key=lambda r:(r['state']=='QUALIFIED',r.get('projected_advantage_usd',D('-Infinity'))),reverse=True)
        for i,row in enumerate(rows,1):
            self.decisions.insert('','end',values=(i,row['pair'],row['side'],row['source']+' → '+row['target'],row['state'],native(row.get('size')),
                native(row.get('price'))+' '+row['pair'].split('-')[1],number(row.get('projected_advantage_usd')),row['reason'].replace('_',' ')))
        chosen=next((r for r in rows if r['state']=='QUALIFIED'),None);o=v['active_order']
        if o is not None:
            candidate=o.get('latest_projection',o['projection'])
            chosen=candidate if candidate.get('state')=='QUALIFIED' else o['projection']
        if chosen:
            reassessed='' if o is None or o.get('latest_projection',{}).get('state','QUALIFIED')=='QUALIFIED' else 'Latest reassessment: HOLD · '+o['latest_projection']['reason'].replace('_',' ')+'\nOriginal intent retained below for audit.\n'
            self.best.set(('Resting order '+o['state']+' · '+o['reason'].replace('_',' ')+'\n'+reassessed if o is not None else 'PROPOSE · conditional shadow hypothesis\n')+
                chosen['explanation']+'\nBase quantity '+native(chosen['size'])+' · '+chosen['side']+' '+chosen['pair']+' · maker limit '+native(chosen['price'])+' '+chosen['pair'].split('-')[1]+
                '\nEstimated own maker fee '+native(chosen['projected_entry_fee_native'])+' '+chosen['fee_currency']+' (quote-currency model assumption)'+
                '\nExpected 24h incremental USD '+number(chosen['expected_24h_incremental_usd'])+' · after risk/uncertainty '+number(chosen['projected_advantage_usd'])+
                '\nForecast / execution uncertainty USD '+number(chosen['forecast_uncertainty_usd'])+' / '+number(chosen['execution_uncertainty_usd'])+
                '\nSource available '+native(chosen['available_source'])+' '+chosen['source']+' · projected remaining '+native(chosen['after_source'])+' '+chosen['source'])
        else:self.best.set('HOLD · '+v['reason'].replace('_',' ')+'\nNo conversion currently has a supported positive 24-hour risk-adjusted portfolio advantage.\nKeep the current inventory; no trade is required.')
        evidence={} if s is None else s['forecast_evidence'];provenance=evidence.get('provenance',{})
        self.model.set('Forecast UNVALIDATED · maker-fill calibration UNKNOWN. Conditional queue/participation assumptions never prove exchange execution.\n'+
            'Historical validation predictions '+str(public['validation_predictions'])+' · unseen chronological holdout predictions '+str(public['holdout_predictions'])+
            '\nHoldout MAE (model / naive momentum / HOLD): '+' / '.join(number(provenance.get('holdout',{}).get(k)) for k in ('prediction_mae','naive_mae','hold_mae'))+
            '\nModel source: closed hourly reference prices; each training outcome covers 24 hours. The model is not a scaled ten-minute return.')
        for row in reversed(v['orders']):
            campaign=s['campaigns'][row['campaign']];now=self.app.clock()
            remaining=0 if row['state'] in ('FILLED','CANCELED') else max(0,round(row['expires_at']-now))
            self.orders.insert('','end',values=(row['reference'],row['pair'],row['side'],row['state'],native(row['price'])+' '+row['pair'].split('-')[1],
                native(row['size']),native(row['filled']),str(round(row['age_s']))+' / '+str(round(row['expires_at']-row['created_at'])),
                str(remaining)+' / '+str(max(0,round(campaign['expires_at']-now))),row['reason'].replace('_',' ')))
        if s is None:
            self.details.set('Start once to freeze a new isolated v1.05 shadow baseline. No account funds move. v1.04 trial records are not adopted or reset.');self.draw_trend();return
        for asset in WATCH_ASSETS:self.holdings.insert('','end',values=(asset,native(s['original'][asset]),native(s['wallet'][asset]),native(s['fees_native'][asset])))
        r=e.rolling_performance();metrics=s['metrics']
        self.details.set('Modeled portfolio USD '+number(perf.get('portfolio_usd') if known else None)+' · original HOLD USD '+number(perf.get('hold_usd') if known else None)+
            '\nLatest fill mark change USD '+number(metrics['last_fill_change_usd'])+' · known modeled fees valued at fill USD '+number(metrics['fees_usd_at_fill'])+
            ' · max marked drawdown '+number(s['max_drawdown']*100)+'%'+
            '\nRolling advantage change: '+ ' · '.join(k+': '+number(x['advantage_change_usd'])+' USD / '+x['state'] for k,x in r.items())+
            '\nMarked value includes paid commissions and open losses. No unexecuted future conversion is deducted. Realized account profit NOT ASSESSED.')
        note='Rejections: '+str(public['rejection_breakdown']['categories'])+'\nForward forecasts: '+str(s['prediction_counts'])+'\n24h forward samples overlap and are not independent statistical evidence.'
        if o is not None:note+='\nOrder remaining reservation '+native(o['reserved'])+' '+o['source']+' · '+o['reason']+'\nReplacement requires reconciled cancellation, original remaining quantity/budget and a fresh positive decision.'
        if o is not None and s['campaigns'][o['campaign']]['pending_replace']:
            row=next((r for r in rows if r['pair']==o['pair'] and r['side']==o['side'] and r['state']=='QUALIFIED'),None)
            note+='\nRepricing is pending cancellation/reconciliation; no replacement is authorized yet.'
            if row is not None:note+=' Current candidate native limit '+native(row['price'])+' '+o['pair'].split('-')[1]+'. Remaining original budget/quantity still binds.'
        self.notes.configure(state='normal');self.notes.delete('1.0','end');self.notes.insert('1.0',note);self.notes.configure(state='disabled');self.draw_trend()
    def draw_trend(self):
        canvas=self.canvas;canvas.delete('all');s=self.app.intelligent.view()['state'];rows=[] if s is None else s['performance_history'];w=max(100,canvas.winfo_width());h=max(80,canvas.winfo_height())
        if len(rows)<2:canvas.create_text(w/2,h/2,text='Observed USD advantage vs original HOLD · trend awaits two samples',fill=MUTED);return
        low=min(D(0),*(r['advantage_usd'] for r in rows));high=max(D(0),*(r['advantage_usd'] for r in rows));span=high-low or D('.01');start,end=rows[0]['at'],rows[-1]['at']
        def point(r):return 60+(w-80)*(r['at']-start)/max(1,end-start),h-25-float((r['advantage_usd']-low)/span)*(h-50)
        zero=h-25-float((D(0)-low)/span)*(h-50);canvas.create_line(60,zero,w-20,zero,fill=EDGE)
        for a,b in zip(rows,rows[1:]):
            if b['at']-a['at']<=600:canvas.create_line(*point(a),*point(b),fill=GREEN if b['advantage_usd']>=0 else RED,width=2)
        canvas.create_text(5,12,text=number(high),fill=MUTED,anchor='nw');canvas.create_text(5,h-12,text=number(low),fill=MUTED,anchor='sw')
