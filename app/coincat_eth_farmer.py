"""Read-only ETH measurements and a proposed reserve calculator.

No client, ledger, settings writer, wallet simulation or execution authority.
USD ranking remains v91's policy. A common ETH divisor cannot create an edge.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_DOWN

from coincat_cross_quote import usd_conversion
from coincat_multicurrency import available_routes, research_order, _paths
from coincat_v80_immediate import _prepare, exact
from coincat_v703_chain import approved_pairs
from coincat_v80_discovery import listed_usd_paths
from coincat_v80_discovery import book_status
from coincat_eth_diagnostics import (structural_details, missing_route_blockers,
    receipt_blockers, conversion_diagnostics)

D = Decimal
UNKNOWN_EVIDENCE = ('SIZED_DEPTH_UNKNOWN', 'FEE_CURRENCY_UNVERIFIED',
                    'EXCHANGE_TIME_UNVERIFIED', 'ALLOCATION_UNRECONCILED')


def _quantity(value):
    n = exact(value)
    if n < 0:
        raise ValueError('NEGATIVE_QUANTITY')
    return n


def eth_quote_plan(*, balances, catalog, rules, excluded=(), cursor=0):
    """Price-independent listed dependencies; no invented prices or allocation.

    Enumerate the canonical route topology without supplying synthetic books.
    A large/incomplete account can receive coordinated per-asset observations,
    but those groups are never summed into a purported account-wide total.
    """
    listed=set(approved_pairs(catalog,rules,excluded))
    output={'groups':[],'account_required_books':None,'known_dependency_books':0,'missing_asset_count':0,
            'all_paths_supported':False,'scope':'ACCOUNT_AVAILABLE_NOT_COINCAT_ALLOCATION'}
    output['structural_blockers']=[]
    for asset,raw in sorted(balances.items()):
        try:
            if not _quantity(raw) or asset in excluded:continue
        except (ValueError,TypeError,ArithmeticError):
            continue
        detail=structural_details(asset,catalog=catalog,rules=rules,excluded=excluded)
        if not detail['supported']:output['structural_blockers'].append(detail)
    if 'ETH-USD' not in listed:
        output['missing_asset_count']=len(output['structural_blockers'])
        return output
    marks=listed_usd_paths(listed)
    account={'ETH-USD'};groups=[]
    for asset,raw in sorted(balances.items()):
        try:
            quantity=_quantity(raw)
        except (ValueError,TypeError,ArithmeticError):
            output['missing_asset_count']+=1
            continue
        if not quantity or asset in excluded:
            continue
        books={'ETH-USD'}
        if asset!='ETH':
            routes=_paths(asset,'ETH',listed,listed,2)
            if not routes or asset not in marks:
                output['missing_asset_count']+=1
                continue
            books.update(marks[asset])
            valid=True
            for pair,side,source,target in routes[0]:
                if source not in marks:
                    valid=False;break
                books.add(pair);books.update(marks[source])
            if not valid:
                output['missing_asset_count']+=1
                continue
        account.update(books)
        groups.append({'kind':'asset','asset':asset,'books':tuple(sorted(books))})
    output['known_dependency_books']=len(account)
    output['all_paths_supported']=output['missing_asset_count']==0
    if output['all_paths_supported']:
        output['account_required_books']=len(account)
        output['groups'].append({'kind':'account','books':tuple(sorted(account))})
    if groups:
        offset=int(cursor)%len(groups)
        output['groups'].extend(groups[offset:]+groups[:offset])
    else:
        output['groups'].append({'kind':'reference','books':('ETH-USD',)})
    return output


def _return_to_eth(wallet, *, books, rules, catalog, now, fee, slip, excluded,
                   observed=None, structural_catalog=None):
    """Fixed shortest/lexical paths, chosen before economics; every leg costs once.

    Unconverted native dust is retained explicitly. Proceeds are a subtotal,
    never called a complete recoverable value when any quantity is unconverted.
    """
    proceeds = D(0)
    leftovers = {}
    orders = []
    dependencies = set()
    missing = {}
    details=[]
    observed=books if observed is None else observed
    structural_catalog=catalog if structural_catalog is None else structural_catalog
    for asset, quantity in sorted(wallet.items()):
        if not quantity:
            continue
        if asset in excluded:
            continue
        detail={'asset':asset,'state':'COMPLETE','blockers':[],'route':[],'residue_assets':[]}
        details.append(detail)
        if asset == 'ETH':
            proceeds += quantity
            continue
        paths = available_routes(asset, 'ETH', catalog, books, now=now)
        if not paths:
            missing[asset] = 'NO_LISTED_ETH_RETURN_PATH'
            leftovers[asset] = leftovers.get(asset, D(0)) + quantity
            detail.update(state='UNCONVERTED',blockers=missing_route_blockers(asset,
                catalog=structural_catalog,rules=rules,observed=observed,now=now,excluded=excluded))
            continue
        path = paths[0]  # Stable shortest/lexical policy, never best-profit search.
        detail['route']=[leg[0] for leg in path]
        current = quantity
        for pair, side, source, target in path:
            fx = usd_conversion(source, books, now=now, max_age=30, max_legs=2)
            if fx is None:
                missing[source] = 'USD_MARK_MISSING'
                leftovers[source] = leftovers.get(source, D(0)) + current
                mark=listed_usd_paths(catalog).get(source)
                reasons=(['USD_MARK_ROUTE_NOT_LISTED'] if mark is None else
                    ['USD_MARK_QUOTE_'+book_status(observed.get(p),now) for p in mark
                     if book_status(observed.get(p),now)!='FRESH'])
                detail['blockers'].extend(reasons or ['USD_MARK_UNVERIFIED'])
                detail['state']='UNCONVERTED';detail['residue_assets'].append(source)
                break
            dependencies.update((pair,) + fx['path'])
            try:
                receipt = research_order(pair=pair, side=side, available=current,
                    cap=current * fx['rate'], usd_rate=fx['rate'], book=books[pair],
                    product_rules=rules, fee=fee, slip=slip)
            except (ValueError, ArithmeticError):
                missing[source] = 'FULL_SIZE_PRODUCT_OR_COST_BLOCK'
                leftovers[source] = leftovers.get(source, D(0)) + current
                detail['blockers'].extend(receipt_blockers(pair=pair,side=side,available=current,
                    book=books[pair],rules=rules,fee=fee,slip=slip))
                detail['state']='UNCONVERTED';detail['residue_assets'].append(source)
                break
            orders.append(receipt)
            residue = current - receipt['input_quantity']
            if residue:
                leftovers[source] = leftovers.get(source, D(0)) + residue
                detail['blockers'].append('CANONICAL_ROUNDING_RESIDUE')
                detail['residue_assets'].append(source);detail['state']='PARTIAL_WITH_RESIDUE'
            current = receipt['output_quantity']
        else:
            proceeds += current
    return {'modeled_eth_proceeds': proceeds,
            'estimated_recoverable_eth': None if leftovers or missing else proceeds,
            'unconverted_native': leftovers, 'missing': missing,
            'orders': orders, 'dependencies': tuple(sorted(dependencies)),
            'conversion_details':details}


def measure_eth(*, result, balances, quotes, rules, catalog, now, balances_at,
                fee_rate, excluded=(), slippage_bps=D(15), observed_quotes=None):
    """Account-AVAILABLE scope only; protected/working allocation is unknown.

    Never infer earnings, settled ETH, reserves or cashflows from snapshots.
    Full portfolio totals fail closed on missing assets, dust or timestamp skew.
    """
    observed=quotes if observed_quotes is None else observed_quotes
    out = {'state': 'UNKNOWN', 'reason': 'ETH_REFERENCE_MISSING_STALE_OR_WIDE',
        'scope': 'ACCOUNT_AVAILABLE_ONLY_NOT_RECONCILED_WORKING_FUNDS',
        'actual_available_eth': None, 'settled_eth': None, 'protected_eth': None,
        'earned_eth': None, 'cashflow_adjusted_gain_eth': None,
        'allocation_state': 'UNRECONCILED', 'reference_eth_usd': None,
        'reference_product': 'ETH-USD', 'at': now, 'balances_at': balances_at,
        'w_eth_by_frame': {}, 'hold': None, 'switch': None,
        'return_advantage_eth': None, 'evidence': UNKNOWN_EVIDENCE,
        'portfolio_usd_mark': None,
        'synchronization_state': 'UNKNOWN',
        'live_order_permission': False}
    unpriced=[]
    for asset,raw in sorted(balances.items()):
        try:
            if not _quantity(raw) or asset in excluded:continue
        except (ValueError,TypeError,ArithmeticError):
            pass
        unpriced.append({'asset':asset,'state':'UNPRICED','blockers':['VALUATION_INPUTS_UNVERIFIED']})
    out['conversion_diagnostics']=conversion_diagnostics(unpriced,
        reference_state=book_status(observed.get('ETH-USD'),now),
        balances_fresh=balances_at is not None and 0<=now-balances_at<=120)
    if balances_at is None or not 0 <= now - balances_at <= 120:
        return dict(out, reason='AVAILABLE_BALANCES_STALE_OR_UNOBSERVED')
    with localcontext() as ctx:
        ctx.prec = 60
        try:
            wallet = {a: _quantity(q) for a, q in balances.items()}
            out['actual_available_eth'] = wallet.get('ETH', D(0))
            fee = exact(fee_rate)
            slip = exact(slippage_bps) / 10000
            if not 0 <= fee < D('.05') or not 0 <= slip <= D('.005'):
                raise ValueError()
        except (ValueError, TypeError, ArithmeticError):
            return dict(out, reason='QUANTITY_OR_COST_ESTIMATE_UNKNOWN')
        books = _prepare({p:b for p,b in quotes.items() if p in catalog}, rules, now)['books']
        allowed = approved_pairs(catalog, rules, excluded)
        clean = {p: books[p] for p in sorted(set(allowed) & set(books))}
        args = dict(books=clean, rules=rules, catalog=allowed, now=now,
                    fee=fee, slip=slip, excluded=set(excluded), observed=observed,structural_catalog=catalog)
        hold = _return_to_eth(wallet, **args)
        out['hold'] = hold
        out['conversion_diagnostics']=conversion_diagnostics(hold['conversion_details'],
            reference_state=book_status(observed.get('ETH-USD'),now))
        if 'ETH-USD' not in books:
            hold['estimated_recoverable_eth']=None;hold['modeled_eth_proceeds']=None
            return out
        reference = books['ETH-USD'][0]  # Same conservative mark for every row.
        out['reference_eth_usd'] = reference
        ref_stamp = books['ETH-USD'][2]
        total_usd = D(0)
        mark_stamps = [ref_stamp]
        for asset, quantity in sorted(wallet.items()):
            if not quantity or asset in excluded:
                continue
            fx = usd_conversion(asset, books, now=now, max_age=30, max_legs=2)
            if fx is None:
                break
            total_usd += quantity*fx['rate']
            mark_stamps.extend(books[p][2] for p in fx['path'])
        else:
            if max(mark_stamps)-min(mark_stamps) <= 12:
                out['portfolio_usd_mark'] = total_usd
        for row in result.get('ranked', ()):
            frame = row['frame']
            stamps = [b[2] for b in frame['books'].values()] + [ref_stamp]
            if max(stamps) - min(stamps) <= 12 and all(0 <= now-t <= 30 for t in stamps):
                out['w_eth_by_frame'][frame['id']] = row['w'] / reference
        best = result.get('best')
        if best:
            # Observational comparison only: no mutable or persistent wallet.
            switched = dict(wallet)
            if best['spent'] > switched.get(best['source'], D(0)):
                return dict(out, reason='PROPOSAL_SOURCE_SNAPSHOT_CONFLICT')
            switched[best['source']] -= best['spent']
            switched[best['target']] = switched.get(best['target'], D(0)) + best['received']
            out['switch'] = _return_to_eth(switched, **args)
        dependencies = {'ETH-USD'} | set(hold['dependencies'])
        if best:
            dependencies.update(best['frame']['dependencies'])
            dependencies.update(out['switch']['dependencies'])
        stamps = [books[p][2] for p in dependencies]
        out['quote_span_s'] = max(stamps) - min(stamps)
        out['oldest_quote_age_s'] = now - min(stamps)
        out['conversion_diagnostics']=conversion_diagnostics(hold['conversion_details'],
            quote_span=out['quote_span_s'])
        if out['quote_span_s'] > 12:
            for value in (hold, out['switch']):
                if value is not None:
                    value['estimated_recoverable_eth'] = None
                    value['modeled_eth_proceeds'] = None
            return dict(out, reason='ETH_RETURN_PRICE_SKEW')
        out['synchronization_state']=('PARTIAL_OR_INCOMPLETE' if hold['missing'] or
            (out['switch'] is not None and out['switch']['missing']) else 'SYNCHRONIZED')
        complete = hold['estimated_recoverable_eth'] is not None
        if out['switch'] is not None:
            complete = complete and out['switch']['estimated_recoverable_eth'] is not None
            if complete:
                out['return_advantage_eth'] = (out['switch']['estimated_recoverable_eth']
                                              - hold['estimated_recoverable_eth'])
        return dict(out, state='MODELED_UNVERIFIED' if complete else 'UNKNOWN',
                    reason='TOP_OF_BOOK_MODEL_NOT_EXECUTION_EVIDENCE' if complete
                           else 'INCOMPLETE_ETH_RETURN_DUST_OR_MISSING_ROUTE')


def measure_working_eth(*, allocation, observation, slippage_bps=D(15)):
    """Only explicit, reconciled working native amounts; never account fallback."""
    if (allocation.get('state')!='AUTHORIZED_RECONCILED_MODEL_ONLY' or
            allocation.get('owner_authorized') is not True or allocation.get('reconciled') is not True or
            not allocation.get('eligible_working_balances')):
        return {'state':'UNKNOWN','reason':'NO_AUTHORIZED_RECONCILED_WORKING_FUNDS',
            'scope':'COINCAT_WORKING_ONLY','estimated_recoverable_eth':None,
            'eth_profit_selection_enabled':False,'live_order_permission':False}
    from coincat_working_allocation import allocation_keys
    observed_key=allocation_keys(observation['balances'],(),observation.get('excluded',()))[0]
    if observed_key!=allocation.get('snapshot_key'):
        return {'state':'UNKNOWN','reason':'WORKING_ALLOCATION_SNAPSHOT_CONFLICT',
            'scope':'COINCAT_WORKING_ONLY','estimated_recoverable_eth':None,
            'eth_profit_selection_enabled':False,'live_order_permission':False}
    inputs=dict(observation,balances=dict(allocation['eligible_working_balances']))
    value=measure_eth(result={'ranked':[]},**inputs,slippage_bps=slippage_bps)
    return {'state':value['state'],'reason':value['reason'],'scope':'COINCAT_WORKING_ONLY',
        'estimated_recoverable_eth':(value.get('hold') or {}).get('estimated_recoverable_eth'),
        'conversion_diagnostics':value['conversion_diagnostics'],
        'eth_profit_selection_enabled':False,'live_order_permission':False}


@dataclass(frozen=True)
class ReservePolicy:
    initial_usd: D = D(10)
    growth_step_usd: D = D(20)
    harvest_usd: D = D(10)


def reserve_preview(policy=ReservePolicy(), *, fixed_reference=None,
                    hypothetical_earned_eth=None, consumed_milestones=0,
                    hypothetical_settled_eth=None):
    """Stateless what-if arithmetic, NOT an earned/reserved balance record.

    Inputs labelled hypothetical must never be filled from account changes or
    passive Lab comparisons. No state is advanced, even when funded in a scenario.
    A later authorized reconciliation design must own all actual milestones.
    """
    result = {'state': 'PENDING_REFERENCE', 'scope': 'PROPOSED_CALCULATOR_ONLY',
              'actual_reserved_eth': None, 'actual_earned_eth': None,
              'assets_earmarked': False, 'fixed_reference': None}
    with localcontext() as ctx:
        ctx.prec = 60
        initial = _quantity(policy.initial_usd)
        step = exact(policy.growth_step_usd)
        harvest = _quantity(policy.harvest_usd)
        if step <= 0 or isinstance(consumed_milestones, bool) or not isinstance(consumed_milestones, int) or consumed_milestones < 0:
            raise ValueError('INVALID_POLICY_OR_CONSUMED_MILESTONES')
        if fixed_reference is None or exact(fixed_reference) == 0:
            return result
        ref = exact(fixed_reference)
        if ref < 0:
            raise ValueError('INVALID_FIXED_REFERENCE')
        initial_eth, step_eth, harvest_eth = initial/ref, step/ref, harvest/ref
        result.update(fixed_reference=ref, initial_target_eth=initial_eth,
                      growth_step_eth=step_eth, harvest_per_step_eth=harvest_eth,
                      next_threshold_eth=(consumed_milestones+1)*step_eth,
                      state='PENDING_RECONCILED_EARNINGS_AND_SETTLED_ALLOCATION')
        if hypothetical_earned_eth is None:
            return result
        earned = exact(hypothetical_earned_eth)
        crossed = max(0, int((earned/step_eth).to_integral_value(rounding=ROUND_DOWN)))
        due = max(0, crossed-consumed_milestones)
        result.update(scenario_new_milestones=due, scenario_harvest_eth=due*harvest_eth,
                      state='SCENARIO_HARVEST_PENDING')
        if hypothetical_settled_eth is not None:
            available = _quantity(hypothetical_settled_eth)
            result['state'] = ('SCENARIO_FUNDED_NO_ACTION' if available >= initial_eth+due*harvest_eth
                               else 'SCENARIO_UNDERFUNDED_NO_AUTO_BUY')
        return result
