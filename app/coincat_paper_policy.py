"""Frozen patient-maker PAPER policy. Pure inputs; no clients or live authority."""
from copy import deepcopy
from dataclasses import dataclass,asdict
from decimal import Decimal as D,localcontext,ROUND_FLOOR,ROUND_CEILING
import hashlib

from coincat_adaptive_eth import Frame
from coincat_multicurrency import research_order
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS,product_eligibility

POLICY='PATIENT_MAKER_ETH_V1'
SHORT_POLICY='SHORT_LIVED_ETH_V1'
POLICIES=(POLICY,SHORT_POLICY)
MODELS=('NO_FILL_V1','CONSERVATIVE_STRESS_V1','PARTIAL_SCARCE_V1','ADVERSE_SLOW_V1')
DIRECTIONS=tuple(dict(id=src+'_'+dst,pair=pair,side=side,source=src,target=dst)
    for src,dst,pair,side in (
        ('ETH','BTC','ETH-BTC','SELL'),('BTC','ETH','ETH-BTC','BUY'),
        ('ETH','SOL','SOL-ETH','BUY'),('SOL','ETH','SOL-ETH','SELL'),
        ('ETH','LINK','LINK-ETH','BUY'),('LINK','ETH','LINK-ETH','SELL'),
        ('ETH','ADA','ADA-ETH','BUY'),('ADA','ETH','ADA-ETH','SELL'),
        ('BTC','SOL','SOL-BTC','BUY'),('SOL','BTC','SOL-BTC','SELL'),
        ('BTC','LINK','LINK-BTC','BUY'),('LINK','BTC','LINK-BTC','SELL'),
        ('BTC','ADA','ADA-BTC','BUY'),('ADA','BTC','ADA-BTC','SELL')))
BY_ID={v['id']:v for v in DIRECTIONS}
KICKOFFS=tuple(v['id'] for v in DIRECTIONS if v['source']=='ETH')


def rounded(value,increment,up=False):
    return (value/increment).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*increment


def direction_defaults():
    return {v['id']:dict(enabled=True,target_pct=D('.25'),entry_bps=D(0),source_pct=D(100),wait_s=86400)
            for v in DIRECTIONS}


@dataclass(frozen=True)
class AutoConfig:
    amount_eth:D
    directions:dict
    opt_in:bool=False
    kickoff:str='ETH_BTC'
    model:str='CONSERVATIVE_STRESS_V1'
    seed:int=1
    review_s:int=30
    cooldown_s:int=30
    duration_s:int=86400
    max_orders:int=16
    fee_ceiling:D=D('.02')
    fee_stress_bps:D=D(5)
    membership:str='Basic'
    policy:str=POLICY
    order_ttl_s:int=120
    min_rest_s:int=30
    reprice_bps:D=D(10)

    def checked(self):
        amount=exact(self.amount_eth)
        if not 0<amount<=D(1000000) or type(self.opt_in) is not bool:raise ValueError('INVALID_PAPER_BUDGET_OR_OPT_IN')
        if self.kickoff not in KICKOFFS or self.model not in MODELS:raise ValueError('INVALID_PAPER_KICKOFF_OR_MODEL')
        if type(self.seed) is not int or not 0<=self.seed<2**32:raise ValueError('INVALID_PAPER_SEED')
        for key,low,high in (('review_s',5,300),('cooldown_s',5,3600),('duration_s',60,259200),('max_orders',2,64)):
            if type(getattr(self,key)) is not int or not low<=getattr(self,key)<=high:raise ValueError('INVALID_PAPER_SESSION_LIMIT')
        ceiling,stress=exact(self.fee_ceiling),exact(self.fee_stress_bps)
        if not 0<ceiling<D('.05') or not 0<=stress<=50:raise ValueError('INVALID_PAPER_FEE_BOUND')
        if self.membership not in ('None','Basic','Preferred','Premium'):raise ValueError('INVALID_MEMBERSHIP_LABEL')
        if self.policy not in POLICIES:raise ValueError('INVALID_PAPER_ORDER_POLICY')
        if (type(self.order_ttl_s) is not int or not 60<=self.order_ttl_s<=600 or
                type(self.min_rest_s) is not int or not 30<=self.min_rest_s<self.order_ttl_s):
            raise ValueError('INVALID_SHORT_ORDER_LIFETIME')
        reprice=exact(self.reprice_bps)
        if not 1<=reprice<=100:raise ValueError('INVALID_PAPER_REPRICE_THRESHOLD')
        if not isinstance(self.directions,dict) or set(self.directions)!=set(BY_ID):raise ValueError('ALL_FOURTEEN_VIEWS_REQUIRED')
        settings=deepcopy(self.directions)
        for row in settings.values():
            if set(row)!={'enabled','target_pct','entry_bps','source_pct','wait_s'} or type(row['enabled']) is not bool:
                raise ValueError('INVALID_PAPER_DIRECTION_SETTING')
            for key,low,high in (('target_pct',D('.01'),D(5)),('entry_bps',D(0),D(50)),('source_pct',D('.01'),D(100))):
                row[key]=exact(row[key])
                if not low<=row[key]<=high:raise ValueError('INVALID_PAPER_DIRECTION_BOUND')
            if type(row['wait_s']) is not int or not 30<=row['wait_s']<=259200:raise ValueError('INVALID_PAPER_ORDER_EXPIRY')
        if not settings[self.kickoff]['enabled']:raise ValueError('CHOSEN_KICKOFF_DISABLED')
        return AutoConfig(amount,settings,self.opt_in,self.kickoff,self.model,self.seed,self.review_s,self.cooldown_s,
            self.duration_s,self.max_orders,ceiling,stress,self.membership,self.policy,self.order_ttl_s,self.min_rest_s,reprice)

    def frozen(self):
        data=asdict(self.checked())
        if self.policy==POLICY:
            # Preserve the exact previously published configuration identity.
            # Old sessions keep their original policy, caps and expiry.
            for key in ('policy','order_ttl_s','min_rest_s','reprice_bps'):data.pop(key)
        return data


