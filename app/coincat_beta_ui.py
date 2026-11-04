"""Beta UI integration. Single worker serializes account/trade operations.

The stream receives independently but has no client, key, order or fill methods.
Only accepted GUI scan generations can queue a live decision. STOP sets the
process gate immediately; subsequent owned-order polling continues while paused.
"""
from copy import deepcopy
from decimal import Decimal as D
import threading
import time
import tkinter as tk
from tkinter import ttk

from coinbase_account import load_encrypted
from coincat_live import client_from_credentials
from coincat_live_beta import LiveBeta,LiveLimits,TERMINAL
from coincat_beta_controller import LiveCoordinator,protect_sdk_logs
from coincat_beta_store import BetaBlocked
from coincat_order_book import BookHub
from coincat_book_stream import BookStream
from coincat_manual_trade import ManualTradeStore,HistoryReader,ReadOnlyAPI,identity
from coincat_adaptive_eth import Frame
from coincat_global_paper import settings_at


class BetaUI:
    def _beta_init(self):
        self.live=LiveBeta(self.data/'research_data'/'live_beta');self.live_coordinator=LiveCoordinator(self.live)
        self.live_public=self.live.public();self.live_observe=False;self.live_limits_applied=None
        self.live_orders_blocked=tk.BooleanVar(value=True)
        self.live_limit_values={k:tk.StringVar(value=v) for k,v in (
            ('max_eth','0.005'),('max_order_usd','5'),('max_orders','4'),('duration_s','1800'),('max_fee_fraction','2'))}
        self.live_limit_status=tk.StringVar(value='Draft limits. Apply locally before starting REAL beta. One open order maximum.')
        self.book_hub=BookHub();self.book_stream=BookStream(self.book_hub)
        self.book_enabled=tk.BooleanVar(value=False);self.book_provider_enabled=tk.BooleanVar(value=False)
        self.book_public=self.book_stream.public();self.fee_units={}
        self.manual_store=ManualTradeStore(self.data/'research_data'/'manual_trade_lab'/'observations.sqlite3')
        self.manual_public=self.manual_store.public();self.manual_cancel=threading.Event()
        self._beta_shutdown_started=False

    def _beta_controls(self,parent,settings_parent,*,inline=False):
        row=parent if inline else ttk.Frame(parent)
        if not inline:row.pack(fill='x',pady=(0,3))
        ttk.Checkbutton(row,text='Live orders blocked · ON by default',variable=self.live_orders_blocked,
            command=self._live_switch_changed).pack(side='left')
        ttk.Checkbutton(row,text='Public order-book stream',variable=self.book_enabled,
            command=self._book_changed).pack(side='left',padx=8)
        box=ttk.LabelFrame(settings_parent,text='REAL beta limits · Apply, switch block OFF, then Start',padding=6);box.pack(fill='x',pady=6)
        for index,(key,label) in enumerate((('max_eth','Maximum session ETH'),('max_order_usd','Maximum order USD reference'),
                ('max_orders','Total order attempts'),('duration_s','Original session seconds'),('max_fee_fraction','Maximum fee %'))):
            r,c=divmod(index,3);cell=ttk.Frame(box);cell.grid(row=r,column=c,sticky='w',padx=8,pady=4)
            ttk.Label(cell,text=label).pack(anchor='w');ttk.Entry(cell,textvariable=self.live_limit_values[key],width=15).pack(anchor='w')
        ttk.Button(box,text='Apply live limits',command=self._apply_live_limits).grid(row=2,column=0,sticky='w',padx=8)
        ttk.Button(box,text='Reconcile owned live orders',command=self._reconcile_live).grid(row=2,column=1,sticky='w')
        ttk.Button(box,text='View private live journal…',command=self._view_live_journal).grid(row=2,column=2,sticky='w')
        ttk.Label(box,textvariable=self.live_limit_status,wraplength=900).grid(row=3,column=0,columnspan=3,sticky='w',pady=4)
        ttk.Checkbutton(box,text='Use healthy public L2 as sized research evidence (optional; fee units still required)',
            variable=self.book_provider_enabled).grid(row=4,column=0,columnspan=3,sticky='w')
        ttk.Label(box,text='STOP / block ON prevents new orders, requests cancellation of CoinCat-owned orders and reconciles racing fills.\n'
            'It never sells inventory. Restart always blocks live orders and requires reconciliation. No taker fallback.',wraplength=900).grid(row=5,column=0,columnspan=3,sticky='w',pady=4)

    def _apply_live_limits(self):
        try:
            if self.busy:raise BetaBlocked('WAIT_FOR_CURRENT_OPERATION')
            if self.live.store is not None:raise BetaBlocked('LIVE_LIMITS_FROZEN_FOR_EXISTING_SESSION')
            raw={k:D(v.get()) for k,v in self.live_limit_values.items()}
            for key in ('max_orders','duration_s'):
                if not raw[key].is_finite() or raw[key]!=raw[key].to_integral_value():raise BetaBlocked('INTEGER_LIMIT_REQUIRED')
                raw[key]=int(raw[key])
            raw['max_fee_fraction']/=100
            self.live_limits_applied=LiveLimits(**raw).checked()
            limit=self.live_limits_applied
            self.live_limit_status.set(f'Applied REAL caps: ≤{limit.max_eth} ETH, ≤${limit.max_order_usd}/order, 1 open, {limit.max_orders} total, {limit.duration_s}s. No automatic start.')
        except (ValueError,ArithmeticError,TypeError):
            self.live_limit_status.set('Limits not applied. Correct finite positive bounds; existing session limits remain frozen.')

    def _live_switch_changed(self):
        if self.live_orders_blocked.get():
            self._stop();self.paper_panel.message.set('LIVE BLOCK ON · owned orders will be canceled and reconciled; inventory is retained.')
        elif self.busy or self.running:
            self.live_orders_blocked.set(True);self.live.set_blocked(True)
            self.paper_panel.message.set('Stop and wait for the current operation before enabling REAL beta.')
        else:
            self.paper.pause(at=time.time());self.paper_public=self.paper.public();self.paper_observe=False
            self.live.set_blocked(False)
            self.paper_panel.message.set('REAL beta enabled. Apply explicit limits and Trading Settings, then press Start REAL Beta Trader. Qualifying checks still apply.')
        self._beta_refresh()

    def _start_auto_trader(self):
        if self.live_orders_blocked.get():self._start_auto_paper()
        else:self._start_live_beta()

    def _start_live_beta(self):
        if self.closed or self.busy:return
        settings=self.paper_panel.global_applied_draft
        if self.scanner is None or not self.connected or settings is None or self.allocation_editor.dirty_fields:
            self.paper_panel.message.set('Connect, apply the working allocation and Trading Settings before REAL Start.');return
        if self.live.store is None and self.live_limits_applied is None:
            self.paper_panel.message.set('Apply live beta limits on Trading Settings first.');return
        if self.live.blocked.is_set():
            self.paper_panel.message.set('Live block is ON. Switch it OFF deliberately before REAL Start.');return
        self.paper.pause(at=time.time());self.paper_observe=False
        self.generation+=1;self.cancel=threading.Event()
        funding=dict(draft=self.allocation_editor.parameters()['allocation_draft'],excluded=tuple(self.allocation_editor.excluded))
        rows=funding['draft'];carveouts={r.asset:r.manual+r.protected for r in rows}
        def start():
            self.live_coordinator.bind(self.scanner.client)
            self.live_coordinator.start(self.live_limits_applied,settings,funding=funding,carveouts=carveouts)
            return {'state':'LIVE_STARTED'}
        self._submit('beta_start',start)

    def _reconcile_live(self):
        if self.closed or self.busy:return
        self._stop()
        if self.scanner is None or self.live.store is None:
            self.paper_panel.message.set('Connect before reconciling a saved live session.');return
        def reconcile():
            self.live_coordinator.bind(self.scanner.client)
            self.live_coordinator.cycle(reconcile=True)
            return {'state':'LIVE_RECONCILED'}
        self._submit('beta_reconcile',reconcile)

    def _book_changed(self):
        if self.book_enabled.get():
            pair=self.paper_panel.selected_pair()
            if not self.book_stream.start(pair):self.book_enabled.set(self.book_stream.enabled)
        else:self.book_stream.stop()
        self._beta_refresh()

    def _beta_frame(self,frame):
        if not self.book_provider_enabled.get():return frame
        quotes=deepcopy(frame._quotes);depth={};units=deepcopy(frame._fee_units)
        # Only this pass's <=6 scheduled native products can enter a decision.
        for pair in tuple(quotes):
            view=self.book_hub.view(pair,at=frame.at)
            if view.state!='HEALTHY':continue
            quotes[pair]=(view.bids[0][0],view.asks[0][0],view.observed_at)
            for side in ('BUY','SELL'):
                depth[(pair,side)]=view.depth(side)
                units.pop((pair,side),None)  # timestamps/provenance must match
                raw=frame._rules.get(pair,{})
                # Accept only explicit authenticated native denomination metadata.
                declared=raw.get('fee_currency') or raw.get('commission_currency')
                if declared==pair.split('-')[1]:units[(pair,side)]=dict(currency=declared,verified=True,
                    observed_at=view.observed_at,source='AUTHENTICATED_PRODUCT_EXPLICIT_FEE_CURRENCY')
        self.fee_units=deepcopy(units)
        return Frame(frame.at,frame._catalog,frame._rules,quotes,frame._tier,frame._excluded,_depth=depth,_fee_units=units)

    def _queue_live_frame(self,frame,reference):
        if self.busy or self.closed:return
        self._submit('beta_cycle',lambda:dict(state='LIVE_CYCLE',public=self.live_coordinator.cycle(frame,reference)))

    def _beta_tick(self):
        if self.closed:return
        if not self.busy and self.live_coordinator.needs_poll():
            self._submit('beta_cycle',lambda:dict(state='LIVE_POLL',public=self.live_coordinator.cycle()))
        self._beta_refresh();self._schedule('beta_tick',1000,self._beta_tick)

    def _book_tick(self):
        if self.closed:return
        panel=getattr(self,'paper_panel',None)
        if panel is not None:
            page=panel.pages.get(panel.selected_pair())
            if page is not None and hasattr(page,'order_book'):page.order_book.refresh()
        self._schedule('book_tick',200,self._book_tick)

    def _beta_result(self,kind,payload,error):
        if kind=='manual_import':
            if error:self.manual_panel.status.set('Import incomplete/unavailable with current scope or native evidence. No balances or orders changed.')
            else:
                self.manual_public=self.manual_store.public();self.manual_panel.refresh()
                self.manual_panel.status.set('Import '+('complete as reported' if payload['complete'] else 'INCOMPLETE')+' · inspect native flow and unresolved evidence below. No bot fills credited.')
            return
        if error:
            self.live.set_blocked(True);self.live_orders_blocked.set(True)
            self.paper_panel.message.set('REAL beta needs attention. Live block ON; known identities and reservations retained. Reconcile before Start.')
        elif kind=='beta_start':
            self.live_observe=True;self.paper_observe=False;self.running=True
            self.applied_eth_key=None
            self.cancel=threading.Event();self.recovery.start();self._scan()
        self._beta_refresh()

    def _beta_refresh(self):
        self.live_public=self.live.public();self.book_public=self.book_stream.public()
        if self.live.blocked.is_set():self.live_orders_blocked.set(True)
        enabled=not self.live_orders_blocked.get()
        retained=self.live_observe or self.live_public['unresolved'] or self.live_public['state'] in ('RECONCILIATION_REQUIRED','UNKNOWN_LOCKED')
        if hasattr(self,'execution_badge'):self.execution_badge.configure(text='REAL BETA · LIVE ENABLED' if enabled else
            'LIVE BLOCK ON · OWNED INVENTORY RETAINED' if retained else 'LIVE ORDERS BLOCKED · PAPER / RESEARCH')
        if not hasattr(self,'paper_panel'):return
        panel=self.paper_panel
        panel.start_button.configure(text='Start REAL Beta Trader' if enabled else 'Start Auto Paper Trader')
        panel.mode_title.configure(text='AUTO TRADER · REAL BETA' if enabled else 'AUTO TRADER · PAPER')
        if enabled or self.live_observe or self.live_public['unresolved'] or self.live_public['state'] in ('RECONCILIATION_REQUIRED','UNKNOWN_LOCKED'):
            state=self.live.private_state()
            panel.message.set(self.live_public['state']+' · '+self.live_public['reason']+' · REAL beta; no demonstrated edge')
            if state:
                settings=settings_at(state)
                panel.applied_summary.set(f"REAL applied v{len(state['auto']['global_history'])} · ${settings.min_net_usd} net floor · source ≤{settings.source_pct}% · {settings.review_s}s review / {settings.reconsider_s}s child · Post Only · UNKNOWN blocks")
                wallet=' · '.join(a+': total '+str(q)+', available '+str(self.live.available(a)) for a,q in state['wallet'].items())
                mark=state.get('last_sample') or {}
                reports=state['auto'].get('completed_rotations',{})
                last=next(reversed(reports.values()),None) if reports else None
                completed='No completed ETH-return slice' if last is None else 'Last completed ETH-return slice '+last['state']+' · net USD '+str(last['net_usd'])+' vs $'+str(last['minimum_usd'])+' floor · settings v'+str(last['policy_version'])
                panel.score.set('REAL session inventory · '+wallet+'\nETH HOLD '+str(state['initial_eth'])+
                    ' · midpoint ΔETH '+str(mark.get('delta_eth','UNKNOWN'))+' before exit costs\n'+completed+' · not tax/account profit')
                active=next((o for o in state['orders'].values() if o['state'] not in TERMINAL),None)
                panel.active_order.set('No active REAL order. Held coins remain exposed.' if active is None else
                    active['pair']+' '+active['side']+' · '+active['state']+' · fixed limit '+str(active['limit_price'])+
                    ' · settled base '+str(active['filled_base'])+'/'+str(active['base_size'])+' · reserved '+str(active['reserved'])+' '+active['source']+
                    ' · resting '+str(round(max(0,time.time()-(active['accepted_at'] or time.time()))))+'s · settings v'+str(active['global_policy_version']))
                from coincat_paper_policy import BY_ID
                for view_id,variable in panel.direction_text.items():
                    row=self.live.view_rows.get(view_id,{})
                    view=BY_ID[view_id]
                    matches=[o for o in state['orders'].values() if o['pair']==view['pair'] and o['side']==view['side']]
                    order=matches[-1] if matches else None
                    phase=order['state'] if order is not None else row.get('state','HOLD')
                    if view_id in panel.direction_pages:
                        panel.direction_pages[view_id].heading_text.set(view['pair']+' · '+view['side']+' · '+view['source']+' → '+view['target']+' · REAL '+phase)
                    variable.set('REAL · '+row.get('state','HOLD')+' · '+row.get('reason','Await fresh eligible evidence / native fees / sized exits')+
                        ('\nFixed limit '+str(order['limit_price'])+' · filled '+str(order['filled_base'])+'/'+str(order['base_size'])+' · '+order['state'] if order else '')+
                        '\nNo automatic order unless complete ETH-return estimate qualifies. Cancel/reconcile precedes replacement.')
        if hasattr(self,'orders_tree'):
            for item in self.orders_tree.get_children():self.orders_tree.delete(item)
            state=self.live.private_state()
            if state:
                for order in state['orders'].values():
                    if order['state'] not in TERMINAL or order.get('reconciliation_unknown'):
                        self.orders_tree.insert('','end',values=(order['pair'],order['side'],order['limit_price'],order['base_size'],
                            order['state']+' / RECEIPT REVIEW' if order.get('reconciliation_unknown') else order['state']))

    def _manual_import(self,*,order_id=None,hours=None):
        if self.closed or self.busy or self.running:
            self.manual_panel.status.set('Stop scanning and wait for the current operation before an explicit history import.');return
        try:
            if order_id is not None:oid=identity(order_id.strip());seconds=None
            else:
                value=D(hours)
                if not value.is_finite() or not 1<=value<=168 or value!=value.to_integral_value():raise ValueError()
                seconds=int(value)*3600;oid=None
        except (ValueError,TypeError,ArithmeticError):
            self.manual_panel.status.set('Enter a complete order ID or 1–168 whole UTC hours.');return
        self.manual_cancel=threading.Event();cancel=self.manual_cancel
        def task():
            protect_sdk_logs()
            client=self.scanner.client if self.scanner is not None else client_from_credentials(self.credentials or load_encrypted())
            reader=HistoryReader(ReadOnlyAPI(client),cancel=cancel)
            if oid:
                record=reader.one(oid)
                run=dict(records=[record],portfolio=reader.portfolio,at=time.time(),complete=record['complete'],reason='EXACT_ORDER_READ')
            else:
                end=time.time();run=reader.window(end-seconds,end)
            self.manual_store.append(run)
            return {'state':'MANUAL_IMPORTED','complete':run['complete']}
        self.manual_panel.status.set('Reading permission-scoped order/fill history… no create/edit/cancel methods available.')
        self._submit('manual_import',task)

    def _cancel_manual_import(self):self.manual_cancel.set()

    def _view_live_journal(self):
        import json
        window=tk.Toplevel(self.root);window.title('Private REAL beta journal · no network request')
        body=ttk.Frame(window,padding=8);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Exact owned native receipts and unresolved evidence. Separate from tax, paper and manual history.').pack(anchor='w')
        text=tk.Text(body,width=110,height=30,wrap='word');text.pack(fill='both',expand=True)
        text.insert('1.0',json.dumps(self.live.private_state(),default=str,indent=2));text.configure(state='disabled')
        ttk.Button(body,text='Close',command=window.destroy).pack(anchor='e')
