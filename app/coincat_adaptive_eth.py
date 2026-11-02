"""Bounded conditional ETH research. Pure, RAM-only; never an order channel.

A frame is a frozen observation, not a fill. Only explicit offline assumption
records advance ResearchFunds. Normal app integration calls observation_summary
only: no seeds, reservations, prediction fitting or synthetic evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal as D, localcontext
import math

from coincat_continuity import eth_funding, quote_reason
from coincat_eth_maker import post_only_eligible
from coincat_multicurrency import research_order
from coincat_v80_immediate import exact
from coincat_watchlist import WATCH_PAIRS, WATCH_ASSETS, eligible_watchlist

MAX_CASES = 32
MAX_EVENTS = 128


def _time(value):
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError('INVALID_TIME')
    return float(value)


def _amount(value):
    value = exact(value)
    if value <= 0:
        raise ValueError('INVALID_QUANTITY')
    return value


def candidate_graph(source, *, catalog, rules, excluded=(), limit=16):
    """HOLD plus listed one-step directions; no fabricated inverse product IDs."""
    if source not in WATCH_ASSETS or type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError('INVALID_GRAPH_INPUT')
    qualified, rejected = eligible_watchlist(catalog, rules, excluded)
    actions = [dict(kind='HOLD', source=source, target=source, leg=())]
    for pair in sorted(qualified):
        base, quote = pair.split('-')
        if source in (base, quote):
            side, target = ('SELL', quote) if source == base else ('BUY', base)
            actions.append(dict(kind='CONDITIONAL_CONVERSION', source=source,
                                target=target, leg=(pair, side, source, target)))
    return dict(actions=actions[:limit], truncated=len(actions) > limit,
                rejected=rejected, execution_eligible=False)


def closed_routes(*, catalog, rules, excluded=(), limit=32):
    """At most three legs: four reversals and six triangles in the full universe."""
    if type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError('INVALID_ROUTE_BOUND')
    graph = {a: candidate_graph(a, catalog=catalog, rules=rules, excluded=excluded)['actions'][1:]
             for a in WATCH_ASSETS}
    routes = []
    def visit(asset, path, seen):
        for action in graph[asset]:
            target = action['target']; leg = action['leg']
            if target == 'ETH':
                if path:
                    routes.append(path + (leg,))
            elif target not in seen and len(path) < 2:
                visit(target, path + (leg,), seen | {target})
    visit('ETH', (), {'ETH'})
    routes.sort(key=lambda r: (len(r), r))
    return dict(routes=routes[:limit], truncated=len(routes) > limit,
                coverage_complete=len(routes) <= limit, max_legs=3)


@dataclass(frozen=True)
class Frame:
    """Caller-independent snapshot. Private dictionaries never leave via accessors."""
    at: float
    _catalog: tuple
    _rules: dict
    _quotes: dict
    _tier: dict
    _excluded: tuple = ()
    _depth: dict = None
    _fee_units: dict = None

    def __post_init__(self):
        object.__setattr__(self, 'at', _time(self.at))
        for field in ('_rules', '_quotes', '_tier', '_depth', '_fee_units'):
            object.__setattr__(self, field, deepcopy(getattr(self, field) or {}))
        object.__setattr__(self, '_catalog', tuple(self._catalog))
        object.__setattr__(self, '_excluded', tuple(self._excluded))

    def rates(self, mode):
        if mode not in ('MAKER', 'TAKER'):
            raise ValueError('UNSUPPORTED_COST_MODE')
        tier = self._tier
        try:
            valid = tier.get('fresh') is True and 0 <= self.at-_time(tier.get('captured_at')) <= 7200
        except (ValueError, TypeError, OverflowError):
            valid = False
        if not valid:
            raise ValueError('ACCOUNT_FEE_TIER_UNAVAILABLE')
        try:
            rate = exact(tier.get(mode.lower()))
            if not 0 <= rate < D('.05'):
                raise ValueError()
        except (ValueError, TypeError, ArithmeticError):
            raise ValueError('FEE_RATE_UNSUPPORTED_NO_REBATE_ASSUMPTION') from None
        return rate

    def graph(self, source):
        return candidate_graph(source, catalog=self._catalog, rules=self._rules, excluded=self._excluded)

    def book(self, pair):
        raw = self._quotes.get(pair)
        reason = quote_reason(raw, self.at)
        if reason:
            raise ValueError(reason)
        bid, ask, stamp = raw
        bid, ask = exact(bid), exact(ask)
        tick = exact(self._rules[pair].get('price_increment', self._rules[pair]['quote_increment']))
        if bid % tick or ask % tick:
            raise ValueError('QUOTE_PRICE_INCREMENT_INVALID')
        return bid, ask, _time(stamp)


def estimate_path(*, source, quantity, path, frame, mode='TAKER', slippage_bps=D(15)):
    """One shared native wallet, canonical receipts, every residual retained.

    MODELED_UNVERIFIED arithmetic can exist without sized depth/fee units.
    recoverable_eth stays UNKNOWN unless every debit unit and sized exit is
    supplied for this frame. Even a complete estimate never establishes a fill.
    """
    out = dict(state='UNKNOWN', reasons=[], limitations=[], receipts=[], inventory={},
               modeled_eth=None, recoverable_eth=None, execution_eligible=False,
               actual_profit_eth=None, evidence_basis='OBSERVATION_OR_ASSUMPTION_NOT_FILL')
    try:
        quantity = _amount(quantity); slip = exact(slippage_bps)/10000
        if source not in WATCH_ASSETS or source in frame._excluded or not 0 <= slip <= D('.005'):
            raise ValueError('SOURCE_OR_STRESS_INVALID')
        if not isinstance(path, tuple) or not 1 <= len(path) <= 3:
            raise ValueError('INVALID_PATH')
        fee = frame.rates(mode)
        if mode == 'MAKER' and slip:
            raise ValueError('MAKER_HAS_NO_TAKER_SLIPPAGE')
        asset = source; books = {}; legs = []
        for leg in path:
            if not isinstance(leg, tuple) or len(leg) != 4:
                raise ValueError('INVALID_PATH')
            pair, side, src, dst = leg
            if src != asset or not any(a['leg'] == leg for a in frame.graph(src)['actions']):
                raise ValueError('PRODUCT_OR_DIRECTION_NOT_APPROVED')
            books[pair] = frame.book(pair); legs.append(leg); asset = dst
        stamps = [b[2] for b in books.values()]
        if max(stamps)-min(stamps) > 12:
            raise ValueError('QUOTE_DECISION_SPAN_EXCEEDS_12S')
        with localcontext() as ctx:
            ctx.prec = 60
            wallet = {source: quantity}
            for pair, side, src, dst in legs:
                bid, ask, stamp = books[pair]
                # A maker limit is a conditional resting price, never an assumed touch-fill.
                price = bid if side == 'BUY' else ask
                book = (price, price, stamp) if mode == 'MAKER' else books[pair]
                if mode == 'MAKER' and not post_only_eligible(side, price, books[pair],
                        exact(frame._rules[pair].get('price_increment', frame._rules[pair]['quote_increment']))):
                    raise ValueError('POST_ONLY_ENTRY_WOULD_CROSS')
                depth = frame._depth.get((pair, side), {})
                levels = None
                if mode == 'TAKER' and depth:
                    if depth.get('pair') != pair or depth.get('observed_at') != stamp or depth.get('side') != side:
                        raise ValueError('DEPTH_FRAME_CONFLICT')
                    levels = depth.get('levels')
                if levels is None:
                    out['limitations'].append('DEPTH_UNVERIFIED')
                units = frame._fee_units.get((pair, side), {})
                if not (units.get('currency') == pair.split('-')[1] and units.get('verified') is True
                        and units.get('observed_at') == stamp):
                    out['limitations'].append('FEE_CURRENCY_UNVERIFIED')
                if mode == 'MAKER':
                    out['limitations'].append('MAKER_FILL_AND_EXIT_UNCERTAIN')
                budget = wallet.get(src, D(0))
                receipt = research_order(pair=pair, side=side, available=budget, cap=budget,
                    usd_rate=D(1), book=book, product_rules=frame._rules, fee=fee,
                    slip=slip, levels=levels)
                receipt.pop('approx_usd_notional', None)
                receipt['cost_mode'] = mode
                wallet[src] = budget-receipt['input_quantity']
                wallet[dst] = wallet.get(dst, D(0))+receipt['output_quantity']
                out['receipts'].append(receipt)
            out['inventory'] = {a: q for a, q in wallet.items() if q > 0}
            if asset == 'ETH':
                out['modeled_eth'] = wallet.get('ETH', D(0))
                if any(q > 0 for a, q in wallet.items() if a != 'ETH'):
                    out['limitations'].append('RESIDUAL_ETH_VALUE_UNKNOWN')
            out['limitations'] = sorted(set(out['limitations']))
            if asset == 'ETH' and not out['limitations']:
                out['recoverable_eth'] = out['modeled_eth']
            out['state'] = 'MODELED_UNVERIFIED'
    except (ValueError, TypeError, ArithmeticError, KeyError, IndexError, OverflowError) as exc:
        known = {'ACCOUNT_FEE_TIER_UNAVAILABLE', 'FEE_RATE_UNSUPPORTED_NO_REBATE_ASSUMPTION',
            'UNSUPPORTED_COST_MODE', 'SOURCE_OR_STRESS_INVALID', 'INVALID_QUANTITY', 'INVALID_PATH',
            'PRODUCT_OR_DIRECTION_NOT_APPROVED', 'QUOTE_NOT_RETURNED', 'QUOTE_STALE', 'QUOTE_WIDE',
            'QUOTE_INVALID', 'QUOTE_FUTURE', 'QUOTE_PRICE_INCREMENT_INVALID',
            'QUOTE_DECISION_SPAN_EXCEEDS_12S', 'MAKER_HAS_NO_TAKER_SLIPPAGE',
            'POST_ONLY_ENTRY_WOULD_CROSS', 'DEPTH_FRAME_CONFLICT', 'DEPTH_INSUFFICIENT',
            'DEPTH_TOP_CONFLICT', 'DEPTH_LEVEL_ORDER_INVALID', 'DEPTH_MISSING_OR_TRUNCATED'}
        reason = str(exc)
        out['reasons'] = [reason if reason in known else 'PRODUCT_SIZE_RULE_OR_INPUT_INVALID']
    return out


class ResearchFunds:
    """One explicit ETH working slice. No account, database or automatic seed.

    Use from_proposal to apply existing manual/protected/excluded/unassigned
    carve-outs. All reserves/events remain local simulated assumptions. Unknown
    partial fills lock their entire source budget until separately designed recovery.
    """
    def __init__(self, working_eth):
        self.initial_eth = _amount(working_eth)
        self._wallet = {'ETH': self.initial_eth}
        self._reservations = {}; self._events = set()

    @classmethod
    def from_proposal(cls, *, amount_eth, **proposal):
        funding = eth_funding(**proposal); amount = _amount(amount_eth)
        if not funding['valid'] or amount > funding['row'].get('working', D(0)):
            raise ValueError('WORKING_ETH_UNAVAILABLE')
        return cls(amount)

    def inventory(self):
        return deepcopy(self._wallet)

    def available(self, asset):
        with localcontext() as ctx:
            ctx.prec = 60
            reserved = sum((r['quantity'] for r in self._reservations.values()
                            if r['source'] == asset), D(0))
            return self._wallet.get(asset, D(0))-reserved

    def reserve(self, reference, *, leg, quantity, frame, mode='TAKER', slippage_bps=D(15)):
        if (not isinstance(reference, str) or not 1 <= len(reference) <= 64 or
                reference in self._events or reference in self._reservations or
                len(self._events)+len(self._reservations) >= MAX_EVENTS):
            raise ValueError('DUPLICATE_OR_BOUNDED_EVENT')
        quantity = _amount(quantity)
        if quantity > self.available(leg[2]):
            raise ValueError('PAPER_FUNDS_EXHAUSTED_OR_RESERVED')
        result = estimate_path(source=leg[2], quantity=quantity, path=(leg,), frame=frame,
                               mode=mode, slippage_bps=slippage_bps)
        if result['state'] == 'UNKNOWN':
            raise ValueError(result['reasons'][0])
        self._reservations[reference] = dict(source=leg[2], quantity=quantity,
            receipt=deepcopy(result['receipts'][0]), state='RESERVED')
        return deepcopy(result)

    def uncertain(self, reference):
        self._reservations[reference]['state'] = 'PARTIAL_OR_UNCERTAIN_FILL'

    def assume_fill(self, reference, *, classification, input_quantity, output_quantity,
                    fee_quantity, fee_currency):
        """Explicit full frozen receipt only; never called by the UI or quote observer."""
        reserved = self._reservations[reference]; receipt = reserved['receipt']
        if classification != 'SIMULATED_ASSUMPTION' or reserved['state'] != 'RESERVED':
            raise ValueError('EXPLICIT_FULL_ASSUMPTION_REQUIRED')
        values = (exact(input_quantity), exact(output_quantity), exact(fee_quantity), fee_currency)
        expected = (receipt['input_quantity'], receipt['output_quantity'],
                    receipt['fee_amount_estimate'], receipt['assumed_fee_currency_for_research'])
        if values != expected:
            raise ValueError('FROZEN_RECEIPT_CONFLICT')
        with localcontext() as ctx:
            ctx.prec = 60
            src, dst = receipt['input_asset'], receipt['output_asset']
            self._wallet[src] -= receipt['input_quantity']
            self._wallet[dst] = self._wallet.get(dst, D(0))+receipt['output_quantity']
        del self._reservations[reference]; self._events.add(reference)
        return dict(classification='SIMULATED_ASSUMPTION', actual_profit_eth=None)

    def no_fill(self, reference):
        if self._reservations[reference]['state'] != 'RESERVED':
            raise ValueError('UNCERTAIN_FUNDS_REMAIN_LOCKED')
        del self._reservations[reference]; self._events.add(reference)

    def has_uncertain(self):
        return any(r['state'] != 'RESERVED' for r in self._reservations.values())


def recoverable_inventory(wallet, frame, *, slippage_bps=D(15)):
    """Same-time conservative direct ETH exits; missing dust/depth/fees => UNKNOWN."""
    total = D(0); modeled = D(0); reasons = []; stamps = []; subtotal_known = True
    with localcontext() as ctx:
        ctx.prec = 60
        for asset, raw in sorted(wallet.items()):
            quantity = exact(raw)
            if asset not in WATCH_ASSETS or quantity < 0:
                raise ValueError('INVALID_PAPER_INVENTORY')
            if quantity == 0:
                continue
            if asset in frame._excluded:
                reasons.append('EXCLUDED'); subtotal_known = False; continue
            if asset == 'ETH':
                total += quantity; modeled += quantity; continue
            action = next((a for a in frame.graph(asset)['actions'] if a['target'] == 'ETH'), None)
            if action is None:
                reasons.append('ETH_EXIT_MARKET_UNAVAILABLE'); subtotal_known = False; continue
            result = estimate_path(source=asset, quantity=quantity, path=(action['leg'],),
                                   frame=frame, slippage_bps=slippage_bps)
            reasons.extend(result['reasons']+result['limitations'])
            if result['modeled_eth'] is not None:
                modeled += result['modeled_eth']
            else:
                subtotal_known = False
            if result['recoverable_eth'] is not None:
                total += result['recoverable_eth']
            try:
                stamps.append(frame.book(action['leg'][0])[2])
            except (ValueError, KeyError):
                pass
        if stamps and max(stamps)-min(stamps) > 12:
            reasons.append('QUOTE_DECISION_SPAN_EXCEEDS_12S')
    return dict(recoverable_eth=None if reasons else total,
                modeled_eth_subtotal=modeled if subtotal_known else None, reasons=sorted(set(reasons)),
                quote_stamps=stamps, actual_profit_eth=None)


def scoreboard(funds, frame, *, real_eth=None, real_eth_at=None, alert_pct=None):
    value = recoverable_inventory(funds.inventory(), frame)
    if funds.has_uncertain():
        value.update(recoverable_eth=None, reasons=sorted(set(value['reasons']+['PARTIAL_OR_UNCERTAIN_FILL'])))
    recovered = value['recoverable_eth']
    with localcontext() as ctx:
        ctx.prec = 60
        delta = None if recovered is None else recovered-funds.initial_eth
        drawdown = None if recovered is None else max(D(0), (1-recovered/funds.initial_eth)*100)
    threshold = None if alert_pct is None else _amount(alert_pct)
    real = None
    if real_eth is not None and real_eth_at is not None and 0 <= frame.at-_time(real_eth_at) <= 120:
        real = exact(real_eth)
        if real < 0:
            raise ValueError('INVALID_REAL_BALANCE')
    return dict(real_account_eth=real, paper_inventory=funds.inventory(),
        paper_label='SIMULATED_ASSUMPTION', after_cost_recoverable_eth=recovered,
        initial_hold_eth=funds.initial_eth, net_vs_hold_eth=delta, drawdown_pct=drawdown,
        alert='UNKNOWN' if drawdown is None else 'REVIEW_ONLY' if threshold is not None and drawdown >= threshold else 'NONE',
        forced_liquidation=False, verified_fills=0, realized_earnings='NOT_ESTABLISHED', reasons=value['reasons'])


class ForwardStudy:
    """Bounded pre-registered conditional branches, fixed horizon; no best-exit search.

    These independent comparisons never credit ResearchFunds. A source position
    must already exist there through an explicit assumption. All results remain
    conditional, and even a favorable outcome cannot demonstrate predictive edge.
    """
    def __init__(self):
        self._cases = {}

    def freeze(self, reference, *, funds, leg, quantity, frame, horizon_s, signal,
               exit_condition, fill_state, slippage_bps=D(15)):
        if (reference in self._cases or len(self._cases) >= MAX_CASES or
                type(horizon_s) is not int or not 1 <= horizon_s <= 259200 or
                fill_state not in ('SIMULATED_ASSUMPTION', 'NO_FILL', 'PARTIAL_OR_UNCERTAIN_FILL', 'UNVERIFIED')):
            raise ValueError('INVALID_FROZEN_HYPOTHESIS')
        quantity = _amount(quantity)
        if quantity > funds.available(leg[2]):
            raise ValueError('PAPER_FUNDS_EXHAUSTED_OR_RESERVED')
        entry = estimate_path(source=leg[2], quantity=quantity, path=(leg,), frame=frame,
                              slippage_bps=slippage_bps)
        if entry['state'] == 'UNKNOWN':
            raise ValueError(entry['reasons'][0])
        hold = {leg[2]: quantity}
        initial = recoverable_inventory(hold, frame, slippage_bps=slippage_bps)
        self._cases[reference] = dict(at=frame.at, horizon_at=frame.at+horizon_s,
            signal=deepcopy(signal), exit_condition=deepcopy(exit_condition), confidence='UNVALIDATED',
            frame=deepcopy(frame), entry=deepcopy(entry), hold=hold, fill_state=fill_state,
            slippage_bps=exact(slippage_bps), initial_eth=initial['recoverable_eth'],
            state='WAITING', observations=0, last_at=frame.at, adverse_vs_hold_eth=None,
            last_value_eth=None, outcome=None)
        return self.case(reference)

    def case(self, reference):
        return deepcopy(self._cases[reference])

    def observe(self, reference, frame):
        case = self._cases[reference]
        if case['state'] != 'WAITING' or frame.at <= case['last_at']:
            return self.case(reference)
        case['last_at'] = frame.at
        case['last_frame'] = deepcopy(frame)
        # First observation at/after horizon is final. Never select a later best price.
        if frame.at > case['horizon_at']+30:
            case.update(state='MISSED_HORIZON', outcome=None)
            return self.case(reference)
        hold = recoverable_inventory(case['hold'], frame, slippage_bps=case['slippage_bps'])
        switched = recoverable_inventory(case['entry']['inventory'], frame,
                                        slippage_bps=case['slippage_bps'])
        stamps = hold['quote_stamps']+switched['quote_stamps']
        coherent = not stamps or max(stamps)-min(stamps) <= 12
        hv, sv = hold['recoverable_eth'], switched['recoverable_eth']
        complete = coherent and hv is not None and sv is not None and not case['entry']['limitations']
        case['observations'] += 1
        case['last_quality_reasons'] = sorted(set(hold['reasons']+switched['reasons']+
            case['entry']['limitations']+([] if coherent else ['QUOTE_DECISION_SPAN_EXCEEDS_12S'])))
        difference = None
        if complete:
            with localcontext() as ctx:
                ctx.prec = 60
                difference = sv-hv
            old = case['adverse_vs_hold_eth']
            case['adverse_vs_hold_eth'] = min(D(0), difference if old is None else min(old, difference))
        assumed = case['fill_state'] == 'SIMULATED_ASSUMPTION'
        case['last_value_eth'] = sv if complete and assumed else hv if complete and case['fill_state'] == 'NO_FILL' else None
        if frame.at >= case['horizon_at']:
            case['state'] = 'CONDITIONAL_OUTCOME' if complete and case['fill_state'] in ('SIMULATED_ASSUMPTION', 'NO_FILL') else 'UNKNOWN_AT_HORIZON'
            case['outcome'] = dict(
                hold_eth=hv if coherent else None, rotation_eth=sv if complete and assumed else None,
                relative_eth=difference if complete and assumed else D(0) if complete and case['fill_state'] == 'NO_FILL' else None,
                forgone_conditional_eth=difference if complete and case['fill_state'] == 'NO_FILL' else None,
                fill_state=case['fill_state'], observation_at=frame.at,
                reasons=list(case['last_quality_reasons']), actual_profit_eth=None)
        return self.case(reference)

    def summary(self):
        cases = list(self._cases.values())
        outcomes = [c['outcome']['relative_eth'] for c in cases if c['outcome'] and c['outcome']['relative_eth'] is not None]
        return dict(registered=len(cases), waiting=sum(c['state'] == 'WAITING' for c in cases),
            favorable=sum(x > 0 for x in outcomes), adverse=sum(x < 0 for x in outcomes),
            no_fill=sum(c['fill_state'] == 'NO_FILL' for c in cases),
            unknown=sum(c['state'] in ('UNKNOWN_AT_HORIZON', 'MISSED_HORIZON') or
                c['fill_state'] in ('PARTIAL_OR_UNCERTAIN_FILL', 'UNVERIFIED') for c in cases),
            underwater_open=sum(c['last_value_eth'] is not None and c['initial_eth'] is not None and
                c['last_value_eth'] < c['initial_eth'] for c in cases),
            edge='NO_DEMONSTRATED_EDGE', decision='HOLD', verified_fills=0)


def observation_summary(frame, *, funding_ok):
    """App hook: topology/quality only, using this pass's books; no funded branches."""
    graph = frame.graph('ETH'); rows = []
    for action in graph['actions'][1:]:
        reason = 'EXPLICIT_HYPOTHETICAL_FILL_REQUIRED'
        try:
            frame.book(action['leg'][0]); frame.rates('TAKER')
        except (ValueError, TypeError, ArithmeticError) as exc:
            reason = str(exc) if str(exc) in PUBLIC_REASONS else 'UNKNOWN'
        if not funding_ok:
            reason = 'WORKING_ETH_UNAVAILABLE'
        rows.append(dict(pair=action['leg'][0], source='ETH', target=action['target'], reason=reason))
    return dict(state='CONDITIONAL_RESEARCH_ONLY', edge='NO_DEMONSTRATED_EDGE', decision='HOLD',
        candidates=rows, truncated=graph['truncated'], synchronized=False,
        recoverable='UNKNOWN', paper_positions=0, verified_fills=0)


