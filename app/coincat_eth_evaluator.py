"""v92 native-unit cycle research. No client, persistence or execution interface."""
from decimal import Decimal, localcontext
import math

from coincat_eth_diagnostics import receipt_blockers
from coincat_multicurrency import research_order
from coincat_v703_chain import approved_pairs
from coincat_v80_discovery import book_status
from coincat_v80_immediate import exact
from coincat_v701_quotes import valid_book

D = Decimal


def enumerate_cycles(*, catalog, rules, excluded=(), max_legs=5,
                     max_cycles=2048, max_expansions=50000):
    """Simple directed ETH cycles; opposite orientations are distinct markets.

    No repeated intermediate asset or product. ETH is the fixed root, eliminating
    rotation duplicates. Two-leg reversals are excluded. Deterministic bounds are
    explicitly reported; a bounded prefix is never called exhaustive coverage.
    """
    if not 3 <= max_legs <= 5 or not 1 <= max_cycles <= 10000 or not 1 <= max_expansions <= 1000000:
        raise ValueError('ENUMERATION_BOUND_INVALID')
    edges = {}
    for pair in sorted(set(approved_pairs(catalog, rules, excluded))):
        base, quote = pair.split('-')
        for side, source, target in (('SELL', base, quote), ('BUY', quote, base)):
            edges.setdefault(source, []).append((pair, side, source, target))
    cycles = []; expansions = 0; truncated = False

    def visit(asset, path, visited, products):
        nonlocal expansions, truncated
        for leg in sorted(edges.get(asset, ())):
            if expansions >= max_expansions:
                truncated = True
                return
            expansions += 1
            pair, side, source, target = leg
            if pair in products:
                continue
            if target == 'ETH':
                if len(path) + 1 >= 3:
                    if len(cycles) >= max_cycles:
                        truncated = True
                        return
                    cycles.append(path + (leg,))
            elif target not in visited and len(path) + 1 < max_legs:
                visit(target, path + (leg,), visited | {target}, products | {pair})
            if truncated:
                return
    visit('ETH', (), {'ETH'}, set())
    return {'cycles': cycles, 'truncated': truncated, 'expansions': expansions,
            'max_legs': max_legs, 'coverage_complete': not truncated}


def evaluate_cycle(*, cycle, starting_eth, catalog, rules, quotes, now,
                   balances_at, fee_rate=D('.009'), excluded=()):
    """Full-source native receipts, fixed 15bps per leg, no USD mark dependency.

    The legacy receipt's cap/usd_rate are only an algebraic budget adapter here:
    cap=source units and rate=1 preserve the full native budget exactly. This is
    NOT a USD price or stablecoin peg. The misleading USD-notional field is removed.
    Quantities are private caller results and must not enter public diagnostics.
    """
    out = {'state': 'UNKNOWN', 'blockers': [], 'receipts': [], 'residuals': {},
           'final_eth': None, 'net_additional_eth': None,
           'live_order_permission': False, 'execution_eligible': False,
           'scope': 'READ_ONLY_PROPOSED_ETH_NOT_RECONCILED_FUNDS',
           'quotes_validated': False, 'quote_span_s': None, 'oldest_quote_age_s': None,
           'evidence': ['DEPTH_UNVERIFIED', 'FEE_CURRENCY_UNVERIFIED',
                        'SETTLEMENT_UNVERIFIED', 'SEQUENTIAL_LEG_RISK_UNVERIFIED']}
    try:
        amount = exact(starting_eth); fee = exact(fee_rate)
        if amount <= 0 or not 0 <= fee < D('.05'):
            raise ValueError()
        if (isinstance(now, bool) or isinstance(balances_at, bool) or
                not math.isfinite(float(now)) or not 0 <= float(now)-float(balances_at) <= 120):
            raise ValueError()
    except (ValueError, TypeError, ArithmeticError, OverflowError):
        out['blockers'] = ['FUNDING_TIME_OR_COST_INPUT_UNVERIFIED']
        return out
    allowed = set(approved_pairs(catalog, rules, excluded))
    asset = 'ETH'; visited = {'ETH'}; products = set()
    if not 3 <= len(cycle) <= 5:
        return dict(out, state='BLOCKED', blockers=['NOT_SIMPLE_ETH_CYCLE'])
    for index, (pair, side, source, target) in enumerate(cycle):
        parts = pair.split('-')
        expected = tuple(parts) if side == 'SELL' else tuple(reversed(parts))
        if (side not in ('BUY', 'SELL') or len(parts) != 2 or
                (source, target) != expected or source != asset or pair in products or
                (target == 'ETH' and index != len(cycle)-1) or
                (target in visited and target != 'ETH')):
            return dict(out, state='BLOCKED', blockers=['NOT_SIMPLE_ETH_CYCLE'])
        if pair not in allowed:
            out['blockers'].append('PRODUCT_NOT_APPROVED:' + pair)
        status = book_status(quotes.get(pair), now)
        if status != 'FRESH':
            out['blockers'].append('QUOTE_' + status + ':' + pair)
        products.add(pair); visited.add(target); asset = target
    if asset != 'ETH':
        out['blockers'].append('CYCLE_NOT_CLOSED')
    if out['blockers']:
        return out
    stamps = [float(quotes[p][2]) for p in products]
    if max(stamps)-min(stamps) > 12:
        return dict(out, blockers=['CYCLE_QUOTE_SKEW'])
    out.update(quotes_validated=True, quote_span_s=max(stamps)-min(stamps),
               oldest_quote_age_s=float(now)-min(stamps))
    with localcontext() as ctx:
        ctx.prec = 60
        current = amount
        for pair, side, source, target in cycle:
            try:
                receipt = research_order(pair=pair, side=side, available=current,
                    cap=current, usd_rate=D(1), book=valid_book(quotes[pair], now, 30, D(".0025")), product_rules=rules,
                    fee=fee, slip=D('.0015'))
            except (ValueError, ArithmeticError):
                reasons = receipt_blockers(pair=pair, side=side, available=current,
                    book=quotes[pair], rules=rules, fee=fee, slip=D('.0015'))
                return dict(out, state='BLOCKED', blockers=[r + ':' + pair for r in reasons])
            receipt.pop('approx_usd_notional')
            receipt['budget_basis'] = 'FULL_NATIVE_SOURCE_NOT_USD'
            out['receipts'].append(receipt)
            residue = current-receipt['input_quantity']
            if residue:
                out['residuals'][source] = out['residuals'].get(source, D(0)) + residue
            current = receipt['output_quantity']
        if any(q for a, q in out['residuals'].items() if a != 'ETH'):
            return dict(out, blockers=['UNCONVERTED_NATIVE_RESIDUE'])
        final = current + out['residuals'].get('ETH', D(0))
        return dict(out, state='MODELED_UNVERIFIED', final_eth=final,
                    net_additional_eth=final-amount)


