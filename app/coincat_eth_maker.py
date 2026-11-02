"""Bounded ETH-only research. No client, broker, wallet posts or order methods."""
from collections import Counter, deque
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal as D, localcontext, ROUND_CEILING, ROUND_FLOOR
import math

from coincat_multicurrency import _rule, research_order
from coincat_v6010_registry import STABLE_AND_FIAT, REJECT_FLAGS
from coincat_v701_quotes import valid_book
from coincat_v80_immediate import exact
from coincat_working_allocation import public_asset
from coincat_continuity import identity_change, quote_reason


@dataclass(frozen=True)
class MakerConfig:
    companions: tuple = ()
    amount_eth: D = D(0)
    entry_offset_bps: D = D(0)
    target_pct: D = D('.25')
    expiry_hours: D = D(24)
    scan_interval_s: D = D(5)
    taker_slippage_bps: D = D(15)

    def validate(self):
        if (not isinstance(self.companions, tuple) or len(self.companions)>3 or
                len(set(self.companions))!=len(self.companions)):
            raise ValueError('AT_MOST_THREE_EXPLICIT_COMPANIONS')
        for asset in self.companions:
            if public_asset(asset)!=asset or asset=='ETH' or asset in STABLE_AND_FIAT:
                raise ValueError('CRYPTO_COMPANIONS_ONLY')
        for name,low,high in (('amount_eth',D(0),D('1000000')),
                ('entry_offset_bps',D(0),D(50)),('target_pct',D(0),D(5)),
                ('expiry_hours',D(1),D(72)),('scan_interval_s',D(5),D(60)),
                ('taker_slippage_bps',D(0),D(50))):
            if not low<=exact(getattr(self,name))<=high:
                raise ValueError('INVALID_RESEARCH_CONTROL')
        return self


def select_markets(catalog, rules, companions, excluded=()):
    """Use actual authenticated direct products, with explicit account eligibility.

    A filtered catalog cannot explain regional absence. No listing, permission or
    liquidity is inferred from BTC/SOL/ADA examples or missing flag values.
    """
    MakerConfig(tuple(companions)).validate()
    selected=[];rejects={};excluded=set(excluded)
    for asset in companions:
        choices=[];reasons=[]
        if asset in excluded or 'ETH' in excluded:
            rejects[asset]=['EXCLUDED'];continue
        for pair in sorted(set(catalog)&{asset+'-ETH','ETH-'+asset}):
            p=rules.get(pair,{})
            if (p.get('product_id')!=pair or str(p.get('product_type','')).upper()!='SPOT'
                    or str(p.get('status','')).lower()!='online'):
                reasons.append('PRODUCT_ID_TYPE_OR_STATUS_UNVERIFIED');continue
            if p.get('view_only') is not False:
                reasons.append('ACCOUNT_TRADABILITY_UNVERIFIED');continue
            if any(p.get(flag) is True for flag in REJECT_FLAGS):
                reasons.append('PRODUCT_RESTRICTED');continue
            try:
                if _rule(rules,pair) is None:raise ValueError()
                tick=exact(p.get('price_increment',p.get('quote_increment')))
                if tick<=0 or exact(p['quote_increment'])<=0:raise ValueError()
                base,quote=pair.split('-')
                if p.get('base_currency_id',base)!=base or p.get('quote_currency_id',quote)!=quote:
                    raise ValueError()
            except (ValueError,TypeError,KeyError,ArithmeticError):
                reasons.append('PRODUCT_RULES_UNVERIFIED');continue
            choices.append(dict(pair=pair,asset=asset,entry_side='BUY' if quote=='ETH' else 'SELL',
                                exit_side='SELL' if quote=='ETH' else 'BUY',tick=tick))
        if choices:
            # Prefer the actual ETH-quoted orientation; never invent an inverse ID.
            selected.append(next((r for r in choices if r['entry_side']=='BUY'),choices[0]))
        else:rejects[asset]=sorted(set(reasons)) or ['NO_ELIGIBLE_DIRECT_ETH_PRODUCT']
    return dict(selected=selected,rejects=rejects,requested=len(companions),
                state='RESEARCH_ONLY' if selected else 'NO_QUALIFIED_EVIDENCE')


