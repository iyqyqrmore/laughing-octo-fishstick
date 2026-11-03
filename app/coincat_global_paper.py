"""Versioned USD-floor PAPER decisions. Pure native receipts; no order client.

USD is a valuation reference only. Exit-depth stress values an exit; it never
authorizes a taker order. A conditional qualification is not a completed profit.
"""
from copy import deepcopy
from dataclasses import dataclass,asdict,replace
from decimal import Decimal as D,localcontext
import hashlib
import json
import math

from coincat_adaptive_eth import Frame,estimate_path
from coincat_paper_policy import reference_costs,realized_orders,SHORT_POLICY,DIRECTIONS,receipt as native_receipt,patient_return_price,rounded
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS,WATCH_ASSETS

GLOBAL_POLICY='GLOBAL_USD_ROTATION_V1'
USD_PAIR='ETH-USD'
USD_SOURCE='COINBASE_PUBLIC_REST_BEST_BID_ASK'
MAX_REVISIONS=64


@dataclass(frozen=True)
class GlobalSettings:
    min_net_usd:D=D('.01')
    source_pct:D=D(50)
    initial_pct:D=D(50)
    review_s:int=30
    reconsider_s:int=120

    def checked(self):
        minimum,source,initial=map(exact,(self.min_net_usd,self.source_pct,self.initial_pct))
        if not D('.01')<=minimum<=D(1000000) or minimum%D('.01'):
            raise ValueError('MINIMUM_USD_REQUIRES_WHOLE_CENTS_AT_LEAST_ONE')
        if not D('.01')<=source<=50 or not D('.01')<=initial<=50:
            raise ValueError('PAPER_ALLOCATION_EXCEEDS_FIFTY_PERCENT')
        for value,low,high in ((self.review_s,5,300),(self.reconsider_s,60,600)):
            if type(value) is not int or not low<=value<=high:raise ValueError('INVALID_GLOBAL_REVIEW_OR_LIFETIME')
        return GlobalSettings(minimum,source,initial,self.review_s,self.reconsider_s)

    def frozen(self):return asdict(self.checked())


def _time(value):
    if isinstance(value,bool):raise ValueError('INVALID_POLICY_TIME')
    number=float(value)
    if not math.isfinite(number):raise ValueError('INVALID_POLICY_TIME')
    return number


def revision(settings,version,at):
    if type(version) is not int or not 1<=version<=MAX_REVISIONS:raise ValueError('GLOBAL_POLICY_REVISION_LIMIT')
    params=settings.checked().frozen()
    body=dict(policy=GLOBAL_POLICY,version=version,applied_at=_time(at),settings=params)
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    return dict(body,digest=digest)


def validate_history(history):
    if not isinstance(history,list) or len(history)>MAX_REVISIONS:raise ValueError('INVALID_GLOBAL_POLICY_HISTORY')
    previous=None
    for version,row in enumerate(history,1):
        if not isinstance(row,dict) or set(row)!={'policy','version','applied_at','settings','digest'}:
            raise ValueError('INVALID_GLOBAL_POLICY_REVISION')
        if type(row['version']) is not int:raise ValueError('INVALID_GLOBAL_POLICY_REVISION')
        try:expected=revision(GlobalSettings(**row['settings']),version,row['applied_at'])
        except (TypeError,ValueError,ArithmeticError):raise ValueError('INVALID_GLOBAL_POLICY_REVISION') from None
        if row!=expected or previous is not None and row['applied_at']<previous:
            raise ValueError('INVALID_GLOBAL_POLICY_REVISION')
        previous=row['applied_at']
    return history