def paper_frame(frame,config,*,planning=False):
    """Narrow current-pass boundary. No cached/deferred books or invented depth."""
    if not isinstance(frame,Frame) or not set(frame._quotes)<=set(WATCH_PAIRS) or len(frame._quotes)>6:
        raise ValueError('PAPER_FRAME_SCOPE_INVALID')
    stamps=[]
    for pair in frame._quotes:
        if product_eligibility(pair,frame._rules) is not None:continue
        try:stamps.append(frame.book(pair)[2])
        except (ValueError,TypeError,KeyError,ArithmeticError):pass
    if stamps and max(stamps)-min(stamps)>12:raise ValueError('QUOTE_DECISION_SPAN_EXCEEDS_12S')
    maker,taker=frame.rates('MAKER'),frame.rates('TAKER')
    maker+=config.fee_stress_bps/10000;taker+=config.fee_stress_bps/10000
    if maker>config.fee_ceiling or taker>=D('.05'):raise ValueError('PAPER_FEE_EVIDENCE_OUTSIDE_BOUND')
    tier=dict(frame._tier,maker=config.fee_ceiling if planning else maker,taker=taker)
    return Frame(frame.at,frame._catalog,frame._rules,frame._quotes,tier,frame._excluded,
        _depth=frame._depth,_fee_units=frame._fee_units)


def receipt(frame,pair,side,budget,price,fee):
    value=research_order(pair=pair,side=side,available=budget,cap=budget,usd_rate=D(1),
        book=(price,price,frame.at),product_rules=frame._rules,fee=fee,slip=D(0))
    value.pop('approx_usd_notional',None)
    value['fee_rate_source']='DECLARED_PAPER_VENUE_FEE_NOT_EXCHANGE_UNIT_VERIFICATION'
    return value


def _reference_ledger(state):
    """Attribute the original simulated ETH to known native receipts, not tax lots.

    Native debits/credits come from the engine's normalize_fill settlement. This
    does not calculate another receipt or touch financial cost-basis records.
    """
    wallet={'ETH':state['initial_eth']};reference={'ETH':state['initial_eth']};realized=D(0);fees={};completed={}
    with localcontext() as ctx:
        ctx.prec=60
        fills=sorted((f for f in state['fills'].values() if f['settled']),key=lambda f:f['settle_index'])
        for index,fill in enumerate(fills,1):
            if fill['settle_index']!=index:raise ValueError('PAPER_REFERENCE_HISTORY_INCOMPLETE')
            src,dst,debit,credit=(fill[k] for k in ('source','target','debit','credit'))
            allocation=reference.get(src,D(0))*debit/wallet[src]
            reference[src]=reference.get(src,D(0))-allocation
            wallet[src]-=debit;wallet[dst]=wallet.get(dst,D(0))+credit
            reference[dst]=reference.get(dst,D(0))+(credit if dst=='ETH' else allocation)
            if dst=='ETH':
                realized+=credit-allocation
                item=completed.setdefault(fill['reference'],dict(net_eth=D(0),allocation_eth=D(0),returned_eth=D(0),at=0))
                item.update(net_eth=item['net_eth']+credit-allocation,allocation_eth=item['allocation_eth']+allocation,
                    returned_eth=item['returned_eth']+credit,at=max(item['at'],fill['raw']['at']))
            currency=fill['raw']['fee_currency'];fees[currency]=fees.get(currency,D(0))+exact(fill['raw']['commission'])
        if any(wallet.get(a,D(0))!=state['wallet'].get(a,D(0)) for a in WATCH_ASSETS):
            raise ValueError('PAPER_REFERENCE_BALANCE_MISMATCH')
    return reference,realized,fees,completed


