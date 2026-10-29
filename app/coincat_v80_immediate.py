"""Strict immediate research contracts. No network, credentials or order API.

Connected qualification is deliberately unavailable in Milestone A. The only
complete evidence accepted here is explicitly synthetic, enabled only by an
offline harness. Real positive estimates remain visible, never invented fills.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import math

from coincat_cross_quote import split_spot, usd_conversion
from coincat_multicurrency import research_order, ResearchDepthError
from coincat_v701_quotes import valid_book
from coincat_v90_telemetry import direction

D = Decimal
RELEASE_LIMIT = ('Immediate discrepancy discovery, modeled positive-opportunity reporting and strict evidence gating. '
    'Live-observation strict qualification is unavailable until candidate-sized depth and candidate-specific '
    'fee/preview evidence integrations are completed and verified.')


def exact(value):
    if isinstance(value,(float,bool)):raise ValueError('Exact decimal required')
    n=D(str(value))
    if not n.is_finite():raise ValueError('Nonfinite financial input')
    return n


def _prepare(quotes,rules,now):
    from coincat_v703_chain import approved_pairs
    listed=set(approved_pairs(list(quotes),rules))
    return {'books':{p:b for p,raw in quotes.items() if p in listed and
        (b:=valid_book(raw,now,30,D('.0025'))) is not None},'fx':{},'at':float(now)}


def _frame(idea, quotes, rules, now, depth=None,prepared=None):
    """Reprice through the SAME canonical native order-receipt implementation."""
    steps=idea.get('shadow_fifo_steps') or ()
    if len(steps)!=1 or idea.get('sends_live_orders') is not False:raise ValueError('NOT_SINGLE_RESEARCH_ORDER')
    original=steps[0];pair=original['pair'];base,quote=split_spot(pair)
    side=original['side'];src=quote if side=='BUY' else base
    dst=base if side=='BUY' else quote
    if side not in ('BUY','SELL') or (src,dst)!=(idea.get('source'),idea.get('target')):
        raise ValueError('RECEIPT_CURRENCY_CONFLICT')
    prepared=_prepare(quotes,rules,now) if prepared is None else prepared
    if prepared['at']!=float(now):raise ValueError('STALE_DECISION_CONTEXT')
    clean=prepared['books']
    if pair not in clean:raise ValueError('CONVERSION_BOOK_MISSING_STALE_OR_WIDE')
    forbidden=() if 'USD' in (base,quote) else (pair,)
    fx_cache=prepared['fx']
    def fx(asset):
        key=(asset,pair)
        if key not in fx_cache:
            fx_cache[key]=usd_conversion(asset,clean,now=now,max_age=30,max_legs=2,excluded_pairs=(pair,))
            if fx_cache[key] is None and not forbidden:
                fx_cache[key]=usd_conversion(asset,clean,now=now,max_age=30,max_legs=2)
        if fx_cache[key] is None:raise ValueError('INDEPENDENT_USD_PATH_MISSING')
        return fx_cache[key]
    source_fx=fx(src);target_fx=fx(dst)
    dependency=set((pair,)+source_fx['path']+target_fx['path'])
    stamps=[clean[p][2] for p in dependency]
    if max(stamps)-min(stamps)>12:raise ValueError('PRICE_SKEW')
    fee=exact(original['fee_rate_used'])
    available=exact(idea.get('source_units',idea.get('input_units_planned')))
    cap=exact(idea.get('research_size_cap_usd',original['approx_usd_notional']))
    allocated=min(available,cap/source_fx['rate'])
    orders=[];retained=[]
    def order(product,direction,quantity,rate):
        if product not in clean:raise ValueError('PATH_BOOK_MISSING')
        level=None
        if depth is not None:
            row=depth.get(product)
            if row is None:raise ResearchDepthError('DEPTH_MISSING')
            if row.get('pair')!=product or float(row.get('observed_at',-1))!=clean[product][2]:
                raise ResearchDepthError('DEPTH_FRAME_CONFLICT')
            level=row.get('asks' if direction=='BUY' else 'bids')
        r=research_order(pair=product,side=direction,available=quantity,
            cap=quantity*rate,usd_rate=rate,book=clean[product],
            product_rules=rules,fee=fee,levels=level)
        orders.append(dict(r,observed_at=clean[product][2]))
        return r
    entry=order(pair,side,allocated,source_fx['rate'])
    entry['output_usd_mark']=entry['output_quantity']*target_fx['rate']
    def liquidation(asset,quantity):
        if quantity==0:return D(0)
        if asset=='USD':return quantity
        result=D(0)
        for product in fx(asset)['path']:
            a,b=split_spot(product)
            direction='SELL' if asset==a else 'BUY'
            next_asset=b if direction=='SELL' else a
            rate=fx(asset)['rate']
            try:r=order(product,direction,quantity,rate)
            except ResearchDepthError:raise
            except ValueError as exc:
                if 'minimum/maximum' not in str(exc):raise
                # Exact unconverted dust is retained, not silently made cash or
                # zero. The comparison explicitly includes its conservative mark.
                retained.append({'asset':asset,'quantity':quantity,'usd_mark':quantity*rate})
                return result+quantity*rate
            remainder=quantity-r['input_quantity']
            if remainder:
                retained.append({'asset':asset,'quantity':remainder,'usd_mark':remainder*rate})
                result+=remainder*rate
            quantity=r['output_quantity'];asset=next_asset
        if asset!='USD':raise ValueError('USD_PATH_INCOMPLETE')
        return result+quantity
    w=entry['output_usd_mark']-entry['approx_usd_notional']
    before=liquidation(src,allocated)
    residual=allocated-entry['input_quantity']
    after=liquidation(dst,entry['output_quantity'])+liquidation(src,residual)
    l=after-before
    identity=repr((pair,side,tuple(sorted((p,tuple(map(str,clean[p]))) for p in dependency)),
        tuple(sorted((p,tuple(sorted((k,str(v)) for k,v in rules[p].items()))) for p in dependency)),
        str(allocated),str(cap),str(fee))).encode()
    changed=dict(idea,shadow_fifo_steps=[entry],input_units_planned=entry['input_quantity'],
        destination_units_estimate=entry['output_quantity'],immediate_change_usd=w,
        snowball_state='IMMEDIATE_ESTIMATE',snowball_immediate_usd=str(l),
        selection_asof=now,sends_live_orders=False)
    ratio=target_fx['rate']/source_fx['rate']
    cross=(1-clean[pair][1]/ratio)*100 if side=='BUY' else (clean[pair][0]*target_fx['rate']/source_fx['rate']-1)*100
    return {'id':hashlib.sha256(identity).hexdigest(),'at':float(now),'pair':pair,'side':side,
        'w':w,'l':l,'before_liquidation_usd':before,'after_liquidation_usd':after,
        'source_rate':source_fx['rate'],'target_rate':target_fx['rate'],
        'source_path':source_fx['path'],'target_path':target_fx['path'],
        'book_span_s':max(stamps)-min(stamps),'oldest_book_age_s':now-min(stamps),
        'dependencies':tuple(sorted(dependency)),'orders':orders,'retained_residuals':retained,
        'cross_market_discrepancy_pct':cross,'fee_currency_assumption':quote,
        'entry_fee_usd_estimate':entry['fee_amount_estimate']*fx(quote)['rate'],
        'usd_mark_source':'PUBLIC_REST_CONSERVATIVE_BID_OR_INVERSE_ASK',
        'exchange_time_verified':False,'liquidation_model':'USD_CASH_PLUS_RETAINED_NATIVE_RESIDUAL_MARKS',
        'idea':changed,'books':{p:clean[p] for p in dependency},
        'rules':{p:deepcopy(rules[p]) for p in dependency if p in rules}}


def evaluate(idea, quotes, rules, *, now, synthetic_evidence=None, allow_synthetic=False,_prepared=None):
    result={'state':'NOT_PRICED','w':None,'l':None,'score_usd':None,'strict':False,
            'positive_estimate':False,'blockers':[],'frame':None,'live_order_permission':False}
    try:
        if not math.isfinite(float(now)):raise ValueError('INVALID_FRAME_TIME')
        with localcontext() as ctx:
            ctx.prec=60
            frame=_frame(idea,quotes,rules,float(now),prepared=_prepared)
        result.update(w=frame['w'],l=frame['l'],frame=frame)
        if min(frame['w'],frame['l'])<=0:
            return dict(result,state='ECONOMIC_ZERO' if min(frame['w'],frame['l'])==0 else 'ECONOMIC_NEGATIVE',
                        blockers=[n for n,v in (('W_NONPOSITIVE',frame['w']),('L_NONPOSITIVE',frame['l'])) if v<=0])
        result.update(state='MODELED_POSITIVE_UNVERIFIED',positive_estimate=True,
                      score_usd=min(frame['w'],frame['l']))
        blockers=['DEPTH_MISSING','FEE_AMOUNT_UNVERIFIED','FEE_CURRENCY_UNVERIFIED','PREVIEW_UNAVAILABLE',
                  'EXCHANGE_TIME_UNVERIFIED','CONNECTED_EVIDENCE_NOT_INTEGRATED']
        proof=synthetic_evidence
        if not (allow_synthetic and isinstance(proof,dict) and proof.get('origin')=='SYNTHETIC_OFFLINE'):
            return dict(result,blockers=blockers)
        if proof.get('frame_id')!=frame['id'] or not 0<=now-float(proof.get('at',-1))<=30:
            return dict(result,blockers=['EVIDENCE_FRAME_CONFLICT'])
        with localcontext() as ctx:
            ctx.prec=60
            priced=_frame(idea,quotes,rules,float(now),depth=proof.get('books',{}),prepared=_prepared)
        if min(priced['w'],priced['l'])<=0:
            return dict(result,state='ECONOMIC_NEGATIVE',positive_estimate=False,frame=priced,
                        w=priced['w'],l=priced['l'],score_usd=None,blockers=['DEPTH_COSTS_ERASE_ADVANTAGE'])
        previews=proof.get('previews',())
        for order in priced['orders']:
            matches=[p for p in previews if p.get('pair')==order['pair'] and p.get('side')==order['side']
                and exact(p.get('base_quantity',-1))==order['gross_base_quantity']]
            if not matches:return dict(result,blockers=['SIZE_MATCHED_PREVIEW_UNAVAILABLE'])
            p=matches[0]
            if p.get('fee_currency')!=order['assumed_fee_currency_for_research']:
                return dict(result,blockers=['FEE_CURRENCY_UNVERIFIED'])
            if (exact(p.get('fee_amount',-1))!=order['fee_amount_estimate'] or
                not 0<=now-float(p.get('at',-1))<=30 or p.get('origin')!='SYNTHETIC_OFFLINE'):
                return dict(result,blockers=['FEE_AMOUNT_OR_PROVENANCE_CONFLICT'])
        return dict(result,state='STRICT_QUALIFIED_MODEL',strict=True,frame=priced,w=priced['w'],l=priced['l'],
                    score_usd=min(priced['w'],priced['l']),blockers=[],evidence_origin='SYNTHETIC_OFFLINE')
    except ResearchDepthError as exc:
        return dict(result,blockers=[str(exc)])
    except (KeyError,TypeError,ValueError,InvalidOperation,OverflowError) as exc:
        reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isalnum() else 'INVALID_OR_MISSING_FRAME_INPUT'
        return dict(result,blockers=[reason])


def rank(ideas,quotes,rules,*,now,limit=12,evaluations=None):
    annotated=[];counts=Counter();unique={};blockers=Counter()
    prepared=_prepare(quotes,rules,now)
    direction_rows={}
    precedence={'NOT_PRICED':0,'ECONOMIC_NEGATIVE':1,'ECONOMIC_ZERO':2,'MODELED_POSITIVE_UNVERIFIED':3}
    for idea in ideas:
        r=evaluate(idea,quotes,rules,now=now,_prepared=prepared);frame=r['frame']
        counts['size_trials']+=1;counts[r['state']]+=1;blockers.update(r['blockers'])
        key=(idea.get('source'),idea.get('target'),str(idea.get('route')))
        previous=unique.get(key)
        # Route outcomes are exclusive: any positive, else zero, else negative,
        # else unpriced. Size outcomes remain separately visible below.
        if previous is None or precedence[r['state']]>precedence[previous['state']]:unique[key]=r
        route_direction=direction(idea)
        if route_direction is not None:
            row=direction_rows.setdefault(route_direction,{'direction':route_direction,
                'evaluated_at':float(now),'size_trials':0,'priced_sizes':0,
                'state':'NOT_PRICED','blockers':set()})
            row['size_trials']+=1;row['priced_sizes']+=int(frame is not None)
            if precedence[r['state']]>precedence[row['state']]:row['state']=r['state']
            row['blockers'].update(r['blockers'])
        out=dict(frame['idea'] if frame else idea)
        out.update(immediate_assessment=r,model_product_rules=frame['rules'] if frame else rules,
                   selection_state=r['state'],selection_reason=','.join(r['blockers']) or r['state'],
                   selection_basis='STRICT_IMMEDIATE',selection_score_usd=r['score_usd'])
        annotated.append(out)
    annotated.sort(key=lambda i:(not i['immediate_assessment']['positive_estimate'],
        -(i['immediate_assessment']['score_usd'] or D('-1e99')),str(i.get('source')),str(i.get('target'))))
    if evaluations is not None:
        evaluations.extend(dict(row,blockers=sorted(row['blockers'])) for row in direction_rows.values())
    summary={'size_trials':counts['size_trials'],'distinct_routes':len(unique),
        'priced_sizes':counts['size_trials']-counts['NOT_PRICED'],
        'unpriced_sizes':counts['NOT_PRICED'],'size_state_counts':{k:v for k,v in counts.items() if k!='size_trials'},
        'priced_routes':sum(r['frame'] is not None for r in unique.values()),
        'route_outcomes_exclusive':True,
        'positive_unverified_routes':sum(r['positive_estimate'] for r in unique.values()),
        'negative_routes':sum(r['state']=='ECONOMIC_NEGATIVE' for r in unique.values()),
        'zero_routes':sum(r['state']=='ECONOMIC_ZERO' for r in unique.values()),
        'unpriced_routes':sum(r['state']=='NOT_PRICED' for r in unique.values()),
        'strict_qualified':0,'ram_conversions':0,'blocker_size_counts':dict(blockers),
        'counts_overlap':True,'connected_strict_qualification_available':False}
    # Preserve distinct positive directions before additional size variants.
    first=[];extra=[];seen=set()
    for item in annotated:
        key=(item.get('source'),item.get('target'),str(item.get('route')))
        if key in seen:extra.append(item)
        else:first.append(item);seen.add(key)
    return (first+extra)[:limit],summary


def economics_text(idea):
    r=idea.get('immediate_assessment') or {};f=r.get('frame') or {}
    return (f"{idea.get('source')} → {idea.get('target')} | {r.get('state','NOT_EVALUATED')} | "
        f"wallet USD {r.get('w')} | comparable liquidation USD {r.get('l')} | "
        f"discrepancy {f.get('cross_market_discrepancy_pct')}% (side-specific ratio basis) | "
        f"modeled fee USD {f.get('entry_fee_usd_estimate')} | input {idea.get('input_units_planned')} | "
        f"oldest book {f.get('oldest_book_age_s')}s / span {f.get('book_span_s')}s | "
        f"unverified: {', '.join(r.get('blockers',())) or 'SYNTHETIC MODEL ONLY'}")


class ObservationLog:
    """Bounded RAM counterfactuals, including positive UNVERIFIED proposals.

    No wallet spending or public-table storage of user-derived quantities.
    Later actual observations cannot retrospectively qualify an earlier frame.
    """
    def __init__(self):
        self.entries={};self.counts=Counter()

    def observe(self,ideas,quotes,*,now):
        for key,row in list(self.entries.items()):
            frame=row['frame'];pair=frame['pair'];step=frame['idea']['shadow_fifo_steps'][0]
            src=frame['idea']['source'];dst=frame['idea']['target']
            forbidden=() if 'USD' in (src,dst) else (pair,)
            for horizon in (300,900,3600):
                if horizon in row['done'] or now-frame['at']<horizon:continue
                if now-frame['at']>horizon+120:
                    self.counts[str(horizon)+'_MISSED_DEADLINE']+=1;row['done'].add(horizon);continue
                a=usd_conversion(src,quotes,now=now,max_age=30,excluded_pairs=forbidden)
                b=usd_conversion(dst,quotes,now=now,max_age=30,excluded_pairs=forbidden)
                if a is None or b is None:
                    self.counts['WAIT_ENDPOINT_USD_PATH']+=1;continue
                stamps=[quotes[p][2] for p in a['path']+b['path']]
                if stamps and max(stamps)-min(stamps)>12:
                    self.counts['WAIT_ENDPOINT_SKEW']+=1;continue
                delta=step['output_quantity']*b['rate']-step['input_quantity']*a['rate']
                self.counts[str(horizon)+('_POSITIVE' if delta>0 else '_NONPOSITIVE')]+=1
                row['done'].add(horizon)
            if len(row['done'])==3:del self.entries[key]
        # One best size per route in an observation. Duplicate frame IDs do not
        # manufacture a new independent event or a conversion.
        seen=set()
        for idea in ideas:
            r=idea.get('immediate_assessment') or {};frame=r.get('frame')
            if not r.get('positive_estimate') or not frame:continue
            route=(frame['pair'],frame['side'])
            if route in seen or frame['id'] in self.entries:continue
            seen.add(route)
            if len(self.entries)>=512:
                self.counts['CAPACITY_DEFERRED']+=1;continue
            self.entries[frame['id']]={'frame':frame,'done':set()}
            self.counts['RECORDED_POSITIVE_UNVERIFIED']+=1
        return self.summary()

    def summary(self):
        return {'pending_candidates':len(self.entries),'outcomes':dict(self.counts),
                'counterfactual_only':True,'independent_samples':False,'wallet_spending':False}


def diagnostic_report(app):
    """Aggregate export; candidate quantities/economics remain in local UI."""
    import time
    from coincat_v90_telemetry import utc
    now=time.time()
    last=getattr(app,'_fast_last_result',{}) or {}
    model=getattr(app,'experimental_shadow',None)
    consumer=getattr(model,'immediate_funnel',{})
    discovery_cycle=last.get('research_cycle') or {}
    consumer_cycle=consumer.get('cycle') or {}
    link=('UNLINKED' if not discovery_cycle.get('id') or not consumer_cycle.get('id') else
          'SAME_CYCLE_REEVALUATED_AT_CONSUMER' if discovery_cycle['id']==consumer_cycle['id'] else 'DIFFERENT_CYCLES')
    tracker=getattr(app,'_direction_coverage',None)
    coverage=tracker.summary(now=now) if tracker is not None else {'state':'NOT_OBSERVED'}
    reconciliation=model.reconciliation() if hasattr(model,'reconciliation') else {'state':'NOT_OBSERVED'}
    return '\n'.join(('STRICT IMMEDIATE SNOWBALL • V90',RELEASE_LIMIT,
        'Diagnostic snapshot UTC: '+utc(now),
        'Experimental consumer: '+('ARMED' if getattr(model,'armed',False) else 'DISARMED; retained session results'),
        'Consumer session start / stop: '+str((getattr(model,'started_at',None),getattr(model,'stop_at',None))),
        'Discovery cycle: '+str(discovery_cycle),
        'Consumer cycle relation: '+link,
        'Discovery runs independently of ARM; compare cycle IDs and observation times before comparing economics.',
        'Direction coverage (app urgent research, not the armed-session counter): '+str(coverage),
        'Complete means a modeled W/L pricing frame; depth, fee units and execution remain unverified.',
        'Route outcomes apply only to costed routes; selected_without_costed_receipt is a separate direction count.',
        'Session candidate reconciliation (repeated sizes): '+str(reconciliation),
        'Latest discovery / pricing funnel: '+str(last.get('immediate_funnel',{'state':'NOT_OBSERVED'})),
        'Latest strict consumer funnel: '+str(getattr(model,'immediate_funnel',{})),
        'Consumer state counts (repeated size reviews): '+str(dict(getattr(model,'immediate_counts',{}))),
        'Consumer blockers (may overlap): '+str(dict(getattr(model,'immediate_blockers',{}))),
        'Positive-unverified counterfactual research: '+str(last.get('immediate_outcomes',{'state':'NOT_OBSERVED'})),
        'Missing evidence is not an economic loss. Positive estimates are retained. No connected strict qualification.'))