def validate_transition(before,after,kind):
    old=before.get('auto',{}).get('global_history',[])
    new=after.get('auto',{}).get('global_history',[])
    validate_history(new)
    if new[:len(old)]!=old or len(new) not in (len(old),len(old)+1):
        raise ValueError('GLOBAL_POLICY_HISTORY_IS_APPEND_ONLY')
    if len(new)>len(old) and kind!='APPLY_GLOBAL_PAPER_SETTINGS':
        raise ValueError('EXPLICIT_GLOBAL_POLICY_APPLY_REQUIRED')
    if kind=='APPLY_GLOBAL_PAPER_SETTINGS' and any(after[key]!=before[key] for key in ('wallet','orders','fills','limits')):
        raise ValueError('SETTINGS_APPLY_CANNOT_MUTATE_ORDERS_OR_FUNDS')
    for ref,order in before['orders'].items():
        current=after['orders'][ref]
        if (current.get('global_policy_version',0)!=order.get('global_policy_version',0) or
                current.get('qualification')!=order.get('qualification') or
                current.get('initial_slice_order',False)!=order.get('initial_slice_order',False)):
            raise ValueError('EXISTING_ORDER_POLICY_CANNOT_BE_REWRITTEN')
    for key in ('funding_working_eth','funding_fraction'):
        if key in before and after.get(key)!=before[key]:raise ValueError('ORIGINAL_FUNDING_CAP_IS_FROZEN')
    if 'global_initial_slice' in before.get('auto',{}) and (
            after.get('auto',{}).get('global_initial_slice')!=before['auto']['global_initial_slice']):
        raise ValueError('INITIAL_PAPER_SLICE_CANNOT_CHANGE')
    old_reports=before.get('auto',{}).get('completed_rotations',{})
    new_reports=after.get('auto',{}).get('completed_rotations',{})
    if any(new_reports.get(ref)!=value for ref,value in old_reports.items()):
        raise ValueError('COMPLETED_ROTATION_RESULTS_ARE_IMMUTABLE')


def settings_at(state,version=None):
    history=state.get('auto',{}).get('global_history',[]);validate_history(history)
    if not history:return None
    if version is None:version=len(history)
    if type(version) is not int or not 1<=version<=len(history):raise ValueError('UNKNOWN_GLOBAL_POLICY_VERSION')
    return GlobalSettings(**history[version-1]['settings']).checked()


def usd_reference(frame,value,*,stamps=()):
    if not isinstance(value,dict) or set(value)!={'pair','source','bid','ask','observed_at'}:
        raise ValueError('USD_REFERENCE_UNAVAILABLE')
    if value['pair']!=USD_PAIR or value['source']!=USD_SOURCE:raise ValueError('USD_REFERENCE_NOT_APPROVED')
    bid,ask=exact(value['bid']),exact(value['ask']);stamp=_time(value['observed_at'])
    if not 0<bid<=ask or (ask-bid)/ask>D('.0025'):raise ValueError('USD_REFERENCE_INVALID_OR_WIDE')
    if not 0<=frame.at-stamp<=30:raise ValueError('USD_REFERENCE_STALE_OR_FUTURE')
    times=tuple(stamps)+(stamp,)
    if max(times)-min(times)>12:raise ValueError('USD_REFERENCE_DECISION_SPAN')
    return dict(value,bid=bid,ask=ask,observed_at=stamp)


def original_eth(state,source,budget):
    refs,_,_=reference_costs(state)
    quantity=exact(state['wallet'].get(source,D(0)))
    if source not in WATCH_ASSETS or quantity<=0 or not 0<budget<=quantity:
        raise ValueError('ORIGINAL_ETH_ALLOCATION_UNKNOWN')
    with localcontext() as ctx:
        ctx.prec=60
        return budget if source=='ETH' else refs[source]*budget/quantity


def entry_evidence(frame,receipt):
    pair,side=receipt['pair'],receipt['side'];book=frame.book(pair);stamp=book[2]
    leg=(pair,side,receipt['input_asset'],receipt['output_asset'])
    if pair not in WATCH_PAIRS or not any(a['leg']==leg for a in frame.graph(receipt['input_asset'])['actions']):
        raise ValueError('PRODUCT_OR_DIRECTION_NOT_APPROVED')
    units=frame._fee_units.get((pair,side),{})
    if not (units.get('verified') is True and units.get('currency')==pair.split('-')[1] and
            units.get('observed_at')==stamp):raise ValueError('FEE_CURRENCY_UNVERIFIED')
    depth=frame._depth.get((pair,side),{})
    if not depth:raise ValueError('DEPTH_UNVERIFIED')
    if depth.get('pair')!=pair or depth.get('side')!=side or depth.get('observed_at')!=stamp:
        raise ValueError('DEPTH_FRAME_CONFLICT')
    levels=depth.get('levels')
    if not isinstance(levels,(list,tuple)) or not 1<=len(levels)<=128:raise ValueError('DEPTH_MISSING_OR_TRUNCATED')
    previous=None;total=D(0)
    for level in levels:
        price,size=exact(level['price']),exact(level['size'])
        if price<=0 or size<=0:raise ValueError('DEPTH_INVALID')
        if previous is None and price!=(book[1] if side=='BUY' else book[0]):raise ValueError('DEPTH_TOP_CONFLICT')
        if previous is not None and (price<previous if side=='BUY' else price>previous):raise ValueError('DEPTH_LEVEL_ORDER_INVALID')
        total+=size;previous=price
    if total<receipt['gross_base_quantity']:raise ValueError('DEPTH_INSUFFICIENT')
    return stamp