def reference_costs(state):return _reference_ledger(state)[:3]


def realized_orders(state):return _reference_ledger(state)[3]


def eth_mark(wallet,frame):
    """Midpoint reference only. Missing prices stay UNKNOWN, never zero loss."""
    total=D(0);stamps=[]
    with localcontext() as ctx:
        ctx.prec=60
        for asset,qty in wallet.items():
            if qty==0:continue
            if asset=='ETH':total+=qty;continue
            pair='ETH-BTC' if asset=='BTC' else asset+'-ETH'
            bid,ask,stamp=frame.book(pair);stamps.append(stamp)
            midpoint=(bid+ask)/2
            total+=qty/midpoint if asset=='BTC' else qty*midpoint
        if stamps and max(stamps)-min(stamps)>12:raise ValueError('QUOTE_DECISION_SPAN_EXCEEDS_12S')
    return total


def patient_return_price(frame,view,budget,required_eth,fee):
    rule=frame._rules[view['pair']];tick=exact(rule.get('price_increment',rule['quote_increment']))
    if view['target']!='ETH':raise ValueError('PATIENT_RETURN_REQUIRES_ETH_DESTINATION')
    if view['side']=='SELL':
        units=rounded(budget,exact(rule['base_increment']))
        price=rounded(required_eth/(units*(1-fee)),tick,up=True)
    else:
        units=rounded(required_eth,exact(rule['base_increment']),up=True)
        native_budget=rounded(budget,exact(rule['quote_increment']))
        price=rounded(native_budget/(units*(1+fee)),tick)
    if price<=0:raise ValueError('TARGET_PRICE_BELOW_TICK')
    return price


