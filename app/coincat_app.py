"""CoinCat v95: a small ETH Growth research shell. Live orders stay blocked."""
from datetime import datetime,timezone
from pathlib import Path
from queue import Queue,Empty
import sys
import threading
import math
import time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox

from coinbase_account import parse_key_json,save_encrypted,load_encrypted
from coincat_live import LiveLedger,client_from_credentials
from coincat_live_forward_store import ForwardStore,Retention
from coincat_state_v50 import data_root
from coincat_v502_fee_learning import FeeLearning
from coincat_scanner import Scanner
from coincat_version import DISPLAY
from coincat_simple_diagnostics import make_report
from coincat_allocation_editor import WorkingAllocationEditor
from coincat_mixer import ResearchMixer
from coincat_eth_maker import MakerConfig,available_companions
from coincat_hover import Hover,help_tree
from coincat_chart import QuoteChart
from coincat_continuity import eth_funding,freshness,age
from coincat_recovery import Recovery,failure


class CoinCatApp:
    def __init__(self,root):
        self.root=root;root.title(DISPLAY+' | ETH Growth — Research Only | LIVE blocked')
        root.geometry('1120x800');root.minsize(1000,740)
        self.data=data_root();self.ledger=LiveLedger(self.data/'CoinCat_Live_Orders.sqlite3')
        self.fees=FeeLearning(self.data/'research_data'/'CoinCat_Fee_Evidence_v502.sqlite3')
        self.market=ForwardStore(self.data/'research_data'/'CoinCat_Forward_Market.sqlite3',Retention())
        self.scanner=None;self.credentials=None;self.last_result=None;self.applied_config=None
        self.applied_eth_key=None;self.recovery=Recovery();self.retry_kind=None
        self.connected=False;self.running=False;self.closed=False;self.busy=False;self.generation=0
        self.cancel=threading.Event();self.jobs=Queue();self._after={};self.last_error=None
        self.last_note_at=0;self._ready=False;self.working_allocation=None
        self.status=tk.StringVar(value='Connect, choose companions, then apply a research plan.')
        self.observation_text=tk.StringVar(value='STOPPED · No completed research observation')
        self.funding_text=tk.StringVar(value='Working proposal: unset · Protected ETH: unverified')
        self.evidence_text=tk.StringVar(value='Fees: unobserved · Fills: unverified · Actual profit: not established')
        self.detail_text=tk.StringVar(value='Select a market for details. Hover any control or result for help.')
        self.companions=[tk.StringVar() for _ in range(3)]
        self._ui();self._ready=True
        for value in self.companions:value.trace_add('write',lambda *args:self._invalidate())
        self.root.protocol('WM_DELETE_WINDOW',self._close);self._schedule('poll',100,self._poll)
        self._schedule('history',200,self.chart.refresh)
        self._schedule('freshness',1000,self._freshness_tick)

    def _ui(self):
        shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        header=ttk.Frame(shell);header.pack(fill='x')
        self.logo=tk.PhotoImage(file=str(Path(__file__).with_name('coincat_logo_banner_520.png'))).subsample(2)
        title=ttk.Label(header,image=self.logo);title.pack(side='left',padx=(0,12))
        Hover(title,DISPLAY+' development preview. ETH Growth research only. Existing CoinCat artwork; no order execution.')
        ttk.Label(header,text=DISPLAY+' · ETH Growth',font=('Segoe UI',17,'bold')).pack(side='left')
        badge=ttk.Label(header,text='RESEARCH ONLY · LIVE BLOCKED',foreground='#a34d00');badge.pack(side='right')
        Hover(badge,'No orders, previews, cancellations or transfers. LiveBroker.submit raises LiveBlocked before doing any work. '
            'This preview does not establish Windows acceptance, settlement, fills or profitability.')
        if sys.platform=='win32':self.root.iconbitmap(str(Path(__file__).with_name('CoinCat50.ico')))
        actions=ttk.Frame(shell);actions.pack(fill='x',pady=(8,5))
        tips=(('Import key JSON',self._import_key,'Select a Coinbase key on this PC. Never paste keys into chat. Existing Windows DPAPI storage is unchanged.'),
            ('Connect / refresh',self._connect,'Read account AVAILABLE, authenticated spot products and account maker/taker fees. No financial enrollment or settings are changed.'),
            ('Start research',self._start,'Start observing only the manually approved direct ETH markets. Apply a research plan first. No USD/USDC bridge or fallback.'),
            ('STOP',self._stop,'Stop scheduling, cancel pending evaluation and reject queued results from earlier generations. Retain displayed findings. No real order exists to cancel.'),
            ('Export diagnostics',self._export,'Export eight quantity-free sections. No native balances, receipts, funding amounts, keys, account IDs or private paths. No network requests from export.'))
        for text,command,tip in tips:
            button=ttk.Button(actions,text=text,command=command);button.pack(side='left',padx=(0,7));Hover(button,tip)
        status=ttk.Label(shell,textvariable=self.status,wraplength=1060);status.pack(anchor='w',pady=(0,5))
        Hover(status,lambda:self.status.get()+' All proposals are RAM-only. STOP before a new connection or configuration change.')
        badge=ttk.Label(shell,textvariable=self.observation_text,wraplength=1060,foreground='#a34d00')
        badge.pack(anchor='w',pady=(0,4))
        Hover(badge,'Current connection/retry state and age of last-good observations. Historical quotes and fee tiers are never rescored as current. STOP cancels retry timers; no order execution is enabled.')
        self.tabs=ttk.Notebook(shell);self.tabs.pack(fill='both',expand=True)
        growth=ttk.Frame(self.tabs,padding=8);allocation=ttk.Frame(self.tabs)
        mixer_tab=ttk.Frame(self.tabs,padding=8)
        lab=ttk.Frame(self.tabs,padding=8)
        self.tabs.add(growth,text='ETH Growth');self.tabs.add(mixer_tab,text='Manual mixer')
        self.tabs.add(allocation,text='Allocation');self.tabs.add(lab,text='Research notes')
        self.mixer=ResearchMixer(mixer_tab,self._invalidate);self.mixer.pack(fill='x')
        self.chart=QuoteChart(growth,self.market.path);self.chart.pack(fill='both',expand=True)
        research=ttk.LabelFrame(growth,text='Coins & research',padding=5);research.pack(fill='x',pady=(7,0))
        watch=ttk.Frame(research);watch.pack(fill='x',pady=3)
        label=ttk.Label(watch,text='Companions');label.pack(side='left',padx=(0,6))
        Hover(label,'ETH plus up to three manually approved companions. Choices come from the authenticated eligible direct-ETH catalog. '
            'BTC, SOL and ADA are examples, never preselected. If no pair qualifies, stop with NO QUALIFIED EVIDENCE; no automatic replacements.')
        self.companion_boxes=[]
        for variable in self.companions:
            box=ttk.Combobox(watch,textvariable=variable,values=('',),state='readonly',width=12)
            box.pack(side='left',padx=(0,6));self.companion_boxes.append(box)
            Hover(box,'Manually choose an eligible companion or leave empty. Changing selection invalidates the applied plan and pending analysis. '
                'At most three companions, direct spot ETH markets only. Region/account restrictions and missing verified rules exclude a product.')
        apply=ttk.Button(watch,text='Apply research plan',command=self._apply_plan);apply.pack(side='left',padx=5)
        Hover(apply,'Acknowledge the exact ETH modeling amount and selected companions for this RAM-only study. '
            'This is not settlement reconciliation, trading authorization or an allocation change. Unapplied allocation edits must be resolved first.')
        self.funding_label=ttk.Label(research,textvariable=self.funding_text,wraplength=1040)
        self.funding_label.pack(anchor='w')
        Hover(self.funding_label,lambda:self.funding_text.get()+'. UNRECONCILED / RESEARCH ONLY. '
            'The model amount must fit the ETH working proposal after manual/protected exclusions. Other assets never supply funding. '
            'Each market is an independent scenario against HOLD of the same initial ETH, not a combined deployment. No earned ETH is inferred.')
        evidence=ttk.Label(research,textvariable=self.evidence_text,wraplength=1040);evidence.pack(anchor='w',pady=(2,5))
        Hover(evidence,lambda:self._fee_details())
        columns=('Market','ETH / coin','Spread / age','Taker ΔETH','Maker ΔETH / move','Fill evidence')
        table=ttk.Frame(research);table.pack(fill='x')
        self.growth_tree=ttk.Treeview(table,columns=columns,show='headings',height=3,selectmode='browse')
        widths=(115,130,125,145,210,200)
        for name,width in zip(columns,widths):
            self.growth_tree.heading(name,text=name);self.growth_tree.column(name,width=width,minwidth=80,stretch=True)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.growth_tree.yview)
        self.growth_tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.growth_tree.pack(fill='both',expand=True)
        self.growth_tree.bind('<<TreeviewSelect>>',lambda event:self._select_row())
        Hover(self.growth_tree,lambda:self._row_help())
        def row_motion(event):
            row=self.growth_tree.identify_row(event.y)
            if row and row!=getattr(self,'_hover_row',None):
                self._hover_row=row;self.growth_tree.hover_help.schedule(event)
        self.growth_tree.bind('<Motion>',row_motion,add='+')
        detail=ttk.Label(research,textvariable=self.detail_text,wraplength=1030);detail.pack(anchor='w',pady=(4,0))
        Hover(detail,lambda:self._row_help())
        self.allocation_editor=WorkingAllocationEditor(allocation,self._allocation_changed)
        self.allocation_editor.pack(fill='both',expand=True)
        self.lab_text=tk.Text(lab,wrap='word',font=('Segoe UI',10),state='disabled',height=7)
        self.lab_text.pack(fill='both',expand=True)
        Hover(self.lab_text,'Passive notes only. No AI changes settings, sets prices, alters funding, arms or places orders. '
            'Notes describe deterministic research observations and uncertainty. They do not gate economics.')
        self._note('Choose a small direct-ETH watch set. Quotes cannot prove maker fills. No ETH earnings established.')
        help_tree(allocation,'Read-only allocation worksheet. Exact native-unit proposals remain in RAM. '
            'Apply each edited row explicitly; manual/protected/excluded funds cannot enter the working model. '
            'An owner checkbox cannot verify settlement, external cashflows, outstanding orders or tax basis. No trading is enabled.')
        help_tree(shell,DISPLAY+' ETH Growth research. ETH is the funding and success unit; '
            'choose up to three direct-ETH companions manually. Compare the same initial ETH versus HOLD. '
            'Maker figures are conditional scenarios with uncertain fills; no earnings or live orders. '
            'Hover individual controls and results for exact costs, timestamps, native dust and risk.')

    def _fee_details(self):
        tier=(self.last_result or {}).get('fee_evidence',{})
        return ('Frozen last-good SPOT transaction-summary account tier (not a live refresh): '+str(tier.get('state','UNOBSERVED'))+
            '; maker='+str(tier.get('maker','UNKNOWN'))+'; taker='+str(tier.get('taker','UNKNOWN'))+
            '; captured UTC='+self._stamp(tier.get('captured_at'))+'. Rates are fractions, not percentages. '
            'Account tier is an estimate, not proof of pair exceptions or fee debit currency. Calculations explicitly assume quote-currency fee debit once. '
            'Maker uses limit prices without taker slippage. Taker uses bid/ask plus the selected per-leg slippage stress. '
            'No sized depth, queue position, volume or exchange quote-event time is verified. Missing fee evidence blocks modeling; no fixed-fee fallback.')

    @staticmethod
    def _stamp(value):
        return 'UNKNOWN' if value is None else datetime.fromtimestamp(value,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    def _row_help(self):
        rows=(self.last_result or {}).get('rows',())
        pair=getattr(self,'_hover_row',None)
        selected=self.growth_tree.selection()
        row=next((r for r in rows if r['market']['pair']==pair),None)
        if row is None:row=next((r for r in rows if selected and r['market']['pair']==selected[0]),None)
        if row is None:
            return ('Immediate taker ΔETH is a bid/ask round-trip benchmark against HOLD, with fees once and explicit slippage stress. '
                'Maker ΔETH / move is a conditional full-fill ETH subtotal difference versus HOLD and the required ETH-per-coin relative improvement, not a prediction or profit. '
                'Fill evidence stays uncertain; missing pricing is not a loss. Select or hover a row for native residuals and matched timestamps.')
        hypothesis=row.get('hypothesis') or {};scenario=hypothesis.get('scenario') or {};benchmark=row.get('benchmark') or {}
        return (row['market']['pair']+' | '+row['state']+' | '+', '.join(row['blockers'])+
            ' | Original expiry '+self._stamp(hypothesis.get('expiry_at'))+
            '\nObservation state '+row.get('observation_state','UNOBSERVED')+'; frozen setup clock is not extended through gaps.'+
            '\nEntry '+row['market']['entry_side']+' limit: '+str(hypothesis.get('entry_price','UNKNOWN'))+
            '; later exit '+row['market']['exit_side']+' target: '+str(hypothesis.get('exit_price','UNKNOWN'))+
            '. Prices are quote units per base unit of the actual product.'+
            '\nEntry decision '+self._stamp(hypothesis.get('entry_at'))+
            '; hypothetical exit decision '+self._stamp(hypothesis.get('exit_at'))+
            '; latest quote '+self._stamp((row.get('book') or (None,None,None))[2])+
            '. Entry and future exit are intentionally separate times.'+
            '\nWaiting '+str(round(max(0,age(hypothesis.get('entry_at'),time.time()) or 0)))+' s; observed adverse relative move '+str(hypothesis.get('adverse_move_pct','UNKNOWN'))+
            '%; ETH exposed in full-entry scenario '+str(hypothesis.get('worst_case_eth_exposure','UNKNOWN'))+
            '. Entire coin exposure can be lost; a real holding may outlast the horizon.'+
            '\nHOLD ETH '+str(scenario.get('initial_eth','UNKNOWN'))+'; retained ETH '+str(scenario.get('retained_eth','UNKNOWN'))+
            '; fully filled scenario ETH subtotal '+str(scenario.get('final_eth_subtotal','UNKNOWN'))+
            '; non-ETH dust '+str(scenario.get('native_dust','UNKNOWN'))+
            '. Dust is not ETH; an incomplete subtotal is not a full realized return.'+
            '\nTaker subtotal ΔETH '+str(benchmark.get('net_eth_subtotal','UNKNOWN'))+'; taker dust '+str(benchmark.get('native_dust','UNKNOWN'))+
            '. No-fill scenario retains the original ETH. Partial/unknown fills have no credited return; remaining coin exposure is unknown.'+
            '\nFill classification '+row['fill_state']+'; entry touch '+self._stamp(hypothesis.get('entry_touched_at'))+
            '; target touch '+self._stamp(hypothesis.get('target_touched_at'))+
            '. Touch/crossing cannot establish queue priority or fills. Proposed exits are never submitted. '+self._fee_details())

    def _select_row(self):
        selection=self.growth_tree.selection()
        if not selection:return
        row=next((r for r in (self.last_result or {}).get('rows',()) if r['market']['pair']==selection[0]),None)
        if row:
            h=row.get('hypothesis') or {}
            waited=age(h.get('entry_at'),time.time())
            phase=('Expired' if h and time.time()>=h['expiry_at'] else 'Paused' if
                row.get('observation_state')=='SETUP_ACTIVE_UNPRICED' or self.recovery.state in ('RETRYING','PAUSED_NEEDS_ATTENTION') else
                'Historical' if age(row.get('at'),time.time()) is not None and time.time()-row['at']>30 else 'Observed')
            self.detail_text.set('Waiting '+('unknown' if waited is None else str(round(max(0,waited)))+' s')+' · '+phase+' · '+
                ('Native dust retained' if h.get('scenario',{}).get('native_dust') else 'Dust: none in scenario' if h else 'Unpriced')+
                ' · No profit credited'+(' · '+', '.join(row['blockers']) if row['blockers'] else ''))

    def _invalidate(self):
        if not self._ready:return
        self._stop();self.applied_config=None;self.applied_eth_key=None;self.last_result=None
        for row in self.growth_tree.get_children():self.growth_tree.delete(row)
        self.evidence_text.set('Plan changed · Previous analysis invalidated')
        self.detail_text.set('Apply the exact research plan before restarting.')
        self.status.set('Plan changed. Apply research plan to continue.')

    def _funding(self):
        editor=self.allocation_editor
        return eth_funding(balances=editor.balances,balances_at=editor.balances_at,
            now=editor.clock(),draft=editor.parameters()['allocation_draft'],excluded=editor.excluded)

    def _allocation_changed(self):
        self.working_allocation=self.allocation_editor.assessment()
        relevant_edit=self.allocation_editor.selected_asset=='ETH' and self.allocation_editor.dirty_fields
        changed=self.applied_eth_key is not None and self._funding()['key']!=self.applied_eth_key
        self._sync_eth_default()
        if relevant_edit or changed:self._invalidate()

    def _sync_eth_default(self):
        if self.allocation_editor.dirty_fields and self.allocation_editor.selected_asset=='ETH':return
        funding=self._funding()
        amount=funding['row'].get('working',0) if funding['assessment']['state']!='INVALID_DRAFT' else 0
        self.mixer.controls['amount_eth'].update_default(amount)

    def _apply_plan(self):
        try:
            self.mixer.commit_entries()
            if self.allocation_editor.dirty_fields:raise ValueError('Apply or correct allocation edits first.')
            config=MakerConfig(companions=tuple(v.get() for v in self.companions if v.get()),**self.mixer.values()).validate()
            if config.amount_eth<=0:raise ValueError('Enter an explicit ETH modeling amount.')
            if not config.companions:raise ValueError('Choose at least one eligible direct-ETH companion.')
            if self.scanner is None or not self.connected:raise ValueError('Connect and verify available markets first.')
            funding=self._funding();row=funding['row']
            if not funding['valid'] or row.get('working',0)<config.amount_eth:
                raise ValueError('ETH amount exceeds the working draft after carve-outs.')
        except (ValueError,ArithmeticError) as exc:
            self.status.set('Plan not applied: '+str(exc));return
        self._stop();self.last_result=None;self.applied_config=config;self.applied_eth_key=funding['key']
        for item in self.growth_tree.get_children():self.growth_tree.delete(item)
        self.evidence_text.set('Plan applied · Awaiting a fresh scan')
        self.detail_text.set('Research scenarios only · No orders or credited profit')
        self.funding_text.set(f'Model {config.amount_eth} ETH per scenario · Protected {row.get("protected",0)} ETH · UNRECONCILED / RESEARCH ONLY')
        self.status.set('Research plan applied in RAM. Start research when ready.')

    def _schedule(self,key,delay,callback):
        if self.closed:return
        old=self._after.pop(key,None)
        if old is not None:
            try:self.root.after_cancel(old)
            except tk.TclError:pass
        def run():
            self._after.pop(key,None);callback()
        self._after[key]=self.root.after(delay,run)

    def _submit(self,kind,task):
        if self.closed or self.busy:return False
        self.busy=True;generation=self.generation
        def work():
            if self.closed or generation!=self.generation:
                self.jobs.put((kind,generation,{'state':'CANCELLED'},None));return
            try:self.jobs.put((kind,generation,task(),None))
            except Exception as exc:self.jobs.put((kind,generation,None,failure(exc)))
        threading.Thread(target=work,daemon=True).start();return True

    def _import_key(self):
        if self.busy:self.status.set('Wait for the read-only request to finish.');return
        path=filedialog.askopenfilename(title='Choose Coinbase CDP JSON',filetypes=[('JSON','*.json')])
        if not path:return
        self._invalidate()
        try:
            credentials=parse_key_json(Path(path).read_text(encoding='utf-8'));save_encrypted(credentials)
            self.credentials=credentials;self.scanner=None;self.connected=False
            self.status.set('Key saved locally with Windows DPAPI. Connect to refresh.')
        except Exception as exc:messagebox.showerror('Key import',f'Import failed ({type(exc).__name__}). Key contents are never exported.')

    def _connect(self):
        if self.busy:self.status.set('Wait for the read-only request to finish.');return
        if self.credentials is None and self.scanner is None:
            try:self.credentials=load_encrypted()
            except Exception:self.credentials=None
            if not self.credentials:self.status.set('Import a key JSON locally first.');return
        self._stop();self.status.set('Reading account, products and fee tier…')
        self._connect_job()

    def _connect_job(self):
        self.cancel=threading.Event();cancel=self.cancel
        def task():
            if cancel.is_set():return {'state':'CANCELLED'}
            if self.scanner is None:self.scanner=Scanner(self.ledger,client_from_credentials(self.credentials),self.fees,self.market)
            return self.scanner.refresh(cancel=cancel,force_catalog=True)
        self._submit('connect',task)

    def _start(self):
        if self.busy:self.status.set('A read-only request is finishing. Retry Start when it completes.');return
        if self.running:return
        if not self.connected or self.scanner is None:self.status.set('Connect first.');return
        if self.applied_config is None:self.status.set('Apply a research plan first.');return
        self.running=True;self.cancel=threading.Event();self.recovery.start()
        self.status.set('RUNNING · Observing direct ETH markets · No orders');self._scan()

    def _stop(self):
        self.running=False;self.cancel.set();self.generation+=1;self.recovery.stop()
        if hasattr(self,'chart'):self.chart.cancel_pending()
        for key in ('scan','retry'):
            task=self._after.pop(key,None)
            if task is not None:
                try:self.root.after_cancel(task)
                except tk.TclError:pass
        self.status.set('STOPPED · Findings retained · No orders')

    def _scan(self,*,force_refresh=False):
        if self.closed or not self.running:return
        if self.busy:self._schedule('scan',250,self._scan);return
        config=self.applied_config;cancel=self.cancel
        draft=self.allocation_editor.parameters()['allocation_draft'];funding_key=self.applied_eth_key
        self._submit('scan',lambda:self.scanner.scan_growth(config,cancel=cancel,allocation_draft=draft,
                     applied_eth_key=funding_key,force_refresh=force_refresh))

    def _retry(self):
        if self.closed or self.recovery.state!='RETRYING':return
        if self.retry_kind=='scan' and (not self.running or self.applied_config is None):return
        if self.busy:self._schedule('retry',250,self._retry);return
        if not self.recovery.begin_retry():self._schedule_retry();return
        self.status.set(f'RETRYING · read-only attempt {self.recovery.attempt}/5')
        if self.retry_kind=='connect':self._connect_job()
        else:self._scan(force_refresh=True)

    def _schedule_retry(self):
        remaining=self.recovery.diagnostics()['retry_in_s']
        if remaining is not None:self._schedule('retry',max(1,math.ceil(remaining*1000)),self._retry)

    def _handle_failure(self,kind,detail):
        if not isinstance(detail,dict):detail=failure(RuntimeError())
        self.last_error=detail['error_class'];self.connected=False;self.retry_kind=kind
        if self.scanner is not None:self.scanner.pause_observation(detail['category'])
        state=self.recovery.failed(detail,operation=kind)
        for key in ('scan','retry'):
            timer=self._after.pop(key,None)
            if timer is not None:
                try:self.root.after_cancel(timer)
                except tk.TclError:pass
        if state=='RETRYING':
            self.status.set(f"RETRYING · {detail['stage']} / {detail['category']} · Last-good results retained")
            self._schedule_retry()
        else:
            self.running=False
            self.status.set(f"PAUSED_NEEDS_ATTENTION · {detail['stage']} / {detail['category']} · Refresh manually")
        self._update_freshness()

    def _poll(self):
        if self.closed:return
        try:
            while True:
                kind,generation,payload,error=self.jobs.get_nowait();self.busy=False
                if generation!=self.generation:continue
                if error:self._handle_failure(kind,error);continue
                if payload.get('state')=='CANCELLED':continue
                self.last_error=None
                if kind=='connect':
                    self.connected=True;self.recovery.authenticated();self._render_wallet()
                    excluded=tuple(r['asset'] for r in self.ledger.assets() if not r.get('enabled',1))
                    available=available_companions(self.scanner.catalog,self.scanner.rules,excluded)
                    for box in self.companion_boxes:box.configure(values=('',*available))
                    self.status.set(f'Connected · {len(available)} eligible direct-ETH companions'+
                        (' · Choose manually' if available else ' · NO QUALIFIED EVIDENCE; no fallback'))
                    self.chart.refresh()
                elif kind=='scan':
                    if payload.get('state')=='PAUSED_NEEDS_ATTENTION':
                        previous_result=self.last_result
                        self.running=False;self.applied_config=None;self.applied_eth_key=None
                        self._render_wallet();self.last_result=previous_result
                        self.recovery.state='PAUSED_NEEDS_ATTENTION'
                        self.status.set('PAUSED_NEEDS_ATTENTION · ETH funding changed · Apply the exact research plan again')
                        self._update_freshness();continue
                    self.recovery.successful(payload['at']);self.connected=True
                    timer=self._after.pop('retry',None)
                    if timer is not None:
                        try:self.root.after_cancel(timer)
                        except tk.TclError:pass
                    self.last_result=payload;self._render(payload)
                    if time.time()-self.last_note_at>=180:
                        self._note(payload['lab_note']);self.last_note_at=time.time()
                    if self.running:self._schedule('scan',int(self.applied_config.scan_interval_s*1000),self._scan)
                self._update_freshness()
        except Empty:pass
        self._schedule('poll',100,self._poll)

    def _freshness_tick(self):
        if self.closed:return
        self._update_freshness();self._schedule('freshness',1000,self._freshness_tick)

    def _update_freshness(self):
        now=time.time();view=freshness(self.last_result or {},now,fee_ttl=self.fees.ttl)
        account_age=age(None if self.scanner is None else self.scanner.account_at,now)
        self.connected=bool(account_age is not None and 0<=account_age<=120 and self.last_error is None and
                            self.recovery.state!='RETRYING')
        scan_age=view['last_good_scan_age_s']
        age_text='none' if scan_age is None else str(round(max(0,scan_age)))+'s ago'
        retry=self.recovery.diagnostics()['retry_in_s']
        self.observation_text.set(self.recovery.state+' · Last-good scan '+age_text+' · '+view['display_state']+
            (f' · Retry in {math.ceil(retry)}s' if retry is not None else ''))
        if self.last_result:
            tier=self.last_result.get('fee_evidence',{})
            rates=(f"maker {tier['maker']*100}% / taker {tier['taker']*100}%" if tier.get('maker') is not None and tier.get('taker') is not None else 'unavailable')
            self.evidence_text.set('Last-good account fees: '+rates+' · '+
                ('within TTL at present' if view['fee_valid_at_export'] else 'STALE / UNVERIFIED NOW')+
                ' · Fill evidence: unverified · Actual profit: not established')
            self._render_rows(self.last_result,view)
            self._select_row()

    def _render_wallet(self):
        if self.scanner is None:return
        excluded={r['asset'] for r in self.ledger.assets() if not r.get('enabled',1)}
        self.allocation_editor.snapshot(self.scanner.balances,self.scanner.account_at,time.time(),excluded)
        self.working_allocation=self.allocation_editor.assessment()
        changed=self.applied_eth_key is not None and self._funding()['key']!=self.applied_eth_key
        self._sync_eth_default()
        if changed:self._invalidate()

    def _render(self,result):
        self._render_wallet()
        if self.last_result is not result:return  # A changed default invalidates this queued plan.
        self.chart.set_products([r['market']['pair'] for r in result['rows']]);self.chart.refresh(live=True)
        self._render_rows(result,freshness(result,time.time(),fee_ttl=self.fees.ttl))
        self.status.set(f"{self.recovery.state} · Scan {result['scan']} · {result['state']}")
        self._select_row()
        self._update_freshness()

    def _render_rows(self,result,view):
        selected=self.growth_tree.selection();pairs={r['market']['pair'] for r in result['rows']}
        by_pair={r['pair']:r for r in view['products']}
        for item in self.growth_tree.get_children():
            if item not in pairs:self.growth_tree.delete(item)
        for row in result['rows']:
            pair=row['market']['pair'];h=row.get('hypothesis');b=row.get('benchmark');current=by_pair[pair]
            age_now=current['quote_age_s_at_export']
            fresh=current['freshness_state']=='LAST_OBSERVATION_WITHIN_AGE_LIMIT'
            paused=row.get('observation_state')=='SETUP_ACTIVE_UNPRICED' or self.recovery.state in ('RETRYING','PAUSED_NEEDS_ATTENTION')
            values=(pair,'—' if 'eth_per_coin' not in row else f'{row["eth_per_coin"]:.9g}',
                '—' if age_now is None or 'spread_pct' not in row else f'{row["spread_pct"]:.3f}% / {max(0,age_now):.1f}s',
                'UNPRICED' if b is None else f'{b["net_eth_subtotal"]:+.9g}'+(' + dust' if b['native_dust'] else ''),
                'EXPIRED' if current['expired_at_export'] else 'PAUSED' if paused else 'UNPRICED' if h is None else f'{h["scenario"]["net_eth_subtotal"]:+.8g} / {h["required_move_pct"]:.3f}%'+
                    (' + dust' if h['scenario']['native_dust'] else ''),
                current['freshness_state'] if not fresh else 'PAUSED / UNPRICED' if paused else row['fill_state'])
            if self.growth_tree.exists(pair):self.growth_tree.item(pair,values=values)
            else:self.growth_tree.insert('','end',iid=pair,values=values)
        if not selected and result['rows']:self.growth_tree.selection_set(result['rows'][0]['market']['pair'])


    def _note(self,text):
        self.lab_text.configure(state='normal');self.lab_text.insert('end',self._stamp(time.time())+'\n'+text+'\n\n')
        if int(self.lab_text.index('end-1c').split('.')[0])>500:self.lab_text.delete('1.0','100.0')
        self.lab_text.configure(state='disabled')

    def _export(self):
        path=filedialog.asksaveasfilename(title='Save v95 diagnostics',defaultextension='.txt',
            initialfile='CoinCat_v95_ETH_Growth_Diagnostics.txt',filetypes=[('Text','*.txt')])
        if path:
            try:Path(path).write_text(make_report(self),encoding='utf-8')
            except OSError as exc:messagebox.showerror('Diagnostics',f'Export failed ({type(exc).__name__}).')

    def _close(self):
        if self.closed:return
        self._stop();self.closed=True
        for task in self._after.values():
            try:self.root.after_cancel(task)
            except tk.TclError:pass
        self._after.clear();self.root.destroy()


def main():
    from coincat_single_instance import SingleInstance,AnotherCoinCatRunning
    from coincat_state_v50 import state_status,StateError
    directory=data_root()
    try:
        state_status(directory)
        with SingleInstance(directory):
            root=tk.Tk();CoinCatApp(root);root.mainloop()
    except (AnotherCoinCatRunning,StateError) as exc:
        print('CoinCat launch blocked:',type(exc).__name__);raise SystemExit(2) from exc


if __name__=='__main__':main()