PUBLIC_REASONS = {'EXPLICIT_HYPOTHETICAL_FILL_REQUIRED', 'WORKING_ETH_UNAVAILABLE',
    'QUOTE_NOT_RETURNED', 'QUOTE_STALE', 'QUOTE_WIDE', 'QUOTE_INVALID', 'QUOTE_FUTURE',
    'ACCOUNT_FEE_TIER_UNAVAILABLE', 'FEE_RATE_UNSUPPORTED_NO_REBATE_ASSUMPTION',
    'QUOTE_PRICE_INCREMENT_INVALID', 'UNKNOWN'}


def public_summary(value):
    """Strict quantity-free projection shared by diagnostics and local monitor."""
    value = value if isinstance(value, dict) else {}
    rows = []
    candidates = value.get('candidates', ())
    for row in (candidates[:4] if isinstance(candidates, (list, tuple)) else ()):
        if not isinstance(row, dict) or row.get('pair') not in WATCH_PAIRS:
            continue
        target = row.get('target')
        if row.get('source') != 'ETH' or target not in WATCH_ASSETS[1:]:
            continue
        if row['pair'] != ('ETH-BTC' if target == 'BTC' else target+'-ETH'):
            continue
        reason = row.get('reason')
        rows.append(dict(pair=row['pair'], source='ETH', target=target,
            reason=reason if isinstance(reason, str) and reason in PUBLIC_REASONS else 'UNKNOWN'))
    return dict(state='CONDITIONAL_RESEARCH_ONLY' if value.get('state') == 'CONDITIONAL_RESEARCH_ONLY' else 'UNOBSERVED',
        edge='NO_DEMONSTRATED_EDGE', decision='HOLD', recoverable='UNKNOWN',
        candidates=rows, truncated=value.get('truncated') is True, synchronized=False,
        paper_positions=0, verified_fills=0)


def validate_public(value):
    """Reject extra fields at every level, including otherwise redacted files."""
    keys = {'state','edge','decision','recoverable','candidates','truncated','synchronized','paper_positions','verified_fills'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('INVALID_ADAPTIVE_SCHEMA')
    if (type(value['truncated']) is not bool or type(value['synchronized']) is not bool
            or type(value['paper_positions']) is not int or type(value['verified_fills']) is not int
            or not isinstance(value['candidates'], list) or len(value['candidates']) > 4):
        raise ValueError('INVALID_ADAPTIVE_TYPES')
    for row in value['candidates']:
        if not isinstance(row, dict) or set(row) != {'pair','source','target','reason'}:
            raise ValueError('INVALID_ADAPTIVE_CANDIDATE')
    if value != public_summary(value):
        raise ValueError('INVALID_ADAPTIVE_VALUES')
    return value