def candidates(engine,frame,config,*,review_reference=None,kickoff=False,budget_limits=None):
    state=engine.private_state();costs,_,_=reference_costs(state);rows={}
    planning=paper_frame(frame,config,planning=True);fee=planning.rates('MAKER')
    released=state['orders'].get(review_reference,{})
    with localcontext() as ctx:
        ctx.prec=60
        for view in DIRECTIONS:
            key=view['id'];setting=config.directions[key]
            row=dict(view,state='BLOCKED',reason='UNOBSERVED',priority=0,score=D(0),at=frame.at)
            rows[key]=row
            try:
                if not setting['enabled']:raise ValueError('USER_DISABLED')
                if view['pair'] not in frame._catalog:raise ValueError('NOT_IN_AUTHENTICATED_CATALOG')
                blocked=product_eligibility(view['pair'],frame._rules)
                if blocked:raise ValueError(blocked)
                if set((view['source'],view['target']))&set(frame._excluded):raise ValueError('EXCLUDED')
                book=frame.book(view['pair']);row['book']=book
                row['quote_age_s']=frame.at-book[2]
                available=engine.available(view['source'])
                if available is None:raise ValueError('PAPER_RECONCILIATION_REQUIRED')
                if released.get('source')==view['source']:available+=released['reserved']
                if available<=0:raise ValueError('UNFUNDED_AWAIT_CONFIRMED_TERMINAL_RECEIPT')
                cap=state['limits']['source_caps'].get(view['source'],D(0))
                budget=min(available,cap)*setting['source_pct']/100
                if config.policy==SHORT_POLICY:
                    if released.get('source')==view['source']:budget=min(budget,released['reserved'])
                    if budget_limits is not None and view['source'] in budget_limits:
                        budget=min(budget,budget_limits[view['source']])
                if budget<=0:raise ValueError('PAPER_NATIVE_CAP_UNAVAILABLE')
                rule=frame._rules[view['pair']];tick=exact(rule.get('price_increment',rule['quote_increment']))
                offset=setting['entry_bps']/10000
                price=rounded(book[0]*(1-offset) if view['side']=='BUY' else book[1]*(1+offset),
                    tick,up=view['side']=='SELL')
                current=receipt(planning,view['pair'],view['side'],budget,price,fee)
                row.update(limit_price=price,market_limit_price=price,source_budget=budget,plan=current,fee_fraction=fee,kind='ROTATION')
                if kickoff and key==config.kickoff:
                    row.update(state='CANDIDATE',reason='EXPLICIT_ONCE_ONLY_KICKOFF',priority=10,kind='KICKOFF');continue
                if view['target']=='ETH':
                    allocated=costs[view['source']]*budget/state['wallet'][view['source']]
                    required=allocated*(1+setting['target_pct']/100)
                    if config.policy==SHORT_POLICY:
                        qualified=current['output_quantity']>=required
                        row.update(state='CANDIDATE' if qualified else 'HOLD',
                            reason='FRESH_MAKER_ETH_TARGET' if qualified else 'HOLD_MARKET_BELOW_NET_ETH_TARGET',
                            kind='RETURN_ETH',priority=3 if qualified else 0,required_eth=required,
                            score=current['output_quantity']/allocated-1)
                        continue
                    target=patient_return_price(planning,view,budget,required,fee)
                    limit=min(price,target) if view['side']=='BUY' else max(price,target)
                    proposed=receipt(planning,view['pair'],view['side'],budget,limit,fee)
                    if proposed['output_quantity']<required:raise ValueError('TARGET_NOT_MET_AFTER_NATIVE_ROUNDING')
                    row.update(state='CANDIDATE',reason='PATIENT_ETH_TARGET_NOT_FORECAST',kind='RETURN_ETH',
                        priority=3 if current['output_quantity']>=required else 1,limit_price=limit,
                        plan=proposed,required_eth=required,score=current['output_quantity']/allocated-1)
                    continue
                # A bounded one-step choice, with a same-frame conditional ETH
                # numeraire comparison. No future prices or executable-edge claim.
                source_wallet={view['source']:budget}
                hold_value=eth_mark(source_wallet,frame)
                target_wallet={view['target']:current['output_quantity']}
                marked=eth_mark(target_wallet,frame)
                # Charge a modeled maker ETH exit with the SAME canonical receipt.
                exit_view=next(v for v in DIRECTIONS if v['source']==view['target'] and v['target']=='ETH')
                exit_book=frame.book(exit_view['pair'])
                if abs(exit_book[2]-book[2])>12:raise ValueError('QUOTE_DECISION_SPAN_EXCEEDS_12S')
                exit_price=exit_book[0] if exit_view['side']=='BUY' else exit_book[1]
                exit_plan=receipt(planning,exit_view['pair'],exit_view['side'],current['output_quantity'],exit_price,fee)
                conditional=exit_plan['output_quantity']
                gain=conditional/hold_value-1
                row.update(score=gain,conditional_eth_subtotal=conditional,marked_eth=marked,
                    state='CANDIDATE' if gain>=setting['target_pct']/100 else 'HOLD',
                    reason='CONDITIONAL_ONE_STEP_THRESHOLD' if gain>=setting['target_pct']/100 else 'NO_AFTER_COST_THRESHOLD',priority=2)
            except (ValueError,KeyError,TypeError,ArithmeticError,StopIteration) as error:
                # Input reasons are reclassified; no private exception strings.
                reason=str(error)
                known={'USER_DISABLED','NOT_IN_AUTHENTICATED_CATALOG','EXCLUDED',
                    'UNFUNDED_AWAIT_CONFIRMED_TERMINAL_RECEIPT','PAPER_RECONCILIATION_REQUIRED',
                    'PAPER_NATIVE_CAP_UNAVAILABLE','QUOTE_NOT_RETURNED','QUOTE_STALE','QUOTE_WIDE',
                    'QUOTE_FUTURE','QUOTE_INVALID','QUOTE_PRICE_INCREMENT_INVALID',
                    'QUOTE_DECISION_SPAN_EXCEEDS_12S','TARGET_PRICE_BELOW_TICK','TARGET_NOT_MET_AFTER_NATIVE_ROUNDING',
                    'ACCOUNT_TRADABILITY_UNVERIFIED','PRODUCT_ID_TYPE_OR_STATUS_UNVERIFIED','PRODUCT_RESTRICTED','PRODUCT_RULES_UNVERIFIED'}
                row.update(state='BLOCKED',reason=reason if reason in known else 'BLOCKED_MINIMUM_OR_NATIVE_RULE')
    return rows


def select_candidate(rows,*,kickoff=None):
    if kickoff is not None:
        row=rows[kickoff];return row if row['state']=='CANDIDATE' else None
    qualified=[r for r in rows.values() if r['state']=='CANDIDATE']
    return max(qualified,key=lambda r:(r['priority'],r['score'],r['id'])) if qualified else None


def random_fraction(seed,reference,step,label):
    raw=hashlib.sha256(f'{seed}:{reference}:{step}:{label}'.encode()).digest()
    return D(int.from_bytes(raw[:8],'big'))/D(2**64)
