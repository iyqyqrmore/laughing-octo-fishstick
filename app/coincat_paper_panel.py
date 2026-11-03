"""Local-only simulated portfolio, seven BBO books and fourteen directional views."""
from datetime import datetime,timezone
from decimal import Decimal as D
import time
import tkinter as tk
from tkinter import ttk

from coincat_hover import Hover
from coincat_paper_policy import AutoConfig,DIRECTIONS,KICKOFFS,MODELS,direction_defaults
from coincat_paper_engine import PaperEngine
from coincat_watchlist import WATCH_PAIRS

DISCLOSURE=('Paper only. No demonstrated edge or guaranteed profit. Maker orders may never fill. '
    'Unfilled orders normally incur no execution fee; partials incur supported fees and change exposure. '
    'Reserved funds, opportunity cost and holding risk remain. Resting orders may fill unfavorably. '
    'Paper gains are simulated and never account profit.')


class PaperPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=8);self.app=app;self.books={};self.pages={};self.direction_pages={};self.tier={}
        self.direction_text={v['id']:tk.StringVar(value='Not funded · Paper session has not started.') for v in DIRECTIONS}
        self.direction_vars={key:{name:tk.BooleanVar(value=value) if name=='enabled' else tk.StringVar(value=str(value))
            for name,value in values.items()} for key,values in direction_defaults().items()}
        self.values={key:tk.StringVar(value=value) for key,value in (
            ('amount_eth',''),('budget_percent','10%'),('kickoff','ETH_BTC'),('model','CONSERVATIVE_STRESS_V1'),
            ('seed','1'),('review_s','30'),('cooldown_s','30'),('duration_hours','24'),('max_orders','16'),
            ('fee_ceiling_pct','2'),('fee_stress_bps','5'),('membership','Basic'))}
        self.opt_in=tk.BooleanVar(value=False);self.session_widgets=[];self.market_widgets=[];self.settings_window=None
        self.message=tk.StringVar(value='OFF · Select a paper allocation and explicitly opt in. No live orders.')
        self.score=tk.StringVar(value='Shared paper wallet: not funded. ETH HOLD baseline: unset. Actual profit: not established.')
        title=ttk.Label(self,text='AUTO MAKER ROTATION · PAPER ONLY · LIVE BLOCKED',style='Metric.TLabel')
        title.pack(anchor='w');Hover(title,DISCLOSURE)
        first=ttk.Frame(self);first.pack(fill='x',pady=4)
        check=ttk.Checkbutton(first,text='Auto-Start Maker Rotation — PAPER ONLY',variable=self.opt_in)
        check.pack(side='left');self.session_widgets.append(check)
        ttk.Label(first,text='Paper budget').pack(side='left',padx=(10,3))
        percent=ttk.Combobox(first,textvariable=self.values['budget_percent'],values=('5%','10%','15%','20%','25%','Exact custom'),state='readonly',width=12)
        percent.pack(side='left');percent.bind('<<ComboboxSelected>>',lambda e:self.update_budget_default());self.session_widgets.append(percent)
        amount=ttk.Entry(first,textvariable=self.values['amount_eth'],width=16);amount.pack(side='left',padx=4)
        amount.bind('<KeyRelease>',lambda e:self.values['budget_percent'].set('Exact custom'));self.session_widgets.append(amount)
        ttk.Label(first,text='ETH · hypothetical working slice').pack(side='left')
        Hover(amount,'Defaults to 10% of the fresh working ETH proposal; 5–25% or exact custom. '
            'No real assets move. Native minima/caps govern; a small order is blocked rather than rounded up. '
            'All fourteen views share this single initial ETH slice.')
        actions=ttk.Frame(self);actions.pack(fill='x',pady=3)
        for label,command in (('Start Auto Paper Trader',app._start_auto_paper),('Pause paper',app._pause_paper),
                ('STOP',app._stop),('Reconcile paper',app._reconcile_paper),('New paper session',app._new_paper_session),
                ('Session settings…',self.settings),('History…',self.history)):
            button=ttk.Button(actions,text=label,command=command);button.pack(side='left',padx=(0,4))
            Hover(button,'Paper session only. Start is explicit; saved opt-in does not resume after restart. '
                'Pause/STOP preserve inventory and reservations; neither confirms cancellation or sells a holding. '
                'Reconciliation leaves PAUSED. A new session retains the previous database and starts a separate baseline.')
        self.message_label=ttk.Label(self,textvariable=self.message,wraplength=950)
        self.message_label.pack(anchor='w',pady=(2,4))
        scoreboard=ttk.Label(self,textvariable=self.score,wraplength=1120,style='Muted.TLabel');scoreboard.pack(anchor='w',pady=(0,5))
        Hover(scoreboard,DISCLOSURE+' Marked ETH is a midpoint reference before exit costs. '
            'After-cost recoverable ETH remains UNKNOWN without sized exits, matched times, fee units and residue valuation. '
            'Underwater time/drawdown use observed samples, not continuous risk coverage.')
        self.market_tabs=ttk.Notebook(self);self.market_tabs.pack(fill='both',expand=True)
        for pair in WATCH_PAIRS:
            page=ttk.Frame(self.market_tabs,padding=5);self.market_tabs.add(page,text=pair);self.pages[pair]=page
        self.market_tabs.bind('<<NotebookTabChanged>>',self._selected)
        def resize(event):
            width=max(350,event.width-20)
            self.message_label.configure(wraplength=width);scoreboard.configure(wraplength=width)
        self.bind('<Configure>',resize)
        self._ensure_market(WATCH_PAIRS[0])
        if app.paper.config is not None:self.from_config(app.paper.config)
        self.refresh()

    def update_budget_default(self):
        if self.app.paper.engine is not None:return
        choice=self.values['budget_percent'].get()
        if choice=='Exact custom':return
        try:
            funding=self.app._funding()
            working=funding['row'].get('working',D(0)) if funding['valid'] else D(0)
            self.values['amount_eth'].set(str(working*D(choice.rstrip('%'))/100) if working>0 else '')
        except (ValueError,ArithmeticError,AttributeError):pass

    def configuration(self):
        def integer(key):
            raw=D(self.values[key].get())
            if not raw.is_finite() or raw!=raw.to_integral_value():raise ValueError('INTEGER_SETTING_REQUIRED')
            return int(raw)
        def wait_seconds(items):
            value=D(items['wait_s'].get())
            if not value.is_finite() or value!=value.to_integral_value():raise ValueError('INTEGER_ORDER_WAIT_REQUIRED')
            return int(value)
        directions={key:dict(enabled=items['enabled'].get(),target_pct=D(items['target_pct'].get()),
            entry_bps=D(items['entry_bps'].get()),source_pct=D(items['source_pct'].get()),
            wait_s=wait_seconds(items)) for key,items in self.direction_vars.items()}
        hours=D(self.values['duration_hours'].get());seconds=hours*3600
        if not seconds.is_finite() or seconds!=seconds.to_integral_value():raise ValueError('INVALID_SESSION_HORIZON')
        return AutoConfig(D(self.values['amount_eth'].get()),directions,self.opt_in.get(),
            self.values['kickoff'].get(),self.values['model'].get(),integer('seed'),integer('review_s'),
            integer('cooldown_s'),int(seconds),integer('max_orders'),D(self.values['fee_ceiling_pct'].get())/100,
            D(self.values['fee_stress_bps'].get()),self.values['membership'].get()).checked()

    def from_config(self,config):
        self.opt_in.set(config.opt_in);self.values['budget_percent'].set('Exact custom')
        data=dict(amount_eth=config.amount_eth,kickoff=config.kickoff,model=config.model,seed=config.seed,
            review_s=config.review_s,cooldown_s=config.cooldown_s,duration_hours=D(config.duration_s)/3600,
            max_orders=config.max_orders,fee_ceiling_pct=config.fee_ceiling*100,fee_stress_bps=config.fee_stress_bps,
            membership=config.membership)
        for key,value in data.items():self.values[key].set(str(value))
        for key,items in config.directions.items():
            for name,value in items.items():self.direction_vars[key][name].set(value if name=='enabled' else str(value))

    def settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():self.settings_window.lift();return
        window=tk.Toplevel(self);self.settings_window=window;window.title('Paper session settings · Frozen at Start')
        body=ttk.Frame(window,padding=12);body.pack(fill='both',expand=True)
        ttk.Label(body,text='BBO stress scenarios; no observed queue/depth or calibrated fill probability.',wraplength=600).grid(row=0,column=0,columnspan=2,sticky='w',pady=5)
        for row,(key,label,choices) in enumerate((
            ('kickoff','Chosen kickoff · no fallback',KICKOFFS),('model','Provider model',MODELS),('seed','Frozen scenario seed',None),
            ('review_s','Resting-order review · seconds',None),('cooldown_s','New-order cooldown · seconds',None),
            ('duration_hours','Original session horizon · hours',None),('max_orders','Maximum session orders',None),
            ('fee_ceiling_pct','Maker fee ceiling · percent',None),('fee_stress_bps','Added fee stress · bps',None),
            ('membership','Membership label · never overrides fees',('None','Basic','Preferred','Premium'))),1):
            ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            widget=ttk.Entry(body,textvariable=self.values[key],width=32) if choices is None else ttk.Combobox(body,
                textvariable=self.values[key],values=choices,state='readonly',width=31)
            widget.grid(row=row,column=1,sticky='ew',pady=4);self.session_widgets.append(widget)
        text=('One open order, 16 session orders, 24-hour horizon, 30-second reviews/cooldown are operational defaults. '
            'The first native cap for a new asset is frozen from its canonical acquisition receipt; a cap never credits funds. '
            'Basic has no assumed Advanced rebate. No membership infers zero fees, rebates or fee currencies. Subscription costs are excluded from execution fees and reported separately as unmodeled. '
            'The simulated venue explicitly charges supported quote-currency fees from fresh account rates plus stress; '
            'actual exchange fee units remain unverified. Missing/stale rates block admission. '+DISCLOSURE)
        ttk.Label(body,text=text,wraplength=620).grid(row=12,column=0,columnspan=2,sticky='w',pady=10)
        ttk.Button(body,text='Close',command=window.destroy).grid(row=13,column=1,sticky='e')
        self._freeze()

    def _freeze(self):
        frozen=self.app.paper.engine is not None
        for widget in self.session_widgets+self.market_widgets:
            if not widget.winfo_exists():continue
            if frozen:widget.state(['disabled'])
            else:
                widget.state(['!disabled'])
                if isinstance(widget,ttk.Combobox):widget.state(['readonly'])

    def history(self):
        """Private read-only paper history. No old loss or wallet is overwritten."""
        window=tk.Toplevel(self);window.title('Local paper sessions · Separate ETH baselines')
        body=ttk.Frame(window,padding=10);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Previous sessions remain separate studies. Their outcomes are not pooled capital or account profit.').pack(anchor='w')
        ttk.Label(body,text='Showing up to 64 recent sessions; older databases are retained locally.',style='Muted.TLabel').pack(anchor='w')
        tree=ttk.Treeview(body,columns=('session','model','state','hold','mark','fills'),show='headings',height=8)
        for key in tree['columns']:tree.heading(key,text=key.title());tree.column(key,width=130,minwidth=80)
        tree.pack(fill='both',expand=True,pady=6)
        detail=tk.Text(body,width=110,height=12,wrap='word');detail.pack(fill='both',expand=True);records={}
        paths=sorted(self.app.paper.directory.glob('paper_*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)[:64]
        for index,path in enumerate(paths):
            try:
                state=PaperEngine.inspect(path);context=state.get('auto',{});performance=context.get('performance',{})
                key=str(index);records[key]=state
                tree.insert('','end',iid=key,values=(context.get('session','UNKNOWN')[:12],context.get('config',{}).get('model','UNKNOWN'),
                    state['mode'],state['initial_eth'],performance.get('midpoint_delta_eth','UNKNOWN'),state['simulated_fills']))
            except Exception:tree.insert('','end',values=('UNAVAILABLE','UNKNOWN','REVIEW REQUIRED','UNKNOWN','UNKNOWN','UNKNOWN'))
        def selected(event=None):
            keys=tree.selection()
            if not keys or keys[0] not in records:return
            state=records[keys[0]];context=state['auto']
            detail.configure(state='normal');detail.delete('1.0','end')
            detail.insert('1.0',str(dict(wallet=state['wallet'],performance=context.get('performance'),
                fixed_horizon=context.get('horizon'),last_reason=context.get('last_reason'),pending=context.get('pending'))))
            detail.configure(state='disabled')
        tree.bind('<<TreeviewSelect>>',selected)
        ttk.Button(body,text='Close',command=window.destroy).pack(anchor='e')
        return window

    def events(self,direction):
        manager=self.app.paper
        window=tk.Toplevel(self);window.title('Local simulated events · '+direction.replace('_',' → '))
        text=tk.Text(window,width=105,height=22,wrap='word');text.pack(fill='both',expand=True)
        text.insert('end','SIMULATED_ASSUMPTION only. No exchange fill, account profit or network request.\n\n')
        if manager.engine is not None:
            state=manager.engine.private_state()
            references=[ref for ref,item in state['auto']['intent_meta'].items() if item['direction']==direction][-4:]
            try:
                for reference in references:
                    for row in manager.engine.local_events(reference):text.insert('end',str(row)+'\n')
            except Exception:text.insert('end','Paper event history unavailable; no records changed.')
        text.configure(state='disabled')
        return window

    def _selected(self,event=None):
        selected=self.market_tabs.select()
        pair=next((p for p,page in self.pages.items() if str(page)==selected),None)
        if pair:self._ensure_market(pair);self.refresh()

    def _ensure_market(self,pair):
        page=self.pages[pair]
        if hasattr(page,'book_trees'):return
        page.columnconfigure(0,weight=1);page.columnconfigure(1,weight=2);page.rowconfigure(1,weight=1)
        ttk.Label(page,text='Best bid/ask · depth and queue size UNKNOWN',style='Muted.TLabel').grid(row=0,column=0,sticky='w')
        book=ttk.Frame(page);book.grid(row=1,column=0,sticky='nsew',padx=(0,8))
        page.book_trees={}
        for label in ('Ask','Bid'):
            ttk.Label(book,text=label).pack(anchor='w')
            tree=ttk.Treeview(book,columns=('price','size'),show='headings',height=1)
            base,quote=pair.split('-')
            tree.heading('price',text=quote+' per '+base);tree.heading('size',text='Observed size')
            tree.column('price',width=125,minwidth=70);tree.column('size',width=90,minwidth=65)
            tree.pack(fill='x',pady=(0,6));page.book_trees[label]=tree
        page.book_status=tk.StringVar(value='Unobserved')
        ttk.Label(book,textvariable=page.book_status,wraplength=320).pack(anchor='w')
        views=ttk.Notebook(page);views.grid(row=1,column=1,sticky='nsew')
        page.direction_tabs=views
        for view in (v for v in DIRECTIONS if v['pair']==pair):
            frame=ttk.Frame(views);views.add(frame,text=view['source']+' → '+view['target'])
            self.direction_pages[view['id']]=frame
            frame.heading_text=tk.StringVar(value=f"{pair} · {view['side']} · {view['source']} → {view['target']} · PAPER not funded")
            ttk.Label(frame,textvariable=frame.heading_text,padding=6).pack(anchor='w')
            container=ttk.Frame(frame);container.pack(fill='both',expand=True)
            viewport=tk.Canvas(container,highlightthickness=0,width=1,background='#0b0e12')
            viewport.pack(side='left',fill='both',expand=True)
            scroll=ttk.Scrollbar(container,orient='vertical',command=viewport.yview);scroll.pack(side='right',fill='y')
            viewport.configure(yscrollcommand=scroll.set)
            body=ttk.Frame(viewport,padding=6);window=viewport.create_window((0,0),window=body,anchor='nw')
            body.bind('<Configure>',lambda e,c=viewport:c.configure(scrollregion=c.bbox('all')))
            viewport.bind('<Configure>',lambda e,c=viewport,w=window:c.itemconfigure(w,width=e.width))
            frame.viewport=viewport
            controls=ttk.Frame(body);controls.pack(fill='x',pady=4)
            enabled=ttk.Checkbutton(controls,text='Enabled',variable=self.direction_vars[view['id']]['enabled'])
            enabled.grid(row=0,column=0,sticky='w');self.market_widgets.append(enabled)
            for index,(name,label) in enumerate((('target_pct','Net ETH target %'),('entry_bps','Entry offset bps'),
                    ('source_pct','Source cap %'),('wait_s','Order wait seconds')),1):
                ttk.Label(controls,text=label).grid(row=(index-1)//2*2,column=1+(index-1)%2,sticky='w',padx=6)
                entry=ttk.Entry(controls,textvariable=self.direction_vars[view['id']][name],width=15)
                entry.grid(row=(index-1)//2*2+1,column=1+(index-1)%2,sticky='ew',padx=6)
                self.market_widgets.append(entry)
            detail=ttk.Label(body,textvariable=self.direction_text[view['id']],wraplength=640,justify='left')
            detail.pack(anchor='w',fill='x',pady=3)
            body.bind('<Configure>',lambda e,label=detail:label.configure(wraplength=max(220,e.width-14)),add='+')
            events=ttk.Button(body,text='Local paper events…',command=lambda key=view['id']:self.events(key));events.pack(anchor='w')
            frame.events_button=events
            def wheel(event,canvas=viewport):
                steps=-1 if event.num==4 else 1 if event.num==5 else -int(event.delta/120)
                if steps:canvas.yview_scroll(steps,'units')
                return 'break'
            def bind_wheel(widget,handler=wheel):
                for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):widget.bind(sequence,handler,add='+')
                for child in widget.winfo_children():bind_wheel(child,handler)
            bind_wheel(body)
            Hover(detail,lambda key=view['id']:DISCLOSURE+' Candidate sizes own no funds. Partial source/proceeds remain locked. '
                'A 30-second review retains a resting order unless a fresh documented reason qualifies replacement. '
                'Cancel must reconcile before a replacement; the original expiry never renews through gaps. '
                'Exact conditional target ETH: '+str(self.app.paper.view_rows.get(key,{}).get('required_eth','UNKNOWN')))
        self._freeze()

    def refresh(self,result=None,*,at=None):
        now=time.time() if at is None else at;manager=self.app.paper
        if result is not None:
            for row in result.get('watched_markets',()):self.books[row['pair']]=row
            self.tier=result.get('fee_evidence',{})
        state=manager.engine.private_state() if manager.engine is not None else None
        if state is None:
            self.message.set('OFF · '+(manager.last_problem or 'Explicit paper opt-in and a fresh working ETH proposal are required.'))
            self.score.set('One shared paper wallet is not funded. No simulated orders. Actual profit NOT ESTABLISHED.')
        else:
            context=state['auto'];performance=context['performance'];public=manager.public()
            expiry=datetime.fromtimestamp(state['limits']['expires_at'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            self.message.set(public['state']+' · '+context['last_reason']+' · '+manager.config.model+' · seed '+str(manager.config.seed)+
                ' · original expiry '+expiry+' · simulated venue / NO DEMONSTRATED EDGE')
            def compact(value):return 'UNKNOWN' if value is None else format(value,'.10g')
            wallet=' · '.join(f'{a}: total {compact(q)}, available '+compact(manager.engine.available(a))+', reserved '+
                compact(manager.engine._held(state,a)) for a,q in state['wallet'].items() if q or a=='ETH')
            known=None if state['mode']=='RECONCILIATION_REQUIRED' else performance.get('recoverable_eth');marked=performance.get('marked_eth')
            fee_text=', '.join(compact(q)+' '+a for a,q in sorted(performance.get('fees',{}).items())) or '0 observed execution fees'
            if any(not f['settled'] for f in state['fills'].values()):fee_text+=' + UNKNOWN pending fee resolution'
            self.score.set('Shared paper inventory · '+wallet+
                f"\nETH HOLD {state['initial_eth']} · Realized paper ΔETH "+compact(performance.get('realized_paper_delta_eth'))+
                ' · Midpoint marked ETH '+compact(marked)+
                ' · Recoverable after-cost ETH '+compact(known)+
                '\nMarked ΔETH '+compact(performance.get('midpoint_delta_eth'))+' · Max observed midpoint drawdown '+compact(performance.get('max_midpoint_drawdown_pct'))+'%'+
                f" · Observed underwater {round(performance.get('observed_underwater_s',0))} s · Fees "+fee_text+
                f" · Paper fills {public['fills']} / non-fills {public['non_fills']} · Actual profit NOT ESTABLISHED")
        for pair,page in self.pages.items():
            if not hasattr(page,'book_trees'):continue
            observed=self.books.get(pair,{})
            book=observed.get('book');age=None if not book else now-book[2]
            for label,index in (('Bid',0),('Ask',1)):
                tree=page.book_trees[label]
                for item in tree.get_children():tree.delete(item)
                tree.insert('','end',values=('UNOBSERVED' if book is None else str(book[index]),'UNKNOWN'))
            page.book_status.set(('No current observation' if age is None else f'Local quote age {round(age)} s')+
                (' · deferred; display only' if observed.get('deferred') else '')+' · '+str(observed.get('reason') or 'BBO only; no sized queue evidence'))
            for view in (v for v in DIRECTIONS if v['pair']==pair):
                row=manager.view_rows.get(view['id'],{})
                text=row.get('state','HOLD')+' · '+row.get('reason','UNFUNDED_AWAIT_EXPLICIT_SESSION_OR_CONFIRMED_RECEIPT')
                heading=f"{pair} · {view['side']} · {view['source']} → {view['target']} · PAPER "+row.get('state','HOLD')
                if state is not None:
                    available=manager.engine.available(view['source']);reserved=manager.engine._held(state,view['source'])
                    text+=f"\n{view['source']} available "+('UNKNOWN' if available is None else str(available))+f" · reserved/partial locked {reserved} · quarantined "+('UNKNOWN' if available is None else '0')
                    matches=[o for ref,o in state['orders'].items() if state['auto']['intent_meta'].get(ref,{}).get('direction')==view['id']]
                    if matches:
                        order=matches[-1]
                        heading=f"{pair} · {view['side']} · {view['source']} → {view['target']} · PAPER "+(
                            'RECONCILIATION_REQUIRED' if state['mode']=='RECONCILIATION_REQUIRED' else order['state'])
                        text+=f"\nPAPER {order['state']} · {order['side']} limit {order['limit_price']} · cumulative {order['filled_base']} / {order['base_size']} · reserve {order['reserved']} {order['source']}"
                        text+=f"\nOrder age {round(max(0,now-order['created_at']))} s · modeled fee currency {pair.split('-')[1]} · next policy review in "+str(round(max(0,manager.config.review_s-(now-(state['auto']['last_review'] or now)))))+' s'
                        text+=' · venue '+state['auto']['venue'].get(order['reference'],{}).get('data_state','AWAITING_RECEIPT')
                if row.get('plan'):
                    text+=f"\nCandidate {row.get('limit_price')} · native base size {row['plan']['gross_base_quantity']} · source cap {row['source_budget']}"
                    required=row.get('required_eth')
                    target='conditional only' if required is None else 'approx '+format(required,'.10g')
                    text+='\nFee ceiling '+format(row['fee_fraction']*100,'.10g')+f"% · target ETH {target} · candidate is not reserved funding"
                fee_at=self.tier.get('captured_at')
                fee_age='UNOBSERVED' if fee_at is None else str(round(now-fee_at))+' s'
                maker=self.tier.get('maker');rate='UNKNOWN' if not isinstance(maker,D) else format(maker*100,'.10g')+'%'
                text+='\nAccount maker '+rate+' · fee capture age '+fee_age+\
                    ' · modeled quote-currency debit; exchange fee units unverified'
                self.direction_text[view['id']].set(text)
                self.direction_pages[view['id']].heading_text.set(heading)
        self._freeze()
