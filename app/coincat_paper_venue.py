"""Seeded BBO stress scenarios, explicitly NOT observed queue reconstruction.

No network, credentials or Coinbase order adapter. Strict quote penetration is
only an eligibility input: delay, sustained observations, synthetic queue ahead
and a seeded execution gate are additionally required. A touch alone never fills.
"""
from copy import deepcopy
from decimal import Decimal as D,localcontext

from coincat_eth_maker import post_only_eligible
from coincat_paper_engine import TERMINAL,PaperBlocked
from coincat_paper_policy import paper_frame,random_fraction,rounded
from coincat_v80_immediate import exact
from coincat_watchlist import product_eligibility

LATENCY_S=2
MODEL_PARAMETERS={
    'NO_FILL_V1':dict(rest_s=30,probability=D(0),partial=D('.25'),fee_multiplier=D(1)),
    'CONSERVATIVE_STRESS_V1':dict(rest_s=30,probability=D('.2'),partial=D('.25'),fee_multiplier=D(1)),
    'PARTIAL_SCARCE_V1':dict(rest_s=60,probability=D('.1'),partial=D('.1'),fee_multiplier=D(1)),
    'ADVERSE_SLOW_V1':dict(rest_s=60,probability=D('.1'),partial=D('.1'),fee_multiplier=D('1.5')),
}


def event(kind,reference,identity,at,data):
    return dict(event_id=identity,source='EXPLICIT_SIMULATION',kind=kind,reference=reference,at=at,data=data)