def available_companions(catalog,rules,excluded=()):
    assets=set()
    for pair in catalog:
        parts=pair.split('-')
        if len(parts)==2 and 'ETH' in parts:
            asset=parts[0] if parts[1]=='ETH' else parts[1]
            if asset!='ETH' and public_asset(asset)==asset and asset not in STABLE_AND_FIAT:
                assets.add(asset)
    return [a for a in sorted(assets) if select_markets(catalog,rules,(a,),excluded)['selected']]


def _round(n,tick,up=False):
    return (n/tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*tick


def _receipt(market,side,amount,price,fee,rules,slip=D(0)):
    """The existing receipt owns quantities, fees and size rules, including dust.

    Native cap/rate=amount/1 cancels the library's USD cap algebraically; it is
    not a USD price. The misleading approximate-USD field is removed.
    """
    receipt=research_order(pair=market['pair'],side=side,available=amount,cap=amount,
        usd_rate=D(1),book=(price,price,0),product_rules=rules,fee=fee,slip=slip)
    receipt.pop('approx_usd_notional',None)
    return receipt


def post_only_eligible(side,price,book,tick):
    price=exact(price)
    return (side in ('BUY','SELL') and price>0 and price%tick==0 and
            (price<book[1] if side=='BUY' else price>book[0]))


def round_trip(market,amount,entry_price,exit_price,entry_fee,exit_fee,rules,slip=D(0)):
    with localcontext() as ctx:
        ctx.prec=60
        first=_receipt(market,market['entry_side'],amount,entry_price,entry_fee,rules,slip)
        remaining=amount-first['input_quantity']
        second=_receipt(market,market['exit_side'],first['output_quantity'],exit_price,exit_fee,rules,slip)
        dust=first['output_quantity']-second['input_quantity']
        final=remaining+second['output_quantity']
        return dict(initial_eth=amount,retained_eth=remaining,final_eth_subtotal=final,
            net_eth_subtotal=final-amount,net_pct_subtotal=(final/amount-1)*100,
            complete_net_eth=final-amount if dust==0 else None,
            native_dust={market['asset']:dust} if dust else {},receipts=(first,second),
            fee_currency='UNVERIFIED_QUOTE_DEBIT_SCENARIO',actual_profit_eth=None)


def model_market(market,config,rules,raw_quote,tier,now):
    """One quote decision. Future limit exit is an explicit target, not a price forecast."""
    config.validate()
    out=dict(market=deepcopy(market),state='UNPRICED',blockers=[],at=float(now),
        benchmark=None,hypothesis=None,fill_state='UNVERIFIED',actual_profit_eth=None,
        execution_eligible=False)
    quote=valid_book(raw_quote,now,30,D('.0025'))
    try:
        stamp=float(raw_quote[2])
        out['quote_observed_at']=stamp if math.isfinite(stamp) else None
    except (TypeError,ValueError,IndexError,OverflowError):out['quote_observed_at']=None
    if quote is None:
        out['blockers']=[quote_reason(raw_quote,now)];return out
    bid,ask,stamp=quote
    out.update(book=quote,quote_age_s=now-stamp,spread_pct=(ask-bid)/ask*100,
        eth_per_coin=(bid+ask)/2 if market['entry_side']=='BUY' else (1/ask+1/bid)/2)
    try:
        if config.amount_eth<=0:raise ValueError('NO_EXPLICIT_ETH_PROPOSAL')
        if not tier.get('fresh'):raise ValueError('ACCOUNT_FEE_TIER_UNAVAILABLE')
        maker,taker=exact(tier.get('maker')),exact(tier.get('taker'))
        if not 0<=maker<D('.05') or not 0<=taker<D('.05'):
            raise ValueError('FEE_RATE_UNSUPPORTED_NO_REBATE_ASSUMPTION')
        with localcontext() as ctx:
            ctx.prec=60
            entry_side=market['entry_side'];tick=market['tick']
            taker_entry=ask if entry_side=='BUY' else bid
            taker_exit=bid if entry_side=='BUY' else ask
            try:
                out['benchmark']=round_trip(market,config.amount_eth,taker_entry,taker_exit,
                    taker,taker,rules,config.taker_slippage_bps/10000)
            except ValueError:out['blockers'].append('TAKER_PRODUCT_SIZE_BLOCK')
            offset=config.entry_offset_bps/10000
            entry_price=_round(bid*(1-offset) if entry_side=='BUY' else ask*(1+offset),
                               tick,up=entry_side=='SELL')
            if not post_only_eligible(entry_side,entry_price,quote,tick):
                raise ValueError('POST_ONLY_ENTRY_WOULD_CROSS')
            try:first=_receipt(market,entry_side,config.amount_eth,entry_price,maker,rules)
            except ValueError:raise ValueError('MAKER_ENTRY_PRODUCT_SIZE_BLOCK') from None
            retained=config.amount_eth-first['input_quantity']
            required=config.amount_eth*(1+config.target_pct/100)-retained
            p=rules[market['pair']]
            if entry_side=='BUY':
                units=_round(first['output_quantity'],exact(p['base_increment']))
                exit_price=_round(required/(units*(1-maker)),tick,up=True)
            else:
                units=_round(required,exact(p['base_increment']),up=True)
                budget=_round(first['output_quantity'],exact(p['quote_increment']))
                exit_price=_round(budget/(units*(1+maker)),tick)
            if exit_price<=0:raise ValueError('TARGET_PRICE_BELOW_TICK')
            try:scenario=round_trip(market,config.amount_eth,entry_price,exit_price,maker,maker,rules)
            except ValueError:raise ValueError('MAKER_EXIT_PRODUCT_SIZE_BLOCK') from None
            # The exact, increment-rounded two-leg scenario must meet the requested target.
            if scenario['final_eth_subtotal']<config.amount_eth*(1+config.target_pct/100):
                raise ValueError('TARGET_NOT_MET_AFTER_NATIVE_ROUNDING')
            move=(exit_price/entry_price-1 if entry_side=='BUY' else entry_price/exit_price-1)*100
            out['hypothesis']=dict(entry_price=entry_price,exit_price=exit_price,
                entry_at=stamp,exit_at=None,required_move_pct=move,target_pct=config.target_pct,
                expiry_at=now+float(config.expiry_hours)*3600,maker_rate=maker,taker_rate=taker,
                scenario=scenario,worst_case_eth_exposure=first['input_quantity'],
                worst_case='ENTIRE_COIN_EXPOSURE_CAN_BE_LOST; WAITING_CAN_EXCEED_TEST_HORIZON',
                fee_evidence=deepcopy(tier),
                limits=('ACCOUNT_TIER_ONLY_PAIR_EXCEPTIONS_UNVERIFIED','FEE_CURRENCY_UNVERIFIED',
                        'NO_QUEUE_VOLUME_OR_FILL_EVIDENCE','EXIT_PRICE_IS_TARGET_NOT_FORECAST'),
                scenario_bounds=dict(no_fill_eth=config.amount_eth,
                    worst_case_retained_eth=retained,full_fill_scenario_eth=scenario['final_eth_subtotal'],
                    partial_completion_eth=None),
                fill_state='UNVERIFIED',entry_touched_at=None,target_touched_at=None,
                observations=1,waiting_s=0,adverse_move_pct=D(0))
            out['state']='RESEARCH_ONLY'
    except (ValueError,TypeError,ArithmeticError) as exc:
        reason=str(exc)
        out['blockers'].append(reason if reason.isupper() and reason.replace('_','').isalnum()
                               else 'INVALID_OR_UNSUPPORTED_MODEL_INPUT')
    return out


def evaluate_completion(*,market,amount,entry_price,exit_price,entry_quote,exit_quote,
                        entry_at,exit_at,entry_fee,exit_fee,rules,fill_state='UNVERIFIED'):
    """Explicit offline scenario helper; never evidence of an actual fill.

    Each decision checks its own 30s quote quality; the two times intentionally
    need not be within 12s. Fractional fills require separate exact quantities;
    they cannot be upgraded to a full-fill return here.
    """
    statuses={'NO_FILL','PARTIAL_OR_UNCERTAIN_FILL','HYPOTHETICAL_FULL_FILL',
              'UNPRICED','CANCELLED_OR_EXPIRED','UNVERIFIED'}
    if fill_state not in statuses:raise ValueError('INVALID_FILL_CLASSIFICATION')
    out=dict(fill_state=fill_state,scenario=None,actual_profit_eth=None,
             entry_at=entry_at,exit_at=exit_at,execution_eligible=False)
    if not math.isfinite(float(entry_at)) or not math.isfinite(float(exit_at)) or exit_at<entry_at:
        return dict(out,fill_state='UNPRICED',reason='INVALID_DECISION_TIMES')
    books=[valid_book(q,t,30,D('.0025')) for q,t in ((entry_quote,entry_at),(exit_quote,exit_at))]
    if any(b is None for b in books):return dict(out,fill_state='UNPRICED',reason='INVALID_DECISION_QUOTE')
    if not all(post_only_eligible(s,p,b,market['tick']) for s,p,b in zip(
            (market['entry_side'],market['exit_side']),(entry_price,exit_price),books)):
        return dict(out,fill_state='UNPRICED',reason='POST_ONLY_WOULD_CROSS')
    if fill_state=='NO_FILL':return dict(out,remaining_eth=amount,native_dust={})
    if fill_state=='HYPOTHETICAL_FULL_FILL':
        out['scenario']=round_trip(market,amount,entry_price,exit_price,entry_fee,exit_fee,rules)
    return out


class MakerStudy:
    """Frozen per-market hypotheses, bounded episodes and no fills across gaps."""
    def __init__(self):
        self.active={};self.identities={};self.key=None;self.counts=Counter()
        self.invalidations=Counter();self.pause_reasons=Counter()
        self.history=deque(maxlen=128);self.history_dropped=0

    def _event(self,pair,event,reason,now):
        if len(self.history)==self.history.maxlen:self.history_dropped+=1
        self.history.append(dict(pair=pair,event=event,reason=reason,at=now))

    def invalidate(self,pair,reason,now):
        if self.active.pop(pair,None) is not None:
            self.counts['invalidated']+=1;self.invalidations[reason]+=1
            self._event(pair,'SETUP_INVALIDATED',reason,now)
        self.identities.pop(pair,None)

    def _pause(self,pair,hypothesis,reasons,now):
        if not hypothesis.get('_paused'):
            self.counts['unpriced_episodes']+=1;hypothesis['_gap_reasons']=set()
            self._event(pair,'SETUP_ACTIVE_UNPRICED',reasons[0],now)
        hypothesis['_paused']=True
        for reason in reasons:
            if reason not in hypothesis['_gap_reasons']:
                self.pause_reasons[reason]+=1;hypothesis['_gap_reasons'].add(reason)

    def pause_all(self,reason,now):
        for pair,h in self.active.items():self._pause(pair,h,[reason],now)

    def diagnostics(self):
        return dict(reset_reasons=dict(self.invalidations),unpriced_episode_reasons=dict(self.pause_reasons),
                    history=list(self.history),dropped_histories=self.history_dropped,
                    active_hypotheses=len(self.active))

    def statistics(self):
        names=('setups','invalidated','unpriced_episodes','resumed_episodes','fee_changes','expired',
               'entry_touches_uncertain','target_touches_uncertain')
        return {k:self.counts[k] for k in names}

    def observe(self,rows,*,key=None,keys=None,now,fees=None,removed=None):
        self.key=key
        keys=keys if keys is not None else {r['market']['pair']:key for r in rows}
        for pair,reason in (removed or {}).items():self.invalidate(pair,reason,now)
        for row in rows:
            pair=row['market']['pair'];current=row.get('hypothesis');old=self.active.get(pair)
            reason=identity_change(self.identities.get(pair),keys.get(pair))
            if reason:self.invalidate(pair,reason,now);old=None
            if old and now>=old['expiry_at']:
                expired=deepcopy(old);expired['fill_state']='CANCELLED_OR_EXPIRED'
                expired['waiting_s']=now-old['entry_at'];row.update(hypothesis=expired,
                    fill_state='CANCELLED_OR_EXPIRED',observation_state='SETUP_EXPIRED',current_estimate_available=False)
                self.active.pop(pair);self.identities.pop(pair,None)
                self.counts['expired']+=1;self._event(pair,'SETUP_EXPIRED','ORIGINAL_EXPIRY_REACHED',now)
                continue
            rates=(fees.get('maker'),fees.get('taker')) if fees and fees.get('fresh') else (
                   (current['maker_rate'],current['taker_rate']) if current else None)
            if rates is not None and not all(isinstance(r,D) and r.is_finite() for r in rates):rates=None
            if old and rates is not None and (old['maker_rate'],old['taker_rate'])!=rates:
                self.counts['fee_changes']+=1;self.invalidate(pair,'ACCOUNT_FEE_RATE_CHANGED',now);old=None
            if current is None:
                row.update(observation_state='SETUP_ACTIVE_UNPRICED' if old else 'NO_SETUP_UNPRICED',
                           current_estimate_available=False)
                if old:
                    self._pause(pair,old,row['blockers'] or ['MODEL_UNPRICED'],now)
                    old['waiting_s']=max(0,now-old['entry_at']);row['hypothesis']=deepcopy(old)
                    row['fill_state']=old['fill_state']
                continue
            if old is None:
                current=deepcopy(current);current['_paused']=False
                current['last_observable_at']=row['book'][2]
                self.active[pair]=current;self.identities[pair]=deepcopy(keys.get(pair))
                self.counts['setups']+=1;self._event(pair,'SETUP_ACTIVE_OBSERVABLE','CREATED',now)
            else:
                bid,ask,stamp=row['book'];buy=row['market']['entry_side']=='BUY'
                last=old.get('last_observable_at',old['entry_at'])
                if stamp-last>30:self._pause(pair,old,['OBSERVATION_GAP'],now)
                if stamp<last:
                    self._pause(pair,old,['QUOTE_TIME_MOVED_BACKWARDS'],now)
                    row.update(hypothesis=deepcopy(old),observation_state='SETUP_ACTIVE_UNPRICED',
                               current_estimate_available=False,state='UNPRICED',fill_state=old['fill_state'])
                    row['blockers'].append('QUOTE_TIME_MOVED_BACKWARDS');continue
                resumed=old.get('_paused',False)
                if resumed:
                    self.counts['resumed_episodes']+=1;old['_paused']=False
                    self._event(pair,'SETUP_ACTIVE_OBSERVABLE','RESUMED_WITHOUT_GAP_TOUCH_INFERENCE',now)
                if stamp>last:old['observations']+=1
                old['waiting_s']=max(0,now-old['entry_at']);old['last_observable_at']=stamp
                price=bid if buy else ask
                move=(price/old['entry_price']-1 if buy else old['entry_price']/price-1)*100
                old['adverse_move_pct']=min(old['adverse_move_pct'],move)
                if stamp>last and not resumed:
                    if old['entry_touched_at'] is None and (ask<=old['entry_price'] if buy else bid>=old['entry_price']):
                        old['entry_touched_at']=stamp;old['fill_state']='PARTIAL_OR_UNCERTAIN_FILL'
                        self.counts['entry_touches_uncertain']+=1
                    if (old['entry_touched_at'] is not None and stamp>old['entry_touched_at'] and
                            old['target_touched_at'] is None and
                            (bid>=old['exit_price'] if buy else ask<=old['exit_price'])):
                        old['target_touched_at']=stamp;self.counts['target_touches_uncertain']+=1
            row['hypothesis']=deepcopy(self.active[pair]);row['fill_state']=row['hypothesis']['fill_state']
            row.update(observation_state='SETUP_ACTIVE_OBSERVABLE',current_estimate_available=True)
        return rows


def public_summary(result):
    """Allowlisted quantity-free export: never serialize private rows or receipts."""
    return dict(scope='ETH_MAKER_RESEARCH_ONLY',state=result.get('state','UNOBSERVED'),
        rejects=deepcopy(result.get('market_selection',{}).get('rejects',{})),
        selected_products=[r['market']['pair'] for r in result.get('rows',())],
        markets=[dict(pair=r['market']['pair'],state=r['state'],blockers=list(r['blockers']),
            quote_age_s=r.get('quote_age_s'),quote_observed_at=r.get('quote_observed_at'),
            observation_state=r.get('observation_state','UNOBSERVED'),fill_state=r['fill_state'],
            dust_status='NATIVE_REMAINDER' if (r.get('hypothesis') or {}).get('scenario',{}).get('native_dust') else
                        'NONE_IN_SCENARIO' if r.get('hypothesis') else 'UNPRICED',
            entry_at=(r.get('hypothesis') or {}).get('entry_at'),
            original_expiry_at=(r.get('hypothesis') or {}).get('expiry_at'),
            target_touched_at=(r.get('hypothesis') or {}).get('target_touched_at'))
            for r in result.get('rows',())],
        observations=dict(result.get('study_counts',{})),continuity=deepcopy(result.get('study_continuity',{})),
        hypothetical_full_fills=0,
        verified_fills=0,actual_profit='NOT_ESTABLISHED',live_order_permission=False)
