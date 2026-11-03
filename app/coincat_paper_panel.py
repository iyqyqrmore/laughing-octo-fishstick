"""Local-only simulated portfolio, seven BBO books and fourteen directional views."""
from datetime import datetime,timezone
from decimal import Decimal as D
import sqlite3
import time
import tkinter as tk
from tkinter import ttk

from coincat_hover import Hover
from coincat_paper_policy import AutoConfig,POLICY,SHORT_POLICY,DIRECTIONS,KICKOFFS,MODELS,direction_defaults
from coincat_paper_engine import PaperEngine
from coincat_watchlist import WATCH_PAIRS
from coincat_global_paper import GlobalSettings,settings_at

DISCLOSURE=('Paper only. No demonstrated edge or guaranteed profit. Maker orders may never fill. '
    'Unfilled orders normally incur no execution fee; partials incur supported fees and change exposure. '
    'Reserved funds, opportunity cost and holding risk remain. Resting orders may fill unfavorably. '
    'Paper gains are simulated and never account profit.')
POLICY_LABELS={POLICY:'Patient target',SHORT_POLICY:'Short-lived / net ETH target'}


class PaperPanel(ttk.Frame):
    def __init__(self,parent,app,*,settings_parent=None,legacy_parent=None):
        super().__init__(parent,padding=8);self.app=app;self.books={};self.pages={};self.direction_pages={};self.tier={}
        self.direction_text={v['id']:tk.StringVar(value='Not funded · Paper session has not started.') for v in DIRECTIONS}
        self.direction_vars={key:{name:tk.BooleanVar(value=value) if name=='enabled' else tk.StringVar(value=str(value))
            for name,value in values.items()} for key,values in direction_defaults().items()}
        self.values={key:tk.StringVar(value=value) for key,value in (
            ('amount_eth',''),('budget_percent','50%'),('kickoff','ETH_BTC'),('model','CONSERVATIVE_STRESS_V1'),
            ('seed','1'),('review_s','30'),('cooldown_s','30'),('duration_hours','24'),('max_orders','16'),
            ('fee_ceiling_pct','2'),('fee_stress_bps','5'),('membership','Basic'))}
        self.values.update({key:tk.StringVar(value=value) for key,value in (
            ('order_policy',POLICY_LABELS[SHORT_POLICY]),('order_ttl_s','120'),('min_rest_s','30'),('reprice_bps','10'))})
        self.global_values={key:tk.StringVar(value=value) for key,value in (
            ('min_net_usd','0.01'),('source_pct','50'),('review_s','30'),('reconsider_s','120'))}
        self.global_applied_draft=None;self.global_status=tk.StringVar(value='Apply Trading Settings before Start. UNKNOWN blocks new entries.')
        self.applied_summary=tk.StringVar(value='No global settings applied. Fields below are drafts until Apply.')
        self.legacy_controls=None
        if legacy_parent is not None:
            self.legacy_controls=ttk.Notebook(legacy_parent);self.legacy_controls.pack(fill='both',expand=True)
        self.opt_in=tk.BooleanVar(value=False);self.session_widgets=[];self.market_widgets=[];self.settings_window=None
        self.short_widgets=[]
        self.message=tk.StringVar(value='OFF · Select a paper allocation and explicitly opt in. No live orders.')
        self.score=tk.StringVar(value='Shared paper wallet: not funded. ETH HOLD baseline: unset. Actual profit: not established.')
        title=ttk.Label(self,text='AUTO MAKER ROTATION · PAPER ONLY · LIVE BLOCKED',style='Metric.TLabel')
        title.pack(anchor='w');Hover(title,DISCLOSURE)
        self._global_controls(self,compact=True)
        applied_label=ttk.Label(self,textvariable=self.applied_summary,wraplength=1100);applied_label.pack(anchor='w')
        check=ttk.Checkbutton(self,text='I opt in to this bounded PAPER session',variable=self.opt_in)
        check.pack(anchor='w');self.session_widgets.append(check)
        controls_parent=self if settings_parent is None else settings_parent
        if settings_parent is not None:
            self._global_controls(settings_parent,compact=False)
            ttk.Label(settings_parent,textvariable=self.global_status,wraplength=900).pack(anchor='w',pady=4)
        first=ttk.Frame(controls_parent);first.pack(fill='x',pady=8)
        ttk.Label(first,text='Initial paper ETH allocation').pack(side='left',padx=(0,3))
        percent=ttk.Combobox(first,textvariable=self.values['budget_percent'],values=('5%','10%','15%','20%','25%','50%','Exact custom'),state='readonly',width=12)
        percent.pack(side='left');percent.bind('<<ComboboxSelected>>',lambda e:self.update_budget_default());self.session_widgets.append(percent)
        amount=ttk.Entry(first,textvariable=self.values['amount_eth'],width=16);amount.pack(side='left',padx=4)
        amount.bind('<KeyRelease>',lambda e:self.values['budget_percent'].set('Exact custom'));self.session_widgets.append(amount)
        ttk.Label(first,text='ETH · hypothetical working slice').pack(side='left')
        Hover(amount,'Defaults to 50% of the fresh working ETH proposal after carve-outs. The first eligible order uses this slice once; it is not halved again. '
            'No real assets move. Native minima/caps govern; a small order is blocked rather than rounded up. '
            'All fourteen views share this single initial ETH slice.')
        actions=ttk.Frame(self);actions.pack(fill='x',pady=3)
        for label,command in (('Start Auto Paper Trader',app._start_auto_paper),('Pause paper',app._pause_paper),
                ('STOP',app._stop),('Reconcile paper',app._reconcile_paper),('New paper session',app._new_paper_session),
                ('History…',self.history)):
            button=ttk.Button(actions,text=label,command=command);button.pack(side='left',padx=(0,4))
            Hover(button,'Paper session only. Start is explicit; saved opt-in does not resume after restart. '
                'Pause/STOP preserve inventory and reservations; neither confirms cancellation or sells a holding. '
                'Reconciliation leaves PAUSED. A new session retains the previous database and starts a separate baseline.')
        ttk.Button(controls_parent,text='Session protections / compatibility settings…',command=self.settings).pack(anchor='w',pady=5)
        info=ttk.Frame(self);info.pack(fill='x',pady=4)
        self.info_canvas=tk.Canvas(info,height=78,highlightthickness=0,background='#0b0f12')
        self.info_canvas.pack(side='left',fill='x',expand=True)
        info_scroll=ttk.Scrollbar(info,orient='vertical',command=self.info_canvas.yview);info_scroll.pack(side='right',fill='y')
        self.info_canvas.configure(yscrollcommand=info_scroll.set)
        info_body=ttk.Frame(self.info_canvas);info_window=self.info_canvas.create_window((0,0),window=info_body,anchor='nw')
        info_body.bind('<Configure>',lambda e:self.info_canvas.configure(scrollregion=self.info_canvas.bbox('all')))
        global_feedback=ttk.Label(info_body,textvariable=self.global_status,style='Muted.TLabel')
        self.active_order=tk.StringVar(value='No active paper order. No completed ETH profit established.')
        active_label=ttk.Label(info_body,textvariable=self.active_order,wraplength=1100);active_label.pack(anchor='w',pady=4)
        self.message_label=ttk.Label(info_body,textvariable=self.message,wraplength=950)
        scoreboard=ttk.Label(info_body,textvariable=self.score,wraplength=1120,style='Muted.TLabel');scoreboard.pack(anchor='w',pady=(0,5))
        self.message_label.pack(anchor='w',pady=(2,4));global_feedback.pack(anchor='w')
        Hover(scoreboard,DISCLOSURE+' Marked ETH is a midpoint reference before exit costs. '
            'After-cost recoverable ETH remains UNKNOWN without sized exits, matched times, fee units and residue valuation. '
            'Underwater time/drawdown use observed samples, not continuous risk coverage.')
        self.market_tabs=ttk.Notebook(self);self.market_tabs.pack(fill='both',expand=True)
        for pair in WATCH_PAIRS:
            page=ttk.Frame(self.market_tabs,padding=5);self.market_tabs.add(page,text=pair);self.pages[pair]=page
        self.market_tabs.bind('<<NotebookTabChanged>>',self._selected)
        def resize_info(event):
            self.info_canvas.itemconfigure(info_window,width=event.width)
            for label in (global_feedback,active_label,self.message_label,scoreboard):label.configure(wraplength=max(300,event.width-8))
        self.info_canvas.bind('<Configure>',resize_info)
        def info_wheel(event):
            steps=-1 if event.num==4 else 1 if event.num==5 else -int(event.delta/120)
            if steps:self.info_canvas.yview_scroll(steps,'units')
            return 'break'
        for widget in (info_body,global_feedback,active_label,self.message_label,scoreboard,self.info_canvas):
            for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):widget.bind(sequence,info_wheel,add='+')
        def resize(event):
            width=max(350,event.width-20)
            applied_label.configure(wraplength=width)
            self.info_canvas.configure(height=max(75,min(160,event.height-460)))
        self.bind('<Configure>',resize)
        self._ensure_market(WATCH_PAIRS[0])
        if app.paper.config is not None:self.from_config(app.paper.config)
        if app.paper.engine is not None:
            applied=settings_at(app.paper.engine.private_state())
            if applied is not None:
                self.global_applied_draft=applied
                for key,value in applied.frozen().items():
                    if key in self.global_values:self.global_values[key].set(str(value))
                self.global_status.set('Applied global settings v'+str(len(app.paper.engine.private_state()['auto']['global_history'])))
        self.refresh()

    def _global_controls(self,parent,*,compact):
        box=ttk.LabelFrame(parent,text='Auto Trader — Global Settings',padding=4 if compact else 8);box.pack(fill='x',pady=5)
        row=ttk.Frame(box);row.pack(fill='x')
        ttk.Label(row,text='Minimum completed-rotation net profit · USD draft').pack(side='left')
        target=ttk.Entry(row,textvariable=self.global_values['min_net_usd'],width=10);target.pack(side='left',padx=6)
        target.bind('<Return>',lambda e:self.apply_global_settings(profit_only=True))
        ttk.Button(row,text='Apply profit target',padding=(6,2) if compact else None,
            command=lambda:self.apply_global_settings(profit_only=True)).pack(side='left')
        presets=ttk.Frame(box);presets.pack(fill='x',pady=(2 if compact else 5,0))
        for value in ('0.01','0.05','0.10','0.25','0.50','1.00'):
            ttk.Button(presets,text='$'+value,width=7,padding=(6,2) if compact else None,
                command=lambda v=value:self._profit_preset(v)).pack(side='left',padx=(0,4))
        Hover(target,'At least one whole USD cent, after native entry/exit costs and the original ETH baseline. '
            'Missing approved USD, fee-unit, sized-exit or residual evidence means UNKNOWN and blocks new entries. '
            'Changing this target never increases size or forces an underwater sale. Existing orders keep their original version/price and are reviewed before any replacement.')
        if not compact:
            for key,label in (('source_pct','Subsequent available source coin per order · % (maximum 50)'),
                    ('review_s','Order review · seconds'),('reconsider_s','Reconsider unfilled orders · seconds')):
                line=ttk.Frame(box);line.pack(fill='x',pady=5)
                ttk.Label(line,text=label,width=63).pack(side='left')
                ttk.Entry(line,textvariable=self.global_values[key],width=12).pack(side='left')
            ttk.Label(box,text='Limit + Post Only · All 7 approved pairs / 14 directions · Basic: authenticated fees, no inferred rebate.\n'
                'One shared paper wallet. Native minima, reserved funds, exits and session protections remain binding.\n'
                'USD is a reference only. UNKNOWN blocks entry; conditional estimates are not completed profit.',wraplength=850).pack(anchor='w',pady=7)
            buttons=ttk.Frame(box);buttons.pack(fill='x')
            ttk.Button(buttons,text='Apply all Trading Settings',command=self.apply_global_settings).pack(side='left')
            ttk.Button(buttons,text='Copy settings for Codex',command=self.copy_global_settings).pack(side='left',padx=6)

    def _profit_preset(self,value):
        self.global_values['min_net_usd'].set(value);self.apply_global_settings(profit_only=True)

    def _global_draft(self):
        from coincat_v80_immediate import exact
        def integer(key):
            value=exact(self.global_values[key].get())
            if value!=value.to_integral_value():raise ValueError('INTEGER_GLOBAL_SETTING_REQUIRED')
            return int(value)
        current=None if self.app.paper.engine is None else settings_at(self.app.paper.engine.private_state())
        choice=self.values['budget_percent'].get()
        initial=current.initial_pct if current is not None else D(50) if choice=='Exact custom' else D(choice.rstrip('%'))
        return GlobalSettings(D(self.global_values['min_net_usd'].get()),D(self.global_values['source_pct'].get()),
            initial,integer('review_s'),integer('reconsider_s')).checked()

    def apply_global_settings(self,*,profit_only=False):
        try:
            from dataclasses import replace
            if profit_only:
                current=None if self.app.paper.engine is None else settings_at(self.app.paper.engine.private_state())
                baseline=current or self.global_applied_draft or GlobalSettings()
                settings=replace(baseline,min_net_usd=D(self.global_values['min_net_usd'].get())).checked()
            else:settings=self._global_draft()
            if self.app.paper.engine is None:
                self.global_applied_draft=settings
                self.global_status.set('Trading Settings applied to next paper session · no wallet or order created')
            else:
                version=self.app.paper.apply_global(settings,at=time.time())
                self.global_applied_draft=settings;self.app.paper_public=self.app.paper.public()
                self.global_status.set('Applied settings v'+str(version)+' · existing orders keep their price/version and receive a safe review')
            self.refresh()
        except (ValueError,ArithmeticError,OSError,sqlite3.Error):
            self.global_status.set('Settings not applied. Use whole USD cents ≥0.01, source ≤50%, valid timing and unchanged session funding. No order rewritten.')

    def copy_global_settings(self):
        try:settings=self._global_draft()
        except (ValueError,ArithmeticError):self.global_status.set('Correct the draft settings before copying.');return
        text=('CoinCat v1.02 proposed PAPER settings\nMinimum completed-rotation net profit: $'+format(settings.min_net_usd,'.2f')+
            ' USD-equivalent\nInitial working ETH allocation: '+str(settings.initial_pct)+'% (once, not halved again)'+
            '\nSubsequent available/unreserved source per order: up to '+str(settings.source_pct)+'%'+
            f'\nReview {settings.review_s}s; reconsider {settings.reconsider_s}s.\n'+
            'All 7 pairs / 14 directions. Limit + Post Only; no taker fallback. Basic; authenticated fees.\n'+
            'Validate fresh approved USD, native fees/rules/precision, sized exits, ETH baseline and residues. UNKNOWN blocks new entries.\n'+
            'Future intents use versioned applied settings; existing orders require safe review/cancel/reconciliation before replacement.\n'+
            'AI Lab is passive. Live execution remains blocked.')
        self.app.root.clipboard_clear();self.app.root.clipboard_append(text)
        self.global_status.set('Draft settings copied locally. Copying does not apply them or create an order.')

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
        policy={label:key for key,label in POLICY_LABELS.items()}.get(self.values['order_policy'].get())
        return AutoConfig(D(self.values['amount_eth'].get()),directions,self.opt_in.get(),
            self.values['kickoff'].get(),self.values['model'].get(),integer('seed'),integer('review_s'),
            integer('cooldown_s'),int(seconds),integer('max_orders'),D(self.values['fee_ceiling_pct'].get())/100,
            D(self.values['fee_stress_bps'].get()),self.values['membership'].get(),
            policy,integer('order_ttl_s') if policy==SHORT_POLICY else 120,
            integer('min_rest_s') if policy==SHORT_POLICY else 30,
            D(self.values['reprice_bps'].get()) if policy==SHORT_POLICY else D(10)).checked()

    def from_config(self,config):
        self.opt_in.set(config.opt_in);self.values['budget_percent'].set('Exact custom')
        data=dict(amount_eth=config.amount_eth,kickoff=config.kickoff,model=config.model,seed=config.seed,
            review_s=config.review_s,cooldown_s=config.cooldown_s,duration_hours=D(config.duration_s)/3600,
            max_orders=config.max_orders,fee_ceiling_pct=config.fee_ceiling*100,fee_stress_bps=config.fee_stress_bps,
            membership=config.membership,order_policy=POLICY_LABELS[config.policy],order_ttl_s=config.order_ttl_s,
            min_rest_s=config.min_rest_s,reprice_bps=config.reprice_bps)
        for key,value in data.items():self.values[key].set(str(value))
        for key,items in config.directions.items():
            for name,value in items.items():self.direction_vars[key][name].set(value if name=='enabled' else str(value))

    def settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():self.settings_window.lift();return
        window=tk.Toplevel(self);self.settings_window=window;window.title('Paper session settings · Frozen at Start')
        window.geometry(f'790x{min(780,window.winfo_screenheight()-70)}')
        outer=ttk.Frame(window);outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,background='#0b0f12',highlightthickness=0)
        scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview);scroll.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
        body=ttk.Frame(canvas,padding=12);item=canvas.create_window((0,0),window=body,anchor='nw')
        body.columnconfigure(1,weight=1)
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        ttk.Label(body,text='BBO stress scenarios; no observed queue/depth or calibrated fill probability.',wraplength=600).grid(row=0,column=0,columnspan=2,sticky='w',pady=5)
        for row,(key,label,choices) in enumerate((
            ('order_policy','Order policy',tuple(POLICY_LABELS.values())),
            ('order_ttl_s','Short-lived mode · order lifetime seconds',None),
            ('min_rest_s','Short-lived mode · minimum rest seconds',None),
            ('reprice_bps','Short-lived mode · reprice threshold bps',None),
            ('kickoff','Chosen kickoff · no fallback',KICKOFFS),('model','Provider model',MODELS),('seed','Frozen scenario seed',None),
            ('review_s','Resting-order review · seconds',None),('cooldown_s','New-order cooldown · seconds',None),
            ('duration_hours','Original session horizon · hours',None),('max_orders','Maximum session orders',None),
            ('fee_ceiling_pct','Maker fee ceiling · percent',None),('fee_stress_bps','Added fee stress · bps',None),
            ('membership','Membership label · never overrides fees',('None','Basic','Preferred','Premium'))),1):
            ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            widget=ttk.Entry(body,textvariable=self.values[key],width=32) if choices is None else ttk.Combobox(body,
                textvariable=self.values[key],values=choices,state='readonly',width=31)
            widget.grid(row=row,column=1,sticky='ew',pady=4);self.session_widgets.append(widget)
            if key in ('order_ttl_s','min_rest_s','reprice_bps'):self.short_widgets.append(widget)
            if key=='order_policy':widget.bind('<<ComboboxSelected>>',lambda e:self._freeze())
        text=('One open order, 16 session orders, 24-hour horizon, 30-second reviews/cooldown are operational defaults. '
            'The first native cap for a new asset is frozen from its canonical acquisition receipt; a cap never credits funds. '
            'Basic has no assumed Advanced rebate. No membership infers zero fees, rebates or fee currencies. Subscription costs are excluded from execution fees and reported separately as unmodeled. '
            'The simulated venue explicitly charges supported quote-currency fees from fresh account rates plus stress; '
            'actual exchange fee units remain unverified. Missing/stale rates block admission. '
            'Short-lived mode uses a 120-second order lifetime, fresh decisions after confirmed cancellation, and '
            'retains the net ETH target. An unavailable target means HOLD; inventory and losses do not disappear. '
            'Every replacement uses an order slot. Sixteen two-minute attempts total 32 minutes of resting time '
            'plus cancellation/review delays; price-move replacements can use the budget sooner. '
            'The 24-hour session horizon does not increase that budget. '+DISCLOSURE)
        ttk.Label(body,text=text,wraplength=700).grid(row=row+1,column=0,columnspan=2,sticky='w',pady=10)
        ttk.Button(window,text='Close',command=window.destroy).pack(anchor='e',padx=12,pady=8)
        def wheel(event):
            steps=-1 if event.num==4 else 1 if event.num==5 else -int(event.delta/120)
            if steps:canvas.yview_scroll(steps,'units')
            return 'break'
        def bind_wheel(widget):
            for event in ('<MouseWheel>','<Button-4>','<Button-5>'):widget.bind(event,wheel,add='+')
            for child in widget.winfo_children():bind_wheel(child)
        bind_wheel(body)
        self._freeze()

    def _freeze(self):
        frozen=self.app.paper.engine is not None
        for widget in self.session_widgets+self.market_widgets:
            if not widget.winfo_exists():continue
            if frozen:widget.state(['disabled'])
            else:
                widget.state(['!disabled'])
                if isinstance(widget,ttk.Combobox):widget.state(['readonly'])
        if not frozen and self.values['order_policy'].get()!=POLICY_LABELS[SHORT_POLICY]:
            for widget in self.short_widgets:
                if widget.winfo_exists():widget.state(['disabled'])

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
                fixed_horizon=context.get('horizon'),last_reason=context.get('last_reason'),pending=context.get('pending'),
                global_settings_versions=context.get('global_history',[]),completed_eth_returns=context.get('completed_rotations',{}))))
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
            tree=ttk.Treeview(book,columns=('price','size'),show='headings' if label=='Ask' else '',height=1)
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
            controls_parent=body
            if self.legacy_controls is not None:
                controls_parent=ttk.Frame(self.legacy_controls,padding=8)
                self.legacy_controls.add(controls_parent,text=view['source']+' → '+view['target'])
                ttk.Label(controls_parent,text='Legacy per-direction configuration. The applied global USD floor and source cap govern new global intents.',
                    wraplength=750).pack(anchor='w',pady=5)
            controls=ttk.Frame(controls_parent);controls.pack(fill='x',pady=4)
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
            applied=self.global_applied_draft
            self.message.set('OFF · '+(manager.last_problem or 'Explicit paper opt-in and a fresh working ETH proposal are required.'))
            self.score.set('One shared paper wallet is not funded. No simulated orders. Actual profit NOT ESTABLISHED.')
            self.active_order.set('No active paper order. UNKNOWN blocks entries; no completed ETH profit established.')
        else:
            context=state['auto'];performance=context['performance'];public=manager.public()
            settings=settings_at(state)
            applied=settings
            expiry=datetime.fromtimestamp(state['limits']['expires_at'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            label='Global USD rotation v'+str(len(context['global_history'])) if settings else POLICY_LABELS[manager.config.policy]
            self.message.set(public['state']+' · '+label+' · '+context['last_reason']+' · '+manager.config.model+' · seed '+str(manager.config.seed)+
                ' · original expiry '+expiry+' · simulated venue / NO DEMONSTRATED EDGE')
            current=next((o for o in state['orders'].values() if o['state'] not in ('FILLED','CANCELED','REJECTED')),None)
            reports=context.get('completed_rotations',{})
            last=next(reversed(reports.values()),None) if reports else None
            result='No completed ETH-return slice'
            if last is not None:
                result=('Last completed paper ETH-return slice: '+last['state']+' · net USD '+(
                    'UNKNOWN' if last['net_usd'] is None else format(last['net_usd'],'.8g'))+' vs $'+str(last['minimum_usd'])+
                    ' minimum (order settings v'+str(last['policy_version'])+')')
            if current is None:self.active_order.set('No active paper order · '+result)
            else:
                native=self.books.get(current['pair'],{}).get('book')
                market='UNOBSERVED' if native is None else str(native[0])+' / '+str(native[1])
                self.active_order.set(current['pair']+' '+current['side']+' · '+current['state']+
                    ' · bid / ask '+market+' · limit '+str(current['limit_price'])+
                    ' · age '+str(round(max(0,now-current['created_at'])))+'s · pinned settings v'+
                    str(current.get('global_policy_version',0))+'\nReview: '+context['last_reason']+' · '+result)
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
                f" · Orders {public['orders']}/{state['limits']['max_orders']} · Paper fills {public['fills']} / non-fills {public['non_fills']} · Actual profit NOT ESTABLISHED")
        self.applied_summary.set('No global settings applied. Fields are drafts until Apply.' if applied is None else
            'Applied $'+format(applied.min_net_usd,'.2f')+' net floor · working ETH '+str(applied.initial_pct)+
            '% once / source ≤'+str(applied.source_pct)+'% · review '+str(applied.review_s)+
            's / reconsider '+str(applied.reconsider_s)+'s · Post Only · UNKNOWN blocks entries')
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
                        if manager.config.policy==SHORT_POLICY:
                            if row.get('reason')=='HOLD_MARKET_BELOW_NET_ETH_TARGET':
                                heading+='\nHOLD · Current quote cannot meet net ETH target'
                            elif order['state'] not in ('FILLED','CANCELED','REJECTED'):
                                heading+=f" · {round(max(0,order['expires_at']-now))}s left"
                        text+=f"\nPAPER {order['state']} · {order['side']} limit {order['limit_price']} · cumulative {order['filled_base']} / {order['base_size']} · reserve {order['reserved']} {order['source']}"
                        interval=settings.review_s if settings else manager.config.review_s
                        text+=f"\nOrder age {round(max(0,now-order['created_at']))} s · modeled fee currency {pair.split('-')[1]} · next policy review in "+str(round(max(0,interval-(now-(state['auto']['last_review'] or now)))))+' s'
                        text+=f" · order lifetime remaining {round(max(0,order['expires_at']-now))} s (expiry requests cancel)"
                        text+=' · venue '+state['auto']['venue'].get(order['reference'],{}).get('data_state','AWAITING_RECEIPT')
                if row.get('plan'):
                    text+=f"\nCandidate {row.get('limit_price')} · native base size {row['plan']['gross_base_quantity']} · source cap {row['source_budget']}"
                    required=row.get('required_eth')
                    target='conditional only' if required is None else 'approx '+format(required,'.10g')
                    text+='\nFee ceiling '+format(row['fee_fraction']*100,'.10g')+f"% · target ETH {target} · candidate is not reserved funding"
                proof=row.get('qualification')
                if proof:
                    text+=('\nCompleted-rotation estimate '+proof['state']+' · conditional net USD '+(
                        'UNKNOWN' if proof['net_usd'] is None else format(proof['net_usd'],'.10g'))+
                        ' · minimum $'+str(proof['minimum_usd'])+' · not completed profit')
                    target=row.get('target_exit')
                    if target:text+='\nModeled return target '+target['pair']+' '+target['side']+' '+str(target['limit_price'])+' (not qualification)'
                fee_at=self.tier.get('captured_at')
                fee_age='UNOBSERVED' if fee_at is None else str(round(now-fee_at))+' s'
                maker=self.tier.get('maker');rate='UNKNOWN' if not isinstance(maker,D) else format(maker*100,'.10g')+'%'
                text+='\nAccount maker '+rate+' · fee capture age '+fee_age+\
                    ' · modeled quote-currency debit; exchange fee units unverified'
                self.direction_text[view['id']].set(text)
                self.direction_pages[view['id']].heading_text.set(heading)
        self._freeze()