class StressVenue:
    """All probabilities/queue sizes are declared assumptions, never market data."""
    def __init__(self,config):self.config=config;self.parameters=deepcopy(MODEL_PARAMETERS[config.model])

    def assumptions(self):
        return dict(version=self.config.model,parameters=deepcopy(self.parameters),latency_s=LATENCY_S,
            strict_penetration=True,min_cross_samples=3,min_cross_span_s=10,queue_multiple=(D(2),D(4)),
            observed_queue=False,observed_volume=False,fee_currency='DECLARED_SIMULATED_QUOTE_DEBIT',
            fee_rounding='UP_TO_NATIVE_QUOTE_INCREMENT_WITHIN_CEILING')

    @staticmethod
    def _context(engine):
        context=engine.private_state().get('auto')
        if not isinstance(context,dict) or context.get('schema')!=1:raise PaperBlocked('AUTO_PAPER_CONTEXT_REQUIRED')
        return context

    def _deliver(self,engine,pending,frame):
        context=self._context(engine);reference=pending['reference']
        state=engine.private_state();order=state['orders'][reference]
        meta=context['venue'][reference]
        context['pending']=[p for p in context['pending'] if p['identity']!=pending['identity']]
        if pending['kind']=='FILL':
            if order['state'] in TERMINAL:
                raise PaperBlocked('PAPER_PENDING_FILL_AFTER_TERMINAL_REQUIRES_REVIEW')
            payload=pending['event'];meta['fills']+=1
        elif pending['kind']=='ACK':
            # Arrival is checked against this fresh observed frame, never a
            # later book used to backdate acceptance to an earlier instant.
            if frame is None:return False
            try:
                fresh=paper_frame(frame,self.config);book=fresh.book(order['pair'])
                tick=order['price_increment']
                eligible=(order['pair'] in frame._catalog and product_eligibility(order['pair'],frame._rules) is None and
                    not set((order['source'],order['target']))&set(frame._excluded))
                accepted=eligible and post_only_eligible(order['side'],order['limit_price'],book,tick) and frame.at<order['expires_at']
            except (ValueError,TypeError,KeyError,ArithmeticError):return False
            if accepted:
                meta.update(accepted_at=frame.at,last_quote_at=book[2],last_seen=frame.at,consecutive=0,
                    cross_started=None,step=0,data_state='BBO_STRESS_WARMUP',
                    queue_left=order['base_size']*(2+random_fraction(self.config.seed,reference,0,'queue')*2))
                payload=event('ACK',reference,pending['identity'],frame.at,dict(venue_order_id=meta['venue_id']))
            else:
                meta['rejected']=True
                payload=event('REJECT',reference,pending['identity'],frame.at,dict(venue_order_id=None,cumulative_base=D(0)))
        else:
            # Only already determined earlier fills can race a known cancel.
            # A cancellation removes not-yet-executed future scenario events.
            context['pending']=[p for p in context['pending'] if p['reference']!=reference or p['due_at']<=pending['due_at']]
            payload=event('CANCEL_ACK',reference,pending['identity'],pending['due_at'],
                dict(venue_order_id=meta['venue_id'],cumulative_base=order['filled_base']))
            meta['canceled']=True
        engine.ingest(payload,context_after=context)
        return True

    def settle_due(self,engine,*,at,frame=None):
        context=self._context(engine)
        due=sorted((p for p in context['pending'] if p['due_at']<=at),
            key=lambda p:(p['due_at'],0 if p['kind']=='FILL' else 1,p['identity']))
        for pending in due:
            if pending['identity'] not in {p['identity'] for p in self._context(engine)['pending']}:continue
            self._deliver(engine,pending,frame)

    def advance(self,engine,frame):
        self.settle_due(engine,at=frame.at,frame=frame)
        state=engine.private_state();context=self._context(engine)
        # Persist command receipt in the same transaction as its once-only grant.
        for command in engine.pending_commands():
            reference=command['reference'];order=engine.private_state()['orders'][reference]
            context=self._context(engine)
            if command['kind']=='PLACE_POST_ONLY':
                context['venue'][reference]=dict(venue_id='sim_'+reference,received_at=frame.at,
                    accepted_at=None,fills=0,gaps=0,last_quote_at=None,last_seen=None,consecutive=0,
                    cross_started=None,queue_left=None,step=0,rejected=False,canceled=False)
                kind='ACK';identity='ack_'+reference
            else:kind='CANCEL_ACK';identity='cancel_ack_'+reference
            context['pending'].append(dict(kind=kind,reference=reference,identity=identity,due_at=frame.at+LATENCY_S))
            grant=engine.mark_dispatched('dispatch_'+command['command_id'],command['command_id'],
                at=frame.at,context_after=context)
            if not grant.get('dispatch_permitted'):raise PaperBlocked('PAPER_DISPATCH_GRANT_NOT_AVAILABLE')
        state=engine.private_state()
        if state['mode']!='ACTIVE':return
        try:fresh=paper_frame(frame,self.config)
        except (ValueError,TypeError,KeyError,ArithmeticError):return
        with localcontext() as precision:
            precision.prec=60
            for reference,order in state['orders'].items():
                if order['state'] in TERMINAL or order['state'] in ('PENDING_NEW','UNKNOWN'):continue
                context=self._context(engine);meta=context['venue'].get(reference)
                if not meta or meta['accepted_at'] is None:continue
                if any(p['reference']==reference and p['kind']=='FILL' for p in context['pending']):continue
                rules=frame._rules.get(order['pair'],{})
                try:
                    eligible=(order['pair'] in frame._catalog and product_eligibility(order['pair'],frame._rules) is None and
                        not set((order['source'],order['target']))&set(frame._excluded) and
                        exact(rules['base_increment'])==order['base_increment'] and
                        exact(rules.get('price_increment',rules['quote_increment']))==order['price_increment'])
                except (ValueError,TypeError,KeyError,ArithmeticError):eligible=False
                if not eligible:
                    meta.update(data_state='PRODUCT_OR_NATIVE_RULE_UNAVAILABLE',consecutive=0,cross_started=None)
                    engine.checkpoint_context(context);continue
                try:book=fresh.book(order['pair'])
                except (ValueError,TypeError,KeyError,ArithmeticError):
                    if (order['pair'] not in frame._quotes and meta['last_quote_at'] is not None and
                            0<=frame.at-meta['last_quote_at']<=30):
                        meta['data_state']='DEFERRED_CURRENT_PASS'
                        engine.checkpoint_context(context);continue
                    if meta.get('data_state')!='GAP':meta['gaps']+=1
                    meta.update(data_state='GAP',consecutive=0,cross_started=None)
                    engine.checkpoint_context(context);continue
                stamp=book[2]
                if meta['last_quote_at'] is not None and stamp<=meta['last_quote_at']:continue
                if meta['last_quote_at'] is not None and stamp-meta['last_quote_at']>30:
                    meta.update(consecutive=0,cross_started=None);meta['gaps']+=1
                meta.update(last_quote_at=stamp,last_seen=frame.at,data_state='BBO_STRESS_ASSUMPTION')
                meta['step']+=1
                crossed=book[1]<order['limit_price'] if order['side']=='BUY' else book[0]>order['limit_price']
                if not crossed:
                    meta.update(consecutive=0,cross_started=None);engine.checkpoint_context(context);continue
                meta['consecutive']+=1
                if meta['cross_started'] is None:meta['cross_started']=stamp
                if (self.config.model=='NO_FILL_V1' or meta['consecutive']<3 or stamp-meta['cross_started']<10 or
                        frame.at-meta['accepted_at']<self.parameters['rest_s']):
                    engine.checkpoint_context(context);continue
                # This is explicitly SYNTHETIC flow capacity, not observed
                # volume/depth. It is never placed in market snapshots or charts.
                assumed_flow=order['base_size']*random_fraction(self.config.seed,reference,meta['step'],'flow')/2
                queue_before=meta['queue_left'];meta['queue_left']=max(D(0),queue_before-assumed_flow)
                if queue_before>=assumed_flow or random_fraction(self.config.seed,reference,meta['step'],'execute')>=self.parameters['probability']:
                    engine.checkpoint_context(context);continue
                remaining=order['base_size']-order['filled_base']
                size=rounded(min(remaining,assumed_flow-queue_before,order['base_size']*self.parameters['partial']),order['base_increment'])
                if size<=0:engine.checkpoint_context(context);continue
                fee=fresh.rates('MAKER')*self.parameters['fee_multiplier']
                if fee>self.config.fee_ceiling:
                    context['last_reason']='PAPER_FEE_BOUND_REVIEW_REQUIRED'
                    engine.checkpoint_context(context);engine.stop('fee_bound_'+reference,at=frame.at);return
                due=frame.at+LATENCY_S
                commission=rounded(size*order['limit_price']*fee,
                    exact(frame._rules[order['pair']]['quote_increment']),up=True)
                if commission>size*order['limit_price']*self.config.fee_ceiling:
                    context['last_reason']='PAPER_NATIVE_FEE_ROUNDING_OUTSIDE_CEILING'
                    engine.checkpoint_context(context);continue
                identity='fill_'+reference+'_'+str(meta['step'])
                payload=event('FILL',reference,identity,due,dict(fill_id=identity,venue_order_id=meta['venue_id'],
                    price=order['limit_price'],size=size,size_in_quote=False,
                    commission=commission,fee_currency=order['pair'].split('-')[1],liquidity='MAKER'))
                context['pending'].append(dict(kind='FILL',reference=reference,identity=identity,due_at=due,event=payload))
                engine.checkpoint_context(context)

    def reconciliation_snapshot(self,engine,*,at):
        """A simulated provider ledger, never a purported Coinbase snapshot.

        Previously scheduled explicit fills settle first. Unknown fees/history
        remain blocked. Requests not accepted before shutdown are rejected;
        existing accepted paper orders retain reserves and original expiry.
        """
        self.settle_due(engine,at=at)
        state=engine.private_state();context=self._context(engine)
        if any(not f['settled'] for f in state['fills'].values()):raise PaperBlocked('PAPER_FEE_EVIDENCE_STILL_REQUIRED')
        from coincat_paper_policy import reference_costs
        reference_costs(state)  # Assert exact replay of all canonical native receipts.
        orders={}
        for reference,order in state['orders'].items():
            if order['state'] in TERMINAL:continue
            meta=context['venue'].get(reference)
            if meta is None or meta.get('accepted_at') is None:
                if order['filled_base']:raise PaperBlocked('PAPER_VENUE_HISTORY_INCOMPLETE')
                orders[reference]=dict(state='REJECTED',filled_base=D(0),venue_order_id=None)
            else:
                orders[reference]=dict(state='CANCELED' if meta.get('canceled') else
                    'PARTIAL' if order['filled_base'] else 'OPEN',filled_base=order['filled_base'],venue_order_id=meta['venue_id'])
        return state['wallet'],orders
