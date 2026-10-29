"""Private-safe, offline diagnostics for the latest shadow rotation research.

No portfolio balances, funding asset names, quantities, API account identifiers,
raw logging, raw order details, or route pairs from actual holdings are exported.
Nothing calls Coinbase or modifies a trading database. A user-selected TXT path
is the only output destination, handled separately by the Tkinter GUI.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import time
from coincat_multicurrency import DEFAULT_SLIPPAGE_BPS
from coincat_version import DISPLAY

_SAFE_MARKET = re.compile(r'[A-Z0-9]{1,18}-[A-Z0-9]{1,18}\Z')
_SAFE_REASON_CATEGORIES = (
    'PRODUCT_RULES_OR_MINIMUMS', 'MISSING_USD_CONVERSION',
    'NO_FRESH_LISTED_ROUTE', 'EXCLUDED_ASSET', 'CAP_SIZE_QUOTE_OR_ROUTE_BLOCK','LIQUIDITY_QUOTE_OR_ROUTE_BLOCK',
)


def _count(value):
    """Bounded nonnegative aggregate; no account numbers or input text."""
    try:
        number = int(value)
        return min(max(number, 0), 1_000_000)
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_timestamp(value):
    """UTC epoch seconds are not aggregate counters; do NOT clamp to 1e6."""
    try:
        stamp=int(value)
        # Validate plausible UTC wall timestamps without disclosing account data.
        return stamp if 946684800 <= stamp <= 4102444800 else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def _state(value):
    return value if value in ('SHADOW ONLY', 'WAIT','MODELED_RESEARCH') else 'UNAVAILABLE'


def _market(value):
    # A target signal is a public market, not an enrolled funding asset.
    return value if isinstance(value, str) and _SAFE_MARKET.fullmatch(value) else 'UNAVAILABLE'


def _usd_change_pct(idea):
    """Mark-to-mark simulated drag %, not an executable gain or a forecast."""
    try:
        before = Decimal(str(idea['initial_wallet_usd_mark']))
        after = Decimal(str(idea['post_route_wallet_usd_mark']))
        if not before.is_finite() or not after.is_finite() or before <= 0:
            return 'unavailable'
        change = ((after-before) / before) * 100
        if not change.is_finite() or abs(change) > Decimal('100000'):
            return 'unavailable'
        return f'{change:+.3f}%'
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return 'unavailable'


def _observed_momentum(idea):
    try:
        value = Decimal(str(idea['observed_momentum_pct']))
        if not value.is_finite() or abs(value)>10000:
            return 'unavailable'
        return f'{value:+.3f}%'
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return 'unavailable'


def shadow_snapshot(cycle, captured_at=None):
    """Minimal, non-private per-cycle summary for bounded RAM-only history."""
    cycle = cycle if isinstance(cycle, dict) else {}
    shadow = cycle.get('auto_rotation') or {}
    if not isinstance(shadow, dict):
        shadow = {}
    raw_blockers=shadow.get('route_blockers') or {}
    blockers={k:_count(raw_blockers.get(k,0)) for k in _SAFE_REASON_CATEGORIES}
    proposals=shadow.get('ideas') or []
    qualified_illustrations=sum(x.get('state')=='SHADOW ONLY' for x in proposals if isinstance(x,dict))
    return dict(
        at=_safe_timestamp(time.time() if captured_at is None else captured_at),
        state=_state(shadow.get('state')),
        proposals=min(qualified_illustrations, 12),
        exploratory=_count(shadow.get('exploratory_shortlist')),
        exploratory_attempts=_count(shadow.get('exploratory_route_attempts')),
        funding_excluded=_count(shadow.get('funding_unpriceable')),
        targets=_count(shadow.get('considered')),
        sources=_count(shadow.get('scanned_sources')),
        attempts=_count(shadow.get('route_attempts')),
        viable=_count(shadow.get('viable_routes')),
        blocked=sum(blockers.values()),
        blockers=blockers,
        signals=min(len(cycle.get('signals') or []), 1000000),
        reviews=min(len(cycle.get('broker_pair_reviews') or []), 1000000),
    )


def _utc(ts):
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (OSError, ValueError, TypeError, OverflowError):
        return 'unavailable'


def make_shadow_report(app, now=None):
    """Render shareable research evidence; NEVER authorizes a real order."""
    now = int(time.time() if now is None else now)
    cycle=getattr(app,'last_cycle',None)
    samples=list(getattr(app,'shadow_snapshots',[]) or [])[-200:]
    totals=getattr(app,'shadow_session_totals',{}) or {}
    armed=bool(getattr(getattr(app,'broker',None),'armed',False))
    lines=[
        f'{DISPLAY} — SHADOW ROTATION DIAGNOSTICS',
        f'Captured {_utc(now)}',
        'OFFLINE REPORT / READ ONLY / NO COINBASE ACCESS / NO ORDER SUBMISSIONS',
        'Privacy: no source funding assets, holding balances, quantities, cost basis, keys, account/order IDs or raw logs.',
        'RESEARCH ONLY: not live order clearance or evidence of trading profitability.',
        *(['PRIMARY V90 IMMEDIATE FUNNEL: '+str((cycle.get('auto_rotation') or {}).get('immediate_summary')),
           'Positive-unverified models remain visible; missing evidence is not an economic loss. Forward labels below are separate advisory/validated research.']
          if isinstance(cycle,dict) and (cycle.get('auto_rotation') or {}).get('primary_policy')=='STRICT_IMMEDIATE_V80' else []),
        '-'*72,
        f'Actual broker armed now: {"YES (do not use this report for arming)" if armed else "NO / DISARMED"}',
        'V60.10 authenticated tradable SPOT pairs, ONE order per modeled route; USD/stablecoin can be a directly held trade asset, never a mandatory bridge.',
        'Existing legacy two-leg research records retained for audit compatibility, not new trade authority.', 
        'Live crypto-to-crypto order submission: BLOCKED',
        'V60.12 decision display: History 0-100% is observed maturity, NOT win probability; Costs is immediate after-cost simulated drag rounded UP 0.1%; S.Ready Y/N is observer handoff, NOT a FIFO fill.',
        'Known-small Coinbase direct BUY prefilter only removes redundant broker review, not market learning.',
        'Direct pair absent from authenticated catalog: no active trading or forward study; refresh/recheck may re-admit later. Missing USD FX: transient mark blocker, not permanent delisting.',

        'Saved SHADOW budget mode: '+str(getattr(app,'_manual_budget_saved',{}).get('mode','MANUAL')),
        'Full Available means fresh, eligible modeled-wallet value; excludes unverified assets; attempted orders still gated.',
        f'Completed shadow scan cycles since this app launch: {_count(totals.get("cycles"))}',
        f'Total shadow qualified-research illustrations (repeated scans): {_count(totals.get("proposals"))}',
        f'Exploratory route illustrations (NOT BUY, session scans): {_count(totals.get("exploratory"))}',
        f'Exploratory route-size checks (session scans): {_count(totals.get("exploratory_attempts"))}',
        f'Scans without SHADOW ONLY state: {_count(totals.get("wait_cycles"))}',
        f'Source/target route checks attempted this app session: {_count(totals.get("attempts"))}',
        f'Blocked route checks this app session: {_count(totals.get("blocked"))}',
        f'Session snapshots retained in RAM: {len(samples)}/200 (lost when app closes)',
        'Totals may repeat the same opportunity across scans; NOT distinct trades or fills.',
    ]
    last_at=getattr(app,'_last_scan_at',0)
    if last_at:
        try:
            seconds=int(max(0,time.monotonic()-last_at))
            lines.append(f'Last completed REST market scan age: {seconds}s')
            if seconds>300:
                lines.append('WARNING: Last shadow screen may be STALE; do not treat as a current opportunity.')
        except (OverflowError, ValueError, TypeError):
            lines.append('Last completed REST market scan age: unavailable')
    else:
        lines.append('Last completed REST market scan: none observed')
    if not cycle:
        lines += [
            'LAST CYCLE: NO COMPLETED SCAN YET — no shadow candidates can be evaluated.',
            'Run an authenticated research scan while DISARMED and export again.',
            '-'*72, 'END OF REPORT', '',
        ]
        return '\n'.join(lines)
    snapshot=shadow_snapshot(cycle, captured_at=now)
    shadow=cycle.get('auto_rotation') or {}
    # Source-first SELL investigations are shown for the EVOLVING SHADOW wallet
    # whenever it is actively modeled, never falsely attributed to the
    # original Coinbase inventory after hypothetical acquisitions.
    modeled=cycle.get('shadow_rotation') or {}
    modeled_active=bool(getattr(getattr(app,'shadow_pilot',None),'armed',False)) and isinstance(modeled,dict)
    sell_observation=(modeled if modeled_active else shadow).get('sell_first') or {}
    lines.extend([
        '', 'LATEST COMPLETED SHADOW SCREEN',
        f'Screen state: {snapshot["state"]}',
        'One-order authenticated spot products: '+str(shadow.get('one_order_eligible_spot_products',0))+
        ' authenticated products, '+str(shadow.get('one_order_routes_evaluated',0))+
        ' cost/size-feasible single-order route checks (not BUY approval)',
        f'Legacy advisory BUY signals (not strict immediate qualification): {snapshot["signals"]}',
        'SELL-FIRST EXIT SCREEN (evolving modeled SHADOW holdings when armed, otherwise current enrolled source inventory):',
        f'  Model wallet funding selected: {modeled_active}',
        f'  Eligible owned/simulated assets checked for independent exit: {_count(sell_observation.get("screened"))}',
        f'  Exit routes satisfying fresh quote/product checks: {_count(sell_observation.get("feasible_exit_routes"))}',
        f'  Exit routes waiting: {_count(sell_observation.get("wait_routes"))}',
        '  SELL-first feasibility is NOT a validated positive USD advantage versus HOLD.',
        f'EXPLORATORY research routes (NOT BUY qualified): {shadow.get("exploratory_shortlist",0)}',
        f'Exploratory route checks: {shadow.get("exploratory_route_attempts",0)}; feasible: {shadow.get("exploratory_viable_routes",0)}',
        f'Candidate destination assets evaluated (max 12): {snapshot["targets"]}',
        f'Enrolled and verified funding sources screened (count only): {snapshot["sources"]}',
        f'Source/target route attempts: {snapshot["attempts"]}',
        f'Routes passing the research-only planner: {snapshot["viable"]}',
        f'Blocked route checks: {snapshot["blocked"]}',
        f'BUY-qualified research illustrations displayed (limited to 12): {snapshot["proposals"]}',
        f'Not-BUY-qualified exploratory ideas displayed: {snapshot["exploratory"]}',
        f'Independent spot broker reviews: {snapshot["reviews"]} (not permission to submit)',
        f'HOLD preferred among evaluated routes: {shadow.get("hold_preferred",0)}',
        f'SWITCH merits further research (not live): {shadow.get("switch_worth_research",0)}',
        f'Relative forward evidence incomplete: {shadow.get("forward_unverified",0)}',
    ])
    for category in _SAFE_REASON_CATEGORIES:
        count=snapshot['blockers'].get(category,0)
        if count:
            lines.append(f'  Route blocker {category}: {count}')
    # Avoid copying the free-form reason string. It can contain operational
    # metadata, raw payloads or user-entered symbols. Explicit safe enums only.
    shadow=cycle.get('auto_rotation') or {}
    ideas=shadow.get('ideas') or []
    if ideas:
        lines.append('')
        lines.append('SHADOW / EXPLORATORY IDEAS — unqualified routes are NOT simulated fills or BUY signals')
        lines.append('Observed momentum is NOT a USD return forecast.')
        lines.append('Immediate wallet mark delta is a simulated percentage, NOT realized profit.')
        # Separately identify proposals with immediate negative wallet marks.
        # Market momentum is not an independently validated future USD edge.
        drag=0
        for idea in ideas[:12]:
            try:
                before=Decimal(str(idea['initial_wallet_usd_mark']))
                after=Decimal(str(idea['post_route_wallet_usd_mark']))
                if before.is_finite() and after.is_finite() and before>0 and after<before:
                    drag+=1
            except (ValueError,KeyError,TypeError,InvalidOperation):pass
        if drag:
            lines.append(f'COST DRAG WARNING: {drag} of {min(len(ideas),12)} shown proposals have negative immediate simulated USD wallet marks; NOT A PROFITABLE TRADE SIGNAL.')
        for idx,idea in enumerate(ideas[:12],1):
            if not isinstance(idea,dict):continue
            route=idea.get('route') or []
            legs=len(route) if isinstance(route,(tuple,list)) else 0
            kind='direct' if legs==1 else 'multi-leg' if legs==2 else 'unknown'
            lines.append(f'  #{idx:02d} trigger={_market(idea.get("trigger_pair"))} '
                         f'route={kind} ({legs} legs) '
                         f'observed_momentum={_observed_momentum(idea)} '
                         f'simulated_immediate_mark_delta={_usd_change_pct(idea)} '
                         f'USD_hold_switch={idea.get("research_decision","UNVERIFIED")} '
                         f'paired_1h_windows={_count(idea.get("evidence_windows",0))} '
                         'forward_USD_edge=NOT_PREDICTIVE | NO_ORDERS')
    else:
        lines.append('No viable shadow route proposals in the latest cycle. This is not evidence of zero opportunities.')
    lines.extend([
        '', 'SESSION TREND (MAX 200 MOST RECENT COMPLETED SCANS)',
    ])
    if samples:
        states=Counter(item['state'] for item in samples)
        lines.append(f'Snapshot window: {_utc(samples[0]["at"])} → {_utc(samples[-1]["at"])}')
        lines.append('Snapshot states: '+', '.join(f'{k}={v}' for k,v in sorted(states.items())))
        for item in samples[-20:]:
            lines.append(f'  {_utc(item["at"])} | state={item["state"]} '
                         f'targets={item["targets"]} attempts={item["attempts"]} '
                         f'viable={item["viable"]} blocked={item["blocked"]} '
                         f'proposals={item["proposals"]} explore={item.get("exploratory",0)}')
    else:
        lines.append('No in-session trend records yet (available after first completed shadow scan).')
    lines += [
        '', 'INTERPRETATION AND LIMITATIONS',
        ('Research cost source: authenticated Coinbase account spot tier when fresh; '
         'NOT a pair-specific preview, real fill, or guarantee of maker execution.'),
        ('Unavailable authenticated tier: shadow routes WAIT instead of using old 1% per-leg fees.'),
        f'Slippage reserve: {DEFAULT_SLIPPAGE_BPS} bps per leg is a research stress assumption, not measured slippage.',
        'Routes are simulations; actual Coinbase previews, independent USD forward advantage, production multi-currency FIFO settlement and crash recovery are still required.',
        'This report cannot reconstruct scans from a previous app process or earlier-version history.',
        'Do not enable cross-crypto live orders based on these numbers.',
        '-'*72, 'END OF REPORT', '',
    ]
    from coincat_v502_microstructure import microstructure_report
    lines.append('')
    lines.append(microstructure_report(app).rstrip())
    return '\n'.join(lines)