def rank_cycles(*, max_legs=5, max_cycles=2048, max_expansions=50000, **inputs):
    inventory = enumerate_cycles(catalog=inputs['catalog'], rules=inputs['rules'],
        excluded=inputs.get('excluded', ()), max_legs=max_legs,
        max_cycles=max_cycles, max_expansions=max_expansions)
    results = [dict(evaluate_cycle(cycle=c, **inputs), cycle=c) for c in inventory['cycles']]
    ranked = sorted((r for r in results if r['net_additional_eth'] is not None),
                    key=lambda r: (-r['net_additional_eth'], r['cycle']))
    return {'inventory': inventory, 'results': results, 'ranked': ranked,
            'best_positive': next((r for r in ranked if r['net_additional_eth'] > 0), None),
            'live_order_permission': False, 'execution_eligible': False}


def public_cycle_report(research):
    """Quantity-free export projection; never export private receipts or amounts."""
    return {'scope': 'NATIVE_ETH_CYCLE_RESEARCH_NOT_REALIZED_INCOME',
            'coverage_complete': research['inventory']['coverage_complete'],
            'funnel': dict(research.get('funnel', {})),
            'scheduling': {k: research.get('scheduling', {}).get(k) for k in
                ('requested_books','selected','groups_deferred','scope','quote_time_evidence')},
            'cycles_reviewed': len(research['results']),
            'complete_modeled_cycles': len(research['ranked']),
            'positive_modeled_cycles': sum(r['net_additional_eth'] > 0 for r in research['ranked']),
            'execution_eligible': False, 'live_order_permission': False,
            'candidates': [{'route': [{'product': p, 'side': s} for p, s, _, _ in r['cycle']],
                            'state': r['state'], 'blockers': list(r['blockers']),
                            'evidence': list(r['evidence'])} for r in research['results']]}


def observe_cycle_snapshot(*, inventory, cancel=None, **inputs):
    """Worker-local result; caller publishes only after a cancellation check."""
    results=[]
    for cycle in inventory['cycles']:
        if cancel is not None and cancel.is_set():
            return None
        results.append(dict(evaluate_cycle(cycle=cycle, **inputs), cycle=cycle))
    if cancel is not None and cancel.is_set():
        return None
    ranked=sorted((r for r in results if r['net_additional_eth'] is not None),
                  key=lambda r: (-r['net_additional_eth'], r['cycle']))
    observed=sum(all(p in inputs['quotes'] for p, *_ in r['cycle']) for r in results)
    return {'inventory': inventory, 'results': results, 'ranked': ranked,
            'best_positive': next((r for r in ranked if r['net_additional_eth'] > 0), None),
            'best_negative': next((r for r in ranked if r['net_additional_eth'] < 0), None),
            'funnel': {'discovered': len(results), 'observed': observed,
                       'validated': sum(r['quotes_validated'] for r in results),
                       'costed': len(ranked),
                       'positive': sum(r['net_additional_eth'] > 0 for r in ranked),
                       'execution_evidence': 0},
            'scope': 'PROPOSED_WORKING_ETH_RESEARCH_ONLY_NOT_RECONCILED',
            'at': inputs['now'], 'live_order_permission': False, 'execution_eligible': False}