def _paths(frame,source):
    if source=='ETH':return ((),)
    paths=[]
    def visit(asset,path,seen):
        for action in frame.graph(asset)['actions'][1:]:
            dst=action['target'];leg=action['leg']
            if dst=='ETH':paths.append(path+(leg,))
            elif len(path)<1 and dst not in seen:visit(dst,path+(leg,),seen|{dst})
    visit(source,(),{source})
    return tuple(sorted(paths,key=lambda p:(len(p),p)))


def qualification(state,frame,receipt,budget,reference,settings):
    """Conditional maker entry plus conservative sized exit valuation.

    All non-ETH residues block qualification. Liquidation reference receipts
    are never dispatched orders. Missing inputs never become a numeric profit.
    """
    out=dict(state='UNKNOWN',reason='UNOBSERVED',net_eth=None,net_usd=None,return_eth=None,
        original_eth=None,minimum_usd=settings.min_net_usd,path=(),exit_receipts=[],
        reference=None,classification='CONDITIONAL_SIMULATION_NOT_COMPLETED_PROFIT',actual_profit_usd=None)
    known={'USD_REFERENCE_UNAVAILABLE','USD_REFERENCE_NOT_APPROVED','USD_REFERENCE_INVALID_OR_WIDE',
        'USD_REFERENCE_STALE_OR_FUTURE','USD_REFERENCE_DECISION_SPAN','ORIGINAL_ETH_ALLOCATION_UNKNOWN',
        'FEE_CURRENCY_UNVERIFIED','DEPTH_UNVERIFIED','DEPTH_FRAME_CONFLICT','DEPTH_MISSING_OR_TRUNCATED',
        'DEPTH_INVALID','DEPTH_TOP_CONFLICT','DEPTH_LEVEL_ORDER_INVALID','DEPTH_INSUFFICIENT',
        'RESIDUAL_ETH_VALUE_UNKNOWN','ETH_EXIT_MARKET_UNAVAILABLE','QUOTE_DECISION_SPAN_EXCEEDS_12S',
        'PRODUCT_OR_DIRECTION_NOT_APPROVED','QUOTE_NOT_RETURNED','QUOTE_STALE','QUOTE_WIDE','QUOTE_FUTURE'}
    try:
        settings=settings.checked();budget=exact(budget)
        ref=usd_reference(frame,reference);entry_stamp=entry_evidence(frame,receipt)
        basis=original_eth(state,receipt['input_asset'],budget)
        residual=budget-receipt['input_quantity']
        if residual<0:raise ValueError('INVALID_SOURCE_BUDGET')
        if residual and receipt['input_asset']!='ETH':raise ValueError('RESIDUAL_ETH_VALUE_UNKNOWN')
        idle_eth=residual if receipt['input_asset']=='ETH' else D(0)
        paths=_paths(frame,receipt['output_asset'])
        if not paths:raise ValueError('ETH_EXIT_MARKET_UNAVAILABLE')
        valuation=Frame(frame.at,frame._catalog,frame._rules,frame._quotes,
            dict(frame._tier,taker=max(frame.rates('MAKER'),frame.rates('TAKER'))),frame._excluded,
            _depth=frame._depth,_fee_units=frame._fee_units)
        successes=[];failures=[]
        for path in paths:
            try:
                stamps=(entry_stamp,)+tuple(frame.book(leg[0])[2] for leg in path)
                usd_reference(frame,ref,stamps=stamps)
                if path:
                    result=estimate_path(source=receipt['output_asset'],quantity=receipt['output_quantity'],
                        path=path,frame=valuation,mode='TAKER',slippage_bps=D(15))
                    if result['recoverable_eth'] is None:
                        failures.extend(result['reasons']+result['limitations']);continue
                    recovered=result['recoverable_eth'];exits=result['receipts']
                else:recovered=receipt['output_quantity'];exits=[]
            except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError) as error:
                failures.append(str(error));continue
            with localcontext() as ctx:
                ctx.prec=60
                returned=recovered+idle_eth;net=returned-basis
                value=net*(ref['bid'] if net>=0 else ref['ask'])
            successes.append((value,net,returned,path,exits))
        if not successes:
            reason=next((r for r in failures if r in known),None)
            raise ValueError(reason or 'EXIT_COST_OR_NATIVE_RULE_UNKNOWN')
        value,net,returned,path,exits=max(successes,key=lambda r:(r[0],r[3]))
        out.update(state='CONDITIONAL_QUALIFIED' if value>=settings.min_net_usd else 'NOT_MET',
            reason='AFTER_COST_USD_FLOOR' if value>=settings.min_net_usd else 'BELOW_GLOBAL_USD_FLOOR',
            net_eth=net,net_usd=value,return_eth=returned,original_eth=basis,path=path,
            exit_receipts=exits,reference=ref)
    except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError) as error:
        reason=str(error);out['reason']=reason if reason in known else 'EXIT_COST_OR_NATIVE_RULE_UNKNOWN'
    return out


