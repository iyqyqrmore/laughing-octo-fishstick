"""Worker-side real beta orchestration. Tk receives cached safe status only."""
from copy import deepcopy
from datetime import datetime,timezone
from coincat_sdk_logging import protect_sdk_logs,_RedactedSDKLog

from coincat_adaptive_eth import Frame
from coincat_beta_store import BetaBlocked
from coincat_live import LiveBroker,LiveBlocked
from coincat_live_beta import LiveBeta,TERMINAL
from coincat_manual_trade import HistoryReader,ReadOnlyAPI
from coincat_global_paper import settings_at


class LiveCoordinator:
    def __init__(self,engine):
        if not isinstance(engine,LiveBeta):raise BetaBlocked('LIVE_BETA_ENGINE_REQUIRED')
        self.engine=engine;self.client=None;self.broker=None;self.last_poll_mono=None;self.carveouts={}
        self.failed_attempts=0;self.retry_at=None

    def bind(self,client):
        protect_sdk_logs();self.client=client;self.broker=LiveBroker(None,client)
        self.broker.live_runtime=self.engine

    def start(self,limits,settings,*,funding,carveouts):
        if self.client is None:raise BetaBlocked('CONNECT_BEFORE_LIVE_BETA_START')
        reader=HistoryReader(ReadOnlyAPI(self.client),clock=self.engine.clock,monotonic=self.engine.monotonic)
        permissions=reader.read('get_api_key_permissions')
        if permissions.get('can_view') is not True or permissions.get('can_trade') is not True or permissions.get('can_transfer') is not False:
            raise BetaBlocked('LIVE_VIEW_TRADE_NO_TRANSFER_REQUIRED')
        portfolio=reader.scope();account=reader.account_snapshot()
        if self.engine.store is None:
            proposal=dict(funding,balances=account['available'],balances_at=account['at'])
            self.engine.create(limits,settings,funding=proposal,portfolio=portfolio,at=self.engine.clock())
        elif self.engine.private_state()['portfolio']!=portfolio:raise BetaBlocked('LIVE_PORTFOLIO_CHANGED_RECONCILE')
        self.carveouts=deepcopy(carveouts);self.engine.apply_settings(settings)
        self.engine.start();self.last_poll_mono=None;self.failed_attempts=0;self.retry_at=None
        return self.engine.public()

    def recover(self,reader,reference):
        state=self.engine.private_state();order=state['orders'][reference]
        if order['order_id']:return
        if order['state']=='RESERVED' and order['dispatch_count']==0:
            self.engine.sent_result(reference,{},definitely_not_sent=True);return
        # Absence is never evidence that an ambiguous POST failed. Keep locked.
        cursor=None;seen=set();found=[]
        for _ in range(8):
            args=dict(product_ids=[order['pair']],retail_portfolio_id=state['portfolio'],limit=100,
                start_date=datetime.fromtimestamp(order['created_at']-60,timezone.utc).isoformat())
            if cursor:args['cursor']=cursor
            page=reader.read('list_orders',**args)
            if not isinstance(page.get('orders'),list):raise BetaBlocked('LIVE_IDENTITY_RECOVERY_INCOMPLETE')
            for actual in page['orders']:
                if actual.get('client_order_id')==reference:found.append(actual)
            if page.get('has_next') is False:break
            cursor=page.get('cursor')
            if page.get('has_next') is not True or not cursor or cursor in seen:raise BetaBlocked('LIVE_IDENTITY_RECOVERY_INCOMPLETE')
            seen.add(cursor)
        else:raise BetaBlocked('LIVE_IDENTITY_RECOVERY_INCOMPLETE')
        unique={o.get('order_id'):o for o in found}
        if len(unique)!=1:raise BetaBlocked('LIVE_UNKNOWN_PLACEMENT_NO_RETRY')
        self.engine.recover_identity(reference,next(iter(unique.values())))

    def _cancel_due(self,order,frame):
        engine=self.engine;now=engine.clock();mono=engine.monotonic()
        if engine.blocked.is_set() or engine.stop_requested.is_set():return True
        if engine.deadline_mono is not None and mono>=engine.deadline_mono:return True
        if now>=order['campaign_deadline']:return True
        accepted=engine.accepted_mono.get(order['reference'])
        settings=settings_at(engine.private_state())
        if accepted is not None:
            pinned=settings_at(engine.private_state(),order['global_policy_version'])
            if mono-accepted>=pinned.reconsider_s:return True
        elif now>=order['expires_at']:return True
        if frame is None:return False
        state=engine.private_state();version=len(state['auto']['global_history'])
        if order['global_policy_version']!=version and order.get('reviewed_version')!=version:
            valid=False
            if not order['filled_base']:
                try:
                    from coincat_paper_policy import paper_frame,receipt
                    from coincat_global_paper import qualification,source_budget
                    planning=paper_frame(frame,engine.config,planning=True)
                    available=engine.available(order['source'])+order['reserved']
                    maximum=source_budget(state,available,dict(source=order['source']),settings,initial=order['initial_slice_order'])
                    plan=receipt(planning,order['pair'],order['side'],order['reserved'],order['limit_price'],planning.rates('MAKER'))
                    valid=order['reserved']<=maximum and qualification(state,planning,plan,order['reserved'],engine.last_reference,settings)['state']=='CONDITIONAL_QUALIFIED'
                except (ValueError,TypeError,KeyError,ArithmeticError):pass
            if valid:
                engine._change('RETAIN_PRICE',dict(reference=order['reference'],version=version),
                    lambda s:s['orders'][order['reference']].update(reviewed_version=version))
            else:return True
        if accepted is not None and mono-accepted>=engine.config.min_rest_s:
            try:
                bid,ask,_=frame.book(order['pair']);market=bid if order['side']=='BUY' else ask
                threshold=max(order['price_increment']*2,order['limit_price']*engine.config.reprice_bps/10000)
                if abs(market-order['limit_price'])>=threshold:return True
            except (ValueError,KeyError,ArithmeticError):pass
        return False

    def cycle(self,frame=None,reference=None,*,reconcile=False):
        engine=self.engine
        if engine.store is None or self.client is None:return engine.public()
        if reconcile:self.failed_attempts=0;self.retry_at=None
        elif self.failed_attempts>=5 or self.retry_at is not None and engine.monotonic()<self.retry_at:return engine.public()
        unresolved=False
        try:
            reader=HistoryReader(ReadOnlyAPI(self.client),clock=engine.clock,monotonic=engine.monotonic);scope=reader.scope()
            state=engine.private_state()
            if scope!=state['portfolio']:raise BetaBlocked('LIVE_PORTFOLIO_CHANGED')
            if reference is not None:engine.last_reference=deepcopy(reference)
            closed_now=False
            for cid,original in state['orders'].items():
                if original['state'] in TERMINAL and not reconcile:continue
                self.recover(reader,cid);current=engine.private_state()['orders'][cid]
                if current['state'] in TERMINAL and not reconcile:closed_now=True;continue
                record=reader.one(current['order_id'])
                if not engine.reconcile_order(cid,record['order'],record['fills'],complete=record['complete']):
                    unresolved=True
                    # Known live resting orders can still be canceled; uncertain
                    # fees never release a reservation or authorize another order.
                    current=engine.private_state()['orders'][cid]
                    if record['order'].get('status') in ('OPEN','PENDING','ACTIVE'):
                        try:self.broker.cancel_live_beta(cid)
                        except (ValueError,LiveBlocked):pass
                    continue
                current=engine.private_state()['orders'][cid]
                if current['state'] in TERMINAL:closed_now=True
                elif self._cancel_due(current,frame):self.broker.cancel_live_beta(cid)
            state=engine.private_state()
            if reconcile:
                if unresolved:raise BetaBlocked('LIVE_NATIVE_RECEIPTS_STILL_UNRESOLVED')
                account=reader.account_snapshot()
                for asset,owned in state['wallet'].items():
                    if owned>max(0,account['available'].get(asset,0)-self.carveouts.get(asset,0)):
                        engine.lock_unknown(None,'LIVE_BALANCE_BELOW_OWNED_FUNDS')
                        raise BetaBlocked('LIVE_BALANCE_BELOW_OWNED_FUNDS')
                engine.finish_reconciliation();return engine.public()
            expired=engine.clock()>=state['limits']['expires_at'] or (
                engine.deadline_mono is not None and engine.monotonic()>=engine.deadline_mono)
            if expired:
                engine.set_blocked(True)
                engine._change('EXPIRED',{},lambda s:s.update(mode='EXPIRED',reason='LIVE_ORIGINAL_SESSION_EXPIRED_HOLD_INVENTORY'))
            if frame is not None and state['mode'] not in ('UNKNOWN_LOCKED','RECONCILIATION_REQUIRED'):
                decision=Frame(engine.clock(),frame._catalog,frame._rules,frame._quotes,frame._tier,frame._excluded,
                    _depth=frame._depth,_fee_units=frame._fee_units)
                engine.sample(decision,reference)
                if (not closed_now and not engine.blocked.is_set() and not engine.stop_requested.is_set() and
                        engine.private_state()['mode']=='ACTIVE'):
                    account=reader.account_snapshot();account['carveouts']=deepcopy(self.carveouts)
                    decision=Frame(engine.clock(),frame._catalog,frame._rules,frame._quotes,frame._tier,frame._excluded,
                        _depth=frame._depth,_fee_units=frame._fee_units)
                    cid=engine.prepare(decision,reference,account=account)
                    if cid:self.broker.submit(live_dispatch=cid)
            if engine.stop_requested.is_set() and not any(o['state'] not in TERMINAL for o in engine.private_state()['orders'].values()):
                if engine.private_state()['mode']=='ACTIVE':engine._change('PAUSE',{},lambda s:s.update(mode='PAUSED',reason='LIVE_STOPPED_KNOWN_RECEIPTS_RETAINED'))
            if unresolved:self._retry_failure()
            else:self.failed_attempts=0;self.retry_at=None
        except (BetaBlocked,LiveBlocked):
            self._retry_failure()
            engine.blocked.set();engine.stop_requested.set();engine._authorized=False
            state=engine.private_state()
            if state is not None and state['mode'] not in ('UNKNOWN_LOCKED','RECONCILIATION_REQUIRED','EXPIRED'):
                engine._change('ATTENTION',{},lambda s:s.update(mode='PAUSED',reason='LIVE_NATIVE_DATA_OR_NETWORK_NEEDS_ATTENTION'))
        except Exception:
            self._retry_failure()
            engine.blocked.set();engine.stop_requested.set();engine._authorized=False;engine.problem='LIVE_STORAGE_OR_READ_REVIEW_REQUIRED'
        finally:self.last_poll_mono=engine.monotonic()
        return engine.public()

    def _retry_failure(self):
        self.failed_attempts+=1
        self.retry_at=self.engine.monotonic()+min(60,3*2**min(4,self.failed_attempts-1))

    def needs_poll(self):
        state=self.engine.private_state()
        if state is None or self.client is None:return False
        if self.failed_attempts>=5 or self.retry_at is not None and self.engine.monotonic()<self.retry_at:return False
        unsettled=any(o['state'] not in TERMINAL for o in state['orders'].values())
        delay=3 if self.engine.stop_requested.is_set() and unsettled else 30
        return unsettled and (self.last_poll_mono is None or self.engine.monotonic()-self.last_poll_mono>=delay)
