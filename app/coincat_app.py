"""CoinCat v1.03beta: explicit paper / bounded real maker workspace."""
from datetime import datetime,timezone
from pathlib import Path
from queue import Queue,Empty
import threading
import math
import time
import tkinter as tk
from tkinter import filedialog,messagebox

from coinbase_account import parse_key_json,save_encrypted,load_encrypted
from coincat_live import LiveLedger,client_from_credentials
from coincat_live_forward_store import ForwardStore,Retention
from coincat_state_v50 import data_root
from coincat_v502_fee_learning import FeeLearning
from coincat_scanner import Scanner
from coincat_version import DISPLAY
from coincat_simple_diagnostics import make_report
from coincat_eth_maker import MakerConfig,available_companions
from coincat_continuity import eth_funding,freshness,age
from coincat_recovery import Recovery,failure
from coincat_monitor import MonitorPublisher
from coincat_portfolio_view import PortfolioView
from coincat_watchlist import WATCH_PAIRS
from coincat_adaptive_eth import Frame
from coincat_research_journal import ResearchJournal,register_from_eth,public_status as journal_public
from coincat_auto_paper import AutoPaper
from coincat_paper_policy import DIRECTIONS
from coincat_beta_ui import BetaUI
import sqlite3
import uuid


class CoinCatApp(BetaUI):
    def __init__(self,root):
        self.root=root;root.title(DISPLAY+' | Maker workspace | LIVE block ON by default')
        root.geometry(f'{max(1000,min(1380,root.winfo_screenwidth()-40))}x{max(740,min(900,root.winfo_screenheight()-70))}')
        root.minsize(1000,740)
        self.data=data_root();self.ledger=LiveLedger(self.data/'CoinCat_Live_Orders.sqlite3')
        self.fees=FeeLearning(self.data/'research_data'/'CoinCat_Fee_Evidence_v502.sqlite3')
        self.market=ForwardStore(self.data/'research_data'/'CoinCat_Forward_Market.sqlite3',Retention())
        try:self.journal=ResearchJournal(self.data/'research_data'/'CoinCat_Prospective_Experiments.sqlite3')
        except (ValueError,OSError,sqlite3.Error):self.journal=None
        self.scanner=None;self.credentials=None;self.last_result=None;self.applied_config=None
        self.applied_eth_key=None;self.recovery=Recovery();self.retry_kind=None
        self.paper=AutoPaper(self.data/'research_data'/'auto_paper')
        self.paper_public=self.paper.public();self.paper_observe=False
        self._beta_init()
        self.connected=False;self.running=False;self.closed=False;self.busy=False;self.generation=0
        self.cancel=threading.Event();self.jobs=Queue();self._after={};self.last_error=None
        self.worker_thread=None;self.shutdown_complete=threading.Event()
        self.last_note_at=0;self._ready=False;self.working_allocation=None
        self.monitor=MonitorPublisher();self.monitor_enabled=tk.BooleanVar(value=False)
        self.monitor_text=tk.StringVar(value='Off · No automatic snapshots')
        self.status=tk.StringVar(value='Connect, choose companions, then apply a research plan.')
        self.observation_text=tk.StringVar(value='STOPPED · No completed research observation')
        self.funding_text=tk.StringVar(value='Working proposal: unset · Protected ETH: unverified')
        self.evidence_text=tk.StringVar(value='Fees: unobserved · Fills: unverified · Actual profit: not established')
        self.adaptive_text=tk.StringVar(value='HOLD · NO DEMONSTRATED EDGE\nRegister explicit conditional cases in the journal. Recoverable ETH: UNKNOWN.')
        self.journal_status=journal_public()
        self.journal_text=tk.StringVar()
        self._refresh_journal_status()
        self.detail_text=tk.StringVar(value='Select a market for details. Hover any control or result for help.')
        self.portfolio_view=PortfolioView();self.portfolio_result={}
        self.eth_held_text=tk.StringVar(value='Unobserved');self.basket_text=tk.StringVar(value='Unpriced')
        self.basket_change_text=tk.StringVar(value='No baseline');self.counter_text=tk.StringVar(value='Scans 0 · Verified bot fills 0')
        self.companions=[tk.StringVar() for _ in range(4)]
        self._ui();self._ready=True
        for value in self.companions:value.trace_add('write',lambda *args:self._companions_changed())
        self.root.protocol('WM_DELETE_WINDOW',self._close);self._schedule('poll',100,self._poll)
        self._schedule('history',200,self.chart.refresh)
        self._schedule('freshness',1000,self._freshness_tick)
        self._schedule('beta_tick',1000,self._beta_tick)
        self._schedule('book_tick',200,self._book_tick)

    def _ui(self):
        from coincat_workspace import build_workspace
        build_workspace(self)

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

    def _companions_changed(self):
        self.allocation_editor.set_watch_assets(v.get() for v in self.companions)
        self._invalidate()

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
            config=MakerConfig(companions=tuple(v.get() for v in self.companions if v.get()),
                observe_watchlist=True,**self.mixer.values()).validate()
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
        self.funding_text.set(f'Model {config.amount_eth} ETH per scenario\nUNRECONCILED / RESEARCH ONLY')
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
        self.worker_thread=threading.Thread(target=work,daemon=False)
        self.worker_thread.start();return True

    def _import_key(self):
        if self.busy:self.status.set('Wait for the read-only request to finish.');return
        if self.live.public()['unresolved']:
            self.status.set('Reconcile owned live orders before changing the saved key. Current identities and reserves are retained.');return
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
            if self.scanner is None:self.scanner=Scanner(self.ledger,client_from_credentials(self.credentials),self.fees,self.market,journal=self.journal)
            return self.scanner.refresh(cancel=cancel,force_catalog=True)
        self._submit('connect',task)

    def _start(self):
        if self.busy:self.status.set('A read-only request is finishing. Retry Start when it completes.');return
        if self.running:return
        if not self.connected or self.scanner is None:self.status.set('Connect first.');return
        if self.applied_config is None:self.status.set('Apply a research plan first.');return
        self.live.set_blocked(True);self.live_orders_blocked.set(True);self.live_observe=False
        self.paper_observe=False
        self.running=True;self.cancel=threading.Event();self.recovery.start()
        self.status.set('RUNNING · Observing direct ETH markets · No live orders');self._scan()

    def _stop(self):
        self.live.set_blocked(True);self.live_orders_blocked.set(True)
        self.live_coordinator.last_poll_mono=None
        self.manual_cancel.set()
        self.running=False;self.cancel.set();self.generation+=1;self.recovery.stop()
        try:self.paper.pause(at=time.time())
        except (ValueError,OSError,sqlite3.Error):pass
        self.paper_public=self.paper.public()
        if hasattr(self,'chart'):self.chart.cancel_pending()
        for key in ('scan','retry'):
            task=self._after.pop(key,None)
            if task is not None:
                try:self.root.after_cancel(task)
                except tk.TclError:pass
        self.status.set('STOPPED · Findings and paper reserves retained · LIVE orders blocked')
        if hasattr(self,'paper_panel'):self.paper_panel.refresh()
        self._beta_refresh()

    def _paper_scan_config(self):
        if self.live_observe and self.live.config is not None:
            return MakerConfig(companions=('BTC','ADA','LINK','SOL'),amount_eth=self.live.config.amount_eth,observe_watchlist=True).validate()
        if not self.paper_observe:return self.applied_config
        config=self.paper.config
        if config is None:return None
        companions=tuple(v['target'] for v in DIRECTIONS if v['source']=='ETH' and
            config.directions[v['id']]['enabled'])
        return MakerConfig(companions=companions,amount_eth=config.amount_eth,observe_watchlist=True).validate()

    def _start_auto_paper(self):
        if self.closed:return
        if self.busy:self.paper_panel.message.set('Wait for the current read-only request to finish.');return
        if self.scanner is None or not self.connected:self.paper_panel.message.set('Connect and verify the current working proposal first.');return
        self.live_observe=False
        try:
            now=time.time()
            if self.paper.engine is None:
                settings=self.paper_panel.global_applied_draft
                if settings is None:raise ValueError('APPLY_GLOBAL_TRADING_SETTINGS_FIRST')
                config=self.paper_panel.configuration()
                if not config.opt_in:raise ValueError('PAPER_OPT_IN_REQUIRED')
                if self.allocation_editor.dirty_fields:raise ValueError('APPLY_WORKING_DRAFT_FIRST')
                self._stop()
                proposal=dict(balances=dict(self.scanner.balances),balances_at=self.scanner.account_at,
                    draft=self.allocation_editor.parameters()['allocation_draft'],excluded=self.allocation_editor.excluded)
                self.paper.create(config,at=now,funding=proposal,global_settings=settings)
            else:
                if not self.paper.engine.private_state()['auto'].get('global_history'):
                    self.paper_panel.message.set('Apply Trading Settings to this saved paper session before Start. Existing records and orders are retained.');return
                if self.paper.engine.private_state()['mode']=='RECONCILIATION_REQUIRED':
                    self.paper_panel.message.set('Reconcile paper first; successful reconciliation leaves PAUSED. Then press Start.');return
                self._stop();self.paper.start(at=now)
            self.paper_observe=True;self.running=True;self.cancel=threading.Event();self.recovery.start()
            self.paper_panel.global_status.set('Applied global settings v'+
                str(len(self.paper.engine.private_state()['auto']['global_history']))+' · UNKNOWN blocks every new entry')
            self.paper_public=self.paper.public();self.paper_panel.refresh()
            self.status.set('RUNNING · Auto maker rotation PAPER ONLY · LIVE blocked');self._scan()
        except (ValueError,ArithmeticError,OSError,sqlite3.Error):
            self.paper_panel.message.set('Paper start blocked. Apply Trading Settings; check opt-in, fresh working ETH, size ≤ approved working slice, original expiry and saved-session recovery. No funds or orders reset.')

    def _pause_paper(self):
        if self.closed:return
        try:self.paper.pause(at=time.time())
        except (ValueError,OSError,sqlite3.Error):
            self.paper_panel.message.set('Paper storage needs review; reservations are retained.');return
        self.paper_public=self.paper.public();self.paper_panel.refresh()

    def _reconcile_paper(self):
        if self.closed:return
        if self.busy:self.paper_panel.message.set('Wait for the current read-only request before paper reconciliation.');return
        self._stop()
        try:self.paper.reconcile(at=time.time())
        except (ValueError,OSError,sqlite3.Error):
            self.paper_panel.message.set('Paper reconciliation blocked. Complete identities, native receipts and known fees are required; no balances guessed.');return
        self.paper_public=self.paper.public();self.paper_panel.refresh()

    def _new_paper_session(self):
        if self.closed:return
        if self.busy:self.paper_panel.message.set('Wait for the current read-only request before a new paper-session draft.');return
        self._stop()
        try:self.paper.new_session()
        except (ValueError,OSError,sqlite3.Error):
            self.paper_panel.message.set('The saved paper session needs review before starting another. No records replaced.');return
        self.paper_public=self.paper.public();self.paper_panel.opt_in.set(False)
        self.paper_panel.global_applied_draft=None
        self.paper_panel.global_status.set('New session: apply Trading Settings, then opt in and Start. Prior databases retained.')
        self.paper_panel.update_budget_default();self.paper_panel.refresh()
        self.paper_panel.message.set('New paper-session draft. Previous database retained; the new Start will create a separate ETH HOLD baseline.')

    def _scan(self,*,force_refresh=False):
        if self.closed or not self.running:return
        if self.busy:self._schedule('scan',250,self._scan);return
        config=self._paper_scan_config();cancel=self.cancel
        if config is None:return
        draft=self.allocation_editor.parameters()['allocation_draft'];funding_key=None if self.paper_observe or self.live_observe else self.applied_eth_key
        usd=bool(self.live_observe or self.paper_observe and self.paper.engine is not None and
            self.paper.engine.private_state()['auto'].get('global_history'))
        self._submit('scan',lambda:self.scanner.scan_growth(config,cancel=cancel,allocation_draft=draft,
                     applied_eth_key=funding_key,force_refresh=force_refresh,include_usd_reference=usd))

    def _retry(self):
        if self.closed or self.recovery.state!='RETRYING':return
        if self.retry_kind=='scan' and (not self.running or self._paper_scan_config() is None):return
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
            self._pause_paper()
            self.status.set(f"PAUSED_NEEDS_ATTENTION · {detail['stage']} / {detail['category']} · Refresh manually")
        self._update_freshness()

    def _poll(self):
        if self.closed:return
        try:
            while True:
                kind,generation,payload,error=self.jobs.get_nowait();self.busy=False
                if generation!=self.generation:continue
                if kind.startswith('beta_') or kind=='manual_import':
                    self._beta_result(kind,payload,error);continue
                if error:self._handle_failure(kind,error);continue
                if payload.get('state')=='CANCELLED':continue
                self.last_error=None
                if kind=='connect':
                    self.connected=True;self.recovery.authenticated();self._render_wallet()
                    self.live_coordinator.bind(self.scanner.client)
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
                    # Only a current accepted Tk generation can mutate the paper
                    # wallet. The collector/worker has no paper order authority.
                    accepted_frame=self._beta_frame(payload['research_frame'])
                    if self.last_result is payload and generation==self.generation and self.paper_observe:
                        self.paper.on_frame(accepted_frame,usd_reference=payload.get('usd_reference'))
                        self.paper_public=self.paper.public();self.paper_panel.refresh(payload)
                    if self.last_result is payload and generation==self.generation and self.live_observe:
                        self._queue_live_frame(accepted_frame,payload.get('usd_reference'))
                    if time.time()-self.last_note_at>=180:
                        self._note(payload['lab_note']);self.last_note_at=time.time()
                    if self.running and self._paper_scan_config() is not None:
                        self._schedule('scan',int(self._paper_scan_config().scan_interval_s*1000),self._scan)
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
        adaptive=(self.last_result or {}).get('adaptive',{})
        names=', '.join(r['target'] for r in adaptive.get('candidates',())) or 'Await eligible markets'
        self.adaptive_text.set('HOLD · NO DEMONSTRATED EDGE · '+self.recovery.state+
            '\nSource ETH; conditional next assets: '+names+
            '\nBTC → SOL research requires an explicit source assumption. Auto Paper is a separate opted-in session.'+
            '\nAfter-cost recoverable paper ETH: UNKNOWN · Forecast confidence: UNVALIDATED · Verified fills: 0')
        self._set_journal_status((self.last_result or {}).get('prospective_journal',self.journal_status))
        self._update_market_view(now)
        if hasattr(self,'paper_panel'):self.paper_panel.refresh(self.last_result,at=now)
        self._beta_refresh()

    def _set_journal_status(self,value):
        journal=journal_public(value);self.journal_status=journal
        if self.last_result is not None:self.last_result['prospective_journal']=journal
        if journal['state']=='EMPTY':
            self.journal_text.set('Journal empty · Register an explicit hypothetical experiment.');return
        if journal['state']=='UNAVAILABLE':
            self.journal_text.set('Journal unavailable · No current experiment verdict; retained records are unchanged.');return
        if journal['state']=='STORAGE_LIMIT':
            self.journal_text.set('Journal storage limit · Writing paused; retained history is not deleted.');return
        self.journal_text.set('Journal '+journal['state']+f" · Registered {journal['registered']} · Waiting {journal['waiting']}"+
            f"\nConditional favorable/adverse {journal['favorable']}/{journal['adverse']} · Unknown {journal['unknown']} · Missed {journal['missed_horizons']} · Unpriced open {journal['unpriced_open_cases']}"+
            '\nNo paper trades · After-cost missing evidence remains UNKNOWN')

    def _refresh_journal_status(self):
        # One startup/manual read; heartbeat, freshness ticks and exports use cache.
        try:value=self.journal.summary() if self.journal is not None else None
        except (ValueError,OSError,sqlite3.Error,TypeError,KeyError,ArithmeticError,RecursionError):value=None
        self._set_journal_status(value)

    def _open_experiment_dialog(self):
        from coincat_experiment_dialog import ExperimentDialog
        ExperimentDialog(self)

    def _view_experiments(self):
        from coincat_experiment_dialog import show_journal
        return show_journal(self)

    def _register_experiment(self,**values):
        if (self.busy or not self.running or not self.connected or self.scanner is None or
                self.recovery.state!='RUNNING' or self.journal is None or self.applied_config is None):
            raise ValueError('JOURNAL_REQUIRES_FRESH_RUNNING_RESEARCH')
        original=(self.last_result or {}).get('research_frame')
        if not isinstance(original,Frame):raise ValueError('NO_ACCEPTED_RESEARCH_FRAME')
        now=time.time();funding=self._funding()
        if not funding['valid'] or not 0<values['initial_eth']<=funding['row'].get('working',0):
            raise ValueError('WORKING_ETH_UNAVAILABLE')
        if funding['key']!=self.applied_eth_key:raise ValueError('ETH_FUNDING_CHANGED_REAPPLY_REQUIRED')
        frame=Frame(now,original._catalog,original._rules,original._quotes,original._tier,original._excluded)
        result=register_from_eth(self.journal,uuid.uuid4().hex,frame=frame,
            slippage_bps=self.applied_config.taker_slippage_bps,**values)
        self.scanner.journal=self.journal
        self._refresh_journal_status()
        self._update_freshness()
        return result

    def _render_wallet(self):
        if self.scanner is None:return
        excluded={r['asset'] for r in self.ledger.assets() if not r.get('enabled',1)}
        self.allocation_editor.snapshot(self.scanner.balances,self.scanner.account_at,time.time(),excluded)
        self.working_allocation=self.allocation_editor.assessment()
        changed=self.applied_eth_key is not None and self._funding()['key']!=self.applied_eth_key
        self._sync_eth_default()
        if hasattr(self,'paper_panel'):self.paper_panel.update_budget_default()
        if changed:self._invalidate()
        self._update_market_view(time.time())

    def _select_watch(self,event=None):
        selected=self.watch_tree.selection()
        if selected and selected[0] in WATCH_PAIRS:
            self.chart.pair.set(selected[0]);self.chart.refresh()

    def _reset_view_baseline(self):
        self.portfolio_view.baseline=None;self.portfolio_view.baseline_at=None
        self._update_market_view(time.time())

    def _update_market_view(self,now):
        from coincat_continuity import quote_reason
        rows={r['pair']:r for r in (self.last_result or {}).get('watched_markets',())}
        for pair in WATCH_PAIRS:
            row=rows.get(pair,{});book=row.get('book')
            reason=row.get('reason') or quote_reason(book,now)
            label=reason or ('Deferred · last observation' if row.get('deferred') else 'Observed')
            if book is not None and self.recovery.state in ('RETRYING','PAUSED_NEEDS_ATTENTION'):
                label='Paused · last observation'
            elif book is not None and not self.running:label='Stopped · last observation'
            price='—' if book is None else f'{(book[0]+book[1])/2:.9g} '+pair.split('-')[1]
            role='ETH scenario' if row.get('mode')=='ETH_SCENARIO' else 'Await BTC inventory' if 'ETH' not in pair.split('-') else 'Watch only'
            self.watch_tree.item(pair,values=(pair,price,label,role))
        result=self.last_result or {};counts=result.get('study_counts',{})
        self.counter_text.set(f'Scans {result.get("scan",0)} · Setups {counts.get("setups",0)}\nVerified bot fills {self.live_public["fills"]} · Bot orders {self.live_public["orders"]}')
        if self.scanner is None:return
        # Display only snapshots accepted on the GUI thread. A late worker from
        # an invalidated generation must not update the reference basket either.
        accepted_books={pair:row['book'] for pair,row in rows.items() if row.get('book') is not None}
        try:value=self.portfolio_view.measure(self.allocation_editor.balances,
            self.allocation_editor.balances_at,accepted_books,now)
        except (ValueError,ArithmeticError,TypeError):
            self.eth_held_text.set('Unverified');self.basket_text.set('Unpriced');self.basket_change_text.set('Unpriced');return
        self.portfolio_result=value
        self.eth_held_text.set('Unobserved / stale' if value['eth_held'] is None else f'{value["eth_held"]:.9g} ETH')
        self.basket_text.set('Unpriced' if value['watched_value_eth'] is None else f'{value["watched_value_eth"]:.9g}')
        self.basket_change_text.set('Unpriced / no baseline' if value['change_eth'] is None else
            '+0 ETH' if value['change_eth']==0 else f'{value["change_eth"]:+.9g} ETH')
        text=('Watched basket: ETH, BTC, ADA, LINK, SOL\n'
            'Midpoint reference before exit fees; change is not flow adjusted or verified bot profit.\n'
            'Outside basket (unvalued): '+(', '.join(value['outside_assets']) or 'None reported')+'\n'
            'Awaiting valid quote: '+(', '.join(value['missing_assets']) or 'None for reported basket holdings')+'\n'
            'Account snapshot: '+('Within freshness limit' if value['account_fresh'] else 'Stale / unobserved'))
        self.portfolio_text.configure(state='normal');self.portfolio_text.delete('1.0','end')
        self.portfolio_text.insert('1.0',text);self.portfolio_text.configure(state='disabled')

    def _render(self,result):
        self._render_wallet()
        if self.last_result is not result:return  # A changed default invalidates this queued plan.
        self.chart.set_products([r['market']['pair'] for r in result['rows']]);self.chart.refresh(live=True)
        self._render_rows(result,freshness(result,time.time(),fee_ttl=self.fees.ttl))
        if self.live_observe:self.status.set(f"{self.recovery.state} · REAL beta {self.live_public['state']} · Native scan {result['scan']}")
        else:
            mode='Auto Paper '+self.paper.public()['state']+' · ' if self.paper_observe else ''
            self.status.set(f"{self.recovery.state} · {mode}Scan {result['scan']} · {result['state']}")
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

    def _monitor_changed(self):
        if self.monitor_enabled.get():
            if not self.monitor.start():
                self.monitor_enabled.set(False);self.monitor_text.set('Previous writer is finishing; retry shortly.');return
            self._monitor_tick()
        else:
            timer=self._after.pop('monitor',None)
            if timer is not None:self.root.after_cancel(timer)
            self._monitor_stop('DISABLED')
            self.monitor_text.set('Off · Last snapshot retained')

    def _monitor_tick(self):
        if self.closed or not self.monitor.enabled:return
        try:
            self.monitor.publish(self.monitor.sample(self))
            detail=self.monitor.diagnostics()
            self.monitor_text.set('Write failed · Check support_monitor access' if detail['error'] else
                'Recording · Local redacted snapshots' if detail['last_written_at'] is not None else 'Starting local recorder')
        except Exception:
            self.monitor_text.set('Snapshot unavailable · Research unchanged')
        self._schedule('monitor',5000,self._monitor_tick)

    def _monitor_stop(self,lifecycle):
        try:final=self.monitor.sample(self,lifecycle=lifecycle)
        except Exception:final=None
        self.monitor.stop(final)

    def _export(self):
        path=filedialog.asksaveasfilename(title='Save v1.03beta diagnostics',defaultextension='.txt',
            initialfile='CoinCat_v1.03beta_ETH_Growth_Diagnostics.txt',filetypes=[('Text','*.txt')])
        if path:
            try:Path(path).write_text(make_report(self),encoding='utf-8')
            except OSError as exc:messagebox.showerror('Diagnostics',f'Export failed ({type(exc).__name__}).')

    def _close(self):
        if self.closed:return
        self._stop();self.book_stream.stop();self.closed=True
        if self.monitor.enabled:self._monitor_stop('CLOSED')
        for task in self._after.values():
            try:self.root.after_cancel(task)
            except tk.TclError:pass
        self._after.clear();self._finish_close()

    def _finish_close(self):
        # Read-only SDK requests have their existing timeout. Leave the GUI
        # responsive while cancellation drains the single worker and bounded
        # scout batch; no paper callback can run after closed/generation changes.
        from coincat_v701_transport import SCOUT
        worker=self.worker_thread
        with SCOUT.lock:scouting=any(not f.done() for f in SCOUT.inflight)
        if (worker is not None and worker.is_alive()) or scouting or self.book_stream.alive():
            self.status.set('Closing · Waiting for bounded workers; live block ON')
            self.root.after(50,self._finish_close);return
        if worker is not None:worker.join()
        if not self._beta_shutdown_started and self.live_coordinator.needs_poll():
            self._beta_shutdown_started=True
            def settle_before_close():
                # One bounded read/cancel pass; unknown orders stay durably locked.
                # It cannot place an order because STOP already set the gate ON.
                self.live_coordinator.cycle()
            self.worker_thread=threading.Thread(target=settle_before_close,name='CoinCat-live-stop-reconcile',daemon=False)
            self.worker_thread.start();self.root.after(50,self._finish_close);return
        self.root.destroy();self.shutdown_complete.set()


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