def effective_config(config,settings):
    return replace(config,policy=SHORT_POLICY,review_s=settings.review_s,order_ttl_s=settings.reconsider_s).checked()


def initial_campaign(state):
    context=state.get('auto',{})
    return bool(context.get('global_initial_slice') is True and not any(
        f['settled'] for f in state.get('fills',{}).values()))


def source_budget(state,available,view,settings,*,initial=False,ceiling=None):
    """A percentage of spendable inventory, then native/session caps, never up."""
    available=exact(available)
    cap=exact(state['limits']['source_caps'].get(view['source'],D(0)))
    budget=available if initial and view['source']=='ETH' else available*settings.source_pct/100
    budget=min(budget,cap)
    if ceiling is not None:budget=min(budget,exact(ceiling))
    return max(D(0),budget)


def global_candidates(engine,frame,config,settings,reference,*,review_reference=None,kickoff=False,budget_limits=None):
    """All fourteen views, one source snapshot, no startup exception for UNKNOWN."""
    state=engine.private_state();rows={};released=state['orders'].get(review_reference,{})
    initial=initial_campaign(state) and kickoff
    for view in DIRECTIONS:
        row=dict(view,state='BLOCKED',reason='UNOBSERVED',priority=0,score=D(0),at=frame.at,
            profit_state='UNKNOWN',qualification=None,target_exit=None)
        rows[view['id']]=row
        try:
            if not config.directions[view['id']]['enabled']:raise ValueError('DIRECTION_DISABLED_IN_FROZEN_SESSION')
            if view['pair'] not in state['limits']['products']:raise ValueError('SESSION_PRODUCT_NOT_APPROVED')
            if not any(a['leg']==(view['pair'],view['side'],view['source'],view['target'])
                    for a in frame.graph(view['source'])['actions']):raise ValueError('PRODUCT_OR_DIRECTION_NOT_APPROVED')
            book=frame.book(view['pair']);available=engine.available(view['source'])
            if available is None:raise ValueError('PAPER_RECONCILIATION_REQUIRED')
            if released.get('source')==view['source']:available+=released['reserved']
            maximum=None if budget_limits is None else budget_limits.get(view['source'])
            if released.get('source')==view['source']:
                maximum=released['reserved'] if maximum is None else min(maximum,released['reserved'])
            budget=source_budget(state,available,view,settings,initial=initial,ceiling=maximum)
            if budget<=0:raise ValueError('UNFUNDED_OR_NATIVE_CAP_UNAVAILABLE')
            rule=frame._rules[view['pair']]
            if view['source']!='ETH':
                increment=exact(rule['base_increment'] if view['side']=='SELL' else rule['quote_increment'])
                budget=rounded(budget,increment)
            tick=exact(rule.get('price_increment',rule['quote_increment']))
            offset=config.directions[view['id']]['entry_bps']/10000
            price=rounded(book[0]*(1-offset) if view['side']=='BUY' else book[1]*(1+offset),tick,up=view['side']=='SELL')
            plan=native_receipt(frame,view['pair'],view['side'],budget,price,frame.rates('MAKER'))
            proof=qualification(state,frame,plan,budget,reference,settings)
            row.update(state='CANDIDATE' if proof['state']=='CONDITIONAL_QUALIFIED' else
                'HOLD' if proof['state']=='NOT_MET' else 'UNKNOWN',reason=proof['reason'],
                profit_state=proof['state'],qualification=proof,source_budget=budget,plan=plan,book=book,
                fee_fraction=frame.rates('MAKER'),limit_price=price,market_limit_price=price,
                kind='KICKOFF' if kickoff and view['source']=='ETH' else
                    'RETURN_ETH' if view['target']=='ETH' else 'ROTATION',
                priority=10 if kickoff and view['source']=='ETH' else 3 if view['target']=='ETH' else 2,
                score=proof['net_usd'] or D(0))
            try:
                ref=usd_reference(frame,reference,stamps=(book[2],))
                basis=original_eth(state,view['source'],budget)
                required=basis+settings.min_net_usd/ref['bid']
                exit_view=view if view['target']=='ETH' else next(v for v in DIRECTIONS
                    if v['source']==view['target'] and v['target']=='ETH')
                exit_budget=budget if view['target']=='ETH' else plan['output_quantity']
                target=patient_return_price(frame,exit_view,exit_budget,required,frame.rates('MAKER'))
                row.update(required_eth=required,target_exit=dict(pair=exit_view['pair'],side=exit_view['side'],
                    limit_price=target,classification='MODELED_TARGET_ONLY_NOT_QUALIFICATION'))
            except (ValueError,TypeError,KeyError,ArithmeticError,StopIteration):pass
        except (ValueError,TypeError,KeyError,ArithmeticError) as error:
            reason=str(error)
            safe={'DIRECTION_DISABLED_IN_FROZEN_SESSION','SESSION_PRODUCT_NOT_APPROVED','PRODUCT_OR_DIRECTION_NOT_APPROVED','PAPER_RECONCILIATION_REQUIRED',
                'UNFUNDED_OR_NATIVE_CAP_UNAVAILABLE','QUOTE_NOT_RETURNED','QUOTE_STALE','QUOTE_WIDE','QUOTE_FUTURE'}
            row['reason']=reason if reason in safe else 'NATIVE_RULE_OR_MINIMUM_BLOCKED'
    return rows


