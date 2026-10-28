"""CoinCat v50.6R four-tab Tkinter dashboard; complete-catalog research and safeguarded live pilot.
Always disarmed on launch. Never place orders from a GUI event handler thread.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal,InvalidOperation
from pathlib import Path
from datetime import datetime,timezone
import os,queue,threading,time,math,textwrap,shutil,tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog

from coinbase_account import parse_key_json,save_encrypted,load_encrypted
from coincat_live_forward_store import ForwardStore,Retention
from coincat_live_history import fetch_public_hourly_candles, fetch_public_hourly_range
from coincat_live import LiveLedger,LiveBroker,LiveBlocked,dec,fmt,sql,client_from_credentials
from coincat_live_ai import LiveSignalLab
from coincat_v607_strategy_research import StrategyResearch, public_summary as strategy_public_summary
from coincat_v608_outcomes import ForwardHorizonLab, status_text as v608_status_text
from coincat_trade_targets import target_exit_for_dollars
from coincat_directional import DirectionalLab,readiness,rotation_reviews
from coincat_universe import choose_discovery
from coincat_cross_quote import USD_QUOTES, split_spot, usd_conversion, research_sell_preview
from coincat_capacity import TIERS,current_stage,evaluate as evaluate_capacity,approve_next_stage
from coincat_market_stream import PublicTickerTape
from coincat_complete_diagnostics import make_complete_report, diagnostic_led_ready, CompleteReportSession
from coincat_v6016_sell_research import verified_full_sell_quantity, research_preview_slice_cap
from coincat_break_even import one_order_reference
from coincat_snowball import screen as snowball_screen, report as snowball_report
from coincat_v6018_fast_path import select_fast_books, fast_candidates, fast_funnel
from coincat_v701_quotes import newest_books, required_shadow_assets, mark_coverage
from coincat_v701_transport import SCOUT, fetch_snapshot, percentiles
from coincat_portfolio_budget import portfolio_ceiling, validate_manual_budget
from coincat_shadow_diagnostics import shadow_snapshot
from coincat_trade_frequency import frequency_report
from coincat_order_verify import verify_latest_filled_order
from coincat_state_v50 import data_root, state_status, StateError
from coincat_version import DISPLAY
from coincat_portfolio_sync import reconcile_authorized
from coincat_portfolio_prices import fetch_portfolio_books, portfolio_usd_rates, portfolio_coverage, DISPLAY_MAX_SPREAD
from coincat_storage import financial_storage_gate, storage_health, verified_ledger_backup, RESEARCH_LIMIT_MIB
from coincat_reporting import utc_window, confirmed_rows, export_csv, handoff_text
from coincat_scan_cadence import AdaptiveCadence
from coincat_market_intelligence import FocusPlanner
from coincat_v604_adaptive_focus import AdaptiveFocusCapacity
from coincat_v604_forward_windows import research_summary
from coincat_v6011_observation import safe_callback_breadcrumb, annotate_study
from coincat_portfolio_objective import balanced_market_universe, full_holding_exit_preview, priority_cross_cohort, quote_mix
from coincat_rotation_autopilot import auto_rotation_screen
from coincat_v609_direct import distinct_catalog_assets
from coincat_v6010_registry import one_order_catalog
from coincat_shadow_preferences import load as load_shadow_preferences, save as save_shadow_preferences, validate_amount as validate_shadow_floor
from coincat_v30_readiness import assess_readiness, format_readiness
from coincat_stream_research import StreamResearch
from coincat_gpu_advisory import advisory as gpu_research_advisory
from coincat_v502_fee_learning import FeeLearning
from coincat_v502_relative_learning import RelativeUSDLab
from coincat_v503_lab_evidence import capture_app_lab, budget_text, saved_gpu_heldout_status
from coincat_v606_budgets import load as load_manual_budgets, save as save_manual_budgets, effective as effective_manual_budgets, validate as validate_manual_budgets
from coincat_v505_pipeline import snapshot as v505_snapshot, status_line as v505_status_line
from coincat_v507_shadow_arm import ShadowArmedResearch
from coincat_v508_table_ui import add_tree_tips
from coincat_v60112_decision_display import decision_label, reason_tooltip, known_small_direct_buy
from coincat_v508_gpu_schedule import GPUResearchSchedule

BG='#0d1624';CARD='#19293d';FG='#eaf2fc';MUTED='#acc4d8';GREEN='#2db879';RED='#e65b65'
ROOT=data_root()

def _wrap_reason_cell(reason, width=36, lines=3):
    """Make a fixed-height ttk.Treeview reason readable while retaining full text.

    Tk does NOT automatically wrap Treeview text. A separate detail label exposes
    the full text if the explicit 3-line preview is shortened. This is UI ONLY.
    """
    words = textwrap.wrap(str(reason or '—').replace('\n',' '), width=width,
                          break_long_words=False, break_on_hyphens=False)
    if len(words) > lines:
        words = words[:lines]
        words[-1] = words[-1][:max(2, width-2)].rstrip(' …') + '…'
    return '\n'.join(words or ['—'])


class CoinCatApp:
    def __init__(self,root):
        self.root=root;self.root.title(DISPLAY + ' • CoinCat Auto Trader • DISARMED by default');self.root.geometry('1510x940');self.root.minsize(1000,650)
        try:self.root.iconbitmap(default=str(Path(__file__).with_name('CoinCat50.ico')))
        except (OSError,tk.TclError):pass
        self.creds=None;self.broker=None;self.catalog=[];self.catalog_at=0;self.current_balances={};self.worker_busy=False
        self.price_previous={};self.usd_previous={};self.target_net_usd=Decimal("0.10");self.preview_target_net_usd=Decimal("0.10")
        self._connection_requested=False;self._connection_in_progress=False;self._connection_started_at=0
        self.jobs=queue.Queue();self.last_observed=[];self.last_cycle=None;self.shadow_snapshots=[];self.shadow_session_totals={"cycles":0,"proposals":0,"wait_cycles":0,"attempts":0,"blocked":0,"exploratory":0,"exploratory_attempts":0};self.next_pair_idx=0;self.cadence=AdaptiveCadence(initial=30);self.loop_secs=self.cadence.seconds;self.max_focus_pairs=64;self.focus_capacity=AdaptiveFocusCapacity(initial=64);self.shutdown=False
        self._history_requested=False;self._history_in_progress=False;self._history_started_at=0
        self._last_poll_heartbeat=0.0;self._last_tick_heartbeat=0.0
        self._research_resume_gap_s=0.0;self._research_resume_at=0.0
        self._last_ui_callback_error_type=None;self._last_ui_callback_error_origin=None
        self._history_auto=False;self._auto_history_checked=0;self._last_trials_cleanup=0
        self._scan_started_at=0;self._last_scan_at=0;self._focus_cycles=0;self._scan_epoch=0;self._scan_processing=False;self._scan_progress_text='Waiting for next scheduled market scan';self._next_scan_at=time.monotonic()+1.5
        self.shadow_pilot=ShadowArmedResearch()  # Validated track, strict held-out gate
        self.experimental_shadow=ShadowArmedResearch(experimental=True)  # Separate RAM-only experiment; NO POST
        self._experimental_model_balances={}
        self.experimental_shadow_status=tk.StringVar(value='EXPERIMENT OFF • unvalidated what-if only; no Coinbase orders')
        self.experimental_pnl_status=tk.StringVar(value='EXPERIMENT P&L vs frozen HOLD • no simulated fills yet')
        self.shadow_mode_status=tk.StringVar(value='SHADOW OFF • Coinbase read-only observation only; never places orders')
        self.ledger=LiveLedger(ROOT/'CoinCat_Live_Orders.sqlite3')
        self.fee_learning=FeeLearning(ROOT/'research_data'/'CoinCat_Fee_Evidence_v502.sqlite3')
        self.relative_lab=RelativeUSDLab(ROOT/'research_data'/'CoinCat_Public_Relative_USD_v502.sqlite3')
        self.external_balance_warning=tk.StringVar(value='CoinCat v60 preserves enrolled eligible liquid assets and settings from your verified data copy; previous exclusions, costs, and traded quantities remain protected. Live trading always starts DISARMED.')
        self.forward=ForwardStore(ROOT/'research_data'/'CoinCat_Forward_Market.sqlite3',Retention(max_mb=RESEARCH_LIMIT_MIB))
        self.lab=LiveSignalLab(self.forward,self.ledger,fee_learning=self.fee_learning)
        self.strategy_lab=StrategyResearch(self.forward)  # SAME public market DB, never a broker
        self.horizon_lab=ForwardHorizonLab(self.forward)  # same DB, costed observations, NO ORDERS
        self.directional=DirectionalLab(self.forward,fee_learning=self.fee_learning)
        self._pulse_phase=0;self._gpu_validated=saved_gpu_heldout_status(ROOT/'gpu_research')
        self.discovery_per_cycle=12  # Complete-catalog rotation; silent markets remain covered
        self._last_scout_rank_count=0
        self._fast_next_at=time.monotonic()+5
        self._fast_interval_s=5      # Urgent checks do not wait for background research
        self._fast_runs=0
        self._fast_candidate_signature=None
        self._fast_candidate_signature_at=0.0
        self._fast_latencies=[]
        self._fast_totals={'attempted':0,'rest_books':0,'rest_errors':0,'simulated_fills':0}
        self._fast_last_result={'state':'WAIT','reason':'Awaiting verified stream movement'}
        self.fast_research_status=tk.StringVar(value='FAST SNOWBALL • waiting for stream alerts; ≤16 REST books, same planner, NO LIVE POST')
        self.stream_research=StreamResearch() # bounded sub-second in-memory ticker telemetry; NO orders
        self.stream=PublicTickerTape(on_tick=self.stream_research.observe)  # trade-price telemetry, never execution
        self.focus_planner=FocusPlanner(self.forward) # persistent ~45min research-only cohorts
        self._last_focus_plan={}
        self._last_stream_render=0
        self.capacity_stage=current_stage(self.ledger)
        self.capacity_preference=tk.IntVar(value=self.capacity_stage)
        self.capacity_status=tk.StringVar(value='Capacity review: collecting actual Coinbase completed BUY→SELL evidence; NO automatic limit increases')
        self.capacity_last_checked=0;self.capacity_proposal=None;self.capacity_snooze_until=int(self.ledger.setting('capacity_snooze_until','0'))
        self.capacity_last_suggested=None
        self.status=tk.StringVar(value='DISARMED • no Coinbase orders will be placed')
        self.account_label=tk.StringVar(value='Not connected • use a CDP view/trade key with transfers disabled')
        self._performance_period_label=tk.StringVar(value='USD performance snapshot: read-only and separate from historical tax cost.')
        self.start_snapshot_summary=tk.StringVar(value='COINCAT START VALUES • Existing approved holdings can be marked from today’s live Coinbase USD bid. This does NOT set historical purchase cost or tax basis.')
        self.connection_detail=tk.StringVar(value='No connection request underway.')
        self.connection_elapsed=tk.StringVar(value='')
        self.research_label=tk.StringVar(value='Waiting for live market observations')
        self.lab_activity=tk.StringVar(value='Idle • waiting for first live scan')
        self.lab_heartbeat=tk.StringVar(value='No completed scan yet')
        self.lab_history=tk.StringVar(value='Auto catch-up: awaits Coinbase connection • hourly historical context only')
        self.directional_status=tk.StringVar(value='Two-way forward research: collecting observable BUY, SELL-vs-HOLD labels; ROTATE is review-only')
        self.rotation_lab_status=tk.StringVar(value='AUTO ROTATION SHADOW • waiting for AI market scan and authorized wallet snapshot')
        self.readiness_status=tk.StringVar(value='Research coverage: 0% • not a prediction of profitability')
        self.storage_status=tk.StringVar(value='Research database: awaiting first scan • bound 1,024 MiB (1 GiB); offline gaps are not forward observations')
        self.universe_status=tk.StringVar(value='All-catalog market discovery: waiting for authenticated Coinbase spot products; deep REST study remains bounded')
        self.gpu_status=tk.StringVar(value='GPU BUY/SELL model: not trained • observe-only, never controls live orders')
        self.strategy_pipeline_status=tk.StringVar(value='STRATEGY RESEARCH • waiting for fresh REST bids/asks • single planner • no orders')
        self.execution_learning=tk.StringVar(value='Exchange fee learning: waiting for CONFIRMED Coinbase fills; previews never count as trade outcomes.')
        self.trader_label=tk.StringVar(value='STOPPED • Connect, review enrolled liquid balances, then separately ARM LIVE')
        self.trade_frequency_status=tk.StringVar(value='Trade frequency: local confirmed order/fill counters, awaiting refresh')
        self._manual_budget_path=ROOT/'research_data'/'CoinCat_Shadow_Manual_Budgets_v606.json'
        self._manual_budget_saved=load_manual_budgets(self._manual_budget_path)
        self.shadow_budget_mode=tk.StringVar(value=self._manual_budget_saved.get('mode','MANUAL'))
        self.limits=[tk.StringVar(value=self._manual_budget_saved[k]) for k in
                     ('per_order_usd','daily_buy_usd','added_exposure_usd')]
        self.max_attempts_entry=tk.StringVar(value=self._manual_budget_saved['attempts_24h'])
        self.manual_budget_status=tk.StringVar(value='SHADOW budgets loaded • choose FULL AVAILABLE or MANUAL and Apply; strict verified wallet fuel only')
        self.target_entry=tk.StringVar(value="0.10")
        self._shadow_settings_path=ROOT/'research_data'/'CoinCat_Shadow_Research_Preferences_v602.json'
        shadow_preferences=load_shadow_preferences(self._shadow_settings_path)
        self.switch_floor_mode=tk.StringVar(value=shadow_preferences['mode'])
        self.switch_manual_usd=shadow_preferences['manual_usd']
        # AI may suggest a threshold only after independent verified held-out
        # outcomes. Until then it does NOT invent a profitable threshold.
        self.switch_minimum_usd=(self.switch_manual_usd if self.switch_floor_mode.get()=='MANUAL'
                                  else Decimal('.10'))
        self.switch_minimum_entry=tk.StringVar(value=f'{self.switch_manual_usd:.2f}')
        self.switch_minimum_status=tk.StringVar(value=(
            f'SHADOW floor: {self.switch_floor_mode.get()} ${self.switch_minimum_usd:.2f}; '
            'AI studies $0.10-$100.00 independently; no orders'))
        self.daily_loss_limit_entry=tk.StringVar(value='5.00')
        self.loss_policy_message=tk.StringVar(value='Daily confirmed realized USD loss: $5.00 BUY pause • independent portfolio floor remains required.')
        self.target_preview_status=tk.StringVar(value='RESEARCH PREVIEW $0.10 net ordinary SELL target • DISARMED • no orders')
        self._target_preview_pending=False
        self.sell_status=tk.StringVar(value='Sell research: awaiting fresh quotes; holdings require original basis or explicitly approved market snapshot')
        self.full_exit_status=tk.StringVar(value='Whole-holding inventory research: waiting for fresh verified balances and quotes • NO ORDERS')
        self.rotation_auto_status=tk.StringVar(value='AUTO ROTATION • AI Lab → Auto Trader research • cross-currency execution not certified')
        self.v30_readiness_status=tk.StringVar(value='READINESS CHECK • Connect Coinbase and collect real market observations while DISARMED')
        self._v30_observation_started=0.0
        self._v30_readiness_last_checked=0.0
        self.fill_sync_status=tk.StringVar(value='Fill monitor idle • automatic pending-order check ~5 seconds while app and network are responsive')
        self._last_fill_poll=0.0
        self.portfolio_sync_secs=60  # Coinbase GET only; may locally auto-enroll NEW, previously unregistered available spot assets; never reprices old lots
        self.catalog_refresh_secs=90*60  # DISARMED read-only authenticated product refresh; cannot enable trades
        self._inactive_market_pairs=set()  # Formerly listed products: disabled from active research; historical SQLite retained
        self._last_catalog_refresh_attempt=0.0
        self._portfolio_quotes={}  # READ-ONLY per-holding Coinbase book quotes for DISPLAY only
        self._portfolio_quote_error='Initial pricing queued'
        self._portfolio_price_at=0.0
        self._portfolio_coverage={'held_count':0,'priced_count':0,'unpriced_count':0,'complete':False,'missing':{}}
        self.portfolio_feed_status=tk.StringVar(value='Portfolio USD price coverage pending • AI Lab and Auto Trader are observation-only')
        self._portfolio_quote_at=0.0
        self._last_portfolio_sync_monotonic=0.0
        self._portfolio_sync_running=False
        self._last_storage_check=0.0
        self._tax_archive_warning_logged=False
        self.portfolio_sync_status=tk.StringVar(value='PORTFOLIO SYNC • Coinbase read-only verification pending')
        self.storage_health_status=tk.StringVar(value='STORAGE HEALTH • Checking ledger and research limits')
        self.market_search=tk.StringVar(value='')
        self.ai_overview_pairs=tk.StringVar(value='— markets')
        self.ai_overview_buy=tk.StringVar(value='0 BUY ideas')
        self.ai_overview_sell=tk.StringVar(value='0 SELL ready')
        self.ai_overview_research=tk.StringVar(value='RESEARCH ACTIVE')
        self.ai_overview_funding=tk.StringVar(value='Waiting for enrolled funding')
        self.ai_overview_exploration=tk.StringVar(value='Waiting for market exploration')
        self.ai_learning_chain=tk.StringVar(value='Portfolio → priced funding → market exploration → verified BUY → SHADOW; waiting for scan')
        self.ai_quote_coverage=tk.StringVar(value='Adaptive deep-study research awaiting scan; full Coinbase catalog scouted separately')
        self.cadence_status=tk.StringVar(value='ADAPTIVE SCAN • 30s start • min 15s REST research floor; WebSocket updates are display-only')
        self.dashboard_portfolio=tk.StringVar(value='— currently verified portfolio value')
        self.dashboard_enrolled=tk.StringVar(value='— enrolled')
        self.dashboard_connection=tk.StringVar(value='OFFLINE')
        self._fill_sync_faulted=False
        self.risk_message=tk.StringVar(value='Risk limits require explicit authorization. Protective exits remain independently safeguarded.')
        self.ai_budget_preview=tk.StringVar(value='Gathering independent, verified trading evidence before proposing any increase')
        self.pipeline_status=tk.StringVar(value='Portfolio → AI Lab → SHADOW / Auto Trader → P&L • waiting for verified data')
        self.reserve_advisory=tk.StringVar(value='RESEARCH FUNDING • No automatic profit reserve or extra 10% BUY holdback. Full verified available ENROLLED balances may fund one-order research after modeled fees/slippage, precision, Coinbase product minimums and existing SHADOW limits. LIVE safety unchanged.')
        self._gpu_folder=ROOT/'gpu_research'
        self._gpu_runtime_info={'status':'NOT_PROBED'}
        self._gpu_schedule=GPUResearchSchedule()
        self._gpu_last_forward_report={}
        self._shadow_stop_reason='NEVER ARMED'
        self._shadow_model_balances={}
        self._shadow_excluded_assets=()
        self._snowball_summary={}
        self.break_even_preview=tk.StringVar(value='Waiting for authenticated fee tier and fresh one-order route evidence')
        self._render_capacity_limits()
        self._skin();self._ui()
        self._scheduled={}
        # Input editing refreshes RESEARCH ONLY while disarmed; never silently changes
        # the live broker's order target. Live target is committed only on ARM LIVE.
        self.target_entry.trace_add('write',self._schedule_target_preview)
        self.limits[0].trace_add('write',self._schedule_target_preview)  # disarmed SELL research size only
        self._scheduled['lab_sash']=self.root.after(250,self._size_lab_columns)
        self.root.protocol('WM_DELETE_WINDOW',self._close)
        self.root.bind('<Destroy>',self._on_root_destroy,add='+')
        self._scheduled['poll']=self.root.after(300,self._poll)
        self._scheduled['tick']=self.root.after(1500,self._tick)
        self._scheduled['connection']=self.root.after(2200,self._auto_connect_saved_key)
        self._paint_arm_switch()
        if self._pulse_phase % 9==0 and hasattr(self,'today_net_display'):
            try:
                stats=self.ledger.today_stats()
                self.today_net_display.set(f'${stats["day_pnl"]:+,.2f}')
                self.pending_count_display.set(str(len(self.ledger.pending())))
            except Exception:
                self.today_net_display.set('—')
                self.pending_count_display.set('—')
        self._refresh_break_even()
        if self._pulse_phase % 9==0:
            self._refresh_budget_advisor()
        self._scheduled['pulse']=self.root.after(450,self._pulse)
        self._log('CoinCat v60.6 started DISARMED. First eligible liquid balances auto-enroll once; live order submission remains BLOCKED.')

    def _resize_brand(self,event=None):
        if event is not None and event.widget is not self.root:return
        desired=210 if self.root.winfo_height()>=860 else 174
        if desired!=self._brand_height:
            self._brand_height=desired
            self.brand_header.configure(height=desired)
            self.brand_panel.configure(height=desired)

    def _draw_brand(self,event=None):
        """Display approved transparent artwork without distorting its proportions."""
        c=self.brand_panel
        width=max(c.winfo_width(),300); height=max(c.winfo_height(),140)
        c.delete('all')
        for y in range(0,height,3):
            c.create_line(0,y,width,y,fill=('#071221' if y%9 else '#091b30'))
        # Preserve the complete approved pool-party artwork and reserve room for
        # the always-visible DISARMED/ARMED safety indicator at the right.
        available_width=max(0,width-225)
        available_height=max(0,height-4)
        fits=[photo for photo in self._brand_images
              if photo.width()<=available_width and photo.height()<=available_height]
        photo=fits[-1] if fits else self._brand_images[0]
        c.create_image(10,height//2,image=photo,anchor='w')
        c.create_line(12,height-2,width-12,height-2,fill='#244466')
        self._paint_brand_status(width,height)

    def _paint_brand_status(self,width,height):
        c=self.brand_panel
        state='ARMED' if self.broker and self.broker.armed else 'DISARMED'
        fg='#3ce296' if state=='ARMED' else '#80bfff'
        c.create_rectangle(width-208,36,width-15,88,outline='#32567a',fill='#10263f',width=2)
        c.create_oval(width-190,54,width-174,70,fill=fg,outline='#cee9ff')
        c.create_text(width-161,62,text=state,anchor='w',font=('Segoe UI Semibold',12),fill=fg)

    def _update_nav(self,event=None):
        try:
            index=self.notebook.index('current')
            for i,button in enumerate(self.nav_buttons):
                button.configure(bg='#184a78' if i==index else '#07172b',
                                 fg='#ffffff' if i==index else '#c7dafa')
        except (tk.TclError,AttributeError):pass

    def _toggle_trader_advanced(self):
        if self.advanced_body.winfo_manager():
            self.advanced_body.pack_forget()
            self.advanced_button.configure(text='Advanced settings & research details ▸')
        else:
            self.advanced_body.pack(fill='x',pady=(3,8))
            self.advanced_button.configure(text='Advanced settings & research details ▾')

    def _paint_arm_switch(self):
        if not hasattr(self,'arm_switch'):return
        c=self.arm_switch;c.delete('all')
        armed=bool(self.broker and self.broker.armed)
        c.create_rectangle(13,5,173,251,fill='#344457',outline='#9fb3c8',width=3)
        c.create_rectangle(22,14,164,242,fill='#182e47',outline='#657e96',width=2)
        c.create_rectangle(33,23,153,232,fill='#081422',outline='#364b66',width=3)
        accent='#38ee96' if armed else '#47aaff'
        for i in range(4):
            c.create_oval(45-i,78-i if armed else 157-i,140+i,173+i if armed else 252+i,
                          outline=accent,width=1)
        knob_y=98 if armed else 176
        for idx,color in enumerate(('#102136','#42546b','#8f9eae','#d3dae2','#708198')):
            inset=idx*4
            c.create_oval(58+inset,knob_y-42+inset,127-inset,knob_y+28-inset,
                          fill=color,outline='#b3c6d5' if idx==0 else color)
        c.create_text(93,49,text='ARMED',fill='#4bf49b' if armed else '#7896b1',
                      font=('Segoe UI Semibold',11))
        c.create_text(93,213,text='DISARMED',fill='#6db8ff' if not armed else '#7896b1',
                      font=('Segoe UI Semibold',10))
        for x,y in ((22,14),(164,14),(22,241),(164,241)):
            c.create_oval(x-3,y-3,x+3,y+3,fill='#bbcddd',outline='#142b45')

    def _arm_switch_click(self,event=None):
        if self.broker and self.broker.armed:
            self._disarm_switch()
        else:
            self._arm()
        self._paint_arm_switch()

    def _arm_switch_keyboard(self,event=None):
        self._arm_switch_click(event)
        return 'break'

    def _disarm_switch(self):
        if self.broker:self.broker.disarm()
        self.status.set('DISARMED • new orders disabled by operator')
        self.trader_label.set('DISARMED • pending Coinbase orders still require reconciliation')

    def _apply_manual_budgets(self):
        if getattr(self.broker,'armed',False):
            messagebox.showwarning('Manual SHADOW budget','Real trading must remain DISARMED.');return
        values=dict(per_order_usd=self.limits[0].get(), daily_buy_usd=self.limits[1].get(),
                    added_exposure_usd=self.limits[2].get(),attempts_24h=self.max_attempts_entry.get(),
                    mode=self.shadow_budget_mode.get())
        try:
            saved=save_manual_budgets(self._manual_budget_path,values)
        except (ValueError,OSError) as exc:
            self.manual_budget_status.set('NOT APPLIED • '+str(exc))
            messagebox.showwarning('Manual SHADOW budget','NOT APPLIED: '+str(exc));return
        self._manual_budget_saved=saved
        self.manual_budget_status.set(('FULL AVAILABLE portfolio SHADOW mode saved • dollar ceilings update from strict verified modeled-wallet fuel each scan'
            if saved['mode']=='FULL_AVAILABLE' else
            'MANUAL SHADOW caps saved • dollar ceilings never exceed strict verified modeled-wallet fuel') +
            ' • attempt safety ceiling and other guards unchanged')
        self._refresh_budget_advisor()

    def _refresh_budget_advisor(self):
        # This is READ-ONLY RESEARCH guidance. Broker risk caps are independent
        # and no evidence grade can change them or authorize cross-pair orders.
        try:
            summary=capture_app_lab(self)
            self.pipeline_status.set(v505_status_line(v505_snapshot(self)))
            self.ai_budget_preview.set(
                'AI LAB RESEARCH FUEL: all strict-price eligible available enrolled holdings; '
                'NOT capped by the manual per-order, daily or exposure boxes. '                'Bounded candidate sampling, fresh FX, spot listing and evidence checks still apply. '
                'Unpriceable holdings are excluded individually; missing evidence means HOLD.\n'
                + budget_text(summary,
                    manual_daily=self._manual_budget_saved['daily_buy_usd'],
                    manual_exposure=self._manual_budget_saved['added_exposure_usd'],
                    manual_attempts=self._manual_budget_saved['attempts_24h'])
                + '\nSHADOW budget mode: '+self._manual_budget_saved.get('mode','MANUAL')+
                    ' • verified available modeled-wallet fuel only • not LIVE authorization.')
            self._refresh_evidence_bars(summary)
        except Exception:
            self.ai_budget_preview.set('AI Lab evidence unavailable • preferred research budget $0 • broker limits unchanged')

    def _refresh_evidence_bars(self,report):
        for item in report.get('cards',()):
            widget=getattr(self,'lab_evidence_bars',{}).get(item['key'])
            if widget is not None:
                gauge,label=widget
                gauge['value']=item['value']
                label.set(f'{item["value"]}% • {item["detail"]}')

    def _refresh_break_even(self):
        """Display the one-order Snowball cost model, never the old round trip."""
        tier=getattr(self,'fee_learning',None)
        fee=tier.latest_tier() if tier is not None else {'fresh':False}
        if not fee.get('fresh'):
            self.break_even_preview.set('FEE UNVERIFIED — no authenticated Coinbase spot tier. Snowball research WAIT; no orders.')
            return
        reference=one_order_reference(fee.get('taker'))
        if not reference:
            self.break_even_preview.set('Account taker tier invalid. Snowball research WAIT; no orders.')
            return
        s=getattr(self,'_snowball_summary',{}) or {}
        best=s.get('best_delta_usd')
        costs=f'One direct order fee/slippage reference {reference["one_order_recovery_pct"]:.2f}% (fee tier + 15bps stress; spread not included).'
        if best is None:
            detail=f'Snowball: {s.get("screened",0)} one-order routes screened; no synchronized conservative USD comparison yet.'
        else:
            detail=(f'Snowball best currently modeled slice: before ${s["best_before_usd"]:.4f} / '
                    f'after ${s["best_after_usd"]:.4f} / delta ${best:+.4f}. '
                    f'{s.get("above_floor",0)} candidates meet ${s.get("threshold_usd","0.10")} target.')
        self.break_even_preview.set(detail+'\n'+costs+'\n'
            'Estimated immediate values are research-only, not real fills. Independent Coinbase depth, pair preview and future performance NOT verified. LIVE BLOCKED.')

    def _size_lab_columns(self):
        # Half-and-half initial split; individual sash positions remain user resizable.
        if self.shutdown:return
        for pane in (self.ai_panes,self.trader_panes,getattr(self,"coinbase_panes",None),getattr(self,"pnl_panes",None)):
            try:
                if pane is None:continue
                width=pane.winfo_width()
                if width>300:pane.sashpos(0,int(width*(.31 if pane in (getattr(self,'coinbase_panes',None),getattr(self,'pnl_panes',None)) else .54 if pane is self.trader_panes else .31)))
            except (tk.TclError,AttributeError):pass

    def _scrollable_body(self, shell, *, padding=(6,4,9,12)):
        """A persistent scrollbar for a full tab/pane, not only its embedded Treeviews."""
        canvas=tk.Canvas(shell,bg=BG,highlightthickness=0,borderwidth=0)
        bar=ttk.Scrollbar(shell,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        inside=ttk.Frame(canvas,padding=padding)
        win=canvas.create_window((0,0),window=inside,anchor='nw')
        def reshape(event=None):
            try:canvas.configure(scrollregion=canvas.bbox('all'))
            except tk.TclError:pass
        def fit(event):
            try:
                width=max(280,event.width)
                canvas.itemconfigure(win,width=width)
                # Long status labels must wrap within the actual pane width.
                def fit_labels(node):
                    for child in node.winfo_children():
                        if isinstance(child,ttk.Label):
                            try:
                                if int(child.cget('wraplength'))>=300:
                                    child.configure(wraplength=max(200,width-24))
                            except (ValueError,tk.TclError):pass
                        # Avoid descending into Treeview internals / large data widgets.
                        if isinstance(child,(ttk.Frame,ttk.LabelFrame)):
                            fit_labels(child)
                fit_labels(inside)
            except tk.TclError:pass
        inside.bind('<Configure>',reshape)
        canvas.bind('<Configure>',fit)
        # Keep scrollbar usable even when cursor is over a heading or label.
        def on_mousewheel(event):
            if getattr(event,'delta',0):canvas.yview_scroll(-int(event.delta/120),'units')
        canvas.bind('<MouseWheel>',on_mousewheel)
        inside.bind('<MouseWheel>',on_mousewheel)
        return inside,canvas,bar

    def _skin(self):
        self.root.configure(background=BG)
        style=ttk.Style();style.theme_use('clam')
        style.configure('TFrame',background=BG);style.configure('TLabel',background=BG,foreground=FG,font=('Segoe UI',10))
        style.configure('TButton',font=('Segoe UI Semibold',10),padding=(10,9),background='#28435e',foreground=FG,borderwidth=1)
        style.map('TButton',background=[('active','#2b617c'),('pressed','#1a7683')])
        style.configure('Primary.TButton',background='#147fd1',foreground='white',font=('Segoe UI Semibold',10),padding=(11,9))
        style.map('Primary.TButton',background=[('active','#2464ac')])
        style.configure('Action.TButton',background='#168e69',foreground='white',font=('Segoe UI Semibold',10),padding=(11,9))
        style.map('Action.TButton',background=[('active','#19a77e')])
        style.configure('Danger.TButton',background='#a53b4b',foreground='white',font=('Segoe UI Semibold',10),padding=(11,9))
        style.configure('Tile.TLabelframe',background='#122136',bordercolor='#305878')
        style.configure('Tile.TLabelframe.Label',background=BG,foreground='#79d6d7',font=('Segoe UI Semibold',10))
        style.configure('Info.TLabel',background=BG,foreground=MUTED,font=('Segoe UI',9))
        style.configure('TEntry',fieldbackground=CARD,foreground=FG)
        style.configure('HighContrast.Horizontal.TProgressbar',troughcolor='#03101b',
                        background='#0ff0cf',bordercolor='#9ac5dc',lightcolor='#0ff0cf',darkcolor='#0ba6a9',thickness=17)
        style.configure('Horizontal.TProgressbar',troughcolor='#03101b',
                        background='#0ff0cf',bordercolor='#9ac5dc',lightcolor='#0ff0cf',darkcolor='#0ba6a9',thickness=14)
        style.configure('Sidebar.TNotebook',background=BG,borderwidth=0);style.layout('Sidebar.TNotebook.Tab', [])
        style.configure('TNotebook',background=BG,borderwidth=0);style.configure('TNotebook.Tab',background=CARD,foreground=FG,padding=(18,10),font=('Segoe UI Semibold',10))
        style.map('TNotebook.Tab',background=[('selected','#207f87')])
        style.configure('Treeview',background='#10243a',fieldbackground='#10243a',foreground=FG,rowheight=30,font=('Segoe UI',9))
        style.map('Treeview',background=[('selected','#236283')],foreground=[('selected','white')])
        style.configure('Treeview.Heading',background='#29445c',foreground='white')
        style.configure('ReasonWrap.Treeview',background='#10243a',fieldbackground='#10243a',foreground=FG,rowheight=31,font=('Segoe UI',9))
        style.configure('TLabelframe',background=BG,bordercolor='#345271')
        style.configure('TLabelframe.Label',background=BG,foreground='#66d6bb',font=('Segoe UI Semibold',10))
        style.configure('Summary.TLabel',background=BG,foreground=GREEN,font=('Segoe UI Semibold',11))
        style.configure('ReasonWrap.Treeview.Heading',background='#29445c',foreground='white')
        style.configure('ResearchDense.Treeview',background='#10243a',fieldbackground='#10243a',foreground=FG,rowheight=25,font=('Segoe UI',9))
        style.map('ResearchDense.Treeview',background=[('selected','#126f84')],foreground=[('selected','#ffffff')])

    def _text(self,parent,string,**kw):return ttk.Label(parent,text=string,**kw)
    def _header(self,p,title,subtitle):
        ttk.Label(p,text=title,font=('Segoe UI Semibold',15),foreground=FG).pack(anchor='w',pady=(2,7))
        self._text(p,subtitle,wraplength=1180).pack(anchor='w',pady=(0,12))
    def _tree(self,p,columns,height=8,hscroll=False):
        frame=ttk.Frame(p);frame.pack(fill='both',expand=True,pady=(6,10))
        tv=ttk.Treeview(frame,columns=columns,show='headings',height=height)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tv.yview)
        tv.configure(yscrollcommand=scroll.set)
        if hscroll:
            xscroll=ttk.Scrollbar(frame,orient='horizontal',command=tv.xview)
            tv.configure(xscrollcommand=xscroll.set)
            xscroll.pack(side='bottom',fill='x')
        for col in columns:
            tv.heading(col,text=col,command=lambda c=col,t=tv:self._sort_table(t,c))
            tv.column(col,width=140,minwidth=65,stretch=True)
        scroll.pack(side='right',fill='y')
        tv.pack(side='left',fill='both',expand=True)
        add_tree_tips(tv)
        return tv
    def _sort_table(self,tree,col,forced=None):
        # Sorting never alters the underlying asset enrollment or live order state.
        previous=getattr(tree,'_sort_state',None)
        reverse=(previous==(col,False)) if forced is None else forced
        def key(item):
            raw=tree.set(item,col)
            try:return (0,Decimal(raw.replace(',','').split('/')[0]))
            except Exception:return (1,raw.casefold())
        if tree is getattr(self,'balance_tree',None):
            ranks={'ENROLLED':0,'EXCLUDED':0,'NOT APPROVED':0,'CATALOG ONLY':1}
            ordered=sorted(tree.get_children(''),key=lambda iid:(ranks.get(str(tree.item(iid,'values')[-1]),1),))
            buckets={0:[],1:[]}
            for iid in ordered:
                status=str(tree.item(iid,'values')[-1]); buckets[ranks.get(status,1)].append(iid)
            rows=sorted(buckets[0],key=key,reverse=reverse)+sorted(buckets[1],key=key,reverse=reverse)
        else:
            rows=sorted(tree.get_children(''),key=key,reverse=reverse)
        for index,item in enumerate(rows):tree.move(item,'',index)
        tree._sort_state=(col,reverse)
    def _reapply_sort(self,tree):
        if getattr(tree,'_sort_state',None):
            col,reverse=tree._sort_state
            self._sort_table(tree,col,forced=reverse)
    def _ui(self):
        head=tk.Frame(self.root,bg='#071221',height=210,highlightthickness=0)
        self.brand_header=head
        self._brand_height=210
        head.pack(fill='x');head.pack_propagate(False)
        self.brand_panel=tk.Canvas(head,height=210,bg='#071221',highlightthickness=0,borderwidth=0)
        self.brand_panel.pack(side='left',fill='both',expand=True)
        # Ready-sized artwork keeps the logo sharp without requiring Pillow on Windows.
        self._brand_images=[tk.PhotoImage(file=str(Path(__file__).with_name(f'coincat_logo_banner_{size}.png')))
                            for size in (520,630,720,930,1100)]
        self.brand_panel.bind('<Configure>',self._draw_brand)
        self.root.bind('<Configure>',self._resize_brand,add='+')
        topline=ttk.Frame(self.root,padding=(13,0,13,5));topline.pack(fill='x')
        for tag,var in (('COINBASE',self.dashboard_connection),('PORTFOLIO',self.dashboard_portfolio),('ENROLLMENT',self.dashboard_enrolled),('SCAN',self.cadence_status)):
            f=ttk.LabelFrame(topline,text=tag,style='Tile.TLabelframe');f.pack(side='left',fill='x',expand=True,padx=(0,7))
            ttk.Label(f,textvariable=var,foreground=GREEN,wraplength=270).pack(anchor='w',padx=8,pady=(2,5))
        self.workspace=ttk.Frame(self.root);self.workspace.pack(fill='both',expand=True,padx=(8,12),pady=(0,8))
        nav=tk.Frame(self.workspace,bg='#07172b',width=165,highlightbackground='#274567',highlightthickness=1)
        nav.pack(side='left',fill='y',padx=(0,9));nav.pack_propagate(False)
        tk.Label(nav,text='WORKSPACES',bg='#07172b',fg='#789ecb',font=('Segoe UI Semibold',9)).pack(anchor='w',padx=15,pady=(22,11))
        self.notebook=ttk.Notebook(self.workspace,style='Sidebar.TNotebook');self.notebook.pack(side='left',fill='both',expand=True)
        self.nav_buttons=[]
        for index,title in enumerate(('COINBASE','AI LAB','AUTO TRADER','P&L  +  EXPORTS')):
            b=tk.Button(nav,text='  '+title,anchor='w',relief='flat',borderwidth=0,
                bg='#07172b',fg='#c7dafa',activebackground='#183f6c',activeforeground='white',
                font=('Segoe UI Semibold',10),padx=10,pady=14,
                command=lambda ix=index:self.notebook.select(ix))
            b.pack(fill='x',padx=7,pady=2);self.nav_buttons.append(b)
        self.notebook.bind('<<NotebookTabChanged>>',self._update_nav)
        tk.Label(nav,text='CoinCat  •  LIVE SAFETY',bg='#07172b',fg='#83a4cb',
                 font=('Segoe UI',9)).pack(side='bottom',pady=20)

        self.tab1,self.tab2,self.tab3,self.tab4=[ttk.Frame(self.notebook,padding=6) for _ in range(4)]
        for frame,title in zip([self.tab1,self.tab2,self.tab3,self.tab4],['1  Coinbase & Authorization','2  AI Lab','3  Auto Trader','4  P&L and CSV']):self.notebook.add(frame,text=title)
        # Every notebook page has its own reachable scrolling controls.
        self.coinbase_panes=ttk.Panedwindow(self.tab1,orient='horizontal');self.coinbase_panes.pack(fill='both',expand=True)
        self.coinbase_sidebar_shell=ttk.Frame(self.coinbase_panes);self.coinbase_assets_shell=ttk.Frame(self.coinbase_panes)
        self.coinbase_panes.add(self.coinbase_sidebar_shell,weight=1);self.coinbase_panes.add(self.coinbase_assets_shell,weight=3)
        tab1_side,self.coinbase_side_scroll,_=self._scrollable_body(self.coinbase_sidebar_shell)
        tab1_body,self.coinbase_scroll,_=self._scrollable_body(self.coinbase_assets_shell)
        self.pnl_panes=ttk.Panedwindow(self.tab4,orient='horizontal');self.pnl_panes.pack(fill='both',expand=True)
        pnl_side_shell=ttk.Frame(self.pnl_panes);pnl_main_shell=ttk.Frame(self.pnl_panes)
        self.pnl_panes.add(pnl_side_shell,weight=1);self.pnl_panes.add(pnl_main_shell,weight=3)
        pnl_side,self.pnl_side_scroll,_=self._scrollable_body(pnl_side_shell)
        tab4_body,self.pnl_scroll,_=self._scrollable_body(pnl_main_shell)
        self.trader_panes=ttk.Panedwindow(self.tab3,orient='horizontal')
        self.trader_panes.pack(fill='both',expand=True)
        trader_left_shell=ttk.Frame(self.trader_panes)
        trader_right_shell=ttk.Frame(self.trader_panes)
        self.trader_panes.add(trader_left_shell,weight=1)
        self.trader_panes.add(trader_right_shell,weight=1)
        trader_left,self.trader_left_scroll,_=self._scrollable_body(trader_left_shell)
        trader_right,self.trader_right_scroll,_=self._scrollable_body(trader_right_shell)
        self.trader_left=trader_left;self.trader_right=trader_right
        self._header(tab1_side,'Coinbase Connection & Asset Control','New verified AVAILABLE spot assets auto-enroll on initial connect and later syncs, preserving existing exclusions and UNKNOWN outside-purchase tax basis. Click the Status column to ENROLL or EXCLUDE a coin. Staked, locked, and reserved quantities are excluded. Trading remains DISARMED until separately armed.')
        bar=ttk.Frame(tab1_side);bar.pack(fill='x')
        self.import_button=ttk.Button(bar,text='Import CDP Key JSON',command=self._load_key)
        self.import_button.pack(fill='x',pady=(0,6))
        self.refresh_button=ttk.Button(bar,text='Refresh live Coinbase balances',style='Primary.TButton',command=self._connect)
        self.refresh_button.pack(fill='x',pady=(0,8))
        ttk.Label(tab1_side,textvariable=self.account_label,wraplength=1150).pack(fill='x',pady=(12,4))
        self.connection_progress=ttk.Progressbar(tab1_body,mode='indeterminate',maximum=100,length=400)
        self.connection_progress.pack(fill='x',pady=(4,5))
        ttk.Label(tab1_side,textvariable=self.connection_detail,wraplength=1140).pack(fill='x',pady=2)
        ttk.Label(tab1_side,textvariable=self.connection_elapsed,foreground=MUTED).pack(fill='x',pady=(0,4))
        ttk.Label(tab1_side,textvariable=self.portfolio_sync_status,foreground=GREEN,wraplength=1050).pack(fill='x',pady=(0,3))
        ttk.Label(tab1_side,textvariable=self.portfolio_feed_status,foreground=MUTED,wraplength=1050).pack(fill='x',pady=(0,3))
        ttk.Label(tab1_side,textvariable=self.strategy_pipeline_status,foreground=MUTED,wraplength=1050).pack(fill='x',pady=(0,4))
        ttk.Label(tab1_side,textvariable=self.external_balance_warning,foreground=MUTED,wraplength=1100).pack(fill='x',pady=(0,4))
        ttk.Label(tab1_body,text='PORTFOLIO STARTING VALUE • market price, not tax cost',foreground=GREEN,
            font=('Segoe UI Semibold',11)).pack(anchor='w',pady=(5,1))
        ttk.Label(tab1_body,textvariable=self.start_snapshot_summary,wraplength=1170,
            foreground=MUTED,justify='left').pack(fill='x',pady=(0,6))
        ttk.Label(tab1_body,text='SPOT COIN CATALOG • Owned/enrolled first • other coins browse-only',foreground=GREEN,font=('Segoe UI Semibold',12)).pack(anchor='w',pady=(6,2))
        self.balance_tree=self._tree(tab1_body,['Asset','Available','Approx. USD value','Price change vs start','Approved remaining','Prior start USD/unit','Historical tax basis','Mark time (UTC)','Enrollment ▾'],height=10)
        self.balance_tree.tag_configure('price_up',foreground='#73e1a2')
        self.balance_tree.tag_configure('price_down',foreground='#ff838a')
        self.balance_tree.bind('<<TreeviewSelect>>',self._balance_selected)
        self.balance_tree.bind('<Button-1>',self._show_asset_status_dropdown,add='+')
        self.portfolio_catalog_summary=tk.StringVar(value='Authenticated spot catalog pending')
        ttk.Label(tab1_body,textvariable=self.portfolio_catalog_summary,foreground=MUTED).pack(anchor='w')
        ttk.Button(tab1_body,text='Recheck excluded pairs (Coinbase read-only)',
                   command=self._recheck_excluded_pairs).pack(anchor='w',pady=(2,5))
        arow=ttk.Frame(tab1_body);arow.pack(fill='x')
        self.approval_choice=tk.StringVar(value='ENROLLED')
        ttk.Label(arow,text='Asset enrollment: click any Status cell for ENROLLED / EXCLUDED ▾',foreground=MUTED).pack(side='left',padx=(0,18))
        ttk.Label(arow,text='Original tax purchase prices cannot be edited here.',foreground=MUTED).pack(side='left',padx=(0,8))
        snaprow=ttk.Frame(tab1_side);snaprow.pack(fill='x',pady=(4,2))
        ttk.Button(snaprow,text='Capture missing starting values (NO ORDERS)',command=self._snapshot_all).pack(fill='x',pady=(0,6))
        ttk.Button(snaprow,text='Start NEW portfolio performance period at today’s prices',command=self._capture_today_start).pack(fill='x',pady=(0,6))
        ttk.Label(tab1_side,textvariable=self._performance_period_label,wraplength=1120,foreground=GREEN).pack(fill='x',pady=(0,4))
        self.snapshot_status=tk.StringVar(value='Your CoinCat starting value is captured at the time you approve the snapshot, not backdated. Actual original purchase/tax cost stays separate; verified bot purchases stay unchanged.')
        ttk.Label(tab1_side,textvariable=self.snapshot_status,wraplength=1190,foreground=MUTED).pack(fill='x',pady=(2,4))
        # Keep the analysis table above the fold; detailed caveats live below it.
        ttk.Label(self.tab2,text='AI Lab • Learn → Compare → SHADOW',font=('Segoe UI Semibold',14),foreground=FG).pack(anchor='w',pady=(1,5))
        overview=ttk.Frame(self.tab2);overview.pack(fill='x',pady=(0,6))
        for heading,var in (('Coinbase markets',self.ai_overview_pairs),
                            ('Available research funding',self.ai_overview_funding),
                            ('Exploratory routes',self.ai_overview_exploration),
                            ('Qualified BUY',self.ai_overview_buy)):
            tile=ttk.LabelFrame(overview,text=heading)
            tile.pack(side='left',fill='x',expand=True,padx=3)
            ttk.Label(tile,textvariable=var,foreground=GREEN,
                font=('Segoe UI Semibold',10)).pack(anchor='w',padx=8,pady=(5,7))
        # A resizable 2-column research workspace. The left control pane scrolls
        # independently, so logs/diagnostics remain reachable on smaller screens.
        self.ai_panes=ttk.Panedwindow(self.tab2,orient='horizontal')
        self.ai_panes.pack(fill='both',expand=True)
        left_shell=ttk.Frame(self.ai_panes)
        right_shell=ttk.Frame(self.ai_panes)
        self.ai_panes.add(left_shell,weight=1)
        self.ai_panes.add(right_shell,weight=3)
        left_scroll=tk.Canvas(left_shell,bg=BG,highlightthickness=0,borderwidth=0)
        left_bar=ttk.Scrollbar(left_shell,orient='vertical',command=left_scroll.yview)
        left_scroll.configure(yscrollcommand=left_bar.set)
        left_bar.pack(side='right',fill='y')
        left_scroll.pack(side='left',fill='both',expand=True)
        lab_left=ttk.Frame(left_scroll,padding=(8,3,9,10))
        lab_window=left_scroll.create_window((0,0),window=lab_left,anchor='nw')
        def resize_lab_left(event=None):
            left_scroll.configure(scrollregion=left_scroll.bbox('all'))
        def fit_lab_left(event):
            left_scroll.itemconfigure(lab_window,width=max(260,event.width))
        lab_left.bind('<Configure>',resize_lab_left)
        left_scroll.bind('<Configure>',fit_lab_left)
        self.ai_left_scroll=left_scroll
        self.ai_left=lab_left
        # Research-only controls are not arming controls; no orders from buttons.
        ttk.Label(lab_left,text='AUTOMATIC LEARNING • Market data and verified results',
            foreground=GREEN,font=('Segoe UI Semibold',11)).pack(anchor='w',pady=(2,5))
        self._advanced_research=tk.BooleanVar(value=False)
        controls=ttk.Frame(lab_left)
        def toggle_manual_controls():
            if self._advanced_research.get():
                controls.pack(fill='x',pady=(0,5),after=advanced)
            else:
                controls.pack_forget()
        advanced=ttk.Checkbutton(lab_left,text='Advanced • manual research tools',
            variable=self._advanced_research,command=toggle_manual_controls)
        advanced.pack(anchor='w',pady=(0,5))
        self.warm_button=ttk.Button(controls,text='↻ Catch up history',style='Action.TButton',command=self._start_history)
        self.warm_button.grid(row=0,column=0,sticky='ew',padx=(0,4),pady=2)
        self.scan_button=ttk.Button(controls,text='Scan quotes (no orders)',style='Primary.TButton',command=self._scan_now)
        self.scan_button.grid(row=0,column=1,sticky='ew',pady=2)
        # CUDA learning starts automatically at first safe connected idle window.
        controls.columnconfigure(0,weight=1);controls.columnconfigure(1,weight=1)
        ttk.Label(lab_left,text='Market scan activity',foreground=GREEN,font=('Segoe UI Semibold',10)).pack(fill='x',pady=(9,2))
        ttk.Label(lab_left,textvariable=self.cadence_status,foreground=MUTED,wraplength=460).pack(fill='x',pady=(0,4))
        ttk.Label(lab_left,textvariable=self.lab_activity,foreground=GREEN,wraplength=405).pack(anchor='w',fill='x',pady=(6,2))
        ttk.Label(lab_left,textvariable=self.strategy_pipeline_status,foreground='#8aceff',wraplength=460).pack(anchor='w',fill='x',pady=(1,4))
        ttk.Label(lab_left,textvariable=self.fast_research_status,foreground='#41c9df',wraplength=465,
                  justify='left').pack(anchor='w',fill='x',pady=(0,5))
        self.lab_progress=ttk.Progressbar(lab_left,mode='indeterminate')
        self.lab_progress.pack(fill='x',pady=(1,4))
        # All telemetry widgets stay alive for the existing callbacks, but
        # are hidden until Advanced is explicitly expanded. This removes
        # repeated status prose without removing any research process.
        self._lab_technical_open=tk.BooleanVar(value=False)
        lab_technical=ttk.Frame(lab_left)
        def toggle_lab_technical():
            if self._lab_technical_open.get():
                lab_technical.pack(fill='both',expand=True,after=technical_toggle,pady=(4,6))
            else:
                lab_technical.pack_forget()
        technical_toggle=ttk.Checkbutton(lab_left,text='Advanced • research details, raw tickers and logs',
            variable=self._lab_technical_open,command=toggle_lab_technical)
        technical_toggle.pack(anchor='w',pady=(4,2))
        for var in (self.lab_heartbeat,self.lab_history,self.storage_status,self.universe_status):
            ttk.Label(lab_technical,textvariable=var,foreground=MUTED,wraplength=405,justify='left').pack(fill='x',anchor='w',pady=2)
        self.universe_gauge=ttk.Progressbar(lab_technical,maximum=100,mode='determinate')
        self.universe_gauge.pack(fill='x',pady=(0,5))
        ttk.Label(lab_technical,textvariable=self.gpu_status,foreground=MUTED,wraplength=405).pack(fill='x',anchor='w',pady=(2,5))
        ttk.Label(lab_technical,textvariable=self.execution_learning,foreground=MUTED,wraplength=405).pack(fill='x',anchor='w',pady=(2,5))
        meter=ttk.LabelFrame(lab_technical,text='Additional data-collection coverage • not a win probability')
        meter.pack(fill='x',pady=(3,7))
        glass_row=ttk.Frame(meter);glass_row.pack(fill='x',padx=5,pady=5)
        self.research_glass=tk.Canvas(glass_row,height=94,width=90,bg=BG,highlightthickness=0)
        self.research_glass.pack(side='left',padx=(0,8))
        meter_labels=ttk.Frame(glass_row);meter_labels.pack(side='left',fill='both',expand=True)
        ttk.Label(meter_labels,textvariable=self.readiness_status,foreground=GREEN,wraplength=290).pack(anchor='w')
        ttk.Label(meter_labels,textvariable=self.directional_status,wraplength=290).pack(anchor='w',pady=(4,0))
        self.research_gauge=ttk.Progressbar(meter_labels,maximum=100,mode='determinate')
        self.research_gauge.pack(fill='x',pady=(5,0))
        # Old Capacity Advisor controls and popup removed from UI. The
        # underlying broker hard risk caps / explicit permissions are retained.
        evidence=ttk.LabelFrame(lab_left,text='Learning progress • observations vs tested outcomes')
        evidence.pack(fill='x',pady=(3,7))
        ttk.Label(evidence,text='Bars show observation coverage or check completion, NOT win rates, forecasts or permissions.',
                  foreground=MUTED,wraplength=390).pack(anchor='w',padx=7,pady=(6,4))
        self.lab_evidence_bars={}
        for key,title in (('catalog','Full-spot discovery'),('quotes','Deep study / live quotes'),
                          ('forward','Forward BUY + SELL outcomes'),
                          ('relative','USD HOLD/SWITCH held-out test'),
                          ('fees','Authenticated trading fees'),('gpu','Neural model validation (optional)')):
            ttk.Label(evidence,text=title,foreground=GREEN).pack(anchor='w',padx=7,pady=(5,0))
            gauge=ttk.Progressbar(evidence,maximum=100,mode='determinate',value=0)
            gauge.pack(fill='x',padx=7,pady=(1,0))
            state=tk.StringVar(value='WAIT • evidence not yet verified')
            ttk.Label(evidence,textvariable=state,foreground=MUTED,wraplength=395).pack(anchor='w',padx=7,pady=(1,2))
            self.lab_evidence_bars[key]=(gauge,state)
        # AI budget advisory now lives directly beneath Auto Trader's editable
        # trading budget on Tab 3; it remains read-only and cannot modify limits.
        self.research_pct=0
        ttk.Label(lab_technical,text='LIVE TICKERS • information only',foreground=GREEN,
            font=('Segoe UI Semibold',10)).pack(anchor='w',pady=(8,1))
        self.stream_status=tk.StringVar(value='All-catalog WebSocket ticker: waiting for authenticated Coinbase products; no order prices')
        ttk.Label(lab_technical,textvariable=self.stream_status,wraplength=405).pack(fill='x',anchor='w')
        self.stream_market_search=tk.StringVar(value='')
        entry=ttk.Entry(lab_technical,textvariable=self.stream_market_search)
        entry.pack(fill='x',pady=(3,4))
        entry.insert(0,'')
        ttk.Label(lab_technical,text='Filter ALL subscribed pair IDs (e.g. -BTC), not just the current deep-study subset',foreground=MUTED,wraplength=405).pack(anchor='w')
        self.ticker_tree=self._tree(lab_technical,['Spot pair','Last matched price','Seconds since trade','Stream status'],height=6)
        ttk.Label(lab_technical,text='WebSocket ticker updates are informative only. Authenticated bid/ask and broker checks control real orders.',foreground=MUTED,wraplength=405).pack(anchor='w',fill='x')
        ttk.Label(lab_technical,text='RESEARCH ACTIVITY LOG',foreground=GREEN,
            font=('Segoe UI Semibold',10)).pack(anchor='w',pady=(10,2))
        self.logbox=tk.Text(lab_technical,height=10,bg=CARD,fg=FG,insertbackground=FG,font=('Consolas',9),wrap='word')
        self.logbox.pack(fill='both',expand=True)
        self.logbox.configure(state='disabled')
        # RIGHT: separate scroll for the entire pair/outcomes column, not merely a table.
        right_body,self.ai_right_scroll,_=self._scrollable_body(right_shell)
        self.ai_right=right_body
        ttk.Label(right_body,text='MARKET ANALYSIS  •  BUY / SELL / HOLD / ROTATE',foreground=GREEN,
            font=('Segoe UI Semibold',12)).pack(anchor='w',padx=8,pady=(4,2))
        self.direction_count=tk.StringVar(value='Awaiting scan • BUY and SELL research on every pair; trading requires authorized holdings')
        ttk.Label(right_body,textvariable=self.direction_count,wraplength=890,foreground=MUTED).pack(fill='x',padx=8,pady=(1,2))
        ttk.Label(right_body,textvariable=self.research_label,wraplength=890).pack(fill='x',padx=8,pady=(1,4))
        ttk.Label(right_body,textvariable=self.ai_learning_chain,foreground='#8aceff',wraplength=890).pack(fill='x',padx=8,pady=(1,4))
        filter_row=ttk.Frame(right_body);filter_row.pack(fill='x',padx=8,pady=(0,4))
        ttk.Label(filter_row,text='Search focused markets:').pack(side='left',padx=(0,6))
        self.market_search_entry=ttk.Entry(filter_row,textvariable=self.market_search,width=24)
        self.market_search_entry.pack(side='left',fill='x',expand=True)
        ttk.Button(filter_row,text='Clear',command=lambda:self.market_search.set('')).pack(side='left',padx=(5,0))
        self.market_search.trace_add('write',lambda *_:self._filter_research_rows())
        ttk.Label(right_body,textvariable=self.target_preview_status,foreground=GREEN,wraplength=880).pack(fill='x',padx=8,pady=(1,3))
        self.signal_tree=self._tree(right_body,
            ['Market','BUY assessment','SELL assessment','Live bid','Live ask','Quotes','SELL-vs-HOLD 30m %','Reason / blocker'],height=20,hscroll=True)
        self.signal_tree.configure(style='ResearchDense.Treeview')
        self._signal_reasons={}
        self.signal_tree._coincat_full_cell_text=lambda iid,index:self._signal_reasons.get(self.signal_tree.item(iid,'values')[0]) if index==len(self.signal_tree['columns'])-1 else None
        self.signal_detail=tk.StringVar(value='Select a market for the full BUY / SELL explanation and exact blockers.')
        self.signal_tree.bind('<<TreeviewSelect>>',self._show_selected_signal_reason)
        self._all_signal_rows=[]
        widths={'Market':100,'BUY assessment':100,'SELL assessment':166,'Live bid':92,'Live ask':92,
                'Quotes':65,'SELL-vs-HOLD 30m %':125,'Reason / blocker':200}
        for col,width in widths.items():self.signal_tree.column(col,width=width,minwidth=65,stretch=(col=='Reason / blocker'))
        self.signal_decision_panel=tk.Frame(right_body,bg='#174a62',highlightbackground='#4fc2e5',highlightthickness=2)
        self.signal_decision_panel.pack(fill='x',padx=8,pady=(7,8))
        tk.Label(self.signal_decision_panel,text='SELECTED MARKET • FULL DECISION / BLOCKER',
            bg='#174a62',fg='#ffffff',font=('Segoe UI Semibold',11)).pack(anchor='w',padx=11,pady=(8,3))
        self.signal_decision_label=tk.Label(self.signal_decision_panel,textvariable=self.signal_detail,
            bg='#174a62',fg='#ffffff',font=('Segoe UI Semibold',11),
            anchor='w',justify='left',wraplength=900,padx=10,pady=9)
        self.signal_decision_label.pack(fill='x')
        self._lab_outcomes_open=tk.BooleanVar(value=False)
        outcome_details=ttk.Frame(right_body)
        def toggle_outcome_details():
            if self._lab_outcomes_open.get():outcome_details.pack(fill='both',expand=True,after=outcome_toggle,pady=5)
            else:outcome_details.pack_forget()
        outcome_toggle=ttk.Checkbutton(right_body,text='Advanced • individual forward outcomes and research notes',
            variable=self._lab_outcomes_open,command=toggle_outcome_details)
        outcome_toggle.pack(anchor='w',padx=8,pady=(3,2))
        ttk.Label(outcome_details,text='Forward BUY / SELL / HOLD outcomes • genuine later market quotes only',foreground=GREEN,
            font=('Segoe UI Semibold',10)).pack(anchor='w',padx=8,pady=(3,2))
        self.direction_tree=self._tree(outcome_details,
            ['Pair / action','Confirmed labels','BUY net 30m %','SELL→rebuy 30m %','HOLD 30m %','Research judgment'],height=5,hscroll=True)
        for col,width in {'Pair / action':205,'Confirmed labels':115,'BUY net 30m %':120,
                         'SELL→rebuy 30m %':155,'HOLD 30m %':112,'Research judgment':280}.items():
            self.direction_tree.column(col,width=width,minwidth=85,stretch=(col=='Research judgment'))
        lab_notes=ttk.LabelFrame(outcome_details,text='Research rules and limitations')
        lab_notes.pack(fill='x',padx=8,pady=(14,8))
        ttk.Label(lab_notes,textvariable=self.ai_quote_coverage,foreground=MUTED,wraplength=1050).pack(fill='x',padx=8,pady=(6,3))
        ttk.Label(lab_notes,textvariable=self.portfolio_feed_status,foreground=GREEN,wraplength=1050).pack(fill='x',padx=8,pady=3)
        for note in (
            'PORTFOLIO OBJECTIVE • Seek net USD portfolio-value improvement, not loyalty to a particular coin. Research is neither a profit forecast nor authority to trade.',
            'Eligible Coinbase spot pairs (including crypto/crypto) are requested for public WebSocket trade-price monitoring. Adaptive 48–128 focused markets get deeper REST bid/ask and forward study. Rare markets may have no recent trade ticks.',
            'BUY spends the quote asset and SELL receives it. ETH-BTC and BTC-ETH are different products; only listed Coinbase products qualify. Public tickers and historical observations cannot authorize orders.',
            'ROTATE and cross-quoted decisions remain READ-ONLY until verified multi-currency accounting and a separately ARMED broker are available.'):
            ttk.Label(lab_notes,text=note,foreground=MUTED,wraplength=1050,justify='left').pack(fill='x',padx=8,pady=(2,5))
        ttk.Label(trader_left,text='Auto Trader • Coinbase Orders',font=('Segoe UI Semibold',14),foreground=FG).pack(anchor='w',pady=(1,5))
        # Actual illuminated switch: interactive, never bypasses typed ARM preflight.
        arm_top=tk.Frame(trader_left,bg='#102036',highlightbackground='#2d567c',highlightthickness=1)
        arm_top.pack(fill='x',pady=(3,7))
        self.arm_switch=tk.Canvas(arm_top,width=183,height=260,bg='#102036',
                                  highlightthickness=0,takefocus=1,cursor='hand2')
        self.arm_switch.pack(side='left',padx=(9,12),pady=7)
        self.arm_switch.bind('<Button-1>',self._arm_switch_click)
        self.arm_switch.bind('<Return>',self._arm_switch_keyboard)
        self.arm_switch.bind('<space>',self._arm_switch_keyboard)
        switch_side=tk.Frame(arm_top,bg='#102036')
        switch_side.pack(side='left',fill='both',expand=True,padx=(4,10),pady=12)
        tk.Label(switch_side,text='LIVE TRADING',bg='#102036',fg='#cde2fc',
                 font=('Segoe UI Semibold',15)).pack(anchor='w',pady=(10,6))
        tk.Label(switch_side,textvariable=self.status,bg='#102036',fg='#a9c8f1',
                 font=('Segoe UI',10),wraplength=205,justify='left').pack(anchor='w',pady=(2,14))
        tk.Button(switch_side,text='EMERGENCY STOP',command=self._stop,bg='#a4384b',fg='white',
                  activebackground='#d24355',activeforeground='white',font=('Segoe UI Semibold',11),
                  padx=12,pady=10,borderwidth=0).pack(anchor='w',fill='x',pady=(8,6))
        ttk.Button(switch_side,text='Release STOP',command=self._release).pack(anchor='w',fill='x')
        self.shadow_mode_button=ttk.Button(switch_side,text='ARM SHADOW (NO REAL ORDERS)',
              command=self._toggle_shadow_arm)
        self.shadow_mode_button.pack(anchor='w',fill='x',pady=(14,4))
        ttk.Label(switch_side,textvariable=self.shadow_mode_status,wraplength=230,
                  foreground='#8aceff').pack(anchor='w',fill='x')
        self.experimental_shadow_button=ttk.Button(switch_side,
            text='ARM EXPERIMENT (UNVALIDATED • NO REAL ORDERS)',
            command=self._toggle_experimental_shadow)
        self.experimental_shadow_button.pack(anchor='w',fill='x',pady=(12,4))
        ttk.Label(switch_side,textvariable=self.experimental_shadow_status,
            foreground='#e4b16b',wraplength=230).pack(anchor='w',fill='x')
        self._paint_arm_switch()
        params=ttk.LabelFrame(trader_left,text='SHADOW budget source • FULL AVAILABLE or MANUAL • LIVE remains BLOCKED')
        params.pack(fill='x',pady=6)
        for i,(label,var) in enumerate(zip(
            ['Maximum per order $','Maximum daily buys $','Maximum added exposure $',
             'Maximum BUY attempts / rolling 24h'],self.limits+[self.max_attempts_entry])):
            ttk.Label(params,text=label).grid(row=i,column=0,sticky='w',padx=8,pady=4)
            ttk.Entry(params,textvariable=var,width=13).grid(row=i,column=1,sticky='ew',pady=4,padx=(0,12))
        params.columnconfigure(1,weight=1)
        ttk.Radiobutton(params,text='Use Full Available Enrolled Portfolio (SHADOW only)',
                        variable=self.shadow_budget_mode,value='FULL_AVAILABLE').grid(
                        row=4,column=0,columnspan=2,sticky='w',padx=8,pady=(4,0))
        ttk.Radiobutton(params,text='Use my manual dollar limits',
                        variable=self.shadow_budget_mode,value='MANUAL').grid(
                        row=5,column=0,columnspan=2,sticky='w',padx=8)
        ttk.Button(params,text='Apply SHADOW budget mode',command=self._apply_manual_budgets).grid(
            row=6,column=0,columnspan=2,sticky='w',padx=8,pady=(5,2))
        ttk.Label(params,textvariable=self.manual_budget_status,wraplength=420,foreground=MUTED,
                  justify='left').grid(row=7,column=0,columnspan=2,sticky='w',padx=8,pady=(2,6))
        # Adjacent to the actual broker budget for quick, side-by-side review.
        # This StringVar is display-only; no trace, command, or ARM side effect.
        advisor=ttk.LabelFrame(trader_left,
            text='AI LAB • TESTED RESULTS AND SUGGESTED TRADE SIZE',
            style='Tile.TLabelframe')
        advisor.pack(fill='x',pady=(1,9))
        ttk.Label(advisor,textvariable=self.ai_budget_preview,wraplength=415,
                  foreground='#8aceff',justify='left').pack(fill='x',padx=10,pady=9)
        ttk.Label(advisor,textvariable=self.pipeline_status,wraplength=415,foreground='#8aceff',justify='left').pack(fill='x',padx=10,pady=(0,7))
        ttk.Label(advisor,textvariable=self.reserve_advisory,wraplength=415,foreground=MUTED,justify='left').pack(fill='x',padx=10,pady=(0,7))
        ttk.Label(advisor,text='Suggestions never adjust broker settings or ARM trading.',
                  foreground=MUTED,wraplength=400).pack(fill='x',padx=10,pady=(0,7))
        advantage=ttk.LabelFrame(trader_left,text='Projected net portfolio USD advantage • research preference')
        advantage.pack(fill='x',pady=(5,6))
        ttk.Label(advantage,text='SHADOW minimum after-cost USD advantage vs HOLD').pack(side='left',padx=6,pady=6)
        ttk.Radiobutton(advantage,text='Manual',variable=self.switch_floor_mode,
                        value='MANUAL',command=self._set_shadow_floor_mode).pack(side='left',padx=3)
        ttk.Radiobutton(advantage,text='AI suggested',variable=self.switch_floor_mode,
                        value='AI_SUGGESTED',command=self._set_shadow_floor_mode).pack(side='left',padx=3)
        ttk.Entry(advantage,textvariable=self.switch_minimum_entry,width=8).pack(side='left',padx=4)
        ttk.Button(advantage,text='Apply',command=self._set_switch_minimum).pack(side='left',padx=4)
        ttk.Label(trader_left,textvariable=self.switch_minimum_status,
                  foreground=MUTED,wraplength=415).pack(fill='x',pady=(0,5))
        advrow=ttk.Frame(trader_left);advrow.pack(fill='x',pady=(5,4))
        self.advanced_button=ttk.Button(advrow,text='Advanced settings & research details ▸',command=self._toggle_trader_advanced)
        ttk.Label(trader_left,text='Verified fee learning: Coinbase spot fee tier refreshes hourly; account tier is NOT a per-pair quote.',
                  wraplength=600,foreground=MUTED).pack(fill='x',pady=(3,5))
        self.advanced_button.pack(anchor='w')
        self.advanced_body=ttk.Frame(trader_left)
        params2=ttk.LabelFrame(self.advanced_body,text='Ordinary SELL profit & daily risk policy')
        params2.pack(fill='x',pady=5)
        ttk.Label(params2,text='Minimum net profit / ordinary SELL $').grid(row=0,column=0,sticky='w',padx=6,pady=4)
        ttk.Entry(params2,textvariable=self.target_entry,width=8).grid(row=0,column=1,sticky='w',padx=6)
        ttk.Label(params2,text='Daily confirmed realized-loss BUY pause $').grid(row=1,column=0,sticky='w',padx=6,pady=4)
        ttk.Entry(params2,textvariable=self.daily_loss_limit_entry,width=12).grid(row=1,column=1,sticky='w',padx=6)
        ttk.Label(params2,text='Range $0.01–$10,000; default $5. This does not replace the portfolio loss floor.',
                  foreground=MUTED,wraplength=440).grid(row=2,column=0,columnspan=2,sticky='w',padx=6,pady=3)
        for v,shade in ((self.target_preview_status,GREEN),(self.loss_policy_message,MUTED),
                        (self.portfolio_feed_status,MUTED),(self.risk_message,MUTED),
                        (self.trader_label,MUTED),(self.external_balance_warning,MUTED),
                        (self.trade_frequency_status,MUTED)):
            ttk.Label(self.advanced_body,textvariable=v,wraplength=630,foreground=shade).pack(fill='x',pady=3)
        ttk.Button(self.advanced_body,text='Recheck LIVE readiness (NO ORDERS)',
                   command=self._update_v30_readiness).pack(anchor='w',pady=5)
        ttk.Label(trader_right,text='LIVE TRADING OVERVIEW',font=('Segoe UI Semibold',14),foreground='#b5d6ff').pack(anchor='w',pady=(1,8))
        overview_cards=tk.Frame(trader_right,bg=BG);overview_cards.pack(fill='x',pady=(0,11))
        self.today_net_display=tk.StringVar(value='$0.00')
        self.pending_count_display=tk.StringVar(value='0')
        for label,var in (("TODAY'S REALIZED P&L",self.today_net_display),
                          ('PENDING ORDERS',self.pending_count_display)):
            tile=tk.Frame(overview_cards,bg='#112640',highlightbackground='#315a81',highlightthickness=1)
            tile.pack(side='left',fill='both',expand=True,padx=(0,7))
            tk.Label(tile,text=label,bg='#112640',fg='#97bcdf',font=('Segoe UI Semibold',9)).pack(anchor='w',padx=12,pady=(14,4))
            tk.Label(tile,textvariable=var,bg='#112640',fg='#ffffff',font=('Segoe UI Semibold',22)).pack(anchor='w',padx=12,pady=(0,16))
        ttk.Label(trader_right,text='SELL / HOLD and verified portfolio research',font=('Segoe UI Semibold',11),
                  foreground='#79d6d7').pack(anchor='w',pady=(3,4))
        ttk.Label(trader_right,textvariable=self.sell_status,foreground=MUTED).pack(anchor='w')
        self.sell_tree=self._tree(trader_right,['Asset / pair','Live bid','Verified sell value $','SELL / HOLD status','Decision / blocker'],height=10,hscroll=True)
        ttk.Label(trader_right,textvariable=self.full_exit_status,wraplength=740,foreground=MUTED).pack(anchor='w',pady=(3,6))
        self.full_exit_tree=self._tree(trader_right,['Held asset','Fresh Coinbase pair','Verified liquid qty','Gross USD before fees','Order-cap slices (estimate)','Research state / blocker'],height=9,hscroll=True)
        ttk.Label(trader_right,text='AI LAB → AUTO TRADER • CONTINUOUS SHADOW ROTATION HANDOFF',foreground=GREEN).pack(anchor='w',pady=(7,0))
        ttk.Label(trader_right,textvariable=self.strategy_pipeline_status,foreground='#8aceff',wraplength=740).pack(anchor='w',pady=(1,5))
        ttk.Label(trader_right,textvariable=self.rotation_auto_status,wraplength=740,foreground=MUTED).pack(anchor='w',pady=(2,4))
        self.rotation_auto_tree=self._tree(trader_right,
            ['Approved funding','AI destination','Real Coinbase route','Capped USD mark change','Decision / blocker'],height=9,hscroll=True)
        self._route_decision_details={}
        self.rotation_auto_tree._coincat_full_cell_text=(
            lambda iid,column: self._route_decision_details.get(iid)
            if column==4 else None)
        ttk.Label(trader_right,text='RECENT REAL COINBASE ORDERS',foreground=GREEN).pack(anchor='w',pady=(7,0))
        self.order_tree=self._tree(trader_right,['Time UTC','Pair','Side','State','Coinbase order ID'],height=7,hscroll=True)
        ttk.Label(trader_right,text='CONFIRMED EXCHANGE FILLS • base quantity, fill USD value and actual trading fee',foreground=GREEN).pack(anchor='w',pady=(7,0))
        self.fill_tree=self._tree(trader_right,['Time UTC','Pair','Side','Base quantity','Price','Gross quote','Actual fee'],height=8,hscroll=True)
        maintenance=ttk.LabelFrame(trader_right,text='ORDER MAINTENANCE • On demand')
        maintenance.pack(fill='x',pady=(14,8))
        ttk.Button(maintenance,text='Sync pending order fills NOW (NO NEW ORDERS)',
                   command=self._sync_order_now).pack(anchor='w',fill='x',padx=7,pady=(7,3))
        ttk.Button(maintenance,text='Verify latest FILLED Coinbase order (READ ONLY)',
                   command=self._verify_last_order_now).pack(anchor='w',fill='x',padx=7,pady=(0,5))
        ttk.Label(maintenance,textvariable=self.fill_sync_status,wraplength=660,foreground=MUTED).pack(fill='x',padx=7,pady=(2,7))
        notes=ttk.LabelFrame(trader_right,text='ORDER SAFETY • Important information')
        notes.pack(fill='x',pady=(12,8))
        for paragraph in (
            'Confirmed fills update independently of AI market scans. Pending orders are checked about every 5 seconds while idle; uncertain results stop new orders.',
            'AI Lab evaluates authorized SELL/HOLD possibilities. All BUY/SELL/ROTATE suggestions remain shadow-only unless the separate live broker independently validates and is ARMED.',
            'One all-spot research/broker-review flow is active. Production order submission is disabled for EVERY spot quote until unified settlement and recovery are certified.',
            'CoinCat must stay running for its software-managed safeguards. STOP or a connection failure does NOT guarantee cancellation of outstanding Coinbase orders.'):
            ttk.Label(notes,text=paragraph,wraplength=780,foreground=MUTED).pack(fill='x',padx=8,pady=4)
        ttk.Label(pnl_side,text='Profit & Loss • Verified Coinbase fills',font=('Segoe UI Semibold',14),foreground=FG).pack(anchor='w',pady=(1,7))
        self.totals=tk.StringVar(value='No confirmed CoinCat fills yet')
        ttk.Label(pnl_side,textvariable=self.totals,wraplength=340,justify='left').pack(anchor='w',fill='x',pady=(2,10))
        breakbox=tk.Frame(pnl_side,bg='#132b44',highlightbackground='#3b6a92',highlightthickness=1)
        breakbox.pack(fill='x',pady=(3,9))
        tk.Label(breakbox,text='◉  SNOWBALL • COST & USD ADVANTAGE',bg='#132b44',fg='#8dcdff',
                 font=('Segoe UI Semibold',12)).pack(anchor='w',padx=10,pady=(10,4))
        tk.Label(breakbox,textvariable=self.break_even_preview,bg='#132b44',fg='#e9f4ff',
                 font=('Segoe UI',10),wraplength=340,justify='left').pack(anchor='w',padx=10,pady=(0,10))

        ttk.Button(pnl_side,text='Inspect personal / bot acquisition lots (READ ONLY)',command=self._view_inventory_lots).pack(fill='x',pady=(0,6))
        ttk.Button(pnl_side,text='About CoinCat • hobby & risk notice',command=self._show_hobby_notice).pack(fill='x',pady=(0,12))
        ttk.Button(pnl_side,text='About / Data storage (v60)',command=self._show_uninstall_options).pack(fill='x',pady=(0,9))
        ttk.Label(tab4_body,text='CONFIRMED SELL OUTCOMES • Profit / Loss',foreground=GREEN,font=('Segoe UI Semibold',12)).pack(anchor='w',pady=(4,5))
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            self.fig=Figure(figsize=(8,3.1),dpi=92,facecolor=BG)
            self.ax=self.fig.add_subplot(111);self.canvas=FigureCanvasTkAgg(self.fig,master=tab4_body)
            self.canvas.get_tk_widget().pack(fill='both',expand=True)
        except Exception:self.fig=None;self._text(tab4_body,'Matplotlib chart unavailable; install requirements.txt').pack()
        datebox=ttk.LabelFrame(pnl_side,text='EXPORT PERIOD • Inclusive UTC dates')
        datebox.pack(fill='x',pady=(3,6))
        today=datetime.now(timezone.utc).date()
        self.export_start_date=tk.StringVar(value=f'{today.year}-01-01')
        self.export_end_date=tk.StringVar(value=today.isoformat())
        date_row=ttk.Frame(datebox);date_row.pack(fill='x',padx=6,pady=6)
        ttk.Label(date_row,text='From').pack(side='left')
        ttk.Entry(date_row,textvariable=self.export_start_date,width=12).pack(side='left',padx=(5,12))
        ttk.Label(date_row,text='Through').pack(side='left')
        ttk.Entry(date_row,textvariable=self.export_end_date,width=12).pack(side='left',padx=5)
        diagnostics=ttk.LabelFrame(pnl_side,text='DIAGNOSTICS • Read-only support export')
        diagnostics.pack(fill='x',pady=(3,10))
        export_row=ttk.Frame(diagnostics);export_row.pack(fill='x',padx=6,pady=(8,6))
        self.complete_export_button=ttk.Button(export_row,text='Export Complete Diagnostics',
                   command=self._export_complete_diagnostics)
        self.complete_export_button.pack(fill='x',expand=True)
        self.diagnostic_export_progress=tk.DoubleVar(value=0)
        self.diagnostic_export_status=tk.StringVar(value='Ready to export all diagnostic sections (read-only).')
        self.diagnostic_export_meter=ttk.Progressbar(diagnostics,mode='determinate',maximum=18,
                            variable=self.diagnostic_export_progress,style='HighContrast.Horizontal.TProgressbar')
        self.diagnostic_export_meter.pack(fill='x',padx=7,pady=(1,5))
        ttk.Label(diagnostics,textvariable=self.diagnostic_export_status,
                  wraplength=370,foreground=FG).pack(fill='x',padx=7,pady=(0,8))

        actions=ttk.Frame(pnl_side);actions.pack(fill='x',pady=4)
        ttk.Button(actions,text='Export P&L for Excel • CSV (selected dates)',command=self._export_pnl).pack(fill='x',pady=4)
        ttk.Button(actions,text='Export tax-support records • CSV (selected dates)',command=self._export_tax_support).pack(fill='x',pady=4)
        ttk.Button(actions,text='Copy tax-preparation handoff for ChatGPT',command=self._tax_handoff).pack(fill='x',pady=4)
        ttk.Button(actions,text='Export verified acquisition/disposal lots',command=self._export_lot_details).pack(fill='x',pady=4)
        self.tax_archive_warning=tk.StringVar(value='Original tax cost may be UNKNOWN. No tax returns or forms are generated.')
        ttk.Label(pnl_side,textvariable=self.tax_archive_warning,wraplength=390,foreground=MUTED).pack(fill='x',pady=(5,9))
        extras=ttk.LabelFrame(pnl_side,text='OTHER RAW RECORDS • Optional backups')
        extras.pack(fill='x',pady=(12,7))
        for name,fn in (
            ('Orders CSV',lambda:self._export('orders')),
            ('Fills CSV',lambda:self._export('fills')),
            ('Enrollment snapshots CSV',lambda:self._export('snapshots')),
            ('Forward market quotes CSV',self._export_quotes)):
            ttk.Button(extras,text=name,command=fn).pack(fill='x',padx=5,pady=2)
        ttk.Label(tab4_body,text='PORTFOLIO HOLDINGS • available liquid quantities • tax basis may be unknown',foreground=GREEN).pack(anchor='w',pady=(5,0))
        ttk.Label(tab4_body,textvariable=self.strategy_pipeline_status,foreground=MUTED,wraplength=1090).pack(anchor='w',pady=(2,5))
        ttk.Label(tab4_body,textvariable=self.experimental_shadow_status,foreground='#e4b16b',wraplength=1090).pack(anchor='w',pady=(2,5))
        ttk.Label(tab4_body,textvariable=self.experimental_pnl_status,foreground='#e4b16b',wraplength=1090).pack(anchor='w',pady=(2,5))
        self.pnl_holdings_tree=self._tree(tab4_body,['Asset','Available','Approx. current value','Enrolled','Historical tax basis status'],height=8,hscroll=True)
        disk_box=ttk.LabelFrame(tab4_body,text='STORAGE HEALTH • active budgets, financial data protected')
        disk_box.pack(fill='x',pady=(5,7))
        ttk.Label(disk_box,textvariable=self.storage_health_status,foreground=GREEN,wraplength=1090,justify='left').pack(anchor='w',padx=8,pady=7)
        ttk.Label(disk_box,text='Market research has a shared 1 GiB cap across research SQLite databases. The ACTIVE financial ledger retains all fills/tax lots and STILL fails closed at 128 MB; a tax-export warning never DISARMS by itself. Backups do NOT free active ledger space.',
                  wraplength=1050,foreground=MUTED).pack(fill='x',padx=8,pady=(0,5))
        ttk.Button(disk_box,text='Export VERIFIED financial SQLite archive • NO ORDERS',command=self._verified_archive).pack(anchor='w',padx=8,pady=(1,9))
        self._refresh_trees()

    def _show_uninstall_options(self):
        """Source distribution has no Windows installer or uninstaller."""
        messagebox.showinfo('About CoinCat v60 source edition',
            'CoinCat v60 runs from source and uses its private .venv.\n\n'
            'Your private credentials, research and financial ledgers live separately at '
            '%APPDATA%\\CoinCatV70.\n\n'
            'Do NOT delete this private data when removing an old program folder. '
            'Back it up and verify it first. No uninstall action is provided.')

    def _show_hobby_notice(self):
        """Information only; no acknowledgment gate; never controls trading."""
        message=("CoinCat is my personal hobby and experimental software for learning about "
            "cryptocurrency markets, programming, and AI research. I intend to use it "
            "lawfully and in accordance with exchange rules. I understand trading can "
            "lose money through volatility, fees, spread, slippage, outages, and software "
            "errors. Any financial gain is incidental to this educational experiment "
            "and is not guaranteed. Real transactions may create tax and recordkeeping "
            "obligations. This statement does not waive any legal or tax requirements. "
            "CoinCat strategy research takes conceptual inspiration from public educational and "
            "open-source documentation; the project-specific acknowledgments and license policy "
            "are in THIRD_PARTY_ATTRIBUTION_AND_RISK.md. No external trading-bot source was "
            "copied into this v60.7 patch. Autonomous live operation remains unavailable until "
            "production verification and an explicit session ARM with operator-defined limits.")
        win=tk.Toplevel(self.root);win.title('About CoinCat • Personal hobby & risk notice')
        win.geometry('610x300');win.configure(bg=BG)
        ttk.Label(win,text='COINCAT • PERSONAL HOBBY & RISK INFORMATION',foreground=GREEN,
                  font=('Segoe UI Semibold',13)).pack(fill='x',padx=18,pady=(18,8))
        ttk.Label(win,text=message,wraplength=555,justify='left').pack(fill='both',expand=True,padx=18,pady=4)
        ttk.Button(win,text='Close',command=win.destroy).pack(anchor='e',padx=18,pady=(5,14))

    def _view_inventory_lots(self):
        """Show preserved opening holdings separately from later verified fills."""
        rows=self.ledger.inventory_lots()
        win=tk.Toplevel(self.root);win.title('CoinCat v60 • Verified inventory lots • NO ORDERS')
        win.geometry('1140x530');win.configure(bg=BG)
        ttk.Label(win,text='Existing approved inventory and confirmed Coinbase buys are separate lots. '
            'A blank original tax cost is UNKNOWN; a market starting value is NOT original tax basis.',
            wraplength=1100).pack(fill='x',padx=12,pady=(10,7))
        content=ttk.Frame(win);content.pack(fill='both',expand=True,padx=12,pady=5)
        fields=['Asset','Origin','Opened UTC','Original quantity','Remaining quantity','CoinCat performance / unit','Tax cost / unit','Quote']
        tree=ttk.Treeview(content,columns=fields,show='headings')
        widths=[90,180,170,130,135,170,145,70]
        for label,width in zip(fields,widths):
            tree.heading(label,text=label);tree.column(label,width=width,stretch=True,minwidth=60)
        sy=ttk.Scrollbar(content,orient='vertical',command=tree.yview)
        sx=ttk.Scrollbar(content,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tree.grid(row=0,column=0,sticky='nsew');sy.grid(row=0,column=1,sticky='ns');sx.grid(row=1,column=0,sticky='ew')
        content.columnconfigure(0,weight=1);content.rowconfigure(0,weight=1)
        add_tree_tips(tree)
        for r in rows:
            utc=datetime.fromtimestamp(int(r['opened_at']),timezone.utc).strftime('%Y-%m-%d %H:%M')
            tree.insert('','end',values=(r['asset'],r['source'],utc,r['initial_qty'],r['remaining_qty'],
                r['performance_unit_quote'] or 'NOT VERIFIED',r['tax_unit_quote'] or 'UNKNOWN',r['quote_ccy']))
        ttk.Label(win,text=f'{len(rows)} acquisition lots • Read-only • Explicit SELL orders still require broker checks and confirmed Coinbase fills.').pack(anchor='w',padx=12,pady=(5,6))
        ttk.Button(win,text='Close • no orders',command=win.destroy).pack(pady=(0,10))

    def _set_shadow_floor_mode(self):
        # Preference is local RESEARCH configuration only, not a broker setting.
        mode=self.switch_floor_mode.get()
        if mode not in ('MANUAL','AI_SUGGESTED'):return
        try:
            save_shadow_preferences(self._shadow_settings_path,mode,self.switch_manual_usd)
            self.switch_minimum_usd=(self.switch_manual_usd if mode=='MANUAL' else Decimal('.10'))
            self.switch_minimum_status.set(
                f'{mode.replace("_"," ")}: SHADOW minimum ${self.switch_minimum_usd:.2f}; '
                'AI comparison $0.10-$100.00 continues; live broker unchanged')
        except (OSError,ValueError):
            self.switch_minimum_status.set('Unable to save SHADOW preference; no change to live limits')

    def _set_switch_minimum(self):
        # Manually chosen floor takes priority even when AI Lab explores other
        # thresholds. Save outside the financial ledger, atomically, in cents.
        try:
            value=validate_shadow_floor(self.switch_minimum_entry.get().strip())
            self.switch_manual_usd=value
            self.switch_floor_mode.set('MANUAL')
            save_shadow_preferences(self._shadow_settings_path,'MANUAL',value)
            self.switch_minimum_usd=value
            self.switch_minimum_status.set(
                f'MANUAL SHADOW minimum ${value:.2f} after-cost USD vs HOLD (saved); '+
                'AI research continues across $0.10-$100.00; does not alter SELL target or broker ARM')
        except (OSError,ValueError,TypeError):
            self.switch_minimum_status.set('UNCHANGED: enter $0.01-$10,000.00 in whole cents')

    def _verify_predictive_safeguards_offline(self):
        # Temporary test control for engineering. The combined diagnostic
        # already embeds the same checks; future UI cleanup may remove this.
        from coincat_v506_gate_verifier import report as gate_report
        path=filedialog.asksaveasfilename(defaultextension='.txt',
            initialfile='CoinCat_v50_6R_Offline_Predictive_Safeguards.txt',
            filetypes=[('Text diagnostics','*.txt')])
        if not path:return
        try:
            text=gate_report(self)
            Path(path).write_text(text,encoding='utf-8')
            messagebox.showinfo('Offline verification exported',
                'Synthetic tests exported. Production trading remains DISABLED; review BLOCKED and NOT VERIFIED lines.')
        except (OSError,ValueError,RuntimeError):
            messagebox.showerror('Offline verification',
                'Could not finish read-only offline verification; no live orders were submitted.')

    def _export_complete_diagnostics(self):
        """Truthful per-section progress; no duplicate, background write or Coinbase orders."""
        if getattr(self,'_diagnostics_session',None) is not None:
            return
        path=filedialog.asksaveasfilename(defaultextension='.txt',
            initialfile='CoinCat_v60_1_Complete_Diagnostics.txt',
            filetypes=[('Text diagnostics','*.txt')])
        if not path:return
        session=CompleteReportSession(self)
        self._diagnostics_session=session
        self.complete_export_button.configure(state='disabled')
        self.diagnostic_export_progress.set(0)
        self.diagnostic_export_status.set(f'Exporting 0/{len(session.sections)} sections. Do not close CoinCat.')
        self._log('Collecting one read-only diagnostics report; the progress bar shows completed sections')
        def collect():
            if self.shutdown:
                self._diagnostics_session=None
                return
            try:
                more=session.step()
                self.diagnostic_export_progress.set(session.index)
                self.diagnostic_export_status.set(
                    f'Exporting {session.index}/{len(session.sections)} sections. Keep CoinCat open.'
                    if more else 'Finishing report and saving…')
                if more:
                    self.root.after(5,collect)
                    return
                report=session.finish()
                Path(path).write_text(report,encoding='utf-8')
                self._diagnostics_session=None
                self.complete_export_button.configure(state='normal')
                self.diagnostic_export_status.set(
                    f'Saved {session.index}/{len(session.sections)} sections. '
                    + ('Some checks were unavailable; see report.' if session.failed else 'All sections completed.'))
                if session.failed:
                    messagebox.showwarning('Incomplete diagnostic export',
                        'Some sections were unavailable: '+', '.join(session.failed)+
                        '. No live orders were enabled.')
                else:
                    messagebox.showinfo('Diagnostics saved',
                        'All diagnostic sections saved. Live trading remains disabled.')
            except (OSError,ValueError,RuntimeError,tk.TclError) as exc:
                self._diagnostics_session=None
                self.complete_export_button.configure(state='normal')
                self.diagnostic_export_status.set('Export failed ('+type(exc).__name__+'). No trading data changed.')
                if not self.shutdown:
                    messagebox.showerror('Diagnostic export failed',
                        'The report could not be saved. No Coinbase orders were placed.')
        self.root.after(1,collect)

    def _refresh_stream_ui(self):
        """Tkinter main-thread rendering; streaming never enters order decision logic."""
        term=getattr(self,'stream_market_search',None)
        data=self.stream.status(search=term.get() if term is not None else '')
        self.ticker_tree.delete(*self.ticker_tree.get_children())
        for tick in data['rows']:
            state=('LIVE' if tick['fresh'] else ('STALE' if tick['last'] else 'NO MATCH YET'))
            self.ticker_tree.insert('','end',values=(tick['pair'],tick['last'] or '—',
                str(tick['age']) if tick['age'] is not None else '—',state))
        age=data['last_message_age']
        hb=data['heartbeat_age']
        good=data['connected'] and hb is not None and hb < 15
        self.stream_status.set(
            f'PUBLIC all-spot WebSocket: {"CONNECTED" if good else "WAIT / DISCONNECTED"} • '
            f'{data["requested"]}/{data["pairs"]} subscriptions REQUESTED (not confirmed) • '
            f'{data["fresh"]} active ≤15s; {data["recent_120s"]} active ≤120s • '
            f'{data["ticks"]} observed ticks • heartbeat {hb if hb is not None else "—"}s • '
            f'filtered pairs {data["matching"]}, showing {len(data["rows"])} • '
            f'{data["truncated"]} beyond safety ceiling • '
            'last trades ONLY, no executable quote, no guaranteed refresh for illiquid pairs')
        self._reapply_sort(self.ticker_tree)

    def _log(self,msg):
        def show():
            self.logbox.configure(state='normal');self.logbox.insert('end',time.strftime('%H:%M:%S')+' '+str(msg)+'\n');self.logbox.see('end')
            if int(self.logbox.index('end-1c').split('.')[0])>550:self.logbox.delete('1.0','100.0')
            self.logbox.configure(state='disabled')
        if not self.shutdown:show()
    def _async(self,fn,operation='background'):
        if self.worker_busy:return False
        self.worker_busy=True
        def work():
            try:self.jobs.put(('ok',fn()))
            except Exception as ex:self.jobs.put(('error',{'operation':operation,'message':str(ex)}))
            finally:self.worker_busy=False
        threading.Thread(target=work,daemon=True).start()
        return True
    def _client(self):
        if not self.creds:raise LiveBlocked('Connect Coinbase with CDP JSON key first')
        return client_from_credentials(self.creds)
    def _auto_connect_saved_key(self):
        """Connect only using pre-existing encrypted CDP credentials; never approve/arm."""
        if self.shutdown or self._connection_requested or self._connection_in_progress or self.broker:return
        try:
            stored=load_encrypted()
        except Exception:
            stored=None
        if stored:
            self.creds=stored
            self._log('RESTART: saved Coinbase key found; refreshing eligible balances and recent market context. Trading remains disarmed.')
            self._connect()
        else:
            self._log('RESTART: no saved Coinbase key; import CDP JSON to enable automatic market-context refresh.')

    def _load_key(self):
        path=filedialog.askopenfilename(title='Choose Coinbase CDP API JSON',filetypes=[('JSON files','*.json')])
        if not path:return
        try:
            self.creds=parse_key_json(Path(path).read_text(encoding='utf-8'))
            save_encrypted(self.creds)
            self.account_label.set('CDP key saved with Windows DPAPI. Refresh balances; no trade permission assumed.')
            self._connect()
        except Exception as ex:messagebox.showerror('Coinbase connection',str(ex))
    def _connect(self):
        if not self.creds:
            try:self.creds=load_encrypted()
            except Exception:self.creds=None
        if not self.creds:messagebox.showwarning('Coinbase','Import your CDP JSON key first');return
        if self._connection_requested or self._connection_in_progress:
            self.connection_detail.set('A Coinbase connection refresh is already running; please wait.')
            return
        # Read-only portfolio refresh while ARMED preserves broker instance and
        # previously typed authorization *only after* verified quantity checks.
        if self.broker and self.broker.armed:
            self._refresh_portfolio_live(manual=True)
            return
        if self.broker:
            self.broker.disarm()
            self.status.set('DISARMED • refreshing connection')
        self._connection_requested=True
        self._connection_started_at=time.monotonic()
        self.account_label.set('Connecting to Coinbase • no real orders will be placed during refresh.')
        self.connection_detail.set('Waiting for the current market scan to finish…' if self.worker_busy else 'Starting Coinbase account snapshot…')
        self.connection_elapsed.set('Elapsed 0s • ETA unknown until Coinbase finishes paginating')
        self.connection_progress.configure(mode='indeterminate',value=0)
        self.connection_progress.start(16)
        self.refresh_button.configure(state='disabled')
        self.import_button.configure(state='disabled')
        self._start_connection_if_ready()

    def _recheck_excluded_pairs(self):
        """Read-only authenticated List Products recheck, without portfolio sync/ledger writes.

        Reuses the SAME broker/client and single serialized background worker,
        never inventing unlisted symbol combinations or triggering a trade.
        """
        if not self.broker or not self.catalog:
            self.portfolio_sync_status.set('Recheck: connect Coinbase first; no trading changes')
            return False
        if self.broker.armed:
            self.portfolio_sync_status.set('Recheck: LIVE must be DISARMED; no permissions changed')
            return False
        if self.worker_busy or self._connection_requested or self._connection_in_progress or self._portfolio_sync_running:
            self.portfolio_sync_status.set('Recheck: research or account refresh busy; retry when idle')
            return False
        if self._last_catalog_refresh_attempt and time.monotonic()-self._last_catalog_refresh_attempt < 180:
            self.portfolio_sync_status.set('Recheck: recently refreshed; retry after 3 minutes to protect Coinbase API limits')
            return False
        def task():
            products=self.broker.catalog()  # ONLY authenticated paginated List Products GET
            if not products:
                raise ValueError('Authenticated Coinbase SPOT catalog empty; previous catalog retained')
            return {'kind':'catalog_recheck','catalog':list(products),'at':time.time()}
        started=self._async(task,operation='catalog recheck')
        if started:
            self._last_catalog_refresh_attempt=time.monotonic()
            self.portfolio_sync_status.set('Rechecking Coinbase SPOT tradability (read-only; no account changes)')
        return started

    def _refresh_portfolio_live(self,manual=False):
        """Read Coinbase balances, never modify permissions, fills, lots or broker.

        All account IO runs on the serialized worker; no second order is sent.
        An uncertain/missing liquid balance FAILS CLOSED while live-armed.
        """
        if not self.broker or not self.catalog:return False
        if self.worker_busy or self._connection_requested or self._connection_in_progress:
            if manual:self.portfolio_sync_status.set('Portfolio sync queued • research/order verification busy; retry when idle')
            return False
        if self._portfolio_sync_running:return False
        self._portfolio_sync_running=True
        # Catalogue observations expire after two hours; refresh them separately
        # from enrollment, at most every 90 minutes, while DISARMED only.
        # This is an authenticated read-only catalog fetch, never an order.
        catalog_refresh_due = bool(
            not self.broker.armed and self.catalog_at and
            time.time()-self.catalog_at >= self.catalog_refresh_secs and
            (not self._last_catalog_refresh_attempt or
             time.monotonic()-self._last_catalog_refresh_attempt >= 180))
        if catalog_refresh_due:
            self._last_catalog_refresh_attempt=time.monotonic()
        self.portfolio_sync_status.set('PORTFOLIO SYNC • checking available Coinbase balances (NO ORDERS)')
        def task():
            # Authentication and catalog are already established; existing broker
            # keeps ARM state and per-session risk settings unchanged.
            fresh=self.broker.balances()
            # One READ-ONLY authenticated fee-tier GET at most hourly; never
            # needed for balance integrity and never opens an execution path.
            # Errors are captured without aborting Coinbase portfolio refresh.
            fee_observation={'status':'NOT_DUE'}
            if not self.broker.armed:
                fee_observation=self.fee_learning.refresh_from_client(self.broker.client)
            # The safety freshness clock starts when Coinbase BALANCES arrive,
            # not after optional (possibly slow) portfolio pricebook calls.
            balance_verified_at=time.monotonic()
            valid={'USD','USDC'}|{asset for pair in self.catalog for asset in pair.split('-')}
            eligible={asset:qty for asset,qty in fresh.items() if asset in valid}
            review=reconcile_authorized(self.ledger,eligible,self.current_balances)
            # v60.9: apply continuing opt-in enrollment ONLY after confirmed
            # authenticated AVAILABLE balances and safe old-inventory parity.
            # Never infer taxable purchase price or un-exclude an existing row.
            auto_added={'created':0,'deferred':'SHORTFALL_OR_UNVERIFIED','assets':[]}
            if review['safe'] and not self.broker.armed and self.catalog_at and time.time()-self.catalog_at<=7200:
                auto_added=self.ledger.auto_enroll_new_spot_available(eligible,valid)
                if auto_added['created']:
                    review=reconcile_authorized(self.ledger,eligible,self.current_balances)
            # Independent portfolio pricing: ALL eligible held coins, not only
            # the AI Lab's 64 focused markets. Pricing failure never converts
            # to a balance/safety success or causes new Coinbase orders.
            try:
                price_result=fetch_portfolio_books(self.broker.client,self.catalog,eligible)
            except Exception as exc:
                price_result={'quotes':{},'requested':0,'received':0,'error':type(exc).__name__}
            refreshed_catalog=None
            catalog_error=None
            catalog_checked_at=None
            if catalog_refresh_due:
                try:
                    refreshed_catalog=self.broker.catalog()  # GET products only
                    if not refreshed_catalog:
                        raise ValueError('Authenticated eligible Coinbase catalog empty')
                    catalog_checked_at=time.time()
                except Exception as exc:
                    # Balance verification still succeeds independently. An
                    # unsuccessful catalog refresh never resets its stale clock.
                    catalog_error=type(exc).__name__
            return {'kind':'portfolio_sync','review':review,'new_auto_enrolled':auto_added,
                    'portfolio_prices':price_result,
                    'fee_observation':fee_observation,
                    'balance_verified_at':balance_verified_at,
                    'refreshed_catalog':refreshed_catalog,
                    'catalog_checked_at':catalog_checked_at,
                    'catalog_refresh_error':catalog_error}
        if not self._async(task,operation='portfolio sync'):
            self._portfolio_sync_running=False
            return False
        return True

    def _shadow_valuation_books(self):
        """Fresh VERIFIED book observations for research only, never the broker.

        The broker fetches independent executable prices after ARM, and cannot
        read this shadow map. No ticker last trades are included.
        """
        now=time.time()
        return newest_books(self.forward.recent_bid_ask(now=now,max_age=180),
                            self._portfolio_quotes, now=now, max_age=180)

    def _shadow_mark_rates(self, session, books, now, ideas=()):
        assets=set(session.model_balances())
        for wallet in session.fifo_portfolios.values(): assets.update(wallet.start)
        coverage=mark_coverage(assets,books,now=now,
            max_spread=DISPLAY_MAX_SPREAD,max_legs=3)
        session.mark_problems=coverage['problems']
        if not coverage['complete']: return {},False
        rates=coverage['rates']
        for idea in ideas:
            for step in idea.get('shadow_fifo_steps') or ():
                for asset in str(step.get('pair','')).split('-'):
                    fx=usd_conversion(asset,books,now=now,max_age=30)
                    if fx is not None: rates[asset]=str(fx['rate'])
        return rates,coverage['complete']

    def _current_shadow_ideas(self, payload, session, key, ideas):
        expected=payload.get(key)
        if expected is not None and ({a:Decimal(str(q)) for a,q in expected.items() if Decimal(str(q))>0}
                != session.model_balances()):
            return ()  # an earlier urgent conversion superseded this queued plan
        return ideas

    def _accept_portfolio_pricebooks(self, prices):
        """One-way Coinbase READ ONLY pricebooks → portfolio/AI/trader display.

        Never alters broker price sources, enrollment, risk settings or lots.
        """
        fresh = dict(prices.get('quotes') or {})
        now = time.time()
        clean={}
        for p,v in {**self._portfolio_quotes, **fresh}.items():
            try:
                if len(v)==3 and 0 <= now-float(v[2]) <= 300:
                    clean[p]=v
            except (ValueError,TypeError,IndexError):
                pass
        self._portfolio_quotes=clean
        self._portfolio_quote_at = now if fresh else self._portfolio_quote_at
        self._portfolio_price_at = now
        error = str(prices.get('error') or '')
        if error:
            self._portfolio_quote_error = 'API read-only snapshot issue: '+error[:90]
        else:
            self._portfolio_quote_error = (f"{prices.get('received',0)}/{prices.get('requested',0)} Coinbase books"
                + (f"; {prices.get('missing_books',0)} missing/invalid" if prices.get('missing_books') else ''))

    def _storage_check(self):
        """Short filesystem health check only; never prune financial records."""
        healthy,sections=financial_storage_gate(ROOT)
        self.storage_health_status.set('STORAGE • '+ ' • '.join(
            f'{key} {v["used_mb"]:.2f}/{v["limit_mb"]} MB'+(' LIMIT!' if v['over'] else ' near cap' if v['warning'] else '')
            for key,v in sections.items()))
        tax=sections.get('tax_exports',{})
        if tax.get('warning'):
            warning=(f'TAX BACKUP STORAGE WARNING • {tax["used_mb"]:.1f} MiB '
                     'in local tax_exports; approaching 1 GiB. Back up your records. '
                     'This alert does NOT DISARM trading.')
            if hasattr(self,'tax_archive_warning'):self.tax_archive_warning.set(warning)
            if not self._tax_archive_warning_logged:
                self._log(warning)
                self._tax_archive_warning_logged=True
        else:
            self._tax_archive_warning_logged=False
        if not healthy and self.broker and self.broker.armed:
            self.broker.disarm()
            self.status.set('DISARMED • financial/research database active size cap reached')
            self.trader_label.set('Storage limit prevents new orders. Archive/inspect; never delete only copies of fills.')
        return healthy

    def _verified_archive(self):
        if self.broker and self.broker.armed:
            messagebox.showwarning('Archive','Stop trading before creating financial archives.')
            return
        destination=filedialog.asksaveasfilename(defaultextension='.sqlite3',
            initialfile='CoinCat_v50_2_Financial_Ledger_Archive.sqlite3',
            filetypes=[('SQLite ledger','*.sqlite3')])
        if not destination:return
        try:
            result=verified_ledger_backup(self.ledger.path,destination)
            messagebox.showinfo('Financial archive verified',
                'Verified, hashed SQLite archive created. Original ledger remains untouched.\n'
                f'Orders: {result["counts"]["orders"]}; fills: {result["counts"]["fills"]}.\n'
                'Store the archive and checksum file safely. This copy does NOT reduce active ledger size.')
        except Exception as exc:
            messagebox.showerror('Archive failed',str(exc))

    def _filter_research_rows(self):
        """UI-only search; never changes which Coinbase markets the AI scans."""
        if not hasattr(self,'signal_tree'):return
        query=self.market_search.get().strip().casefold()
        tree=self.signal_tree
        # Reattach preserved rows without changing the stored research result.
        for iid in list(tree.get_children('')):tree.detach(iid)
        for iid in getattr(self,'_all_signal_rows',[]):
            try:
                values=tree.item(iid,'values')
                if not query or (values and query in str(values[0]).casefold()):tree.move(iid,'','end')
            except tk.TclError:pass

    def _start_connection_if_ready(self):
        if not self._connection_requested or self._connection_in_progress or self.worker_busy or self.shutdown:return
        self._connection_requested=False
        self._connection_in_progress=True
        deadline=time.monotonic()+180
        def report(phase,page,total):
            if time.monotonic()>deadline:
                raise TimeoutError('Coinbase refresh exceeded 180 seconds; try again or check network/API responsiveness')
            self.jobs.put(('connect_progress',f'{phase}: page {page} completed • {total} entries received'))
        def task():
            self.jobs.put(('connect_progress','Authenticating CDP key and opening Coinbase connection…'))
            client=self._client();broker=LiveBroker(self.ledger,client)
            self.jobs.put(('connect_progress','Step 1/2 • Reading available account balances…'))
            balances=broker.balances(progress=lambda page,total:report('Step 1/2 • Balances',page,total))
            if time.monotonic()>deadline:raise TimeoutError('Coinbase account lookup exceeded 180 seconds')
            self.jobs.put(('connect_progress',f'Step 1/2 complete • {len(balances)} currencies with available balances'))
            self.jobs.put(('connect_progress','Step 2/2 • Checking eligible Coinbase spot pairs…'))
            pairs=broker.catalog(progress=lambda page,total:report('Step 2/2 • Market catalog',page,total))
            # Quote currencies are real enrolled assets too: holding BTC can
            # fund an ETH-BTC BUY in the eventual quote-aware trader. Inclusion
            # is NEVER an order authorization by itself.
            valid={'USD','USDC'}|{asset for p in pairs for asset in p.split('-')}
            eligible={k:v for k,v in balances.items() if k in valid}
            self.jobs.put(('connect_progress','Checking initial automatic enrollment; live trading remains DISARMED…'))
            bootstrap=broker.enrol_first_connection(eligible,valid)
            auto_marks={'marked':[],'skipped':[]}
            if not bootstrap['created'] and not broker.armed:
                prior=reconcile_authorized(self.ledger,eligible)
                if prior['safe']:
                    broker.ledger.auto_enroll_new_spot_available(eligible,valid)
            if bootstrap['created']:
                self.jobs.put(('connect_progress',f'Automatically enrolled {bootstrap["count"]} liquid assets; freezing new USD performance marks…'))
                try:
                    auto_marks=broker.snapshot_approved_inventory(eligible.keys(),set(pairs),authorization='V50 INITIAL AUTO')
                except Exception as exc:
                    # The market mark is optional for enrollment and may be retried
                    # later. Never claim a mark succeeded if Coinbase data failed.
                    auto_marks['skipped'].append(('MARKET SNAPSHOTS',str(exc)[:150]))
            self.jobs.put(('connect_progress','Initial read-only USD portfolio pricing (Coinbase bid/ask; no orders)…'))
            try:
                initial_prices=fetch_portfolio_books(client,pairs,eligible)
            except Exception as exc:
                initial_prices={'quotes':{},'requested':0,'received':0,'error':type(exc).__name__}
            return {'kind':'connect','broker':broker,'balances':eligible,'catalog':pairs,
                    'bootstrap':bootstrap,'auto_marks':auto_marks,'portfolio_prices':initial_prices}
        if not self._async(task,operation='connect'):
            self._connection_in_progress=False;self._connection_requested=True

    def _finish_connection(self,success):
        self._connection_in_progress=False
        self.connection_progress.stop()
        self.connection_progress.configure(mode='determinate',value=100 if success else 0)
        self.refresh_button.configure(state='normal')
        self.import_button.configure(state='normal')
        if not success:
            self.broker=None;self.catalog=[];self.catalog_at=0;self.current_balances={}
            self._refresh_trees()
    def _show_asset_status_dropdown(self,event):
        """Inline ENROLLED/EXCLUDED drop-down in the table's Status column.

        Tk's Treeview doesn't support native editable cells. Place a real
        readonly Combobox over the chosen Status cell until a choice is made.
        No choice changes order permissions without a separate ARM LIVE.
        """
        if self.balance_tree.identify_region(event.x,event.y)!='cell':return
        item=self.balance_tree.identify_row(event.y)
        if not item:return
        values=self.balance_tree.item(item,'values')
        if not values:return
        if values[-1]=='CATALOG ONLY':return  # browser rows cannot change consent
        self.balance_tree.selection_set(item)
        self._hide_asset_dropdown()
        bounds=self.balance_tree.bbox(item,'#9')
        if not bounds:return
        x,y,w,h=bounds
        # Tk's identify_column can disagree with bbox under DPI scaling or
        # a horizontal viewport; the actual Status-cell bounds are reliable.
        if not (x <= event.x < x+w and y <= event.y < y+h):return
        self.approval_choice.set('EXCLUDED' if values[-1] in ('EXCLUDED','NOT APPROVED') else 'ENROLLED')
        drop=ttk.Combobox(self.balance_tree,textvariable=self.approval_choice,
            values=('ENROLLED','EXCLUDED'),state='readonly',width=13)
        self._status_editor=drop
        drop.place(x=x,y=y,width=max(w,115),height=max(h,24))
        def selection(_event=None):
            choice=self.approval_choice.get()
            self._hide_asset_dropdown()
            self.balance_tree.selection_set(item)
            self._change_approval(asset=str(values[0]),choice=choice)
        drop.bind('<<ComboboxSelected>>',selection)
        drop.bind('<Return>',selection)
        drop.bind('<Escape>',lambda e:self._hide_asset_dropdown())
        drop.focus_set()
        try:self.root.after(30,lambda:drop.winfo_exists() and drop.event_generate('<Down>'))
        except tk.TclError:pass

    def _hide_asset_dropdown(self):
        editor=getattr(self,'_status_editor',None)
        self._status_editor=None
        if editor is not None:
            try:editor.destroy()
            except tk.TclError:pass

    def _show_selected_signal_reason(self,event=None):
        """Always expose the complete justification, never only the truncated cell."""
        selected=self.signal_tree.selection()
        if selected:
            market=str(self.signal_tree.item(selected[0],'values')[0])
            detail=self._signal_reasons.get(market,'No full reason available yet.')
            self.signal_detail.set(market+' • '+detail)
            action=str(self.signal_tree.set(selected[0],'BUY assessment')).upper()
            sell=str(self.signal_tree.set(selected[0],'SELL assessment')).upper()
            color=('#165438' if 'BUY' in action or sell=='SELL' else
                   '#61471b' if 'WAIT' in action or 'HOLD' in sell else '#3c385c')
            if hasattr(self,'signal_decision_panel'):
                self.signal_decision_panel.configure(bg=color)
                self.signal_decision_label.configure(bg=color,fg='#ffffff')
                # Keep title consistent with the selected state's contrast.
                for child in self.signal_decision_panel.winfo_children():
                    if isinstance(child,tk.Label):child.configure(bg=color,fg='#ffffff')

    def _balance_selected(self,event=None):
        selected=self.balance_tree.selection()
        if selected:
            vals=self.balance_tree.item(selected[0],'values')
            self.approval_choice.set('EXCLUDED' if vals[-1] in ('EXCLUDED','NOT APPROVED','CATALOG ONLY') else 'ENROLLED')

    def _change_approval(self,asset=None,choice=None):
        selected=self.balance_tree.selection()
        if asset is None and not selected:return
        coin=asset if asset is not None else self.balance_tree.item(selected[0],'values')[0]
        choice=choice or self.approval_choice.get()
        enabled=choice=='ENROLLED';existing=next((x for x in self.ledger.assets() if x['asset']==coin),None)
        if not self.broker or self._connection_in_progress or self._connection_requested:
            messagebox.showwarning('Approval','Connect Coinbase and finish balance loading first.');return
        current=bool(existing and existing.get('enabled',1))
        if existing and enabled==current:return
        if not messagebox.askyesno('Change asset authorization',
                    f'{"ENROLL" if enabled else "EXCLUDE"} {coin}?\n\nThis will DISARM live trading. '
                    'On enrollment, CoinCat may set a fresh USD market-performance snapshot if no snapshot exists. '
                    'Original taxable purchase cost stays separate. New eligible available coins may automatically enroll; existing exclusions and existing quantity increases remain protected.'):
            return
        self.broker.disarm();self.status.set('DISARMED • asset authorization changed')
        if existing:
            try:
                self.ledger.set_asset_enabled(coin,enabled)
                self._log(f'User changed authorization: {coin} -> {choice}')
                self._refresh_trees()
                if enabled and existing.get('snapshot_unit_usd') is None and existing.get('basis_source')!='BOT_FILL':
                    self._snapshot_run([coin],'SNAPSHOT '+coin)
            except Exception as ex:messagebox.showerror('Asset approval',str(ex))
            return
        if not enabled:return
        if time.time()-self.catalog_at>600:
            messagebox.showwarning('Approval','Refresh live Coinbase balances and catalog before enrolling this new asset.');return
        qty=self.current_balances.get(coin)
        if qty is None or dec(qty)<=0:
            messagebox.showwarning('Approval','No eligible available Coinbase balance for this coin.');return
        typed=simpledialog.askstring('Approve selected asset',
                 f'Authorize up to {qty} {coin} of AVAILABLE liquid balance and snapshot its live USD bid for performance measurement? Original tax cost stays separate.\n\nType APPROVE {coin} to confirm:',parent=self.root)
        if typed!=f'APPROVE {coin}':return
        valid={'USD','USDC'}|{asset for x in self.catalog for asset in x.split('-')}
        def task():
            self.broker.enrol_one_from_current(coin,qty,valid)
            marks=self.broker.snapshot_approved_inventory([coin],set(self.catalog),authorization='SNAPSHOT '+coin)
            return {'kind':'one_enrolled','asset':coin,'marks':marks}
        if not self._async(task,operation='per-asset approval'):
            messagebox.showwarning('Approval','A Coinbase scan is already running. Try again after it completes.')

    def _snapshot_run(self,coins,phrase):
        if not self.broker or not self.catalog or time.time()-self.catalog_at>600:
            messagebox.showwarning('Market snapshot','Refresh live Coinbase balances and market catalog first.');return
        if self.ledger.pending():
            messagebox.showwarning('Market snapshot','Unresolved Coinbase order. Reconcile it before changing approvals.');return
        if self._connection_in_progress or self._connection_requested:
            messagebox.showwarning('Market snapshot','Coinbase balances are still loading.');return
        self.broker.disarm();self.status.set('DISARMED • market snapshot authorization')
        def task():
            result=self.broker.snapshot_approved_inventory(coins,set(self.catalog),authorization=phrase)
            return {'kind':'snapshot','result':result}
        self.snapshot_status.set('Refreshing liquid balances and market bids • working in background, trading DISARMED...')
        if not self._async(task,operation='market-value snapshot'):
            messagebox.showwarning('Market snapshot','The AI Lab is scanning. Try again after the current scan completes.')
    def _snapshot_one(self):
        chosen=self.balance_tree.selection()
        if not chosen:return
        asset=self.balance_tree.item(chosen[0],'values')[0]
        if asset in ('USD','USDC'):return
        row=self.ledger.asset(asset)
        if not row:
            messagebox.showwarning('Market snapshot','Approve this crypto balance first.');return
        if row.get('snapshot_unit_usd') is not None:
            messagebox.showinfo('Market snapshot','This asset already has a frozen performance starting mark.');return
        if row.get('basis_source')=='BOT_FILL':
            messagebox.showinfo('Market snapshot','This coin was purchased by CoinCat; its verified original fill cost is preserved.');return
        token='SNAPSHOT '+asset
        entered=simpledialog.askstring('Authorize performance snapshot',
            f'CoinCat will read a NEW live Coinbase USD bid for {asset} and freeze the value as its trading-performance starting point. This is NOT the original taxable acquisition cost.\n\nAny authorized real sells could trigger gains or losses versus the TRUE original cost.\n\nType {token}:',parent=self.root)
        if entered==token:self._snapshot_run([asset],token)
    def _snapshot_all(self):
        coins=[r['asset'] for r in self.ledger.assets() if r.get('enabled',1) and r['asset'] not in ('USD','USDC')
               and r.get('snapshot_unit_usd') is None and r.get('basis_source')!='BOT_FILL']
        if not coins:
            messagebox.showinfo('Market snapshot','No enrolled existing crypto needs a market snapshot.');return
        token='SNAPSHOT APPROVED'
        entered=simpledialog.askstring('Authorize ALL existing asset snapshots',
            f'{len(coins)} previously enrolled crypto holdings: {", ".join(coins)}\n\n'
            'CoinCat will retrieve NEW Coinbase USD bid quotes TODAY. This becomes the performance START VALUE, not your original purchase price. Only quoted holdings will be marked.\n'
            'Actual historical/tax purchase cost remains unknown unless separately entered.\n'
            'Live trading will be disarmed; this does NOT submit orders.\n\n'
            f'Type exactly {token} to authorize:',parent=self.root)
        if entered==token:self._snapshot_run(coins,token)

    def _basis(self):
        """Deprecated: manual cost-basis editing is prohibited."""
        messagebox.showinfo('Tax cost protected',
            'Original taxable purchase costs cannot be reset to today’s prices. '
            'Historical entries are kept for review; only authenticated acquisition '
            'records can verify tax lots.')

    def _capture_today_start(self):
        """Explicit new performance period, not a mutation of historical tax basis."""
        from coincat_v601_baseline import capture, BaselineBlocked
        if not self.broker or not self.catalog or time.time()-self.catalog_at>600:
            messagebox.showwarning('New starting value','Connect and refresh Coinbase prices first.');return
        if self.broker.armed or self.ledger.pending():
            messagebox.showwarning('New starting value','Keep live trading disarmed and resolve existing orders first.');return
        now=time.time()
        if (not self._portfolio_coverage.get('complete') or
                not self._portfolio_quote_at or now-self._portfolio_quote_at>120 or
                not self._last_portfolio_sync_monotonic or
                time.monotonic()-self._last_portfolio_sync_monotonic>120):
            messagebox.showwarning('New starting value',
                'Portfolio prices or verified Coinbase balances are stale or incomplete. Refresh and try again.');return
        quotes=self.forward.recent_bid_ask(now=now,max_age=120)
        for pair,book in self._portfolio_quotes.items():
            try:
                if 0<=now-float(book[2])<=120:quotes[pair]=book
            except (TypeError,ValueError,IndexError):pass
        coverage=portfolio_coverage(self.current_balances,self.catalog,quotes,now=now)
        if not coverage.get('complete'):
            messagebox.showwarning('New starting value','Not all available currencies have fresh USD prices.');return
        holdings=self.ledger.assets()
        marks={key:val['rate'] for key,val in coverage['rates'].items()}
        token='START TODAY'
        answer=simpledialog.askstring('Start a new performance period',
            'Record TODAY’S verified Coinbase USD market value for your available ENROLLED '
            'holdings. The actual UTC capture time is saved; no date is backdated. '
            'This does NOT change historical tax purchase costs, real Coinbase holdings, '
            'existing earlier snapshots, or place orders.\n\nType START TODAY:',parent=self.root)
        if answer!=token:return
        try:
            from coincat_live import sql
            with sql(self.ledger.path) as conn:
                result=capture(conn,enrollments=holdings,available=dict(self.current_balances),
                    usd_rates=marks,now=int(time.time()))
            self._performance_period_label.set(
                f'New performance start saved: ${float(result["total_usd"]):,.2f} '
                f'across {result["assets"]} enrolled currencies. Tax cost unchanged.')
            self._log('New verified performance baseline recorded (not tax cost)')
            self._refresh_trees()
            messagebox.showinfo('Starting value saved',
                'New dated USD performance baseline recorded. Historical tax lots are unchanged.')
        except (BaselineBlocked,ValueError,OSError,RuntimeError) as exc:
            messagebox.showerror('Starting value not saved',
                'No performance snapshot was saved: '+str(exc)[:180])

    def _render_capacity_limits(self):
        level=current_stage(self.ledger)
        cap=TIERS[level]
        self.capacity_stage=level
        self.risk_message.set(f'MANUAL BUDGET SAFETY CEILING: ${cap.order}/order • '
            f'${cap.daily} buys/day • ${cap.exposure} NEW exposure • '
            f'{cap.orders_day} order attempts/day; manual increases require verified enrolled portfolio value, separate approval, and re-ARM.')

    def _capacity_preference_changed(self,value):
        # The slider NEVER changes broker settings or stored hard limits.
        max_stage=int(round(float(value)))
        cur=current_stage(self.ledger)
        if max_stage<=cur:
            self.capacity_status.set(f'Capacity ceiling {max_stage} selected; approved stage {cur} stays unchanged. '
                                     'No budget changes or orders. Select a higher stage to permit FUTURE proposals.')
        else:
            self.capacity_status.set(f'Growth preference up to stage {max_stage} (approved stage {cur}). '
                'Slider does not authorize spending. Evidence review and a typed pop-up approval are still required.')

    def _capacity_evidence(self):
        labels=self.directional.overview()['verified']
        return evaluate_capacity(self.ledger,labels)

    def _manual_capacity_review(self):
        try:
            report=self._capacity_evidence()
            self._show_capacity_status(report,manual=True)
            if report['ready'] and self.capacity_preference.get()>=report['next_stage']:
                self._capacity_approval_popup(report)
            else:
                messagebox.showinfo('CoinCat capacity review',
                    self.capacity_status.get()+ '\n\nThis check never places orders or changes limits.',parent=self.root)
        except Exception as ex:messagebox.showerror('Capacity review',str(ex),parent=self.root)

    def _show_capacity_status(self,report,manual=False):
        stage=report['stage'];next_stage=report['next_stage']
        detail=(f'{report["cycles"]} completed verified bot-owned SELL orders; '
                f'win {report["win_pct"]:.1f}%; real net ${report["net"]:.2f}; '
                f'forward labels {report["forward_labels"]}; '
                f'approved stage {stage}. ')
        if next_stage is None:
            detail+='Maximum optional pilot stage reached.'
        elif report['ready']:
            detail+=f'EVIDENCE READY for stage {next_stage}; approval required. '
            if self.capacity_preference.get()<next_stage:
                detail+='Slider ceiling is lower, so no proposal will be shown.'
        else:
            detail+='WAIT — '+report['reason']
        self.capacity_status.set(detail)

    def _capacity_approval_popup(self,report):
        if self.shutdown or not report['ready']:return
        level=report['next_stage']
        if level is None or level>int(self.capacity_preference.get()):return
        if not self.broker or self.broker.armed:
            self.capacity_status.set('Capacity evidence ready, but DISARM and connect before reviewing the increase. No limits changed.')
            return
        cap=TIERS[level];old=TIERS[current_stage(self.ledger)]
        msg=(f'AI Lab is ready to increase capacity — PROPOSAL stage {level}\n\n'
             f'Current authorized maxima: ${old.order}/order, ${old.daily} daily buys, '
             f'${old.exposure} new exposure, {old.orders_day} attempts/day.\n\n'
             f'PROPOSED NEW MAXIMA: ${cap.order}/order, ${cap.daily} daily buys, '
             f'${cap.exposure} new exposure, {cap.orders_day} attempts/day.\n\n'
             f'Evidence: {report["cycles"]} REAL reconciled completed bot-owned exits, '
             f'{report["win_pct"]:.1f}% winners, ${report["net"]:.2f} net P&L, '
             f'{report["forward_labels"]} genuine directional outcomes.\n\n'
             'Your funds are at greater risk after this increase. Past results do not predict future returns. '
             'This approval NEVER arms live orders.\n\n'
             f'Type exactly APPROVE CAPACITY {level} to raise authorized ceilings; Cancel declines:')
        response=simpledialog.askstring('CoinCat • capacity increase requires approval',msg,parent=self.root)
        if response!=f'APPROVE CAPACITY {level}':
            self.capacity_snooze_until=int(time.time()+86400)
            self.ledger.set_setting('capacity_snooze_until',self.capacity_snooze_until)
            self._log(f'CAPACITY PROPOSAL stage {level} declined/deferred; no changes to limits.')
            return
        try:
            if self.broker.armed:raise LiveBlocked('Disarm before any capacity change')
            # Recheck evidence and unresolved orders immediately before durable approval.
            approved=approve_next_stage(self.ledger,level,response,
                forward_labels=self.directional.overview()['verified'])
            self._render_capacity_limits()
            # Deliberately set user-editable limits to the previous values.
            # The newly approved ceiling becomes available only if the user
            # chooses larger budgets and separately re-arms this Windows session.
            self.capacity_snooze_until=int(time.time()+86400)
            self.ledger.set_setting('capacity_snooze_until',self.capacity_snooze_until)
            self._log(f'USER APPROVED capacity stage {level}. No live orders; trading still DISARMED. '
                'Broker limits unchanged until user edits them and ARM LIVE.')
            self._capacity_preference_changed(str(level))
            messagebox.showinfo('Capacity approval saved',
                f'Stage {level} approved. New ceiling: ${approved.order}/order, '
                f'${approved.daily}/day, ${approved.exposure} exposure, '
                f'{approved.orders_day} daily attempts.\n\n'
                'Current broker budgets were NOT raised. Edit Auto Trader budgets as needed '
                'and separately ARM LIVE to apply them.',parent=self.root)
        except Exception as ex:messagebox.showerror('Capacity approval blocked',str(ex),parent=self.root)

    def _capacity_check_automatic(self):
        # UI-only every ~60s: no orders, no changes, no fake AI predictions.
        now=time.monotonic()
        if now-self.capacity_last_checked<60:return
        self.capacity_last_checked=now
        try:
            report=self._capacity_evidence()
            self._show_capacity_status(report)
            next_stage=report['next_stage']
            if report['ready'] and next_stage is not None and self.capacity_preference.get()>=next_stage \
               and time.time()>=self.capacity_snooze_until and not self.worker_busy \
               and not self._connection_in_progress and self.broker is not None and not self.broker.armed:
                self._capacity_approval_popup(report)
        except Exception as ex:
            self.capacity_status.set('Capacity review paused: '+str(ex)[:160])

    def _schedule_target_preview(self,*_):
        """Debounce UI edits; no Coinbase APIs or broker.submit are used."""
        if self.shutdown:return
        task=self._scheduled.pop('target_preview',None)
        if task is not None:
            try:self.root.after_cancel(task)
            except tk.TclError:pass
        self._scheduled['target_preview']=self.root.after(400,self._apply_target_preview)

    def _apply_target_preview(self):
        """Apply a proposed SELL target to DISARMED research ONLY.

        Real trading target remains frozen at ARM authorization. Never update
        broker limits, ledger settings, or orders from this UI callback.
        """
        self._scheduled.pop('target_preview',None)
        try:
            value=Decimal(self.target_entry.get().strip())
            if not value.is_finite() or not Decimal('0.01')<=value<=Decimal('5.00'):
                raise ValueError('Enter an amount from $0.01 to $5.00')
        except Exception:
            self.target_preview_status.set('INVALID SELL target • use $0.01–$5.00; previous target remains in effect')
            return
        if self.broker is not None and self.broker.armed:
            self.target_preview_status.set(
                f'NOT APPLIED while LIVE ARMED • active target stays ${self.target_net_usd:.2f}; '
                'disarm before updating research, rearm separately to change live policy')
            return
        self.preview_target_net_usd=value
        self._target_preview_pending=True
        self.target_preview_status.set(
            f'RESEARCH PREVIEW ${value:.2f} net ordinary SELL • no orders; '
            'refreshing SELL/HOLD against most recent authenticated bid observations')
        self._render_target_preview_if_idle()

    def _render_target_preview_if_idle(self):
        """Recalculate only visible HOLD/SELL reasons using already-recorded quotes."""
        if not self._target_preview_pending or self.worker_busy:return
        if self.broker is not None and self.broker.armed:
            self._target_preview_pending=False
            return
        if not self.last_cycle:
            self.target_preview_status.set(
                f'RESEARCH PREVIEW ${self.preview_target_net_usd:.2f} • next quote scan will show SELL/HOLD assessments • NO ORDERS')
            self._target_preview_pending=False
            return
        try:
            sells=self._review_sell_inventory()
            self.last_cycle['sell_reviews']=sells
            # Whole-holding previews are independent of profit target and
            # never change broker submission sizes or authorizations.
            self.sell_tree.delete(*self.sell_tree.get_children())
            for item in sells:
                self.sell_tree.insert('','end',values=(item['pair'],
                    f'{item["bid"]:.8g}' if item['bid'] is not None else '—',
                    f'{item["value"]:.2f}' if item['value'] is not None else '—',
                    item['action'],item['reason']))
            self._reapply_sort(self.sell_tree)
            blocked=sum(x['action']=='BLOCKED' for x in sells)
            chosen=sum(x['action']=='SELL' for x in sells)
            self.sell_status.set(f'RESEARCH PREVIEW • {len(sells)} approved assets evaluated • '
                f'{chosen} SELL candidate(s) • {blocked} blocked • full verified holding, no LIVE dollar cap • NO ORDERS')
            # Update both directions in the current AI Lab table. The BUY reason
            # is unchanged: a sell target cannot turn HOLD into a BUY candidate.
            reviews={r['pair']:r for r in self.last_cycle.get('reviews',[])}
            sell_by_pair={r['pair']:r for r in sells if r.get('pair')}
            for iid in self.signal_tree.get_children():
                fields=list(self.signal_tree.item(iid,'values'))
                if not fields:continue
                pair=fields[0]
                review=reviews.get(pair)
                if review is None:continue
                sell=sell_by_pair.get(pair)
                if sell:
                    fields[2]=sell['action']
                    detail=review['reason']+' | SELL: '+sell['reason']
                else:
                    detail=review['reason']
                fields[-1]=_wrap_reason_cell(detail,width=50,lines=1)
                self._signal_reasons[pair]=detail
                self.signal_tree.item(iid,values=fields)
            self._show_selected_signal_reason()
            self.target_preview_status.set(
                f'RESEARCH PREVIEW ${self.preview_target_net_usd:.2f} net ordinary SELL '
                f'• {chosen} SELL candidate(s) • {len(sells)} holdings reviewed • NO ORDERS / LIVE DISARMED')
            self._target_preview_pending=False
        except Exception as exc:
            self._target_preview_pending=False
            self.target_preview_status.set('RESEARCH PREVIEW unavailable • '+str(exc)[:160]+' • NO ORDERS')

    def _update_v30_readiness(self):
        """Read-only UI / ARM preflight. No Coinbase submissions or account mutations."""
        try:
            storage_ok,_=financial_storage_gate(ROOT)
            now=time.monotonic()
            report=assess_readiness(
                broker=self.broker, catalog=self.catalog,
                catalog_age_s=(time.time()-self.catalog_at if self.catalog_at else float('inf')),
                balance_age_s=(now-self._last_portfolio_sync_monotonic if self._last_portfolio_sync_monotonic else float('inf')),
                scan_age_s=(now-self._last_scan_at if self._last_scan_at else float('inf')),
                observed_runtime_s=(now-self._v30_observation_started if self._v30_observation_started else 0),
                external_mismatches=self.external_mismatches if hasattr(self,'external_mismatches') else [],
                storage_ok=storage_ok,
                valuation_complete=bool(self._portfolio_coverage.get('complete')),
                valuation_age_s=(time.time()-self._portfolio_quote_at if self._portfolio_quote_at else float('inf')))
            self.v30_readiness_status.set(format_readiness(report))
            return report
        except Exception as exc:
            self.v30_readiness_status.set('NOT READY • readiness check failed: '+type(exc).__name__)
            return {'ready':False,'blockers':['readiness check exception: '+type(exc).__name__]}

    def _verified_enrolled_budget(self):
        """No cached previous prices; independent fail-closed portfolio ceiling."""
        now=time.time()
        if not self.broker or time.time()-self.catalog_at>7200:
            return None
        if not self._last_portfolio_sync_monotonic or time.monotonic()-self._last_portfolio_sync_monotonic>300:
            return None
        if not self._portfolio_quote_at or now-self._portfolio_quote_at>300:
            return None
        quotes=self.forward.recent_bid_ask(now=now,max_age=300)
        for pair,book in self._portfolio_quotes.items():
            try:
                if 0<=now-float(book[2])<=300:quotes[pair]=book
            except (TypeError,ValueError,IndexError):pass
        coverage=portfolio_coverage(self.current_balances,self.catalog,quotes,now=now)
        if not coverage['complete'] or getattr(self,'external_mismatches',[]):
            return None
        return portfolio_ceiling(self.ledger.assets(),self.current_balances,coverage['rates'])

    def _arm(self):
        # No legacy USD-only pilot remains armed by an old GUI sequence. A
        # full-spot production broker must pass technical gates before risk
        # acknowledgment can authorize any future 12-order pilot.
        messagebox.showwarning('Unified live pilot not yet certified',
            'All eligible spot pairs share one research and review pathway. '
            'Production multi-currency settlement, Coinbase-confirmed fills, '
            'durable restart recovery, portfolio loss floor and the bounded '
            '12-order approval gate are NOT yet certified. No orders are enabled.')
        return
        if self._connection_in_progress or self._connection_requested:
            messagebox.showwarning('Live blocked','Wait until the Coinbase refresh finishes.');return
        if not self.broker or not self.catalog or time.time()-self.catalog_at>7200:
            messagebox.showwarning('Live blocked','Connect and refresh the authenticated Coinbase catalog first.');return
        if not self._storage_check():
            messagebox.showwarning('Live blocked','Local ledger or research store reached its active budget. Preserve financial history; do not erase fills.')
            return
        if not self._last_portfolio_sync_monotonic or time.monotonic()-self._last_portfolio_sync_monotonic>300:
            messagebox.showwarning('Live blocked','Coinbase available balances have not been verified in the last five minutes. Refresh balances first.')
            return
        # The active v40 ledger is the only authoritative CoinCat financial state.
        # Never inspect/require an installed old version's data to ARM.
        if self.ledger.pending():
            messagebox.showwarning('Live blocked: pending Coinbase order',
                'The CoinCat financial ledger contains an unresolved order. Reconcile on Coinbase first.');return
        if getattr(self,'external_mismatches',[]):
            messagebox.showwarning('Live blocked: external Coinbase trade reconciliation',
                'Some enrolled quantities exceed currently available Coinbase quantities following external activity. '
                'Review/reconcile your Coinbase transaction history and CoinCat inventory lots first. '
                'No current-value snapshot can replace original tax lots. Affected assets: '+', '.join(x['asset'] for x in self.external_mismatches[:12]));return
        readiness=self._update_v30_readiness()
        if not readiness['ready']:
            messagebox.showwarning('Live blocked: readiness check', '\n'.join(readiness['blockers']))
            return
        confirm=simpledialog.askstring('ARM REAL MONEY TRADING','CoinCat will place REAL Coinbase orders in supported spot markets within approved limits only AFTER future unified production certification. This build cannot submit new orders. Profits are not guaranteed.\n\nType exactly ARM LIVE to authorize this session:',parent=self.root)
        if confirm!='ARM LIVE':return
        try:
            self.broker.portfolio_ceiling_usd=None
            self.broker.portfolio_ceiling_seen_at=0.0
            self.broker.per_order_max=dec(self.limits[0].get());self.broker.daily_buy_cap=dec(self.limits[1].get());self.broker.exposure_cap=dec(self.limits[2].get())
            raw_attempts=self.max_attempts_entry.get().strip()
            if not raw_attempts.isdecimal():raise LiveBlocked('Daily order-attempt limit must be a positive integer')
            self.broker.max_orders_day=int(raw_attempts)
            old_cap=TIERS[current_stage(self.ledger)]
            raised=(self.broker.per_order_max>old_cap.order or
                self.broker.daily_buy_cap>old_cap.daily or
                self.broker.exposure_cap>old_cap.exposure or
                self.broker.max_orders_day>old_cap.orders_day)
            if raised:
                fresh_ceiling=self._verified_enrolled_budget()
                validate_manual_budget(self.broker.per_order_max,self.broker.daily_buy_cap,
                    self.broker.exposure_cap,self.broker.max_orders_day,fresh_ceiling)
                approval=simpledialog.askstring('MANUAL PORTFOLIO BUDGET',
                    'These limits exceed the original stage-zero pilot maxima. CoinCat will cap them to the '
                    'verified available enrolled portfolio USD value and keep the separately approved daily realized '
                    'loss stop and other protections. All trading can lose money.\n\n'
                    'Type exactly APPROVE PORTFOLIO BUDGET to authorize these values for this session:',parent=self.root)
                if approval!='APPROVE PORTFOLIO BUDGET':
                    raise LiveBlocked('Portfolio budget increase not approved; no orders')
                self.broker.portfolio_ceiling_usd=fresh_ceiling
                self.broker.portfolio_ceiling_seen_at=time.monotonic()
            from coincat_daily_risk import daily_loss_limit, DEFAULT_LIMIT
            target=dec(self.target_entry.get())
            if not Decimal('0.01')<=target<=Decimal('5.00'):
                raise LiveBlocked('Ordinary SELL minimum net target must be $0.01–$5.00')
            limit=daily_loss_limit(self.daily_loss_limit_entry.get())
            if limit>DEFAULT_LIMIT:
                confirmation=simpledialog.askstring('INCREASE DAILY LOSS PAUSE',
                    f'This raises the daily confirmed realized-loss BUY pause to ${limit:.2f}. '
                    'It is NOT a portfolio-wide loss floor, and the broker is still DISARMED. '
                    'Funds are at risk.\n\n'
                    f'Type exactly APPROVE DAILY LOSS {limit:.2f} to confirm:',parent=self.root)
                if confirmation!=f'APPROVE DAILY LOSS {limit:.2f}':
                    raise LiveBlocked('Increased daily realized-loss threshold not separately approved')
            self.target_net_usd=target;self.preview_target_net_usd=target
            self.broker.daily_realized_loss_limit_usd=limit
            self.broker.arm();self.status.set('LIVE NOT CERTIFIED • all-spot review only');self.trader_label.set('ARMED • awaiting verified forward signals / actual fill reconciliation')
            self.ledger.log('USER_ARMED_LIVE','Current Windows process only')
            self.target_preview_status.set(f'LIVE ARMED • active ordinary SELL target ${target:.2f}; edits will NOT change live orders until separately rearmed')
        except Exception as ex:messagebox.showerror('Live blocked',str(ex))
    def _shadow_start_inputs(self):
        """Read-only start gate shared by both RAM wallets; never authorizes LIVE."""
        if str(self.ledger.setting('halted','0'))=='1':
            raise ValueError('EMERGENCY_STOP_ACTIVE — release STOP only after reviewing Coinbase')
        age=time.monotonic()-self._last_portfolio_sync_monotonic
        if not 0<=age<=300:
            raise ValueError('BALANCES_STALE — refresh verified Coinbase balances before starting SHADOW')
        mismatches=getattr(self,'external_mismatches',[])
        if mismatches:
            symbols=', '.join(str(row.get('asset','?')) for row in mismatches[:12])
            raise ValueError('BALANCE_MISMATCH — '+symbols+
                '. Reconcile approved and available holdings; no lots were changed.')
        holdings={};excluded=[]
        for row in self.ledger.assets():
            name=str(row.get('asset','')).upper()
            if not name:continue
            if not row.get('enabled',1):
                excluded.append(name);continue
            approved=Decimal(str(row.get('remaining_qty','0')))
            available=Decimal(str(self.current_balances.get(name,'0')))
            if not approved.is_finite() or not available.is_finite() or min(approved,available)<0:
                raise ValueError('INVALID_BALANCE — refresh verified Coinbase balances')
            qty=min(approved,available)
            if qty>0:holdings[name]=str(qty)
        if not holdings:raise ValueError('NO_ENROLLED_AVAILABLE_HOLDINGS')
        # Full authorized holdings can be valued at conservative bid/inverse ask
        # without granting a wide-spread holding permission to fund any trade.
        coverage=portfolio_coverage(holdings,self.catalog,self._shadow_valuation_books(),now=time.time())
        if not coverage['complete']:
            missing=coverage['missing']
            details='; '.join(asset+': '+reason for asset,reason in list(missing.items())[:12])
            raise ValueError(f'USD_VALUATION_INCOMPLETE — {len(missing)}/{len(holdings)} enrolled holdings. '+
                details+'. Refresh portfolio prices and retry. No amounts or lots were changed.')
        rates={name:str(info['rate']) for name,info in coverage['rates'].items()
               if isinstance(info,dict) and info.get('rate') is not None}
        return holdings,tuple(excluded),rates

    def _toggle_shadow_arm(self):
        """NO LIVE AUTHORIZATION: create/stop segregated in-memory FIFO scenarios."""
        shadow=self.shadow_pilot
        if shadow.armed:
            shadow.disarm()
            self._shadow_stop_reason='MANUAL STOP SHADOW'
            self.shadow_mode_button.configure(text='ARM SHADOW (NO REAL ORDERS)')
            self.shadow_mode_status.set('SHADOW OFF • modeled FIFO results retained in RAM until restart')
            return
        if not self.broker or getattr(self.broker,'armed',False):
            messagebox.showwarning('Shadow unavailable','Connect Coinbase read-only and leave ARM LIVE DISARMED.')
            return
        try:
            holdings,excluded,rates=self._shadow_start_inputs()
            shadow.arm(connected=True,real_arm=False,stopped=False,
                 verified_balances=True,usd_coverage=True,
                 enrolled_quantities=holdings,fresh_usd_rates=rates)
            self._shadow_model_balances={k:str(v) for k,v in shadow.model_balances().items()}
            self._shadow_excluded_assets=excluded
            self._shadow_stop_reason='RUNNING'
            self.shadow_mode_button.configure(text='STOP SHADOW (NO REAL ORDERS)')
            self.shadow_mode_status.set('ARMED SHADOW • real Coinbase data + isolated model FIFO; no order POST')
        except (ValueError,TypeError,InvalidOperation,KeyError) as exc:
            messagebox.showwarning('ARM SHADOW blocked',str(exc))

    def _toggle_experimental_shadow(self):
        """Explicit, separate experimental what-if consent. NEVER ARM LIVE."""
        shadow=self.experimental_shadow
        if shadow.armed:
            shadow.disarm()
            self.experimental_shadow_button.configure(text='ARM EXPERIMENT (UNVALIDATED • NO REAL ORDERS)')
            self.experimental_shadow_status.set('EXPERIMENT OFF • results remain in RAM until restart')
            return
        if not self.broker or getattr(self.broker,'armed',False):
            messagebox.showwarning('Experimental SHADOW unavailable',
                'Connect Coinbase read-only; real LIVE must remain DISARMED.')
            return
        try:
            holdings,excluded,rates=self._shadow_start_inputs()
            shadow.arm(connected=True,real_arm=False,stopped=False,
                verified_balances=True,usd_coverage=True,
                enrolled_quantities=holdings,fresh_usd_rates=rates)
            self._experimental_model_balances={k:str(v) for k,v in shadow.model_balances().items()}
            self._experimental_excluded_assets=excluded
            self.experimental_shadow_button.configure(text='STOP EXPERIMENT (NO REAL ORDERS)')
            self.experimental_shadow_status.set('EXPERIMENT ARMED • unvalidated what-if FIFO; LIVE blocked')
        except (ValueError,TypeError,InvalidOperation,KeyError) as exc:
            messagebox.showwarning('Experimental SHADOW blocked',str(exc))

    def _stop(self):
        if getattr(self,'experimental_shadow',None) and self.experimental_shadow.armed:
            self.experimental_shadow.disarm()
            self.experimental_shadow_button.configure(text='ARM EXPERIMENT (UNVALIDATED • NO REAL ORDERS)')
            self.experimental_shadow_status.set('EXPERIMENT OFF • emergency STOP latched')
        if self.shadow_pilot.armed:
            self.shadow_pilot.disarm()
            self._shadow_stop_reason='EMERGENCY STOP'
            self.shadow_mode_button.configure(text='ARM SHADOW (NO REAL ORDERS)')
            self.shadow_mode_status.set('SHADOW OFF • emergency STOP remains latched')
        if self.broker:self.broker.disarm(emergency=True)
        else:self.ledger.set_setting('halted','1')
        self.status.set('EMERGENCY STOP LATCHED • no new orders');self.trader_label.set('STOP LATCHED • any already-submitted Coinbase orders must be checked directly')
    def _release(self):
        if not messagebox.askyesno('Release emergency stop','Have you checked open Coinbase orders, positions and fills? Clearing STOP does NOT arm trading.'):
            return
        try:
            if not self.broker:raise LiveBlocked('Connect Coinbase first')
            self.broker.release_stop();self.status.set('DISARMED • emergency stop cleared')
        except Exception as ex:messagebox.showerror('Stop release',str(ex))
    def _watchlist(self,advance=False):
        """Study eligible spot markets independently of existing holdings.

        Holdings are authorized trade funding, NOT a research ranking input.
        Dollar-conversion anchor quotes consume only a few fixed priority slots;
        otherwise mature scout results and a balanced fallback span the catalog.
        """
        if not self.catalog:return []
        valid=set(self.catalog)
        anchors=[p for p in ('BTC-USD','ETH-USD','SOL-USD','USDC-USD') if p in valid]
        capacity=max(getattr(self,'max_focus_pairs',22),len(anchors))
        # Ensure actual crypto-quoted markets reach 64-pair deep research.
        # The cohort is selected without reference to personal holdings.
        cross_priority=priority_cross_cohort(self.catalog,anchors,capacity=capacity,
            cohort_epoch=int(time.time())//2700)
        required=anchors+cross_priority
        other=balanced_market_universe(self.catalog,reserved=required)
        planner=getattr(self,'focus_planner',None)
        if planner is not None:
            plan=planner.select(required,required+other,capacity=capacity)
            self._last_focus_plan=plan
            return plan['watch']
        slots=max(0,capacity-len(required));chosen=[]
        if other and slots:
            start=self.next_pair_idx%len(other)
            chosen=[other[(start+i)%len(other)] for i in range(min(slots,len(other)))]
            if advance:
                self._focus_cycles+=1
                if self._focus_cycles>=10:
                    self.next_pair_idx=(start+slots)%len(other)
                    self._focus_cycles=0
        return required+chosen


    def _full_exit_research(self):
        """Gross valuation of complete enrolled liquid inventory, NOT orders.

        This separate inventory view never consumes AI Lab priority slots.
        Missing quotes, USD FX or Coinbase-verified available qty fail closed.
        """
        now=time.time()
        fresh = self._last_portfolio_sync_monotonic and (
            time.monotonic()-self._last_portfolio_sync_monotonic <= 300)
        allowed=set(self.catalog)
        # Research-only complete-holding exit view must see the independently
        # refreshed Coinbase portfolio books, not just 64 deep-study pairs.
        # Do NOT feed these read-only quotes into the executable SELL broker.
        quote_map=self._shadow_valuation_books()
        # READ-ONLY full-quantity research NEVER disappears when a proposed
        # manual order cap exceeds legacy LIVE capacity. The broker's approved
        # conservative limit is used ONLY to show how many hypothetical LIVE
        # order slices a full exit would take, not to reduce research quantity.
        per_order=research_preview_slice_cap(
            getattr(self.broker,'per_order_max',None),
            TIERS[current_stage(self.ledger)].order)
        reports=[]
        for row in self.ledger.assets():
            asset=row['asset']
            if asset=='USD' or not row.get('enabled',1) or dec(row['remaining_qty'])<=0:
                continue
            choices=[p for p in quote_map if p in allowed and p.startswith(asset+'-')]
            choices.sort(key=lambda p:(p.split('-')[1]!='USD',p))
            item={'asset':asset,'state':'WAIT','pair':'—','gross_usd_before_fees':None,
                  'min_cap_slices_estimate':None,'reason':'No fresh quote for a supported sell-side product'}
            if not fresh:
                item['reason']='Coinbase available balances not verified within five minutes'
            elif not choices:
                item['reason']='No fresh sell-side quote in current cohort; not necessarily untradable'
            else:
                for pair in choices:
                    bid,ask,at=quote_map[pair]
                    quote=pair.split('-')[1]
                    conversion=usd_conversion(quote,quote_map,now=now,max_age=180)
                    if conversion is None:continue
                    try:
                        preview=full_holding_exit_preview(
                            authorized_qty=row['remaining_qty'],
                            verified_available_qty=self.current_balances.get(asset,'0'),
                            bid_quote=bid,quote_to_usd=conversion['rate'],
                            usd_per_order_cap=per_order,price_age_s=now-at,
                            balance_age_s=time.monotonic()-self._last_portfolio_sync_monotonic)
                    except (ValueError,TypeError,ArithmeticError) as exc:
                        item['reason']=str(exc);continue
                    item.update(preview);item['pair']=pair
                    item['reason']='Complete authorized liquid quantity, BEFORE fees; NOT a trade signal or guaranteed gain'
                    break
                if item['state']=='WAIT' and item['reason'].startswith('No fresh'):
                    item['reason']='No independently verifiable fresh quote→USD conversion'
            reports.append(item)
        return reports

    def _review_sell_inventory(self):
        """Evaluate SELL/HOLD on a fresh observed bid for each enrolled coin.

        READ-ONLY. No simulated fills, broker call or live arming. Prefer USD
        quotes for a basis recorded in dollars; use USDC if it is the only
        fresh eligible quotation. A stale preferred pair must not hide an
        actionable quote on another eligible pair.
        """
        results=[];now=time.time()
        # Sell/HOLD is informational FULL-ENROLLED-AVAILABLE research. Neither
        # legacy broker default $5 nor edited LIVE limits may restrict the
        # displayed value or fee-aware assessment, even while LIVE is armed.
        # The production broker retains its independent frozen order caps.
        balances_fresh=bool(self._last_portfolio_sync_monotonic and
            0<=time.monotonic()-self._last_portfolio_sync_monotonic<=300)
        for asset in self.ledger.assets():
            base=asset['asset'];enrolled_qty=dec(asset['remaining_qty'])
            if base in ('USD','USDC') or enrolled_qty<=0:continue
            if not asset.get('enabled',1):
                results.append(dict(pair=base,bid=None,value=None,action='EXCLUDED',reason='User excluded asset from management'))
                continue
            qty=verified_full_sell_quantity(enrolled_qty,self.current_balances.get(base),
                                            fresh=balances_fresh)
            if qty is None:
                results.append(dict(pair=base,bid=None,value=None,action='WAIT',
                    reason='Coinbase available quantity missing, invalid, or older than 5 minutes; no full-value guess'))
                continue
            if qty<=0:
                results.append(dict(pair=base,bid=None,value=None,action='WAIT',
                    reason='No independently verified available enrolled units; reserved/staked units excluded'))
                continue
            pairs=[base+'-'+q for q in ('USD','USDC') if base+'-'+q in self.catalog]
            if not pairs:
                results.append(dict(pair=base,bid=None,value=None,action='WAIT',reason='No eligible USD/USDC spot pair'))
                continue
            options=[]
            for pair in pairs:
                rows=self.lab.observations(pair)
                if rows and 0<=now-rows[-1][0]<=180 and rows[-1][1]>0:
                    options.append((pair,rows[-1][1]))
            if not options:
                results.append(dict(pair=base,bid=None,value=None,action='WAIT',reason='No fresh live sell bid in a watched pair'))
                continue
            pair,bid=options[0]  # USD preferred; only freshly observed candidates
            value=qty*bid
            if asset.get('snapshot_unit_usd') is not None and not pair.endswith('-USD'):
                results.append(dict(pair=pair,bid=bid,value=value,action='WAIT',reason='USD performance mark requires fresh USD sell pair; no implicit USDC/USD conversion'))
                continue
            if asset.get('trading_basis_unit_quote') is None:
                action='BLOCKED';reason='A held lot has no approved market-performance mark; inspect inventory lots'
            elif value<1:
                action='WAIT';reason='Full verified holding below $1 research minimum (product-specific limits still apply)'
            else:
                # While DISARMED, use operator's research-only preview target;
                # once ARMED, always use the separately authorized live target.
                target=self.target_net_usd if self.broker and self.broker.armed else self.preview_target_net_usd
                tier=self.fee_learning.latest_tier()
                policy=self.lab.recommendation(pair,bid,
                    sell_fee=(tier['taker'] if tier['fresh'] else None),
                    target_net_usd=target,planned_quote_value=value)
                action=policy['action'];reason=policy['reason']
                if action=='SELL' and policy['net_pct']<0:
                    reason='PROTECTIVE EXIT • '+reason
            results.append(dict(pair=pair,bid=bid,value=value,action=action,reason=reason))
        # Cross-currency SELL opportunities are compared in conservative USD
        # terms for display ONLY. Existing execution and FIFO disposal pathways
        # cannot safely settle crypto quote lots or timestamped USD costs yet.
        watch=getattr(self,'_last_research_watch',None) or self._watchlist(advance=False)
        quote_map={}
        for name in watch:
            observations=self.lab.observations(name)
            if observations:
                stamp,b,a=observations[-1]
                quote_map[name]=(b,a,stamp)
        for asset in self.ledger.assets():
            base=asset['asset'];enrolled=dec(asset['remaining_qty'])
            if base in USD_QUOTES or enrolled<=0 or not asset.get('enabled',1):continue
            qty=verified_full_sell_quantity(enrolled,self.current_balances.get(base),
                                            fresh=balances_fresh)
            if qty is None or qty<=0:
                results.append(dict(pair=base,bid=None,value=None,action='RESEARCH WAIT',
                    reason='Cross-quote SELL research needs fresh verified liquid enrolled quantities'))
                continue
            for name in watch:
                if not name.startswith(base+'-'):continue
                quote=name.split('-')[1]
                if quote in USD_QUOTES:continue
                latest=quote_map.get(name)
                if not latest or not 0<=now-latest[2]<=180:continue
                bid=latest[0]
                conversion=usd_conversion(quote,{k:v for k,v in quote_map.items() if k!=name},now=now,max_age=180)
                if conversion is None:
                    results.append(dict(pair=name,bid=bid,value=None,action='RESEARCH WAIT',
                        reason=f'Cannot verify fresh {quote}/USD conversion; cross-quote trading disabled'))
                    continue
                usd_bid=bid*conversion['rate']
                value=qty*usd_bid
                if value<1:
                    results.append(dict(pair=name,bid=bid,value=value,action='RESEARCH WAIT',
                        reason='Full verified holding below $1 research minimum (no order preview)'))
                    continue
                quantity=value/usd_bid
                try:
                    # Historical performance marks are USD; never re-label a
                    # USDC-denominated opening lot as USD or infer original tax.
                    basis=self.ledger.sale_basis(base,quantity,'USD')['performance_basis']
                    target=self.target_net_usd if self.broker and self.broker.armed else self.preview_target_net_usd
                    tier=self.fee_learning.account_cost(name)
                    if not tier['fresh']:
                        results.append(dict(pair=name,bid=bid,value=value,action='RESEARCH WAIT',
                            reason='Authenticated fee tier missing; net USD preview cannot be computed'))
                        continue
                    preview=research_sell_preview(bid,conversion['rate'],available_base=qty,
                            usd_order_cap=value,basis_usd=basis,target_net_usd=target,
                            assumed_fee_rate=tier['taker'])
                    signal=preview['action']
                    action='RESEARCH SELL' if signal in ('SELL','PROTECTIVE EXIT') else 'RESEARCH HOLD'
                    results.append(dict(pair=name,bid=bid,value=value,action=action,
                        reason=f'{signal}: estimated net ${preview["net_usd"]:.3f} using fresh {quote}→USD quote path; read-only, no live cross-pair order'))
                except (ValueError,TypeError,ArithmeticError) as exc:
                    results.append(dict(pair=name,bid=bid,value=value,action='RESEARCH WAIT',
                        reason='USD lot-performance basis unverified: '+str(exc)[:150]))
        return results

    def _start_history(self,auto=False):
        if self._connection_requested or self._connection_in_progress:
            messagebox.showwarning('AI Lab','Wait for Coinbase connection to finish.');return
        if not self.broker or not self.catalog:
            if not auto:messagebox.showwarning('AI Lab','Connect to Coinbase and load the eligible spot catalog first.')
            return
        if self._history_requested or self._history_in_progress:
            self._log('Historical warm-up is already queued/running.');return
        # Only the user-initiated manual bootstrap disarms; unattended context
        # refresh neither arms nor places orders, and never replaces fresh signals.
        if not auto:
            self.broker.disarm()
            self.status.set('DISARMED • manual AI Lab historical warm-up')
        self._history_auto=bool(auto)
        self._history_requested=True;self._history_started_at=time.monotonic()
        self.lab_activity.set(('Automatic' if auto else 'Manual')+' hourly-candle catch-up queued • live signals remain separate')
        self.lab_heartbeat.set('Waiting for any active live quote scan to finish…' if self.worker_busy else 'Starting historical candle requests…')
        self.warm_button.configure(state='disabled')
        self._start_history_if_ready()

    def _start_history_if_ready(self):
        if not self._history_requested or self._history_in_progress or self.worker_busy or self.shutdown:return
        if not self.broker or not self.catalog:
            self._history_requested=False;self.warm_button.configure(state='normal');return
        if self._fast_due(): return
        self._history_requested=False;self._history_in_progress=True
        watch=self._watchlist(advance=False)
        self.lab_progress.start(16)
        self._log(('AUTO CATCH-UP' if self._history_auto else 'MANUAL CATCH-UP')+
                  ': fetch recent Coinbase hourly context for '+str(len(watch))+
                  ' pairs (last 10 days maximum, incremental where cached).')
        def task():
            total=len(watch);stored=0;done=0;errors=[];cached=0
            # Bounded concurrency to respect public endpoint rate limits.
            with ThreadPoolExecutor(max_workers=3) as pool:
                ranges={p:self.forward.history_refresh_window(p) for p in watch if not self.forward.history_current(p)}
                jobs={pool.submit(fetch_public_hourly_range,p,*r):p for p,r in ranges.items()}
                cached=total-len(jobs)
                done=cached
                self.jobs.put(('history_progress',f'Historical candles • cached {cached}/{total} pairs; fetching {len(jobs)}'))
                for future in as_completed(jobs):
                    self._service_fast_checkpoint()
                    pair=jobs[future];done+=1
                    try:
                        candles=future.result();count=self.forward.save_history(pair,candles)
                        if count<1:raise ValueError('No valid recent hourly candles')
                        stored+=count;self.jobs.put(('history_progress',f'{done}/{total} • {pair}: {count} hourly candles stored'))
                    except Exception as ex:
                        errors.append((pair,str(ex)[:110]))
                        self.jobs.put(('history_progress',f'{done}/{total} • {pair}: unavailable ({type(ex).__name__})'))
            return {'kind':'history','pairs':total,'cached':cached,'candles':stored,'errors':errors,
                    'auto':self._history_auto,'storage':self.forward.history_health()}
        if not self._async(task,operation='10-day history'):
            self._history_requested=True;self._history_in_progress=False

    def _train_gpu(self):
        """Manual diagnostic override; same research-only path as scheduled training."""
        self._launch_gpu_research(automatic=False)

    def _launch_gpu_research(self,automatic=True):
        # Training runs in a dedicated background worker so it does not block
        # the market-scan/portfolio worker. It never modifies broker or tax lots.
        schedule=self._gpu_schedule
        now=time.monotonic()
        broker=self.broker
        not_safe=(self.shutdown or not broker or not self.catalog
            or bool(getattr(broker,'armed',False)) or bool(self.ledger.setting('halted','0')=='1')
            or bool(self.ledger.pending()) or self.worker_busy or self._scan_processing
            or self._history_in_progress or self._connection_in_progress)
        try:disk_free=shutil.disk_usage(ROOT).free
        except OSError:disk_free=0
        if not_safe or disk_free<256*1024*1024 or schedule.active:
            if not automatic:
                self.gpu_status.set('GPU research waiting for DISARMED, idle, connected and adequate disk; NO ORDERS')
            return False
        # Manual user action may trigger early; still reschedule with a cooldown.
        if not automatic:schedule.next_due=min(schedule.next_due,now)
        if not schedule.claim(now):return False
        self.gpu_status.set('GPU research '+('AUTO' if automatic else 'MANUAL')+
                            ' • training historical + forward market-only labels, no orders')
        # No manual GPU train button: scheduled CUDA worker owns the lifecycle.
        def task():
            from coincat_gpu_research import train_observe_only
            from coincat_v505_historical_gpu import probe_gpu
            runtime=probe_gpu()
            # No CPU fallback in a missing-CUDA packaged EXE; show BLOCKED rather
            # than claiming a GPU training run. Automatic retraining is optional.
            if runtime.get('status')!='CUDA_READY':
                return {'kind':'gpu','automatic':automatic,'report':{'status':'WAIT','labeled':0},
                        'runtime':runtime,'historical':{'status':'WAIT'}}
            # v60.5 redundancy review: the legacy hourly candle-direction
            # network predicted gross pair price, not our after-fee portfolio
            # objective. Retain archived reports for diagnostics, but DO NOT
            # launch that second training workload every time CoinCat starts.
            historical={'status':'LEGACY_CONTEXT_ONLY_NOT_RETRAINED'}
            forward=train_observe_only(self.forward.path,ROOT/'gpu_research')
            return {'kind':'gpu','automatic':automatic,'report':forward,
                    'runtime':runtime,'historical':historical}
        def work():
            error_type=None
            try:self.jobs.put(('ok',task()))
            except Exception as ex:
                error_type=type(ex).__name__
                self.jobs.put(('error',{'operation':'GPU research','message':error_type}))
            finally:schedule.finish(time.monotonic(),exception_type=error_type)
        threading.Thread(target=work,daemon=True,name='CoinCat-ObserveOnly-GPU').start()
        return True

    def _scan_now(self):
        if self._history_requested or self._history_in_progress:
            self._log('Scan NOW: wait for the historical load to finish.');return
        if self.worker_busy:
            self._log('Scan NOW: current background task still running; no duplicate request.');return
        self._scan_started_at=time.monotonic()
        self._scan_processing=True
        self._next_scan_at=self._scan_started_at+self.loop_secs
        self.lab_activity.set('Reading fresh live Coinbase bid/ask quotes (manual, no orders)')
        self.lab_progress.start(16)
        if self._async(lambda:self._cycle(allow_orders=False),operation='manual research scan'):
            self._log('MANUAL LIVE QUOTE SCAN started • this command will NOT submit orders.')
        else:self._scan_processing=False

    def _verify_last_order_now(self):
        if not self.broker:
            self.fill_sync_status.set('Read-only check: connect Coinbase first')
            return False
        if self.worker_busy:
            self.fill_sync_status.set('Read-only check: background operation busy; try again shortly')
            return False
        self.fill_sync_status.set('Read-only Coinbase order/fill verification in progress • no trades')
        return self._async(lambda:{'kind':'filled_order_check',
            'result':verify_latest_filled_order(self.broker.client,self.ledger)},
            operation='read-only fill check')

    def _sync_order_now(self):
        """Reconcile ONLY previously submitted orders, never create new ones."""
        if not self.broker:
            self.fill_sync_status.set('Fill sync: connect Coinbase first • no new orders')
            return False
        if self._fill_sync_faulted:
            self.fill_sync_status.set('Fill sync paused after uncertainty; check Coinbase and diagnose before retrying')
            return False
        if self.worker_busy:
            self.fill_sync_status.set('Fill sync queued by next idle opportunity • existing research worker busy')
            return False
        self._last_fill_poll=time.monotonic()
        self.fill_sync_status.set('Checking Coinbase existing order and verified fills • NO NEW ORDERS')
        return self._async(lambda:{'kind':'fill_sync','reconcile':self.broker.reconcile()},operation='fill sync')

    def _tick(self):
        """Protect periodic scheduling from an unexpected Tk callback failure.

        If UI processing fails, immediately DISARM and resume the watcher;
        NEVER recover by retrying a possibly transmitted Coinbase order.
        """
        now_tick=time.monotonic()
        prior_tick=self._last_tick_heartbeat
        if prior_tick and now_tick-prior_tick>120:
            # Sleep/disconnect gap is missing market evidence, never pretend that
            # skipped intervals contained verified quotes or hypothetical fills.
            self._research_resume_gap_s=now_tick-prior_tick
            self._research_resume_at=time.time()
            try:self.lab_activity.set('RESUMED AFTER OBSERVATION GAP • fresh bid/ask maturity rebuilding; SHADOW evidence is not backfilled')
            except (AttributeError,tk.TclError):pass
        self._last_tick_heartbeat=now_tick
        try:
            return self._tick_impl()
        except Exception as exc:
            self._last_ui_callback_error_type=type(exc).__name__
            self._last_ui_callback_error_origin='tick'
            if self.broker:
                self.broker.disarm()
            # A callback failure cannot be taken as a successful market scan.
            try:
                self.status.set('DISARMED • tick callback error; inspect diagnostics')
                self._log('TICK CALLBACK ERROR • '+type(exc).__name__+' • no automatic submit retry')
            except Exception:
                pass
            if not self.shutdown:
                self._scheduled['tick']=self.root.after(1000,self._tick)

    def _fast_due(self):
        """A scout alert is urgency, never trading permission or a research gate."""
        return bool(self.broker and self.catalog and not self.shutdown
            and time.monotonic()>=self._fast_next_at
            and not self._connection_requested and not self._connection_in_progress
            and not self._fill_sync_faulted and not self.broker.ledger.pending()
            and 0<=time.monotonic()-self._last_portfolio_sync_monotonic<=120
            and self.stream_research.rank_for_rest_scout(self.catalog,now=time.time(),limit=1))

    def _service_fast_checkpoint(self):
        # Called ONLY on the existing serial market/history worker, between
        # completed requests. No parallel planners or RAM-wallet SQLite access.
        if not self._fast_due(): return False
        self._fast_next_at=time.monotonic()+self._fast_interval_s
        self._fast_queued_at=time.monotonic()
        self.jobs.put(('ok',self._fast_cycle()))
        return True

    def _tick_impl(self):
        if self.shutdown:return
        now=time.monotonic()
        busy=(self.worker_busy or self._connection_requested or self._connection_in_progress
              or self._scan_processing)
        needs_sync=bool(self.broker and
                    now-self._last_portfolio_sync_monotonic>=min(120,self.portfolio_sync_secs))
        needs_fills=bool(self.broker and self.broker.ledger.pending())
        # Account verification/reconciliation always precede market research.
        # Urgent opportunities precede full scans and automatic history/GPU work.
        if not busy and not needs_sync and not needs_fills and self._fast_due():
            self._fast_next_at=now+self._fast_interval_s
            self._fast_queued_at=now
            self._async(self._fast_cycle,operation='fast Snowball research')
        elif (now>=self._next_scan_at and not busy and not needs_sync and not needs_fills
                and not self._history_in_progress and self.broker and self.catalog):
            self._scan_started_at=now
            self._scan_processing=True
            self._scan_epoch+=1
            self.lab_activity.set('Scanning live Coinbase bid/ask quotes…')
            self.lab_progress.start(16)
            if self._async(lambda:self._cycle(allow_orders=True),operation='market scan'):
                self._next_scan_at=now+self.loop_secs
            else:self._scan_processing=False
        if (self.broker and self.catalog and not self._connection_requested
                and not self._connection_in_progress and not self._history_requested
                and not self._history_in_progress and not self.worker_busy
                and not self._scan_processing and not needs_sync and not needs_fills
                and time.monotonic()-self._auto_history_checked>3600):
            self._auto_history_checked=time.monotonic()
            watch=self._watchlist(advance=False)
            if any(not self.forward.history_current(p) for p in watch):
                self._log('AUTO CATCH-UP: refreshing background context; urgent checks take priority.')
                self._start_history(auto=True)
        if (self._gpu_schedule.next_due<=now and not self._gpu_schedule.active
                and self.broker and self.catalog and not self.worker_busy
                and not self._scan_processing and not self._history_in_progress
                and not self._connection_in_progress and not needs_sync and not needs_fills):
            self._launch_gpu_research(automatic=True)
        self._scheduled['tick']=self.root.after(1000,self._tick)

    def _finish_fast(self,result,started):
        now=time.monotonic()
        result['research_duration_s']=round(now-started,3)
        self._fast_next_at=max(getattr(self,'_fast_next_at',0),now+1)
        return result

    def _fast_cycle(self):
        """Between-scan urgency research using the EXISTING unified planner.

        Uses public REST executable-side research quotes, but never calls the
        authenticated broker preview, live ARM, or order POST. The live broker's
        independent controls are untouched. No independent trading engine.
        """
        started=time.monotonic()
        result={'kind':'fast_snowball','state':'WAIT','reason':'NO_STREAM_ALERTS',
                'alerts':0,'selected':0,'fetched':0,'failed':0,'targets':0,
                'plan':{},'snowball':{},'quote_pairs':[],'captured_at':time.time(),
                'live_order_permission':False,'route_count':0}
        if not self.broker or not self.catalog:return self._finish_fast(result,started)
        now_mono=time.monotonic()
        balance_age=now_mono-self._last_portfolio_sync_monotonic if self._last_portfolio_sync_monotonic else float('inf')
        if not 0<=balance_age<=120 or getattr(self,'external_mismatches',[]):
            result['reason']='STALE_OR_MISMATCHED_ENROLLED_BALANCES';return self._finish_fast(result,started)
        tier=self.fee_learning.latest_tier()
        if not tier.get('fresh'):
            result['reason']='FEE_EVIDENCE_UNAVAILABLE';return self._finish_fast(result,started)
        alerts=self.stream_research.rank_for_rest_scout(self.catalog,now=time.time(),limit=12)
        result['alerts']=len(alerts)
        sources=[str(row.get('asset','')).upper() for row in self.ledger.assets()
                 if row.get('enabled',1) and Decimal(str(row.get('remaining_qty','0')))>0]
        if self.experimental_shadow.armed and self._experimental_model_balances:
            sources=[a for a,q in self._experimental_model_balances.items()
                     if Decimal(str(q))>0 and a not in getattr(self,'_experimental_excluded_assets',())]
        cached_assets=set(sources)
        if self.shadow_pilot.armed: cached_assets.update(getattr(self,'_shadow_model_balances',{}))
        if self.experimental_shadow.armed: cached_assets.update(getattr(self,'_experimental_model_balances',{}))
        required=required_shadow_assets(self.experimental_shadow,self.shadow_pilot,funding=cached_assets)
        before_quotes=self._shadow_valuation_books()
        plan=select_fast_books(alerts,self.catalog,sources,required_assets=required,
                              quotes=before_quotes,now=time.time())
        result['required_mark_assets']=required
        result['unlisted_mark_assets']=plan['unlisted_mark_assets']
        result['queue_delay_ms']=round(max(0,started-getattr(self,'_fast_queued_at',started))*1000,2)
        result['selected']=len(plan['targets']);result['book_requests']=len(plan['books'])
        stream_rows=self.stream_research.snapshot(now=time.time()).get('rows',())
        latest={r.get('pair'):r.get('last_trade') for r in stream_rows}
        ages=[r['age_ms'] for r in stream_rows if r.get('pair') in plan['books'] and r.get('age_ms') is not None]
        result['alert_age_ms']=max(ages) if ages else None
        fingerprint=tuple((p,str(latest.get(p))) for _,p in plan['targets'])
        if (fingerprint and fingerprint==self._fast_candidate_signature and
                time.monotonic()-self._fast_candidate_signature_at<10):
            result['reason']='STREAM_PRICES_UNCHANGED_COOLDOWN';return self._finish_fast(result,started)
        result['selected_pairs']=[p for a,p in plan['targets']]
        if not plan['books'] and not plan['targets']:
            result['reason']='NO_DIRECTLY_FUNDABLE_STREAM_ALERTS';return self._finish_fast(result,started)
        snapshots,errors,fetch_ms=SCOUT.collect(plan['books'],fetch=fetch_snapshot)
        result['get_errors']=errors
        result['failed']=sum(errors.values())
        result['fetch_ms']=fetch_ms
        result['quote_provenance']={'source':'COINBASE_PUBLIC_REST_BEST_BID_ASK',
            'age_basis':'LOCAL_REQUEST_START','exchange_timestamp_verified':False,
            'depth_verified':False}
        result['request_latency_ms']=percentiles([b.request_ms for b in snapshots.values()])
        for pair,book in snapshots.items():
            self.forward.record_quote(pair,book.observed_at,book.bid,book.ask,source=book.source)
            result['quote_pairs'].append(pair)
        result['fetched']=len(snapshots)
        valuation_quotes=newest_books(self._shadow_valuation_books(),now=time.time(),max_age=25)
        quotes=newest_books(valuation_quotes,now=time.time(),max_age=25,max_spread=Decimal('.0025'))
        coverage=mark_coverage(required,valuation_quotes,now=time.time(),max_age=25,
                               max_spread=DISPLAY_MAX_SPREAD,max_legs=3)
        result['mark_coverage']={k:v for k,v in coverage.items() if k not in ('rates','problems')}
        result['mark_coverage']['problem_counts']={reason:list(coverage['problems'].values()).count(reason)
            for reason in sorted(set(coverage['problems'].values()))}
        result['fresh_books']=len(newest_books(
            {p:q.book() for p,q in snapshots.items()},now=time.time(),max_age=25,max_spread=Decimal('.0025')))
        # A failed mark fetch cannot trigger the unchanged-alert cooldown.
        if not coverage['complete'] or plan['mark_refresh_deferred']:
            result['reason']='MARK_REFRESH_DEFERRED' if plan['mark_refresh_deferred'] else 'INCOMPLETE_FRESH_QUOTES'
            return self._finish_fast(result,started)
        stream=self.stream_research.snapshot(now=time.time())
        candidates,rejected=fast_candidates(plan['targets'],quotes,stream,now=time.time())
        result['targets']=len(candidates);result['candidate_quote_rejects']=rejected
        if not candidates:
            result['reason']='NO_FRESH_NARROW_SPREAD_TARGET_BOOKS';return self._finish_fast(result,started)
        if not errors:
            self._fast_candidate_signature=fingerprint
            self._fast_candidate_signature_at=time.monotonic()
        planner_started=time.monotonic()
        rate=tier['taker']
        fee_rates={p:rate for p in self.catalog}
        if self.experimental_shadow.armed and self._experimental_model_balances:
            from coincat_v605_shadow_bridge import shadow_screen
            result['experimental_model_snapshot']=dict(self._experimental_model_balances)
            researched=shadow_screen(balances=result['experimental_model_snapshot'],
                excluded=getattr(self,'_experimental_excluded_assets',()),
                buy_signals=(),age_s=balance_age,catalog=self.catalog,quotes=quotes,
                product_rules=getattr(self.broker,'catalog_product_rules',{}),
                portfolio_usd_cap=Decimal('1e24'),now=time.time(),
                fee_rates_by_pair=fee_rates,relative_evidence=self.relative_lab.paired_outcomes,
                exploratory_candidates=candidates, direct_only=True,max_targets=3)
        else:
            from coincat_v605_shadow_bridge import shadow_screen
            balances={}
            for row in self.ledger.assets():
                if not row.get('enabled',1):continue
                asset=str(row.get('asset','')).upper()
                try:
                    qty=min(Decimal(str(row.get('remaining_qty',0))),
                            Decimal(str(self.current_balances.get(asset,0))))
                    if qty>0:balances[asset]=str(qty)
                except (InvalidOperation,TypeError,ValueError):continue
            researched=shadow_screen(balances=balances,excluded=(),buy_signals=(),
                age_s=balance_age,catalog=self.catalog,quotes=quotes,
                product_rules=getattr(self.broker,'catalog_product_rules',{}),
                portfolio_usd_cap=Decimal('1e24'),now=time.time(),
                fee_rates_by_pair=fee_rates,relative_evidence=self.relative_lab.paired_outcomes,
                exploratory_candidates=candidates,direct_only=True,max_targets=3)
        # Validated SHADOW may observe urgent research using its own modeled
        # wallet, but its held-out OOS qualification remains unchanged.
        if self.shadow_pilot.armed and self._shadow_model_balances:
            from coincat_v605_shadow_bridge import shadow_screen
            result['validated_model_snapshot']=dict(self._shadow_model_balances)
            result['validated_plan']=shadow_screen(
                balances=result['validated_model_snapshot'],
                excluded=getattr(self,'_shadow_excluded_assets',()),
                buy_signals=(),age_s=balance_age,catalog=self.catalog,quotes=quotes,
                product_rules=getattr(self.broker,'catalog_product_rules',{}),
                portfolio_usd_cap=Decimal('1e24'),now=time.time(),
                fee_rates_by_pair=fee_rates,relative_evidence=self.relative_lab.paired_outcomes,
                exploratory_candidates=candidates,direct_only=True,max_targets=3)
        result['plan']=researched
        ideas,stats=snowball_screen(researched.get('ideas') or (),quotes,now=time.time(),
            taker_fee=rate,minimum_usd=str(self.switch_minimum_usd))
        result['plan']=dict(researched,ideas=ideas)
        result['snowball']=stats
        result['planner_ms']=round((time.monotonic()-planner_started)*1000,2)
        result['state']='RESEARCHED'
        result['reason']='EXPERIMENT_READY' if self.experimental_shadow.armed else 'READ_ONLY_RESEARCH'
        result['captured_at']=time.time()
        result['research_duration_s']=round(time.monotonic()-started,2)
        return self._finish_fast(result,started)

    def _cycle(self,allow_orders=True):
        result={'kind':'cycle','strategy_horizons':{'state':'NOT_RUN'},'strategy_research':{'state':'NOT_RUN'},'gpu_advisory':{},'quotes':0,'failures':0,'signals':[],'reviews':[],'handoffs':[],'sell_reviews':[],'full_exit_reviews':[],'trade':None,'reconcile':None,'message':'','storage':None,'two_way':None,'rotation':[],'auto_rotation':{'state':'WAIT','reason':'Not yet evaluated','ideas':[]},'broker_pair_reviews':[],'cross_spot_previews':[],'discovery':{'sampled':0,'failed':0,'coverage':0,'total':0,'progress':0}}
        if self.broker:
            try:
                result['reconcile']=self.broker.reconcile()
            except Exception as ex:
                self.broker.disarm();result['message']='Order reconciliation stopped live trading: '+str(ex)
                return result
        # Realtime quotes are separate from the prior 10-day OHLCV context.
        watch=self._watchlist(advance=True)
        self._last_research_watch=list(watch)
        result['focused_discovery']=dict(getattr(self,'_last_focus_plan',{}))
        result['catalog_quote_mix']=quote_mix(self.catalog)
        result['registry_audit']=dict(getattr(self.broker,'catalog_registry_audit',{}) or {})

        result['focused_quote_mix']=quote_mix(watch)
        # Optional read-only Coinbase product-book microstructure: at most one
        # authenticated pair per 10 minutes, never a duplicate quote journal,
        # order preview, authority, or a substitute for later bid/ask outcomes.
        # Nonblocking *advisory*, on a separate daemon; never wait for extra
        # REST calls in the quote scan, SHADOW planner or UI thread. If a GET
        # hangs, the one-in-flight guard prevents a new accumulating queue.
        result['authenticated_market_probe']=dict(getattr(self,'_depth_probe_result',
            {'state':'NOT_OBSERVED','extra_gets':0}))
        pending=getattr(self,'_depth_probe_pending',False)
        if (self.broker and watch and not pending and
            time.monotonic()-getattr(self,'_last_depth_probe_at',0)>600):
            allowed=set(one_order_catalog(self.catalog,getattr(self.broker,'catalog_product_rules',{})))
            candidates=[p for p in watch if p in allowed]
            previous=((getattr(self,'last_cycle',{}) or {}).get('auto_rotation',{}) or {}).get('ideas',[]) or []
            evidence_pair=next((str(idea.get('trigger_pair','')) for idea in previous
                                if str(idea.get('trigger_pair','')) in candidates),None)
            sample=evidence_pair or (candidates[int(time.monotonic()//600)%len(candidates)] if candidates else None)
            if sample:
                self._depth_probe_pending=True
                self._last_depth_probe_at=time.monotonic()
                client=self.broker.client
                def _background_depth_probe():
                    try:
                        from coincat_v6010_microstructure import bounded_readonly_probe
                        self._depth_probe_result=bounded_readonly_probe(client,sample)
                    except Exception:
                        self._depth_probe_result={'state':'OPTIONAL_READ_ONLY_UNAVAILABLE','extra_gets':0}
                    finally:
                        self._depth_probe_pending=False
                threading.Thread(target=_background_depth_probe,
                    name='CoinCatReadOnlyDepthAdvisory',daemon=True).start()
                result['authenticated_market_probe']={'state':'ASYNC_PENDING','extra_gets':0}

        result['stream_telemetry']=self.stream_research.snapshot()
        result['adaptive_focus']=self.focus_capacity.snapshot()
        self.stream.set_pairs(self.catalog)  # ALL authenticated eligible spot pairs; public trade tickers ONLY
        self.jobs.put(('scan_progress',f'Scanning {len(watch)} eligible pairs for fresh bid/ask…'))
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(fetch_snapshot,p):p for p in watch}
            for future in as_completed(futures):
                self._service_fast_checkpoint()
                pair=futures[future]
                try:
                    quote=future.result()
                    self.forward.record_quote(pair,quote.observed_at,quote.bid,quote.ask,source=quote.source)
                    result['quotes']+=1
                    self.jobs.put(('scan_progress',f'Quote {result["quotes"]+result["failures"]}/{len(watch)} • {pair} bid/ask verified'))
                except Exception as ex:
                    result['failures']+=1
                    self.jobs.put(('scan_progress',f'Quote {result["quotes"]+result["failures"]}/{len(watch)} • {pair}: {type(ex).__name__}'))
        # Explore the wider catalog with one-off public ticker snapshots. These
        # are stored in a SEPARATE latest-only table so they cannot mature a
        # BUY signal or become a forward trade label. Live order policy unchanged.
        if self.catalog:
            cursor=self.forward.get_state_int('universe_discovery_cursor',0)
            rotation,next_cursor=choose_discovery(self.catalog,watch,cursor,self.discovery_per_cycle)
            # Any actively trading rare pair can request EXTRA REST scouting,
            # never replace the systematic rotation that observes silent pairs.
            # Event-driven scout budget expands with healthy research throughput,
            # but complete-catalog rotation always gets its 12 guaranteed slots.
            stream_scout_budget=max(4,min(12,self.max_focus_pairs//8))
            extra=getattr(self.stream_research,'rank_for_rest_scout',lambda *a,**kw:[])(
                self.catalog,exclude=set(watch)|set(rotation),now=time.time(),limit=stream_scout_budget)
            scouts=rotation+[p for p in extra if p not in rotation]
            sampled=failed=0
            self.jobs.put(('scan_progress',f'Deep study {len(watch)} done; sampling {len(rotation)} rotating + {len(extra)} stream-alert catalog pairs (REST verification; research only)…'))
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures={pool.submit(fetch_snapshot,p):p for p in scouts}
                for future in as_completed(futures):
                    self._service_fast_checkpoint()
                    pair=futures[future]
                    try:
                        quote=future.result()
                        self.forward.record_discovery(pair,quote.observed_at,quote.bid,quote.ask)
                        sampled+=1
                    except Exception:
                        failed+=1
            self.forward.set_state_int('universe_discovery_cursor',next_cursor)
            coverage=self.forward.universe_coverage(self.catalog)
            result['discovery']={'sampled':sampled,'failed':failed,'coverage':coverage,
                                 'total':len(set(self.catalog)),
                                 'progress':round(100*coverage/max(1,len(set(self.catalog))),1),
                                 'stream_alerts_rest':len(extra),
                                 'stream_alert_budget':stream_scout_budget,
                                 'focused_capacity':len(watch)}
        # Bid/ask market observations supply counterfactual results for BOTH
        # sides; history candles and hypothetical labels are NEVER fills.
        direct_watch=[p for p in watch if p in set(one_order_catalog(self.catalog,
            getattr(self.broker,'catalog_product_rules',{}))) ]
        for pair in direct_watch:
            recent=self.lab.observations(pair)
            if recent:self.directional.record(pair,recent[-1][1],recent[-1][2])
        self.directional.evaluate()
        result['two_way']=self.directional.overview()
        # Keep daily/pressure-driven retention and weekly SQLite compaction.
        # Prune the additional public USD relative-mark research cache without
        # ever touching financial fills, cost basis or tax documents.
        self.relative_lab.maintenance(now=int(time.time()))
        maintenance=self.forward.maintenance()
        if time.time()-self._last_trials_cleanup>=86400:
            self.lab.prune_forward_trials()
            self.directional.prune()
            self._last_trials_cleanup=time.time()
        result['storage']=self.forward.history_health()
        if maintenance['over_limit'] and self.broker:self.broker.disarm();result['message']='Forward DB storage cap; trading stopped'
        if self.catalog:
            self.lab.update_trials(direct_watch,now=int(time.time()))
        fee_snapshot=self.fee_learning.latest_tier()
        result['fee_evidence_state']=fee_snapshot['state']
        result['fee_cost_screened']=0
        result['fee_below_cost']=0
        for pair in direct_watch:
            s=self.lab.signal(pair)
            if s.get('action')=='BUY':
                try:
                    # ONE direct Coinbase order, not an entry-and-later-exit round trip.
                    # Fee prescreen determines BUY-signal eligibility only;
                    # the currency-aware route planner prices the actual receipt independently.
                    screening=self.fee_learning.research_screen(
                        pair,s['momentum_pct'],s['spread_bps'],legs=1)
                    result['fee_cost_screened']+=1
                    if screening['state']=='MOMENTUM_BELOW_COST':
                        result['fee_below_cost']+=1
                        s=dict(s,action='WAIT',reason='Fee-informed research WAIT: observed momentum below authenticated '
                            'account-tier taker fees and slippage reserve (not a forward USD prediction)')
                    elif screening['state']=='UNVALIDATED_MOMENTUM_ABOVE_COST':
                        s=dict(s,reason=s['reason']+' | Fee tier screen passed; pair preview and forward USD alpha still unverified')
                    else:
                        s=dict(s,action='WAIT',reason='Account fee data unavailable; net USD evidence cannot be trusted')
                except Exception:
                    s=dict(s,action='WAIT',reason='Fee evidence validation unavailable; research WAIT')
            if s['action']=='BUY':result['signals'].append(s)
            observations=self.lab.observations(pair)
            history=self.forward.history_status(pair)
            trend=None
            if len(observations)>=2:
                first=(observations[0][1]+observations[0][2])/2
                last=(observations[-1][1]+observations[-1][2])/2
                if first>0:trend=float((last/first-1)*100)
            last=observations[-1] if observations else None
            cross=pair.split('-')[1] not in USD_QUOTES
            reason=s['reason'] + (' | SPOT RESEARCH ONLY; no live orders' if cross else '')
            result['reviews'].append({'pair':pair,'bid':last[1] if last else None,'ask':last[2] if last else None,
                'count':len(observations),'trend':trend,'history':history,'action':s['action'],'reason':reason})
        # One canonical bid/ask database also supports short-horizon, independent
        # observational feedback; NEVER a broker BUY signal or portfolio alpha.
        try:
            tier_for_windows=self.fee_learning.latest_tier()
            result['forward_windows']=research_summary(
                self.forward,[r['pair'] for r in result['reviews']],
                now=int(time.time()),
                fee_rate=(tier_for_windows['taker'] if tier_for_windows['fresh'] else None),
                max_pairs=12)
            if not tier_for_windows['fresh']:
                result['forward_windows']['state']='FEE_UNVERIFIED_DESCRIPTIVE_ONLY'
        except Exception as exc:
            result['forward_windows']={'state':'UNAVAILABLE_'+type(exc).__name__,
                'pair_count':0,'horizons':{}}
        # New original strategy comparisons share ONE genuine Coinbase REST quote
        # source. Every result is EXPLORE_ONLY until independent positive portfolio
        # HOLD-vs-SWITCH out-of-sample evidence passes the UNCHANGED planner.
        try:
            verified_tier=self.fee_learning.latest_tier()
            result['strategy_research']=self.strategy_lab.scan(
                [r['pair'] for r in result['reviews'] if r['pair'] in direct_watch],now=int(time.time()),
                fee_rate=verified_tier['taker'] if verified_tier['fresh'] else None)
        except Exception as exc:
            # A new strategy research failure may NEVER inhibit broker STOP,
            # fabricate an order, or silently turn a WAIT into BUY.
            result['strategy_research']={'state':'WAIT_'+type(exc).__name__,
                'studied_pairs':0,'patterns':{},'candidates':[],
                'may_authorize_orders':False}
        # V60.8: separately timestamped 5m/15m/60m forward outcomes in the
        # SAME canonical market DB. Only genuine later Coinbase REST bids are
        # outcomes; no filled orders, shadow finance or GPU predictions inferred.
        try:
            current_tier=self.fee_learning.latest_tier()
            result['strategy_horizons']=self.horizon_lab.record_and_mature(
                result['strategy_research'].get('candidates') or (),
                now=int(time.time()),fee_rate=(current_tier['taker'] if current_tier['fresh'] else None))
        except Exception as exc:
            result['strategy_horizons']={'state':'WAIT_'+type(exc).__name__,
                'matured':0,'eligible_for_shadow':False,'eligible_for_live':False}
        # Compute and display SELL/HOLD even when DISARMED; decisions alone never submit orders.
        result['sell_reviews']=self._review_sell_inventory()
        result['full_exit_reviews']=self._full_exit_research()
        # ROTATE comparisons are intentionally RESEARCH-ONLY. A two-leg
        # rotation has execution and tax risks and is not broker-enabled.
        result['rotation']=rotation_reviews(
            [item for item in result['sell_reviews'] if item['action'] in ('HOLD','SELL') and item.get('pair')],
            result['signals'],self.directional.stats)
        # Research-market-only USD marks: persisted, synchronized, independent
        # of account enrollment. No ledger writes, execution requests or orders.
        try:
            result['relative_mark_count']=self.relative_lab.observe(
                catalog=self.catalog,quotes=self._shadow_valuation_books(),
                now=time.time(),fee_verified=self.fee_learning.latest_tier()['fresh'])
        except Exception:
            result['relative_mark_count']=0
        # Existing single GPU model is evaluated ONCE per scan. It prioritizes
        # already-qualified BUY research candidates but never makes or authorizes
        # a signal, and SHADOW/LIVE consume the same candidate ordering.
        for candidate in result['signals'][:8]:
            try:
                result['gpu_advisory'][candidate['pair']]=gpu_research_advisory(
                    ROOT/'gpu_research',candidate['bid'],candidate['ask'],
                    spot_taker_fee=(fee_snapshot['taker'] if fee_snapshot['fresh'] else None))
            except Exception as exc:
                result['gpu_advisory'][candidate['pair']]={'status':'WAIT','reason':type(exc).__name__,
                    'affects_live_orders':False}
        # AI Lab and Auto Trader receive the SAME automatic rotation screen
        # every cycle. This is continuous SHADOW research, never an order
        # permission or a second brokerage execution path.
        try:
            # V60 RESEARCH ONLY: the old $10 capacity stage and manual live-order
            # dollar caps must not suppress a valid $100 or whole-enrolled-holding
            # counterfactual. Every route uses only its independently verified
            # available enrolled source units; neither this ceiling nor a model
            # can authorize a production order.
            from coincat_v60_research_sizing import funding_inventory_snapshot
            from coincat_relative_strength_research import rank_observed_markets
            research_books=self._shadow_valuation_books()
            funding=funding_inventory_snapshot(self.ledger.assets(),
                self.current_balances,research_books,self.catalog,now=time.time())
            cap=funding['funding_usd']
            result['research_portfolio_usd_ceiling']=cap
            result['research_funding_eligibility']={
                'considered':funding['considered_count'],
                'eligible':funding['eligible_count'],
                'excluded':funding['ineligible_count'],
                'partial':funding['partial'],
                'reasons':dict(funding['ineligible_reasons'])}
            # Exploratory feature research remains completely separate from
            # qualified BUY signals, broker reviews, and execution permission.
            # A wider bounded shortlist prevents a few historic strategies from
            # monopolizing destination research. Uses already-fetched REST books.
            # Zero new requests and no weakening of risk/profit checks.
            rank_capacity=max(4,min(12,4+len(result['reviews'])//16))
            exploratory=rank_observed_markets(result['reviews'],max_targets=rank_capacity)
            # Research-only alternatives get representation in the EXACT same
            # downstream planner, not a competing simulated broker/trader.
            # Bounded destination research, never converting EXPLORE_ONLY to BUY.
            alternatives=result['strategy_research'].get('candidates') or []
            extra=[];seen=set()
            for signal in alternatives:
                try:
                    pair=signal['pair']; base=pair.split('-')[0]
                    if base in seen or signal.get('action')!='EXPLORE_ONLY':continue
                    if signal.get('strategy')=='MOMENTUM_BASELINE':continue
                    seen.add(base)
                    extra.append({'pair':pair,'momentum_pct':signal['momentum_pct'],
                        'strategy':signal['strategy'],'action':'EXPLORE_ONLY'})
                except (KeyError,ValueError,TypeError):continue
                if len(extra)>=2:break
            merged=extra+list(exploratory['candidates'])
            # Favor upward moves over observed declines, and select the best
            # liquid quoted product for each asset, not the earliest appearance.
            def _rank_key(item):
                try:
                    movement=Decimal(str(item.get('momentum_pct',0)))
                    spread=Decimal(str(item.get('spread_bps',0)))
                    return (movement>0,movement-spread/Decimal('100'))
                except (ValueError,TypeError,InvalidOperation):
                    return (False,Decimal('-999'))
            merged.sort(key=_rank_key,reverse=True)
            by_asset={}
            for item in merged:
                asset=item['pair'].split('-')[0]
                if asset not in by_asset:by_asset[asset]=item
            exploratory['candidates']=list(by_asset.values())[:rank_capacity]
            result['exploratory_market_research']={
                'eligible_markets':exploratory['eligible_markets'],
                'ranked':len(exploratory['candidates']),
                'rising_prioritized':sum(_rank_key(x)[0] for x in exploratory['candidates']),
                'shortlist_capacity':rank_capacity,
                'method':exploratory['method']}
            balance_age=(time.monotonic()-self._last_portfolio_sync_monotonic
                if self._last_portfolio_sync_monotonic else float('inf'))
            tier=self.fee_learning.latest_tier()
            # Same account fee tier can screen all authenticated spot pairs, but
            # no pair-specific discounts/rebates are invented.
            pair_fees={pair:tier['taker'] for pair in self.catalog} if tier['fresh'] else {}
            strategy_candidates=annotate_study(
                result['strategy_research'].get('candidates') or (),
                (result.get('strategy_horizons') or {}).get('study') or {})
            result['strategy_forward_handoff']={
                'candidates':len(strategy_candidates),
                'with_observed_60m':sum(bool(x.get('forward_observed_hourly')) for x in strategy_candidates),
                'execution_authorized':False}
            result['auto_rotation']=auto_rotation_screen(
                buy_signals=result['signals'],holdings=self.ledger.assets(),
                verified_balances=dict(self.current_balances),balance_age_s=balance_age,
                catalog=self.catalog,quotes=research_books,
                product_rules=(getattr(self.broker,'catalog_product_rules',{}) if self.broker else {}),
                usd_per_order_cap=cap,now=time.time(),stats_for_pair=self.directional.stats,
                fee_rates_by_pair=pair_fees,
                relative_evidence=self.relative_lab.paired_outcomes,
                minimum_net_advantage_usd=Decimal('.10'),
                exploratory_candidates=exploratory['candidates'],
                strategy_candidates=strategy_candidates,
                gpu_advisories=result['gpu_advisory'],direct_only=True)  # NEVER GPU-only BUY signals
            # After ARM SHADOW, ONLY the modeled wallet funds follow-on routes.
            # The same core planner is reused; no parallel strategy/trader engine.
            if (self.shadow_pilot.armed and self._shadow_model_balances):
                from coincat_v605_shadow_bridge import shadow_screen
                result['validated_model_snapshot']=dict(self._shadow_model_balances)
                result['shadow_rotation']=shadow_screen(
                    balances=result['validated_model_snapshot'],
                    excluded=self._shadow_excluded_assets,
                    buy_signals=result['signals'],age_s=balance_age,
                    catalog=self.catalog,quotes=research_books,
                    product_rules=(getattr(self.broker,'catalog_product_rules',{}) if self.broker else {}),
                    portfolio_usd_cap=Decimal('1e24'),now=time.time(),fee_rates_by_pair=pair_fees,
                    relative_evidence=self.relative_lab.paired_outcomes,
                    exploratory_candidates=exploratory['candidates'],
                    strategy_candidates=strategy_candidates,
                    gpu_advisories=result['gpu_advisory'],direct_only=True)
            # EXPERIMENTAL SHADOW reuses the SAME market observations and planner.
            # First cycle uses the portfolio screen; after a hypothetical fill,
            # recalculate routes from the evolved experimental wallet inside
            # this already-running background scan (never a second REST scan).
            if self.experimental_shadow.armed:
                if self.experimental_shadow.fifo_posted>0 and self._experimental_model_balances:
                    from coincat_v605_shadow_bridge import shadow_screen
                    result['experimental_model_snapshot']=dict(self._experimental_model_balances)
                    result['experimental_rotation']=shadow_screen(
                        balances=result['experimental_model_snapshot'],
                        excluded=getattr(self,'_experimental_excluded_assets',()),
                        buy_signals=result['signals'],age_s=balance_age,
                        catalog=self.catalog,quotes=research_books,
                        product_rules=(getattr(self.broker,'catalog_product_rules',{}) if self.broker else {}),
                        portfolio_usd_cap=Decimal('1e24'),now=time.time(),fee_rates_by_pair=pair_fees,
                        relative_evidence=self.relative_lab.paired_outcomes,
                        exploratory_candidates=exploratory['candidates'],
                        strategy_candidates=strategy_candidates,
                        gpu_advisories=result['gpu_advisory'],direct_only=True,
                        max_targets=8)  # bounded experimental rescreen; no network or new scanner
                else:
                    result['experimental_rotation']=result['auto_rotation']
            result['funding_size_observations']=result['auto_rotation'].get('funding_size_observations',{})
        except Exception as exc:
            # The new research sibling may never obstruct the older
            # Coinbase/ledger risk gates or silently enable live orders.
            result['auto_rotation']={'state':'WAIT','ideas':[],
                'reason':'Shadow rotation unavailable: '+type(exc).__name__}
        # AI-to-BROKER research gateway accepts *all* exchange-listed spot
        # candidates, regardless of quote currency. It has NO submit action.
        try:
            shared_books=self._shadow_valuation_books()
            for sig in result['signals']:
                if not self.broker:continue
                # Leave all market/forward observations in AI Lab; do not
                # forward a known-too-small direct BUY to broker review.
                # Uncertain limits continue to normal fail-closed review.
                small=known_small_direct_buy(sig['pair'],
                    getattr(self.broker,'catalog_product_rules',{}),
                    self.ledger.assets(),self.current_balances,shared_books,
                    now=time.time())
                if small:
                    result.setdefault('minimum_prefiltered',[]).append(
                        {'pair':sig['pair'],'reason':small,'state':'SMALL'})
                    continue
                review=self.broker.review_spot_candidate(
                    pair=sig['pair'],side='BUY',catalog=self.catalog,
                    quotes=shared_books,verified=self.current_balances,
                    balance_age_s=(time.monotonic()-self._last_portfolio_sync_monotonic
                         if self._last_portfolio_sync_monotonic else float('inf')),
                    usd_order_cap=min(TIERS[current_stage(self.ledger)].order,
                        dec(self.broker.per_order_max)),now=time.time(),
                    fee_reserve_bps=(fee_snapshot['taker']*Decimal(10000) if fee_snapshot['fresh'] else None))
                result['broker_pair_reviews'].append(review)
                # Bounded authenticated Coinbase PREVIEW, never POST/submit.
                # Only one cross-pair candidate per DISARMED cycle to preserve
                # API health and the independent order-reconciliation worker.
                if (review.get('candidate') and sig['pair'].split('-')[-1] not in USD_QUOTES
                    and not self.broker.armed and not result['cross_spot_previews']
                    and hasattr(self.broker,'preview_cross_spot_candidate')):
                    try:
                        authenticated_preview=self.broker.preview_cross_spot_candidate(
                            pair=sig['pair'],side='BUY',catalog=self.catalog,
                            quotes=shared_books,
                            balance_age_s=(time.monotonic()-self._last_portfolio_sync_monotonic
                                if self._last_portfolio_sync_monotonic else float('inf')),
                            usd_order_cap=min(TIERS[current_stage(self.ledger)].order,
                                dec(self.broker.per_order_max)),now=time.time(),
                    fee_reserve_bps=(fee_snapshot['taker']*Decimal(10000) if fee_snapshot['fresh'] else None))
                        result['cross_spot_previews'].append(authenticated_preview)
                        # The fee sample is a preview only (not a maker fill),
                        # valid solely for its pair/side and short TTL.
                        if (authenticated_preview.get('state')=='PREVIEW_VALIDATED_RESEARCH'
                            and authenticated_preview.get('preview_fee_fraction') is not None):
                            try:
                                self.fee_learning.capture_pair_preview(
                                    pair=sig['pair'],side='BUY',
                                    rate=authenticated_preview['preview_fee_fraction'])
                            except Exception:
                                pass
                    except Exception as exc:
                        result['cross_spot_previews'].append(dict(pair=sig['pair'],state='BLOCKED',
                            reason='Authenticated preview unavailable: '+type(exc).__name__,
                            live_eligible=False,order_submitted=False))
        except Exception:
            result['broker_pair_reviews']=[{'state':'BLOCKED','reason':'All-pair broker preview unavailable'}]
        # Nothing here changes ARM/STOP, approval limits or financial-ledger fields.
        # Hard storage gate immediately before any real broker submission.
        # No financial fill/lot pruning is ever used to make more space.
        disk_ok, _disk_status=financial_storage_gate(ROOT)
        if not disk_ok and self.broker and self.broker.armed:
            self.broker.disarm()
            result['message']='Ledger or market storage limit reached: new orders DISARMED; preserve fills and verify backups'
        if not allow_orders or not self.broker or not self.broker.armed or self.broker.ledger.pending() or maintenance['over_limit'] or not disk_ok:
            # AI-Lab BUY is a research candidate, NOT an order permission. Every
            # candidate gets an explicit reason why the trader did not act.
            if not allow_orders: reason='manual quote-only scan; orders disabled for this scan'
            elif not self.broker: reason='no authenticated broker connection'
            elif not self.broker.armed: reason='live trader disarmed'
            elif self.broker.ledger.pending(): reason='pending/uncertain Coinbase order requires reconciliation'
            else: reason='financial/research storage capacity reached; no new orders'
            for s in result['signals']:
                result['handoffs'].append({'pair':s['pair'],'state':'SKIPPED','reason':reason})
            return result
        if not self.catalog or time.time()-self.catalog_at>7200:
            self.broker.disarm();result['message']='Coinbase authenticated catalog expired; trading disarmed'
            for s in result['signals']:
                result['handoffs'].append({'pair':s['pair'],'state':'SKIPPED','reason':'Coinbase catalog stale; trading disarmed'})
            return result
        # Unified all-spot execution Handoff. Trading is held DISARMED until
        # authenticated fills, fees, production FIFO and crash recovery are
        # integrated. No dollar-only fast lane or synthetic trade shortcut.
        for idea in (result.get('auto_rotation') or {}).get('ideas',[]):
            result['handoffs'].append({
                'pair':idea['trigger_pair'], 'state':idea.get('research_decision','HOLD_UNTIL_VERIFIED'),
                'reason':'USD HOLD-vs-SWITCH evidence review; no submit permission'})
        known_small={x['pair']:x['reason'] for x in result.get('minimum_prefiltered',())}
        for sig in result['signals']:
            if sig['pair'] in known_small:
                result['handoffs'].append({'pair':sig['pair'],'state':'SMALL',
                    'reason':known_small[sig['pair']]+'; no trader review; AI Lab learning continues'})
            elif not any(x.get('pair')==sig['pair'] for x in result['handoffs']):
                result['handoffs'].append({'pair':sig['pair'],'state':'ALL_SPOT_REVIEW_ONLY',
                    'reason':'Unified product/fee review; production posting and recovery not certified'})
        return result
    def _pulse(self):
        if self.shutdown:return
        self._pulse_phase=(self._pulse_phase+1)%60
        canvas=self.research_glass
        canvas.delete('all')
        canvas.create_rectangle(16,6,74,87,outline='#b1c8db',width=2)
        height=77*max(0,min(100,self.research_pct))/100
        if height>0:
            y=85-height
            canvas.create_rectangle(18,y,72,85,fill='#207f87',outline='')
            # A gently moving surface indicates UI heartbeat, NOT trades.
            wiggle=2*math.sin(self._pulse_phase*.23)
            canvas.create_line(20,y+wiggle,70,y-wiggle,fill='#6adab9',width=2)
        canvas.create_text(45,47,text=f'{self.research_pct}%',font=('Segoe UI Semibold',12),fill='white')
        phase=self._pulse_phase*.31
        canvas.create_oval(77,14+7*math.sin(phase),86,23+7*math.sin(phase),fill='#41c59b',outline='')
        self._scheduled['pulse']=self.root.after(450,self._pulse)

    def _poll(self):
        """Protect periodic scheduling from an unexpected Tk callback failure.

        If UI processing fails, immediately DISARM and resume the watcher;
        NEVER recover by retrying a possibly transmitted Coinbase order.
        """
        self._last_poll_heartbeat=time.monotonic()
        try:
            return self._poll_impl()
        except Exception as exc:
            self._last_ui_callback_error_type=type(exc).__name__
            self._last_ui_callback_error_origin='poll'
            self._last_ui_callback_breadcrumb=safe_callback_breadcrumb(exc)
            if self.broker:
                self.broker.disarm()
            # A callback failure cannot be taken as a successful market scan.
            try:
                self.status.set('DISARMED • poll callback error; inspect diagnostics')
                self._log('POLL CALLBACK ERROR • '+type(exc).__name__+' • no automatic submit retry')
            except Exception:
                pass
            if not self.shutdown:
                self._scheduled['poll']=self.root.after(1000,self._poll)

    def _poll_impl(self):
        if self.shutdown:return
        for _ in range(12):
            try:kind,payload=self.jobs.get_nowait()
            except queue.Empty:break
            if kind=='connect_progress':
                self.connection_detail.set(str(payload))
                continue
            if kind=='history_progress':
                self.lab_activity.set(str(payload));self._log('HISTORY • '+str(payload))
                continue
            if kind=='scan_progress':
                self._scan_progress_text=str(payload)
                self.lab_activity.set('Research scanning • '+str(payload))
                continue
            if kind=='error':
                operation=payload.get('operation','background') if isinstance(payload,dict) else 'background'
                detail=payload.get('message','Unknown error') if isinstance(payload,dict) else str(payload)
                self._log(f'{operation} issue: '+detail[:220])
                if operation=='catalog recheck':
                    self.portfolio_sync_status.set('Recheck failed: '+detail[:120]+'. Prior catalog retained; no account changes')
                if operation=='portfolio sync':
                    self._portfolio_sync_running=False
                    if self.broker and self.broker.armed:self.broker.disarm()
                    self.status.set('DISARMED • Coinbase balance verification failed')
                    self.portfolio_sync_status.set('PORTFOLIO SYNC FAILED • '+detail[:140]+' • new orders blocked')
                    self.trader_label.set('Balance sync failed: review Coinbase before separately rearming')
                elif operation=='connect':
                    self._finish_connection(False)
                    self.account_label.set('Coinbase connection FAILED • no asset balances loaded')
                    self.connection_detail.set('Error: '+detail[:450]+' • Check the CDP key, permissions, network, or Coinbase availability; then retry.')
                    self.status.set('DISARMED • Coinbase connection failed')
                    elapsed=int(time.monotonic()-self._connection_started_at)
                    self.connection_elapsed.set(f'Failed after {elapsed//60:02d}:{elapsed%60:02d} • retry after checking error above')
                elif operation=='read-only fill check':
                    self.fill_sync_status.set('Read-only verification ERROR: '+detail[:170]+' • no order submitted')
                elif operation=='fast Snowball research':
                    self._fast_last_result={'state':'WAIT','reason':'WORKER_'+str(detail)[:40]}
                    self._fast_next_at=time.monotonic()+max(30,self._fast_interval_s)
                    self.fast_research_status.set('FAST SNOWBALL • data worker paused; regular scan continues • LIVE blocked')
                elif operation in ('market scan','manual research scan'):
                    self._scan_processing=False
                    # A failed whole scan receives the same backoff as a severe
                    # REST/API error; never spin rapidly on a network outage.
                    spent=max(0.,time.monotonic()-self._scan_started_at)
                    self.loop_secs=self.cadence.update(elapsed=spent,pairs=64,
                        failures=64,ws_healthy=False,portfolio_healthy=False)
                    self._next_scan_at=time.monotonic()+self.loop_secs
                    self.cadence_status.set(f'ADAPTIVE SCAN BACKOFF • {self.loop_secs}s • check connectivity')
                    self.lab_progress.stop()
                    self.lab_activity.set('SCAN ERROR • adaptive backoff enabled; '+detail[:100])
                    if self.broker:self.broker.disarm()
                    self.status.set('DISARMED • failed market scan')
                elif operation=='fill sync':
                    self._fill_sync_faulted=True
                    if self.broker:self.broker.disarm()
                    self.status.set('DISARMED • Coinbase fill reconciliation uncertain')
                    self.fill_sync_status.set('PAUSED • Coinbase fill/status conflict: '+detail[:170])
                    self.trader_label.set('Fill reconciliation halted new trading. Review Coinbase; no duplicate orders.')
                elif operation=='GPU research':
                    # No redundant manual GPU training control.
                    self.gpu_status.set('GPU research FAILED • '+detail[:180]+' • live trading policy unchanged')
                elif operation=='per-asset approval':
                    self.account_label.set('Per-asset approval FAILED • '+detail[:180])
                elif operation=='10-day history':
                    self._history_in_progress=False
                    self.lab_progress.stop();self.warm_button.configure(state='normal')
                    self.lab_activity.set('Historical bootstrap FAILED • '+detail[:180])
                    self.lab_heartbeat.set('Historical data is optional; keep live data running while investigating.')
                    if self.broker:self.broker.disarm()
                else:
                    self.lab_progress.stop()
                    self.lab_activity.set('Scan FAILED • '+detail[:150])
                    self.status.set('DISARMED / CHECK LOG' if not self.broker or not self.broker.armed else 'Live: worker issue; check log')
                    if self.broker:self.broker.disarm()
            elif payload.get('kind')=='filled_order_check':
                result=payload.get('result') or {}
                if result.get('state')=='MATCH':
                    self.fill_sync_status.set(f'READ-ONLY VERIFIED • {result["pair"]} {result["side"]} • '
                        f'{result["base_qty"]} base • {result["n_fills"]} fills • '
                        f'gross {result["gross_quote"]} quote • fee {result["fees"]} quote')
                    self._log('Read-only latest FILLED order verified against Coinbase • no new orders')
                else:self.fill_sync_status.set('Read-only verification: '+result.get('message','No matching order'))
            elif payload.get('kind')=='catalog_recheck':
                # Catalog-only GET; never touches available balances, enrollment,
                # financial/tax lots, ARM, account fees, or Coinbase POST.
                if not self.broker or self.broker.armed:
                    self.portfolio_sync_status.set('Recheck result ignored: disconnected or armed during GET')
                else:
                    updated=set(payload['catalog'])
                    previous=set(self.catalog)
                    self._inactive_market_pairs.update(previous-updated)
                    self._inactive_market_pairs.difference_update(updated)
                    new_count=len(updated-previous)
                    retired_count=len(previous-updated)
                    self.catalog=sorted(updated)
                    self.catalog_at=float(payload.get('at') or time.time())
                    self.stream.set_pairs(self.catalog)
                    self.portfolio_sync_status.set(
                        f'Catalog recheck complete • {len(self.catalog)} active Coinbase SPOT products • '
                        f'{new_count} newly eligible, {retired_count} no longer eligible • NO orders/enrollment changes')
                    self._log(f'Authenticated catalog-only recheck: {new_count} added, {retired_count} excluded; no portfolio financial writes')
                    self._refresh_trees()
            elif payload.get('kind')=='fast_snowball':
                self._fast_runs+=1
                duration=payload.get('research_duration_s')
                if duration is not None:
                    self._fast_latencies.append(float(duration)*1000)
                    self._fast_latencies=self._fast_latencies[-256:]
                self._fast_latency_summary=percentiles(self._fast_latencies)
                self._fast_last_result={k:v for k,v in payload.items() if k not in ('plan','validated_plan','experimental_model_snapshot','validated_model_snapshot')}
                self._fast_totals['attempted']+=1
                self._fast_totals['rest_books']+=int(payload.get('fetched',0))
                self._fast_totals['rest_errors']+=int(payload.get('failed',0))
                plan=dict(payload.get('plan') or {})
                plan['ideas']=self._current_shadow_ideas(payload,self.experimental_shadow,
                    'experimental_model_snapshot',plan.get('ideas') or ())
                snow=payload.get('snowball') or {}
                posted=0
                # This is an EXTRA experimental observation between full
                # scans, NOT permission for an additional live broker attempt.
                if self.experimental_shadow.armed and payload.get('state')=='RESEARCHED':
                    try:
                        now_fast=time.time()
                        books=self._shadow_valuation_books()
                        fx_rates,marks_complete=self._shadow_mark_rates(
                            self.experimental_shadow,books,now_fast,plan.get('ideas',()))
                        before=self.experimental_shadow.fifo_posted
                        effective=effective_manual_budgets(self._manual_budget_saved,
                            plan.get('funding_inventory_usd',0))
                        if effective is not None:
                            self.experimental_shadow.observe(now=now_fast,quotes=books,
                                usd_rates=fx_rates,researched_reviews=(),
                                route_ideas=(plan.get('ideas') or ()) if marks_complete else (),
                                minimum_advantage=str(self.switch_minimum_usd),
                                strict_quotes=True,risk_budgets=effective)
                            self._experimental_model_balances={k:str(v) for k,v in
                                self.experimental_shadow.model_balances().items()}
                            posted=max(0,self.experimental_shadow.fifo_posted-before)
                    except Exception as exc:
                        self._fast_last_result['shadow_observation_error']=type(exc).__name__
                        # Fast research failure MUST NOT unlock other modes.
                if self.shadow_pilot.armed and payload.get('validated_plan'):
                    try:
                        now_valid=time.time()
                        books_valid=self._shadow_valuation_books()
                        from coincat_cross_quote import usd_conversion
                        rates_valid,valid_marks_complete=self._shadow_mark_rates(
                            self.shadow_pilot,books_valid,now_valid,
                            payload['validated_plan'].get('ideas',()))
                        valid_ideas=self._current_shadow_ideas(payload,self.shadow_pilot,
                            'validated_model_snapshot',payload['validated_plan'].get('ideas') or ())
                        cap=effective_manual_budgets(self._manual_budget_saved,
                            payload['validated_plan'].get('funding_inventory_usd',0))
                        if cap is not None:
                            self.shadow_pilot.observe(now=now_valid,quotes=books_valid,
                                usd_rates=rates_valid,researched_reviews=(),
                                route_ideas=valid_ideas if valid_marks_complete else (),
                                minimum_advantage=str(self.switch_minimum_usd),
                                strict_quotes=True,risk_budgets=cap)
                            self._shadow_model_balances={k:str(v) for k,v in
                                self.shadow_pilot.model_balances().items()}
                    except Exception as exc:
                        self._fast_last_result['validated_shadow_error']=type(exc).__name__
                self._fast_totals['simulated_fills']+=posted
                self._fast_last_result['funnel']=fast_funnel(
                    detected=payload.get('alerts',0),selected=payload.get('selected',0),
                    fetched=payload.get('fetched',0),errors=payload.get('failed',0),
                    targets=payload.get('targets',0),planner=plan,snowball=snow,
                    simulated_delta=posted,fresh=payload.get('fresh_books',0))
                funnel=self._fast_last_result['funnel']
                self.fast_research_status.set(
                    f'FAST SNOWBALL • events {self._fast_runs} • alerts {funnel["stream_alerts"]} → '
                    f'fundable {funnel["fundable_alerts"]} → fresh quotes {funnel["fresh_books"]} → '
                    f'costed routes {funnel["one_order_routes"]} → immediate +$ target {funnel["above_target"]} → '
                    f'experimental FIFO +{posted} • {payload.get("reason","WAIT")} • LIVE BLOCKED')
                if posted:
                    self._log(f'FAST Snowball: {posted} hypothetical FIFO conversion(s); no Coinbase order')
            elif payload.get('kind')=='portfolio_sync':
                fee_update=payload.get('fee_observation') or {}
                if fee_update.get('status')=='VERIFIED':
                    self._log('VERIFIED SPOT FEE TIER • maker/taker observations refreshed for AI Lab; pair previews still required; no orders')
                elif fee_update.get('status')=='UNAVAILABLE':
                    self._log('SPOT FEE TIER • read-only refresh unavailable; prior fee source not upgraded; no orders')
                self._portfolio_sync_running=False
                review=payload['review']
                added=payload.get('new_auto_enrolled') or {}
                if added.get('created'):
                    self._log(f'AUTO-ENROLLED {added["created"]} newly verified available spot assets; original tax basis UNKNOWN; no real orders')
                self._last_portfolio_sync_monotonic=payload.get('balance_verified_at',time.monotonic())
                self.current_balances=review['balances']
                prices=payload.get('portfolio_prices') or {}
                self._accept_portfolio_pricebooks(prices)
                # Refresh the *research catalog* on the same serialized worker.
                # Never reset ARM, approvals, verified lots or cost basis. A
                # refresh is discarded if user armed mid-flight.
                new_catalog=payload.get('refreshed_catalog')
                if new_catalog and self.broker and not self.broker.armed:
                    previous=set(self.catalog)
                    new_active=set(new_catalog)
                    self._inactive_market_pairs.update(previous-new_active)
                    self._inactive_market_pairs.difference_update(new_active)
                    self.catalog=list(new_catalog)
                    self.catalog_at=float(payload.get('catalog_checked_at') or time.time())
                    self.stream.set_pairs(self.catalog)
                    one_order_count = len(one_order_catalog(
                        self.catalog, getattr(self.broker, "catalog_product_rules", {})
                    ))
                    self._log(
                        f"READ ONLY catalog refreshed: {len(self.catalog)} eligible products; "
                        f"{one_order_count} one-order spot products; "
                        "no approvals or orders altered"
                    )
                elif payload.get('catalog_refresh_error'):
                    self._log('Catalog refresh unavailable ('+str(payload['catalog_refresh_error'])+'); previous catalog remains subject to expiry')
                self.external_mismatches=review['shortfalls']
                if review['safe']:
                    armed=bool(self.broker and self.broker.armed)
                    self.portfolio_sync_status.set('PORTFOLIO VERIFIED • '+time.strftime('%H:%M:%S')+
                        f' local • {len(self.current_balances)} liquid currencies • '+
                        ('LIVE remains ARMED' if armed else 'DISARMED')+
                        f' • pricing books {prices.get("received",0)}/{prices.get("requested",0)}'+
                        (' (price retry)' if prices.get('error') else '')+
                        f' • new automatically enrolled {added.get("created",0)} (tax basis unknown)')
                    self.external_balance_warning.set('No enrolled crypto shortfalls. Newly acquired spot assets automatically enroll when verified AVAILABLE; outside acquisition tax basis stays UNKNOWN. Existing excluded assets stay excluded.')
                    self.account_label.set(f'Connected • {len(self.current_balances)} live liquid balances • '+
                        f'{len(self.catalog)} pairs • {sum(bool(r.get("enabled",1)) for r in self.ledger.assets())} enrolled • '+
                        ('ARMED' if armed else 'DISARMED'))
                else:
                    if self.broker:self.broker.disarm()
                    names=', '.join(x['asset'] for x in review['shortfalls'][:12])
                    self.portfolio_sync_status.set('PORTFOLIO MISMATCH • '+names+' • DISARMED; no automatic lot corrections')
                    self.external_balance_warning.set('Coinbase available quantities below authorized inventory: '+names+
                        '. Compare fills/manual trades, reserved funds, and tax lots before rearming.')
                    self.status.set('DISARMED • live Coinbase portfolio inventory mismatch')
                    self.trader_label.set('Trading paused: enrolled quantities do not reconcile to fresh Coinbase AVAILABLE balances')
                self._refresh_trees()
            elif payload.get('kind')=='fill_sync':
                result=payload.get('reconcile') or {}
                state=result.get('state','UNKNOWN')
                self.fill_sync_status.set('Coinbase existing-order sync: '+state+' • checked '+time.strftime('%H:%M:%S')+' local • no orders sent')
                if state=='FILLED':
                    self._log('Coinbase CONFIRMED real fills, quantities and fees; ledger updated')
                    self.trader_label.set('Verified Coinbase fill(s) confirmed • inspect right-hand order/fill table')
                elif state=='WAITING':
                    self.trader_label.set('Coinbase accepted existing order; awaiting final fill verification')
                self._refresh_trees()
            elif payload.get('kind')=='gpu':
                # Automatic GPU research; no manual button to reset.
                r=payload['report']
                self._gpu_last_forward_report={k:r.get(k) for k in ('status','labeled','required','message','train','test')}
                self._gpu_runtime_info=payload.get('runtime') or {'status':'NOT_PROBED'}
                h=payload.get('historical') or {}
                if self._gpu_runtime_info.get('status')!='CUDA_READY':self._gpu_validated=False
                self.gpu_status.set('GPU '+self._gpu_runtime_info['status']+' • historical '+h.get('status','WAIT')+' • verified forward '+r['status']+' • observe-only')
                if r.get('status')=='EVALUATED':
                    # An evaluated model is not necessarily BETTER than its
                    # held-out no-skill baseline. Mark validated only if both
                    # separately held-out directions beat the baseline.
                    self._gpu_validated=bool(r.get('BUY',{}).get('better_than_baseline') and
                                             r.get('SELL_REBUY',{}).get('better_than_baseline'))
                    self.gpu_status.set(f'GPU BUY + SELL/rebuy research • {r["device"]} • {r["labeled"]} real two-way observations • '
                           f'BUY Brier {r["BUY"]["brier"]:.4f}, SELL/rebuy Brier {r["SELL_REBUY"]["brier"]:.4f} • '
                           'OBSERVE-ONLY • historical '+h.get('status','WAIT')+' (not used for orders)')
                self._log(self.gpu_status.get())
            elif payload.get('kind')=='history':
                self._history_in_progress=False;self.lab_progress.stop();self.warm_button.configure(state='normal')
                disk=payload.get('storage',{})
                self.lab_history.set(f'Auto-refreshable history: {payload["pairs"]-len(payload["errors"])}/{payload["pairs"]} watched pairs, '
                                     f'{payload["candles"]} refreshed hourly candles, {payload["cached"]} cached, '
                                     f'{len(payload["errors"])} errors • research DB {disk.get("size_mb", "?")} / {disk.get("limit_mb", "?")} MB')
                self.lab_activity.set('10-day context complete • continuous LIVE scan continues in background')
                self._log(self.lab_history.get())
                for pair,err in payload['errors'][:20]:self._log(f'HISTORY ERROR • {pair} • {err}')
                self._log('Offline gaps are historical CANDLES, not actual forward quotes or verified trade outcomes.')
                self._auto_history_checked=time.monotonic()
            elif payload.get('kind')=='connect':
                self.broker=payload['broker'];self.current_balances=payload['balances'];self.catalog=payload['catalog'];self.catalog_at=time.time()
                self._last_portfolio_sync_monotonic=time.monotonic()
                self._portfolio_sync_running=False
                self._accept_portfolio_pricebooks(payload.get('portfolio_prices') or {})
                self.portfolio_sync_status.set('PORTFOLIO VERIFIED • first account load • DISARMED • read-only sync every 60s while connected')
                bootstrap=payload.get('bootstrap',{})
                marks=payload.get('auto_marks',{})
                if bootstrap.get('created'):
                    self._log(f'INITIAL AUTO ENROLLMENT: {bootstrap["count"]} currently available liquid assets; no trading armed')
                    self._log(f'Performance starting marks: {len(marks.get("marked",[]))} obtained; {len(marks.get("skipped",[]))} skipped (review missing marks)')
                    self.snapshot_status.set(f'Initial auto-enrollment: {bootstrap["count"]} coins/currencies enrolled; {len(marks.get("marked",[]))} fresh performance marks; {len(marks.get("skipped",[]))} missing or inapplicable. Missing USD marks must be reviewed before selling. Original tax cost remains UNKNOWN.')
                    for asset,reason in marks.get('skipped',[])[:20]:self._log(f'AUTO SNAPSHOT SKIPPED • {asset}: {reason}')
                from coincat_external_check import compare_managed_balances
                self.external_mismatches=compare_managed_balances(self.ledger.assets(),self.current_balances)
                if self.external_mismatches:
                    self.external_balance_warning.set('MANUAL COINBASE ACTIVITY DETECTED: '+', '.join(x['asset'] for x in self.external_mismatches[:10])+'. Reconcile before ARM; no automatic asset/tax-lot changes.')
                    self.broker.disarm()
                    self.status.set('DISARMED • manually changed Coinbase holdings need ledger review')
                    self._log('EXTERNAL HOLDING DIFFERENCES • '+', '.join(x['asset'] for x in self.external_mismatches)[:110]+'; no automatic tax-lot change')
                if not self.external_mismatches:
                    self.external_balance_warning.set('No enrolled quantity shortfalls seen in latest available Coinbase balances. Recent manual trades may still need tax-lot reconciliation.')
                self._finish_connection(True)
                # 24-hour discovery coverage is informational only, never a
                # trade-readiness score. Recomputed on each scan completion.
                cov=self.forward.universe_coverage(self.catalog)
                self.universe_status.set(f'Full catalog discovery: {cov}/{len(set(self.catalog))} eligible Coinbase spot pairs REST sampled in last 24h • full public WebSocket discovery (activity permitting) / adaptive 48–128 deep-study (holdings do not bias research) / 12 discovery per cycle • no scout quotes enter live orders')
                self.universe_gauge['value']=100*cov/max(1,len(set(self.catalog)))
                self.account_label.set(f'Connected • {len(self.current_balances)} eligible liquid balances • {len(self.catalog)} eligible Coinbase spot pairs • {sum(bool(r.get("enabled",1)) for r in self.ledger.assets())} ENROLLED • trade DISARMED')
                self.connection_detail.set('Coinbase account/catalog loaded • first-time eligible assets auto-enrolled; click Status cells to change individual eligibility.')
                elapsed=int(time.monotonic()-self._connection_started_at)
                self.connection_elapsed.set(f'Completed in {elapsed//60:02d}:{elapsed%60:02d} • Coinbase data fully loaded')
                self.status.set('DISARMED • review externally changed holdings before trading' if self.external_mismatches else 'DISARMED • eligible assets enrolled; ARM LIVE separately')
                self._log('Authenticated Coinbase balances/catalog refreshed. Orders still DISARMED.')
                watch=self._watchlist(advance=False)
                self.stream.set_pairs(self.catalog)
                self.stream.start()
                cached=sum(self.forward.history_status(pair)['candles']>=12 for pair in watch)
                self.lab_history.set(f'10-day historical context present for {cached}/{len(watch)} watched Coinbase pairs • click START to refresh/import')
                self._refresh_trees()
                self._auto_history_checked=time.monotonic()
                if any(not self.forward.history_current(p) for p in watch):
                    self._log('AUTO CATCH-UP: missing/stale hourly market context detected on connection.')
                    self._start_history(auto=True)
            elif payload.get('kind') in ('one_enrolled','enrolled','snapshot'):
                marks=payload.get('marks') or payload.get('result') or {'marked':[],'skipped':[]}
                if payload.get('kind')=='enrolled':
                    self.account_label.set(f'Approved {payload["count"]} balances • market snapshots are trading marks, NOT actual tax basis')
                count=len(marks['marked']);miss=len(marks['skipped'])
                msg=f'PERFORMANCE SNAPSHOT • {count} marked from fresh Coinbase USD bid • {miss} skipped. Original tax basis unchanged.'
                self.snapshot_status.set(msg);self._log(msg)
                for coin,reason in marks['skipped'][:50]:self._log(f'  SNAPSHOT WAIT {coin}: {reason}')
                self._refresh_trees()
            elif payload.get('kind')=='cycle':
                self._scan_processing=False
                # Deliberately adjust ONLY the next scan due-time. Never change ARM,
                # per-order hard limits, or Coinbase order reconciliation behavior.
                now_scan=time.monotonic()
                elapsed=max(0.0,now_scan-self._scan_started_at) if self._scan_started_at else 0.0
                try:
                    stream_health=self.stream.status()
                    self.loop_secs=self.cadence.update(elapsed=elapsed,
                        pairs=int(payload.get('quotes',0))+int(payload.get('failures',0))+int((payload.get('discovery') or {}).get('sampled',0))+int((payload.get('discovery') or {}).get('failed',0)),
                        failures=int(payload.get('failures',0))+int((payload.get('discovery') or {}).get('failed',0)),
                        ws_healthy=bool(stream_health.get('connected')),
                        portfolio_healthy=not bool(getattr(self,'external_mismatches',[])))
                    # A separate bounded coverage controller uses the SAME
                    # completed scan evidence, with no independent market feed.
                    self.max_focus_pairs=self.focus_capacity.observe(
                        elapsed=elapsed,scan_interval=self.loop_secs,
                        quotes=int(payload.get('quotes',0))+int((payload.get('discovery') or {}).get('sampled',0)),
                        failures=int(payload.get('failures',0))+int((payload.get('discovery') or {}).get('failed',0)),
                        websocket_healthy=bool(stream_health.get('connected')),
                        portfolio_healthy=not bool(getattr(self,'external_mismatches',[])))
                    self._next_scan_at=now_scan+self.loop_secs
                    self.cadence_status.set(f'ADAPTIVE FULL SCAN every ~{self.loop_secs}s • last {elapsed:.1f}s • '+self.cadence.last_reason)
                except Exception as e:
                    self.loop_secs=max(120,self.loop_secs)
                    self._next_scan_at=now_scan+self.loop_secs
                    self.cadence_status.set('ADAPTIVE SCAN ERROR • using conservative 120s minimum')
                    self._log('Adaptive scan scheduler error: '+type(e).__name__)

                if getattr(self.shadow_pilot,'armed',False):
                    try:
                        now_shadow=time.time()
                        latest_books=self._shadow_valuation_books()
                        shadow_ideas=(payload.get('shadow_rotation') or {}).get('ideas') or ()
                        shadow_rates,marks_complete=self._shadow_mark_rates(
                            self.shadow_pilot,latest_books,now_shadow,shadow_ideas)
                        shadow_ideas=self._current_shadow_ideas(payload,self.shadow_pilot,
                            'validated_model_snapshot',shadow_ideas)
                        if not marks_complete: shadow_ideas=()
                        self.shadow_pilot.observe(now=now_shadow,quotes=latest_books,
                            usd_rates=shadow_rates,
                            researched_reviews=payload.get('reviews') or (),
                            route_ideas=shadow_ideas,
                            minimum_advantage=str(self.switch_minimum_usd),
                            strict_quotes=True,
                            risk_budgets=(effective_manual_budgets(self._manual_budget_saved,
                                (payload.get('shadow_rotation') or {}).get('funding_inventory_usd',0))
                                or {'per_order_usd':'0','incremental_exposure_usd':'0',
                                    'daily_buy_usd':'0','max_attempts':'0'}))
                        self._shadow_model_balances={k:str(v) for k,v in
                            self.shadow_pilot.model_balances().items()}
                        ss=self.shadow_pilot.snapshot()
                        effective=effective_manual_budgets(self._manual_budget_saved,
                            (payload.get('shadow_rotation') or {}).get('funding_inventory_usd',0))
                        if effective is None:
                            self.manual_budget_status.set('SHADOW effective budget: WAIT for strict fresh USD funding marks')
                        else:
                            self.manual_budget_status.set(
                                'SHADOW '+effective['mode']+' effective ceiling $'+str(Decimal(effective['per_order_usd']).quantize(Decimal('.01')))+
                                '/order, $'+str(Decimal(effective['daily_buy_usd']).quantize(Decimal('.01')))+
                                '/day, $'+str(Decimal(effective['incremental_exposure_usd']).quantize(Decimal('.01')))+
                                ' exposure, '+effective['max_attempts']+' attempts/24h'+
                                (' • verified modeled-wallet fuel (not a live ARM)' if effective['mode']=='FULL_AVAILABLE' else
                                 ' • manually applied caps')+
                                (' • rolling attempt anti-storm cap applies' if effective['clamped'] else ''))
                        self.shadow_mode_status.set('ARMED SHADOW • scans '+str(ss['completed_fresh_scans'])+
                            ' • modeled FIFO legs '+str(ss['shadow_fifo_posted_legs'])+
                            ' • actual Coinbase orders ZERO')
                    except Exception as exc:
                        self.shadow_pilot.disarm()
                        self._shadow_stop_reason='AUTO PAUSE: '+type(exc).__name__
                        self.shadow_mode_button.configure(text='ARM SHADOW (NO REAL ORDERS)')
                        self.shadow_mode_status.set('SHADOW PAUSED • '+type(exc).__name__+
                            ' • original trading ledger unchanged')
                # SNOWBALL: evaluate the same already-completed REST books and
                # planner receipts. No extra fetch, ledger write, or live permission.
                # This research is displayed even when experimental mode is OFF.
                try:
                    now_snow=time.time()
                    snow_books=self._shadow_valuation_books()
                    source=(payload.get('experimental_rotation') or
                            payload.get('auto_rotation') or {})
                    tier=self.fee_learning.latest_tier()
                    annotated,snow_stats=snowball_screen(
                        source.get('ideas') or (),snow_books,now=now_snow,
                        taker_fee=tier.get('taker') if tier.get('fresh') else None,
                        minimum_usd=str(self.switch_minimum_usd))
                    self._snowball_summary=snow_stats
                    if payload.get('experimental_rotation') is source:
                        # Do not change historical held-out approvals.
                        payload['experimental_rotation']=dict(source,ideas=annotated)
                    elif payload.get('auto_rotation') is source:
                        payload['auto_rotation']=dict(source,ideas=annotated)
                    self._refresh_break_even()
                except Exception as exc:
                    self._snowball_summary={'status':'NOT_VERIFIED_'+type(exc).__name__}
                    self._refresh_break_even()
                if getattr(self.experimental_shadow,'armed',False):
                    try:
                        now_exp=time.time()
                        exp_books=self._shadow_valuation_books()
                        exp_rotation=payload.get('experimental_rotation') or {}
                        exp_ideas=exp_rotation.get('ideas') or ()
                        exp_rates,marks_complete=self._shadow_mark_rates(
                            self.experimental_shadow,exp_books,now_exp,exp_ideas)
                        exp_ideas=self._current_shadow_ideas(payload,self.experimental_shadow,
                            'experimental_model_snapshot',exp_ideas)
                        if not marks_complete: exp_ideas=()
                        # Costed, one-order model receipts; no broker or order POST.
                        effective=effective_manual_budgets(self._manual_budget_saved,
                            exp_rotation.get('funding_inventory_usd',0)) or {
                            'per_order_usd':'0','incremental_exposure_usd':'0',
                            'daily_buy_usd':'0','max_attempts':'0'}
                        self.experimental_shadow.observe(
                            now=now_exp,quotes=exp_books,usd_rates=exp_rates,
                            researched_reviews=payload.get('reviews') or (),
                            route_ideas=exp_ideas,
                            minimum_advantage=str(self.switch_minimum_usd),
                            strict_quotes=True,risk_budgets=effective)
                        self._experimental_model_balances={k:str(v) for k,v in
                            self.experimental_shadow.model_balances().items()}
                        sx=self.experimental_shadow.snapshot()
                        self.experimental_shadow_status.set('EXPERIMENT ARMED • scans '+
                            str(sx['completed_fresh_scans'])+' • what-if FIFO legs '+
                            str(sx['shadow_fifo_posted_legs'])+
                            ' • historical validation BYPASSED FOR TEST ONLY • LIVE ZERO')
                        exp_value=(sx.get('shadow_fifo_bands') or {}).get('TAKER_ASK',{})
                        self.experimental_pnl_status.set('EXPERIMENT ONLY • modeled FIFO '+
                            str(sx['shadow_fifo_posted_routes'])+' routes / '+
                            str(sx['shadow_fifo_posted_legs'])+' legs • mark vs frozen HOLD $'+
                            str(exp_value.get('counterfactual_portfolio_vs_hold_usd','N/A'))+
                            ' • modeled fees $'+str(exp_value.get('estimated_fees_usd','N/A'))+
                            ' • simulated, NOT real P&L')
                    except Exception as exc:
                        self.experimental_shadow.disarm()
                        self.experimental_shadow_button.configure(
                            text='ARM EXPERIMENT (UNVALIDATED • NO REAL ORDERS)')
                        self.experimental_shadow_status.set(
                            'EXPERIMENT PAUSED • '+type(exc).__name__+' • NO REAL ORDERS')
                self.last_cycle=payload
                self.strategy_pipeline_status.set(v608_status_text(payload.get('strategy_research'),
                    payload.get('shadow_rotation') if self.shadow_pilot.armed else payload.get('auto_rotation'),
                    payload.get('strategy_horizons')))
                # Session-only, privacy-safe shadow counters. Nothing is stored
                # in the trading ledger, account vault, or research database.
                shadow_record=shadow_snapshot(payload, captured_at=int(time.time()))
                self.shadow_snapshots.append(shadow_record)
                if len(self.shadow_snapshots)>200:del self.shadow_snapshots[:-200]
                totals=self.shadow_session_totals
                totals['cycles']+=1
                totals['proposals']+=shadow_record['proposals']
                totals['exploratory']+=shadow_record.get('exploratory',0)
                totals['exploratory_attempts']+=shadow_record.get('exploratory_attempts',0)
                totals['wait_cycles']+=int(shadow_record['state']!='SHADOW ONLY')
                totals['attempts']+=shadow_record['attempts']
                totals['blocked']+=shadow_record['blocked']
                ai_advisory=payload.get('gpu_advisory') or {}
                qualified=[(pair,row) for pair,row in ai_advisory.items() if row.get('status')=='ADVISORY']
                if qualified:
                    self.gpu_status.set('GPU advisory / RESEARCH ONLY • '+str(len(qualified))+
                        ' model-scored BUY ideas • no influence on broker orders or arming')
                self._last_scan_at=time.monotonic();self.lab_progress.stop()
                storage=payload.get('storage')
                if storage:
                    last=storage.get('latest_live_quote')
                    ago=('never' if last is None else f'{max(0,int(time.time()-last))} seconds ago')
                    self.storage_status.set(f'Research DB: {storage["size_mb"]:.2f} / {storage["limit_mb"]} MB • '
                                            f'{storage["candles"]} rolling hourly candles across {storage["pairs"]} pairs • '
                                            f'last actual live quote {ago} • auto-prune daily / compact weekly')
                catalog_mix=payload.get('catalog_quote_mix') or {}
                deep_mix=payload.get('focused_quote_mix') or {}
                if catalog_mix and deep_mix:
                    self.universe_status.set(
                        f'Catalog {len(self.catalog)}: {catalog_mix.get("CRYPTO/OTHER",0)} crypto/other, '
                        f'{catalog_mix.get("USD/USDC",0)} USD/USDC, {catalog_mix.get("USDT/DAI",0)} USDT/DAI • '
                        f'Deep {len(payload.get("reviews",[]))}: {deep_mix.get("CRYPTO/OTHER",0)} crypto/other • '
                        'live multi-currency settlement still blocked')
                plan=payload.get('focused_discovery') or {}
                if plan:
                    self.universe_status.set(
                        f'Full catalog discovery: {(payload.get("discovery") or {}).get("coverage", 0)}/{len(set(self.catalog))} '
                        f'eligible pairs observed in 24h • WebSocket requested {self.stream.status().get("requested",0)} catalog pairs • up to {len(plan.get("watch",[]))} deep study • '
                        f'{len(plan.get("promoted",[]))} scout promotions ({plan.get("rising_promoted",0)} rising) / {len(plan.get("urgent_added",[]))} urgent • '
                        f'focus cohort held {plan.get("min_dwell_s",2700)//60}min for honest forward maturity • '
                        'ticker prices and scout snapshots cannot authorize trades')
                reviewed=payload.get('reviews',[])
                disc=payload.get('discovery') or {}
                if disc.get('total'):
                    self.universe_status.set(f'Full catalog REST discovery: {disc["coverage"]}/{disc["total"]} spot pairs sampled in last 24h ({disc["progress"]:.1f}%) • current cycle: {len(reviewed)} deep-study, {disc["sampled"]} broader discovery, {disc["failed"]} scouting errors • scout snapshots NEVER authorize trades')
                    self.universe_gauge['value']=disc['progress']
                tw=payload.get('two_way') or self.directional.overview()
                warm=sum(1 for r in reviewed if r.get('history',{}).get('candles',0)>=12)
                mature=sum(1 for r in reviewed if r.get('count',0)>=8)
                status=readiness(warm,len(reviewed),mature,tw['verified'],self._gpu_validated)
                self.research_pct=status['percent'];self.research_gauge['value']=self.research_pct
                self.readiness_status.set(f'Research coverage {self.research_pct}% • {warm}/{len(reviewed)} pairs with context • '
                    f'{mature}/{len(reviewed)} live-quote mature • {tw["verified"]} two-way future labels • '
                    'NOT a win probability or permission to trade')
                reviews=payload.get('broker_pair_reviews') or []
                inspected=sum(x.get('candidate',False) for x in reviews)
                if payload.get('minimum_prefiltered'):
                    self._log(f'AI Lab → trader: {len(payload["minimum_prefiltered"])} known-small direct BUY candidate(s) stopped before broker review; market history retained')
                if reviews and hasattr(self,'rotation_lab_status'):
                    # A broker-eligible market is NOT automatically a profitable trade.
                    self._log(f'All-spot broker read-only checks: {inspected}/{len(reviews)} signals pass product/size/FX checks; all-spot live POST blocked')
                cross_preview=payload.get('cross_spot_previews') or []
                if cross_preview:
                    p=cross_preview[0]
                    self._log('Coinbase cross-quote PREVIEW ONLY • '+str(p.get('pair','?'))+' • '+
                        str(p.get('state','BLOCKED'))+' • no order, no ledger write')
                auto=payload.get('auto_rotation') or {'state':'WAIT','reason':'No rotation screen','ideas':[]}
                proposals=auto.get('ideas',[])
                cross_ideas=sum(x.get('trigger_pair','').split('-')[-1] not in USD_QUOTES for x in proposals)
                # Display portfolio-wide RESEARCH ceiling separately from the
                # untouched manual LIVE broker caps. No order permission follows.
                funding=payload.get('research_portfolio_usd_ceiling',Decimal(0))
                auto_line=(f'V60.10 AUTHENTICATED SPOT ONE-ORDER research ({auto.get("one_order_eligible_spot_products",0)} products) • '
                    f'one-order routes {auto.get("one_order_routes_evaluated",0)} • '+f'V60.5 strict-price funding ${funding:,.2f} (eligible assets {auto.get("funding_assets",0)}; unpriced {auto.get("funding_unpriceable",0)}) • '
                    f'{auto.get("size_candidates_tested",0)} funding-size checks • '
                    f'{auto.get("exploratory_shortlist",0)} exploratory NOT BUY, {len(proposals)-auto.get("exploratory_shortlist",0)} other route rows, '
                    f'{auto.get("hold_preferred",0)} HOLD favored, '
                    f'{auto.get("switch_worth_research",0)} further SWITCH research, {auto.get("forward_unverified",0)} insufficient forward evidence • '
                    +auto.get('reason','No forward USD evidence')+' • NO LIVE ORDERS')
                if hasattr(self,'rotation_lab_status'):self.rotation_lab_status.set(auto_line)
                eligibility=payload.get('research_funding_eligibility') or {}
                explorer=payload.get('exploratory_market_research') or {}
                self.ai_overview_funding.set(str(eligibility.get('eligible',0))+' verified / '+str(eligibility.get('considered',0))+' enrolled')
                self.ai_overview_exploration.set(str(auto.get('exploratory_shortlist',0))+' observed; not trade signals')
                self.ai_learning_chain.set(
                    'Portfolio: '+str(eligibility.get('eligible',0))+' eligible, '+str(eligibility.get('excluded',0))+' excluded from research'
                    +' → market ideas: '+str(explorer.get('ranked',0))
                    +' → route checks: '+str(auto.get('exploratory_route_attempts',0))
                    +' → BUY qualified: '+str(len(payload.get('signals',[])))
                    +' → SHADOW models: '+str(sum(1 for x in proposals if x.get('oos_validated')))
                    +' • Pair-level future window observations: '+str(sum(
                        x.get('matured',0) for x in (payload.get('forward_windows') or {}).get('horizons',{}).values()))
                    +' (NOT portfolio alpha or trade permission)')
                if hasattr(self,'rotation_auto_status'):self.rotation_auto_status.set(auto_line)
                if hasattr(self,'rotation_auto_tree'):
                    self.rotation_auto_tree.delete(*self.rotation_auto_tree.get_children())
                    self._route_decision_details={}
                    # Y records a completed handoff to the *simulated observer*,
                    # NOT a fill. The source route itself still needs valid OOS.
                    active_shadow=bool(getattr(self.shadow_pilot,'armed',False))
                    modeled=(payload.get('shadow_rotation') or {}).get('ideas') or ()
                    observed_ids={(x.get('source'),x.get('target'),x.get('trigger_pair'),
                        str(x.get('research_size_cap_usd'))) for x in modeled}
                    for idea in proposals:
                        route=' → '.join(pair+' '+side for pair,side in idea['route'])
                        key=(idea.get('source'),idea.get('target'),idea.get('trigger_pair'),
                             str(idea.get('research_size_cap_usd')))
                        delivered=bool(active_shadow and key in observed_ids and
                            (idea.get('oos_validated') is True or idea.get('shadow_simulation_eligible') is True))
                        label=decision_label(idea,shadow_armed=active_shadow,
                            delivered_to_shadow=delivered)
                        iid=self.rotation_auto_tree.insert('','end',values=(
                            idea['source'],idea['target'],route,
                            f"${idea['immediate_change_usd']:+.4f}",label))
                        self._route_decision_details[iid]=reason_tooltip(
                            idea,shadow_armed=active_shadow,delivered_to_shadow=delivered)
                if proposals:self._log(f'AI → AUTO TRADER • {auto.get("exploratory_shortlist",0)} prequalification exploratory routes, {len(proposals)-auto.get("exploratory_shortlist",0)} normal research routes • no BUY permission or orders')
                self.directional_status.set(f'Two-way verified: {tw["verified"]} • offline gaps excluded {tw["missed"]} • '
                    f'ROTATE comparisons {len(payload.get("rotation",[]))} (research-only) • last scanner active')
                self.direction_tree.delete(*self.direction_tree.get_children())
                for idea in payload.get('rotation',[]):
                    self.direction_tree.insert('','end',values=(f'{idea["source"]} → {idea["target"]}',
                        'RESEARCH', '—','—','—',idea['reason']))
                for row in sorted(reviewed,key=lambda x:x['pair']):
                    st=self.directional.stats(row['pair'])
                    fmt_avg=lambda k: '—' if st[k] is None else f'{st[k]:+.2f}'
                    self.direction_tree.insert('','end',values=(row['pair']+' BUY / SELL / HOLD',
                       st['n'],fmt_avg('buy_net_avg'),fmt_avg('sell_rebuy_avg'),fmt_avg('hold_avg'),
                       'OBSERVED, NOT predictive' if st['n'] else 'Collecting 30m future observations'))
                self._reapply_sort(self.direction_tree)
                deep_mix=payload.get('focused_quote_mix') or quote_mix([r['pair'] for r in reviewed])
                total_mix=payload.get('catalog_quote_mix') or quote_mix(self.catalog)
                self.ai_overview_pairs.set(
                    f'{len(self.catalog)} catalog ({total_mix["CRYPTO/OTHER"]} cross) • '
                    f'{len(reviewed)} deep ({deep_mix["CRYPTO/OTHER"]} cross)')
                if not self._v30_observation_started and payload.get('quotes',0)>0:
                    self._v30_observation_started=time.monotonic()
                quote_counts={'USD/USDC':0,'USDT/DAI':0,'crypto/other':0}
                for review in payload.get('reviews',[]):
                    parts=str(review.get('pair','')).rsplit('-',1)
                    if len(parts)!=2:continue
                    quote=parts[1]
                    bucket=('USD/USDC' if quote in ('USD','USDC') else
                            'USDT/DAI' if quote in ('USDT','DAI') else 'crypto/other')
                    quote_counts[bucket]+=1
                if hasattr(self,'ai_quote_coverage'):
                    self.ai_quote_coverage.set(
                        f'DEEP STUDY ACTUAL MIX • USD/USDC {quote_counts["USD/USDC"]} • '
                        f'USDT/DAI {quote_counts["USDT/DAI"]} • '
                        f'crypto/other {quote_counts["crypto/other"]} • '
                        f'{sum(quote_counts.values())} reviewed; all eligible catalog pairs are public stream/scout candidates, '
                        'NOT 64 simultaneous REST markets')
                self.ai_overview_buy.set(f'{len(payload["signals"])} candidates')
                self.ai_overview_sell.set(f'{sum(x["action"]=="SELL" for x in payload.get("sell_reviews",[]))} candidates')
                self.ai_overview_research.set('SCANNING • '+str(payload['failures'])+' errors' if payload['failures'] else 'SCANNER ACTIVE')
                self.lab_activity.set(f'LIVE SCAN COMPLETE • {payload["quotes"]} fresh pairs, {payload["failures"]} errors, '
                                      f'{len(payload["signals"])} BUY, {sum(x["action"]=="SELL" for x in payload.get("sell_reviews",[]))} SELL candidate(s); scanner stays active')
                self.research_label.set(f'{payload["quotes"]} fresh Coinbase quotes / {len(reviewed)} pairs reviewed • '
                                        f'{len(payload["signals"])} qualified BUY • {sum(x["action"]=="SELL" for x in payload.get("sell_reviews",[]))} SELL candidate(s) in research-visible spot markets • ~{self.loop_secs}s adaptive scan cycle • WAIT reasons shown below')
                exits=payload.get('full_exit_reviews',[])
                valued=[x for x in exits if x.get('state')=='RESEARCH ONLY']
                total=sum((x['gross_usd_before_fees'] for x in valued),Decimal(0))
                self.full_exit_status.set(
                    f'FULL HOLDING RESEARCH • {len(valued)}/{len(exits)} authorized liquid assets have fresh USD-valued exits • '
                    f'${total:.2f} gross before fees • LIVE caps apply only to real orders / illustrative slices • '
                    '100% disposal may require multiple confirmed orders, and is NOT triggered by this preview')
                self.full_exit_tree.delete(*self.full_exit_tree.get_children())
                for entry in exits:
                    self.full_exit_tree.insert('','end',values=(entry['asset'],entry['pair'],
                        str(entry.get('liquid_qty','—')),
                        f"${entry['gross_usd_before_fees']:.2f}" if entry.get('gross_usd_before_fees') is not None else '—',
                        str(entry.get('min_cap_slices_estimate') or '—'),
                        entry['state']+': '+entry['reason']))
                self._reapply_sort(self.full_exit_tree)
                sells=payload.get('sell_reviews',[])
                self.sell_tree.delete(*self.sell_tree.get_children())
                for item in sells:
                    self.sell_tree.insert('','end',values=(item['pair'],
                        f'{item["bid"]:.8g}' if item['bid'] is not None else '—',
                        f'{item["value"]:.2f}' if item['value'] is not None else '—',
                        item['action'],item['reason']))
                self._reapply_sort(self.sell_tree)
                n_sell=sum(x['action']=='SELL' for x in sells)
                n_block=sum(x['action']=='BLOCKED' for x in sells)
                sale=((payload.get('shadow_rotation') if self.shadow_pilot.armed else payload.get('auto_rotation')) or {}).get('sell_first') or {}
                self.sell_status.set(f'{len(sells)} existing assets evaluated • {n_sell} ordinary SELL candidate(s) • '
                                     f'{n_block} basis-blocked • full verified holdings, not $5 limited • SELL-first spot exits studied={sale.get("screened",0)} '
                                     f'feasible={sale.get("feasible_exit_routes",0)} • '
                                     'exit feasibility is NOT a positive HOLD-vs-SWITCH edge')
                if n_sell:self._log(f'SELL MONITOR • {n_sell} qualified sell decisions evaluated this cycle')
                for item in sells:
                    if item['action'] in ('SELL','BLOCKED'):
                        self._log(f'  SELL/HOLD • {item["pair"]}: {item["action"]} • {item["reason"]}')
                self.signal_tree.delete(*getattr(self,'_all_signal_rows',self.signal_tree.get_children()))
                self._all_signal_rows=[]
                self._signal_reasons.clear()
                self.signal_detail.set('Select a market for the full BUY and SELL justification (reason column is abbreviated).')
                sell_lookup={r['pair']:r for r in sells if r.get('pair')}
                held_assets={r['asset'] for r in self.ledger.assets()
                    if r.get('enabled',1) and r['asset'] not in ('USD','USDC')
                    and dec(r.get('remaining_qty','0'))>0}
                for s in sorted(reviewed,key=lambda r:(r['action']!='BUY',r['pair'])):
                    pair=s['pair'];base=pair.split('-',1)[0]
                    sell=sell_lookup.get(pair)
                    # SELL is studied for all pairs; an actionable SELL still
                    # requires an approved actual holding and broker validation.
                    if sell:
                        sell_decision=sell['action']
                    elif base in held_assets:
                        sell_decision='HOLD / check basis'
                    else:
                        sell_decision='RESEARCH (no holdings)'
                    st=self.directional.stats(pair)
                    sell_edge=('—' if st['sell_rebuy_avg'] is None else
                        f'{st["sell_rebuy_avg"]:+.2f}% ({st["n"]} labels)')
                    info=s['reason']
                    if sell and sell['action'] in ('BLOCKED','SELL','HOLD'):
                        info=f'{info} | SELL: {sell["reason"]}'
                    self._signal_reasons[pair]=info
                    self.signal_tree.insert('','end',values=(pair,s['action'],sell_decision,
                        f'{s["bid"]:.8g}' if s['bid'] else '—',
                        f'{s["ask"]:.8g}' if s['ask'] else '—',
                        f'{s["count"]}/8',sell_edge,_wrap_reason_cell(info,lines=1)))
                n_pairs=len(reviewed)
                active_sell=sum(1 for r in sells if r['action']=='SELL')
                self.direction_count.set(f'{n_pairs} distinct exchange pairs  •  {2*n_pairs} BUY + SELL directions under study  •  '
                    f'{len(payload["signals"])} qualified BUY, {active_sell} inventory SELL research candidates  •  '
                    'SELL can trade only approved holdings with verified/snapshotted performance basis')
                if disc.get('sampled') or disc.get('failed'):
                    self._log(f'CATALOG DISCOVERY • {disc["sampled"]} additional sampled, {disc["failed"]} errors; 24h market coverage {disc["coverage"]}/{disc["total"]}. Scouts never trigger orders.')
                self._log(f'LIVE SCAN • {payload["quotes"]}/{len(reviewed)} valid quotes; {len(payload["signals"])} BUY candidates, '
                          f'{len(reviewed)-len(payload["signals"])} WAIT/blocked')
                for s in reviewed[:30]:self._log(f'  {s["pair"]}: {s["action"]} • {s["count"]} live quotes • {s["reason"]}')
                self._reapply_sort(self.signal_tree)
                self._all_signal_rows=list(self.signal_tree.get_children())
                self._filter_research_rows()
                for check in payload.get('handoffs',[]):
                    self._log(f'AI → TRADER • {check["pair"]} • {check["state"]} • {check["reason"]}')
                if payload.get('handoffs') and not payload.get('message'):
                    first=payload['handoffs'][0]
                    self.trader_label.set(f'{len(payload["handoffs"])} qualified AI BUY signal(s) reviewed • '
                         f'{first["pair"]}: {first["state"]} • {first["reason"]}')
                if payload.get('trade'):
                    self._log('REAL order '+str(payload['trade']['state'])+' • '+payload['trade'].get('message',''))
                if (payload.get('reconcile') or {}).get('state')=='FILLED':self._log('Coinbase CONFIRMED real fill; ledger and AI history updated')
                if payload.get('message'):self._log(payload['message']);self.trader_label.set(payload['message'])
                if self.broker:self.status.set('LIVE NOT CERTIFIED • all-spot review only' if self.broker.armed else 'DISARMED • no new orders')
                self._refresh_trees()
        if self._connection_in_progress or self._connection_requested:
            elapsed=int(time.monotonic()-self._connection_started_at)
            self.connection_elapsed.set(f'Elapsed {elapsed//60:02d}:{elapsed%60:02d} • ETA unknown (Coinbase page count varies)')
        if self._history_in_progress:
            elapsed=int(time.monotonic()-self._history_started_at)
            self.lab_heartbeat.set(f'Historical import active for {elapsed//60:02d}:{elapsed%60:02d}; pair completion count shown above • ETA varies')
        elif self._scan_started_at and self.worker_busy and not self._connection_in_progress:
            elapsed=int(time.monotonic()-self._scan_started_at)
            self.lab_heartbeat.set(f'Live research worker active for {elapsed}s • '+self._scan_progress_text)
            if elapsed>90:
                self.lab_activity.set('WARNING: Scan has exceeded 90s; check connectivity. No new automatic scan can start while busy.')
                if self.broker and self.broker.armed:
                    self.broker.disarm();self.status.set('DISARMED • research scan timeout warning')
        elif self._last_scan_at:
            seconds=int(time.monotonic()-self._last_scan_at)
            upcoming=max(0,int(self._next_scan_at-time.monotonic()))
            self.lab_heartbeat.set(f'Last successful live scan {seconds}s ago • next scheduled scan in ~{upcoming}s • real orders only when independently armed')
            if seconds>300:
                self.lab_activity.set('WARNING: No completed live scan for more than five minutes')
                if self.broker and self.broker.armed:self.broker.disarm();self.status.set('DISARMED • live research stale')
        if time.monotonic()-self._last_stream_render>1.5:
            try:
                frep=frequency_report(self.ledger,time.time())
                self.trade_frequency_status.set(
                    'TODAY UTC • attempts '+str(frep['order_attempts'])+
                    ' • filled BUY orders '+str(frep['filled_buy_orders'])+
                    ' • filled SELL orders '+str(frep['filled_sell_orders'])+
                    ' • profitable exits '+str(frep['profitable_sell_orders'])+
                    ' • fee-aware realized $'+str(frep['realized_after_fee_result']))
            except Exception:self.trade_frequency_status.set('Trade-frequency counters unavailable; review diagnostic log')
        if time.monotonic()-self._last_stream_render>1.5:
            self._last_stream_render=time.monotonic()
            self._refresh_stream_ui()
        # Frequent reconciliation is serialized with research/order submission.
        # NEVER submits a new order and NEVER retries uncertain submissions.
        if (self.broker and self.broker.ledger.pending() and not self._fill_sync_faulted
                and not self.worker_busy and not self._connection_in_progress
                and time.monotonic()-self._last_fill_poll>=5):
            self._sync_order_now()
        # Prevent an ARM session from continuing indefinitely on an unverifiable
        # portfolio, even when slow network/history work delays normal polling.
        if (self.broker and self.broker.armed and self._last_portfolio_sync_monotonic
                and time.monotonic()-self._last_portfolio_sync_monotonic>300):
            self.broker.disarm()
            self.status.set('DISARMED • verified portfolio snapshot is over five minutes old')
            self.portfolio_sync_status.set('PORTFOLIO STALE • refresh current Coinbase balances before rearming')
        # Periodic read-only portfolio verification is independent from price
        # scans, order submission, and per-asset enrollment changes.
        if self.broker and not self._portfolio_sync_running and not self.worker_busy:
            if time.monotonic()-self._last_portfolio_sync_monotonic>=self.portfolio_sync_secs:
                self._refresh_portfolio_live()
        if time.monotonic()-self._last_storage_check>60:
            self._last_storage_check=time.monotonic()
            self._storage_check()
        if time.monotonic()-self._v30_readiness_last_checked>15:
            self._v30_readiness_last_checked=time.monotonic()
            self._update_v30_readiness()
        self._start_connection_if_ready()
        self._start_history_if_ready()
        # Retired legacy Capacity Advisor popup; risk caps remain in broker.
        self._render_target_preview_if_idle()
        self._scheduled['poll']=self.root.after(800,self._poll)
    def _refresh_trees(self):
        selected=self.balance_tree.selection()
        selected_coin=self.balance_tree.item(selected[0],'values')[0] if selected else None
        self.balance_tree.delete(*self.balance_tree.get_children())
        enrolled={x['asset']:x for x in self.ledger.assets()}
        fresh_start_prices={}
        new_period=None
        try:
            from coincat_v601_baseline import latest as latest_performance_start
            from coincat_live import sql
            with sql(self.ledger.path) as conn:
                new_period=latest_performance_start(conn)
                if new_period:
                    fresh_start_prices={a:dec(p) for a,p in conn.execute(
                        'SELECT asset,usd_per_unit FROM v601_performance_holdings WHERE period_id=?',
                        (new_period['id'],)).fetchall()}
        except Exception:
            fresh_start_prices={}
        if hasattr(self,'_performance_period_label'):
            self._performance_period_label.set(
                f'Current performance start: {new_period["date_utc"]}, '
                f'${float(new_period["total_usd"]):,.2f} across {new_period["assets"]} enrolled currencies. '
                'Not a tax purchase cost.' if new_period else
                'No new performance period yet. Capture one from fresh verified Coinbase prices.')
        # Sub-second book timestamps must be compared against a SUB-second
        # current clock; truncation to int otherwise makes a fresh quote from
        # this very second appear to have a *negative* age (and be unpriced).
        now=time.time()
        # Research/portfolio price sources must NOT feed the execution broker.
        # Include existing verified REST quotes, then overlay fresh dedicated
        # Coinbase portfolio book snapshots. No old enrollment snapshot fallback.
        quotes=newest_books(self.forward.recent_bid_ask(now=now,max_age=300),
                            self._portfolio_quotes,now=now,max_age=300)
        coverage=portfolio_coverage(self.current_balances,self.catalog,quotes,now=now)
        self._portfolio_coverage={k:v for k,v in coverage.items() if k!='rates'}
        usd_rates=coverage['rates']
        # Holdings outside live available balances are not counted as current
        # spendable portfolio value or used in any trade decision.
        # These are *different* accounting concepts:
        #   current_value: spot-estimated liquid value, changes with quotes;
        #   start_mark: frozen USD bid × initial approved quantity;
        #   original_cost: real historical acquisition/tax cost (may be UNKNOWN).
        current_value=Decimal('0');start_mark=Decimal('0')
        if hasattr(self,'pnl_holdings_tree'):
            self.pnl_holdings_tree.delete(*self.pnl_holdings_tree.get_children())
        current_quoted=0;current_missing=[];marked=0;unmarked=[];bot_owned=0
        catalog_coins=distinct_catalog_assets(self.catalog,self.current_balances,enrolled)
        if hasattr(self,'portfolio_catalog_summary'):
            one_order_count = len(one_order_catalog(
                self.catalog, getattr(self.broker, "catalog_product_rules", {})
            ))
            self.portfolio_catalog_summary.set(
                f'{len(catalog_coins)} unique catalog assets • '
                f'{one_order_count} eligible one-order spot pairs • holdings first • '
                f'{len(getattr(self,"_inactive_market_pairs",()))} formerly listed pairs excluded • CATALOG ONLY rows cannot be enrolled without confirmed available holdings'
            )
        for coin in catalog_coins:
            row=enrolled.get(coin)
            fx=usd_rates.get(coin)
            p=fx['rate'] if fx else None
            available=self.current_balances.get(coin)
            usd=f'${(dec(available)*p):,.2f}' if available is not None and p is not None else '—'
            usd_value=dec(available)*p if available is not None and p is not None else None
            # Market unit-price change since frozen CoinCat enrollment mark.
            # NOT taxable cost basis or a total-value change after transfers.
            start_unit=(fresh_start_prices.get(coin) if coin in fresh_start_prices else
                        dec(row.get('snapshot_unit_usd') or '0') if row else Decimal(0))
            change='—';tags=()
            if p is not None and start_unit > 0:
                pct=(p/start_unit-1)*100
                change=f'{pct:+.3f}%'
                tags=('price_up',) if pct>0 else ('price_down',) if pct<0 else ()
            if usd_value is not None:
                self.usd_previous[coin]=usd_value
                if available is not None and dec(available)>0:
                    current_value+=usd_value;current_quoted+=1
            elif available is not None and dec(available)>0:
                current_missing.append(coin)
            if row and row.get('enabled',1) and coin not in ('USD','USDC'):
                if row.get('snapshot_unit_usd') is not None and row.get('snapshot_qty') is not None:
                    start_mark+=dec(row['snapshot_unit_usd'])*dec(row['snapshot_qty']);marked+=1
                elif row.get('basis_source')=='BOT_FILL':
                    bot_owned+=1
                elif dec(row.get('remaining_qty') or '0')>0:
                    unmarked.append(coin)
            if p is not None:self.price_previous[coin]=p
            status=('ENROLLED' if row.get('enabled',1) else 'EXCLUDED') if row else (
                'NOT APPROVED' if available is not None and dec(available)>0 else 'CATALOG ONLY')
            if hasattr(self,'pnl_holdings_tree') and available is not None and dec(available)>0:
                self.pnl_holdings_tree.insert('','end',values=(coin,str(available),usd,status,
                    ('CONFIRMED BUY LOTS' if row and row.get('basis_source')=='BOT_FILL' else 'HISTORICAL / REVIEW' if row and row.get('basis_unit_quote') else 'UNKNOWN')))
            basis=('CONFIRMED BUY LOTS' if row and row.get('basis_source')=='BOT_FILL'
                   else 'UNVERIFIED PRIOR COST' if row and row.get('basis_unit_quote') else 'UNKNOWN')
            mark=row.get('snapshot_unit_usd') if row else None
            mark_at=time.strftime('%Y-%m-%d %H:%M',time.gmtime(row['snapshot_at'])) if row and row.get('snapshot_at') else '—'
            item=self.balance_tree.insert('','end',values=(coin,str(available if available is not None else '—'),usd,change,
                    row.get('remaining_qty','—') if row else '—',mark or '—',basis if row else '—',mark_at,status),tags=tags)
            if coin==selected_coin:self.balance_tree.selection_set(item)
        missing_note=(f'{len(current_missing)} unpriced liquid assets: '+', '.join(current_missing[:12])+
                      ('…' if len(current_missing)>12 else '') if current_missing else
                      'All liquid assets priced from recent spot books')
        missing_reasons='; '.join(f'{asset}:{reason}' for asset,reason in list(coverage['missing'].items())[:6])
        self.portfolio_feed_status.set(
            f'PORTFOLIO → AI LAB → AUTO TRADER (READ ONLY): {coverage["priced_count"]}/{coverage["held_count"]} '
            f'liquid currencies have usable USD quotes; '
            + ('COMPLETE portfolio observation' if coverage['complete'] else
               'INCOMPLETE USD valuation, live preflight BLOCKED')
            + (' • '+missing_reasons if missing_reasons else '')
            + ' • HOLD/SWITCH all-spot research only; no live execution')
        quote_note=('Values use recent Coinbase USD quotes, not guaranteed execution prices. '
                    'Prices more than five minutes old are excluded. '
                    'Price change is NOT realized profit or original tax cost. ')
        self.start_snapshot_summary.set(
            f'Available liquid portfolio: approximately ${current_value:,.2f} across {current_quoted} priced currencies. '
            f'{missing_note}.  {quote_note}'
            f'Older frozen enrollment marks: ${start_mark:,.2f} across {marked} holdings; '
            f'{len(unmarked)} still need a historical enrollment mark. '
            'Your new dated starting value, if captured, appears separately. '
            'Previous typed tax costs are NOT proof of purchase price; past lots are kept for review.')
        self.dashboard_portfolio.set(f'${current_value:,.2f} EST. partial • {len(current_missing)} unpriced' if current_missing else f'~${current_value:,.2f} EST. liquid')
        if self.broker and self.broker.armed and self.broker.portfolio_ceiling_usd is not None:
            cap=portfolio_ceiling(self.ledger.assets(),self.current_balances,usd_rates) if coverage['complete'] else None
            try:
                if cap is None: raise LiveBlocked('Missing verified portfolio cap')
                validate_manual_budget(self.broker.per_order_max,self.broker.daily_buy_cap,
                    self.broker.exposure_cap,self.broker.max_orders_day,cap)
                cap_safe=True
            except LiveBlocked:
                cap_safe=False
            if not cap_safe:
                self.broker.disarm()
                self.status.set('DISARMED • portfolio budget exceeds verified available portfolio value')
            else:
                self.broker.portfolio_ceiling_usd=cap
                self.broker.portfolio_ceiling_seen_at=time.monotonic()
        self.dashboard_enrolled.set(f'{sum(bool(a.get("enabled",1)) for a in enrolled.values())} active assets')
        self.dashboard_connection.set('CONNECTED' if self.broker else 'DISARMED / offline')
        self._reapply_sort(self.balance_tree)
        self.order_tree.delete(*self.order_tree.get_children())
        for r in self.ledger.orders()[:40]:
            self.order_tree.insert('','end',values=(time.strftime('%Y-%m-%d %H:%M',time.gmtime(r['created_at'])),r['pair'],r['side'],r['state'],r['order_id'] or '—'))
        self._reapply_sort(self.order_tree)
        if hasattr(self,'fill_tree'):
            self.fill_tree.delete(*self.fill_tree.get_children())
            for r in self.ledger.fills()[:60]:
                qty=dec(r['base_qty']);price=dec(r['price']);fee=dec(r['fee_quote'])
                self.fill_tree.insert('','end',values=(
                    time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(r['at_utc'])),
                    r['pair'],r['side'],str(qty),str(price),f'{qty*price:.6f}',f'{fee:.6f}'))
            self._reapply_sort(self.fill_tree)
        # Cost learning uses confirmed Coinbase fills, including any historical
        # manual-portfolio-purpose fills that were recorded before this removal.
        # User's OUTSIDE-CoinCat Coinbase trades are NOT invented as local fills.
        from coincat_live import sql
        with sql(self.ledger.path) as con:
            fee_rows=con.execute("SELECT pair,side,COUNT(*) n FROM fills GROUP BY pair,side").fetchall()
        observed=sum(int(x['n']) for x in fee_rows)
        self.execution_learning.set(
            f'Execution cost research: {observed} CONFIRMED local Coinbase fills across {len(fee_rows)} pair/sides. '
            'Manual trades made directly on Coinbase require account and tax-lot reconciliation; '
            'they are not counted as AI predictions. No on-chain fee is inferred from a spot trade.')
        s=self.ledger.today_stats()
        from coincat_daily_risk import daily_loss_limit,loss_decision,LossEvidenceUnavailable
        try:
            requested=daily_loss_limit(self.daily_loss_limit_entry.get())
            current=(self.broker.daily_realized_loss_limit_usd if self.broker and self.broker.armed
                     else requested)
            result=loss_decision(self.ledger.path,current)
            state='PAUSED new BUYs (may auto-resume after a verified SELL)' if not result['new_buys_allowed'] else 'BUY eligibility restored/available under daily rule'
            pending=(' • edit not applied while armed' if self.broker and self.broker.armed and requested!=current else '')
            self.loss_policy_message.set(f'UTC confirmed SELL USD P&L ${result["pnl_usd"]:+,.2f}; '
                f'daily BUY pause ${current:,.2f} • {state}{pending}. '
                'A confirmed profit can automatically restore this eligibility; emergency STOP never auto-clears.')
        except (ValueError,LossEvidenceUnavailable) as ex:
            self.loss_policy_message.set('DAILY LOSS POLICY NOT VERIFIED • new BUYs must be blocked: '+str(ex)[:130])
        self.totals.set(f'Confirmed fill performance (NOT tax P&L): ${s["realized"]:.2f} cumulative; '
            f'UTC today ${s["day_pnl"]:.2f}; BUY gross ${s["buy_spend"]:.2f}; '
            f'historical quote-currency fill fees (not a unified settlement record) ${s["fees"]:.2f}; '
            f'closed SELL winners {s["wins"]}, non-winners {s["losses"]}; orders/24h {s["order_count"]}. '
            'Value changes of unsold holdings are NOT realized trading P&L.')
        if self.fig:
            self.ax.clear();self.ax.set_facecolor(BG)
            wins,losses=int(s['wins']),int(s['losses'])
            if wins+losses:
                sizes=[v for v in (wins,losses) if v]
                labels=[text for text,count in [('Profitable completed SELL orders',wins),
                        ('Break-even / losing completed SELL orders',losses)] if count]
                palette=[color for color,count in [('#23b785',wins),('#e65b65',losses)] if count]
                self.ax.pie(sizes,labels=labels,colors=palette,autopct='%1.0f%%',
                    startangle=85,pctdistance=.74,wedgeprops={'width':.44,'edgecolor':BG},
                    textprops={'color':'white','fontsize':9})
                self.ax.set_title('Confirmed SELL orders: wins vs non-wins',color='white',fontsize=11)
            else:
                self.ax.pie([1],colors=['#29445c'],wedgeprops={'width':.44,'edgecolor':BG})
                self.ax.text(0,0,'No closed\nSELL orders',ha='center',va='center',color='white',fontsize=11)
                self.ax.set_title('Awaiting verified SELL outcomes',color='white',fontsize=11)
            self.canvas.draw_idle()
    def _export(self,kind):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=f'CoinCat_v50_2_{ {"orders":"Orders","fills":"Fills","snapshots":"Enrollment_Snapshots"}.get(kind,kind)}.csv',filetypes=[('CSV','*.csv')])
        if path:
            n=self.broker.export(kind,path) if self.broker else LiveBroker(self.ledger,None).export(kind,path)
            messagebox.showinfo('CSV saved',f'Exported {n} {kind} records')
    def _export_quotes(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='CoinCat_v50_2_Forward_Research.csv',filetypes=[('CSV','*.csv')])
        if not path:return
        import csv
        with self.forward._db() as c:
            rows=c.execute('SELECT pair,at_utc,bid,ask,source FROM market_quotes ORDER BY at_utc DESC LIMIT 100000').fetchall()
        with open(path,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['pair','at_utc','bid','ask','source']);w.writerows(rows)
        messagebox.showinfo('CSV saved',f'Exported {len(rows)} forward quote observations')
    def _export_dates(self):
        start=self.export_start_date.get().strip()
        end=self.export_end_date.get().strip()
        utc_window(start,end)  # Reject bad dates BEFORE any file is created.
        return start,end

    def _date_report(self, tax_support=False):
        try:
            start,end=self._export_dates()
        except ValueError as exc:
            messagebox.showerror('Invalid UTC date range',str(exc));return
        tag='Tax_Support' if tax_support else 'Profit_Loss'
        export_dir=ROOT/'tax_exports'
        export_dir.mkdir(parents=True,exist_ok=True)
        dest=filedialog.asksaveasfilename(defaultextension='.csv',
            initialdir=str(export_dir), initialfile=f'CoinCat_v60_1_{tag}_{start}_through_{end}.csv',
            filetypes=[('Excel-compatible CSV','*.csv')])
        if not dest:return
        try:
            n,size=export_csv(dest,self.ledger.path,start,end,tax_support=tax_support)
            if size >= 850*1024*1024:
                self.tax_archive_warning.set('TAX EXPORT WARNING • File is approaching 1 GiB. Back it up to a second location; this warning does not DISARM trading.')
                messagebox.showwarning('Large tax/report export','The export exceeds 850 MiB. Back it up now. This WARNING does not DISARM CoinCat.')
            messagebox.showinfo('Excel-compatible CSV exported',
                f'Exported {n} confirmed exchange fills for {start} through {end} UTC.\n'
                'No 2,000-row display cap. Tax basis can be UNKNOWN; fees and gains use labeled quote currencies.')
        except FileExistsError:
            messagebox.showerror('Existing export','That file already exists. Choose a new filename; CoinCat will not overwrite your tax backup.')
        except Exception as exc:messagebox.showerror('Export failed',str(exc))

    def _export_pnl(self):
        self._date_report(False)

    def _export_tax_support(self):
        self._date_report(True)

    def _tax_handoff(self):
        try:
            start,end=self._export_dates()
            text=handoff_text(self.ledger.path,start,end)
        except (ValueError,OSError) as exc:
            messagebox.showerror('Tax handoff',str(exc));return
        window=tk.Toplevel(self.root)
        window.title('Tax-preparation handoff • copy only, no forms filed')
        window.geometry('800x570')
        field=tk.Text(window,wrap='word',font=('Consolas',10),bg=CARD,fg=FG,insertbackground=FG)
        field.pack(fill='both',expand=True,padx=12,pady=9)
        field.insert('1.0',text);field.configure(state='disabled')
        footer=ttk.Frame(window);footer.pack(fill='x',padx=12,pady=(0,10))
        def copy():
            window.clipboard_clear();window.clipboard_append(text)
            messagebox.showinfo('Copied','Tax handoff text copied to your clipboard. No tax forms filed.',parent=window)
        ttk.Button(footer,text='Copy tax handoff to clipboard',command=copy).pack(side='left')
        ttk.Button(footer,text='Close',command=window.destroy).pack(side='right')

    def _export_lot_details(self):
        """Read-only lot records; original UNKNOWN tax basis remains empty."""
        import csv
        from coincat_live import sql
        directory=filedialog.askdirectory(title='Save CoinCat acquisition and disposal CSV files')
        if not directory:return
        with sql(self.ledger.path) as c:
            from coincat_inventory_lots import seed_opening
            seed_opening(c)
            lots=[dict(r) for r in c.execute('SELECT * FROM inventory_lots ORDER BY asset,opened_at,lot_id')]
            sold=[dict(r) for r in c.execute('SELECT * FROM inventory_disposals ORDER BY trade_id,lot_id')]
        # Historic manually typed opening cost may be incorrect. Preserve it in
        # the canonical ledger but NEVER emit it as certified tax-cost evidence.
        sources={row['lot_id']:row['source'] for row in lots}
        for row in lots:
            proven=row['source']=='COINBASE_CONFIRMED_BUY'
            row['tax_cost_status']=('LOCAL CONFIRMED BUY; VERIFY AGAINST COINBASE' if proven
                                     else 'ORIGINAL ACQUISITION DOCUMENTS REQUIRED')
            if not proven:row['tax_unit_quote']=''
        for row in sold:
            proven=sources.get(row['lot_id'])=='COINBASE_CONFIRMED_BUY'
            row['tax_cost_status']=('LOCAL CONFIRMED BUY; VERIFY AGAINST COINBASE' if proven
                                     else 'ORIGINAL ACQUISITION DOCUMENTS REQUIRED')
            if not proven:
                row['tax_basis_quote']=''
                row['tax_realized_quote']=''
        for filename,items,fields in (
            ('CoinCat_v60_1_Acquisition_Lots.csv',lots,['lot_id','asset','source','source_trade_id','opened_at','initial_qty','remaining_qty','performance_unit_quote','tax_unit_quote','quote_ccy','tax_cost_status']),
            ('CoinCat_v60_1_Lot_Disposals.csv',sold,['trade_id','lot_id','used_qty','performance_basis_quote','tax_basis_quote','fee_quote','performance_realized_quote','tax_realized_quote','tax_cost_status']),
        ):
            with open(os.path.join(directory,filename),'w',newline='',encoding='utf-8-sig') as out:
                writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader();writer.writerows(items)
        messagebox.showinfo('Separate lots exported',
            f'Saved {len(lots)} acquisition lots and {len(sold)} disposal allocations. '
            'PERSONAL_OPENING cost fields, even when filled, are UNVERIFIED historical entries; '
            'do not file them as certified tax basis without original Coinbase purchase records.')

    def _on_root_destroy(self,event):
        if event.widget is not self.root:return
        self.shutdown=True
        if self.stream:self.stream.close()
        if self.broker:self.broker.disarm()
        for token in self._scheduled.values():
            try:self.root.after_cancel(token)
            except Exception:pass
        self._scheduled.clear()

    def _close(self):
        if getattr(self,'_diagnostics_session',None) is not None:
            if not messagebox.askyesno('Diagnostics still exporting',
                'The diagnostic export is not finished. Closing now may lose this report. Close anyway?'):
                return
        self.shutdown=True
        if getattr(self,'experimental_shadow',None):
            self.experimental_shadow.disarm()
            for wallet in self.experimental_shadow.fifo_portfolios.values():
                try:wallet.close()
                except Exception:pass
        if getattr(self,'shadow_pilot',None):
            self.shadow_pilot.disarm()
            for wallet in self.shadow_pilot.fifo_portfolios.values():
                try:wallet.close()
                except Exception:pass
        if self.stream:self.stream.close()
        if self.broker:self.broker.disarm()
        self.root.destroy()

def main():
    from coincat_single_instance import SingleInstance,AnotherCoinCatRunning
    try:
        state_status(ROOT)  # required even when launched directly without START_WINDOWS.bat
        with SingleInstance(ROOT):
            root=tk.Tk();CoinCatApp(root);root.mainloop()
    except (AnotherCoinCatRunning, StateError) as exc:
        # No Tk created, no connection/ledger changes and no Coinbase orders.
        print('CoinCat launch blocked:',exc)
        raise SystemExit(2) from exc

if __name__=='__main__':main()