def completed_reports(state,frame,reference):
    """Immutable first-observation USD result for actual terminal ETH-return slices."""
    reports=deepcopy(state['auto'].get('completed_rotations',{}))
    for ref,values in realized_orders(state).items():
        order=state['orders'][ref];version=order.get('global_policy_version',0)
        if ref in reports or not version or order['state'] not in ('FILLED','CANCELED'):
            continue
        item=dict(values,policy_version=version,net_usd=None,state='UNKNOWN',reason='USD_AT_COMPLETION_UNAVAILABLE',
            minimum_usd=settings_at(state,version).min_net_usd,classification='SIMULATED_COMPLETED_ETH_RETURN_SLICE',
            actual_profit_usd=None)
        try:
            if not 0<=frame.at-values['at']<=30:raise ValueError('MISSED_COMPLETION_VALUATION_WINDOW')
            value=usd_reference(frame,reference,stamps=(values['at'],))
            with localcontext() as ctx:
                ctx.prec=60
                item['net_usd']=values['net_eth']*(value['bid'] if values['net_eth']>=0 else value['ask'])
            item.update(state='MET' if item['net_usd']>=item['minimum_usd'] else 'NOT_MET',reason='KNOWN_SIMULATED_NATIVE_RECEIPTS',
                usd_reference=value)
        except (ValueError,TypeError,KeyError,ArithmeticError,OverflowError):pass
        reports[ref]=item
    return reports
