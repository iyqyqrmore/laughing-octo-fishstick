"""Read-only Coinbase portfolio → AI Lab → Auto Trader → P&L evidence map.

No imports of the live SDK or order submission. Never modifies a trade setting,
never assumes research coverage equals forecast skill or verified execution.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import sqlite3,time
from coincat_v505_historical_gpu import saved_warmup_summary

def verified_closed_usd_feedback(path):
    """Count only past USD-quoted SELL fills with terminal Coinbase/local order state.

    Legacy performance is not tax P&L, nor an independently reconciled multi-quote
    production fill. No amount, holding, symbol, order ID or tax basis exported.
    """
    path=Path(path)
    result={'status':'UNAVAILABLE','wins':0,'losses':0,'unknown':0,
            'neural_training_authorized':False}
    if not path.is_file():return result
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            rows=db.execute('''SELECT f.pair,f.performance_realized_quote,f.net_realized_quote
                FROM fills f JOIN orders o ON f.cid=o.cid
                WHERE f.side='SELL' AND o.state='FILLED' ''').fetchall()
        for pair,performance,net in rows:
            if not isinstance(pair,str) or not pair.endswith('-USD'):
                result['unknown']+=1;continue
            from decimal import Decimal,InvalidOperation
            try:
                n=Decimal(str(performance if performance is not None else net))
                if not n.is_finite():raise InvalidOperation
            except (InvalidOperation,ValueError,TypeError):result['unknown']+=1;continue
            result['wins' if n>0 else 'losses']+=1
        result['status']='LEGACY_LOCAL_FILL_FEEDBACK_ONLY'
    except (sqlite3.Error,OSError):pass
    return result

def snapshot(app,*,wall=None,mono=None):
    wall=time.time() if wall is None else float(wall)
    mono=time.monotonic() if mono is None else float(mono)
    catalog=set(getattr(app,'catalog',()) or ())
    last=getattr(app,'last_cycle',None) or {}
    discovery=last.get('discovery') or {}
    ai=(last.get('auto_rotation') or {})
    portfolio=(getattr(app,'_portfolio_coverage',{}) or {})
    try:fee=app.fee_learning.latest_tier(now=int(wall))
    except (AttributeError,TypeError,ValueError,sqlite3.Error):fee={'fresh':False}
    raw_handoffs=last.get('handoffs') or []
    feedback=verified_closed_usd_feedback(app.ledger.path)
    gpu=saved_warmup_summary(Path(getattr(app,'_gpu_folder',None) or
                            getattr(app,'_v505_gpu_folder','') or Path(app.forward.path).parent.parent/'gpu_research'))
    scan_ts=float(getattr(app,'_last_scan_at',0) or 0)
    balance_ts=float(getattr(app,'_last_portfolio_sync_monotonic',0) or 0)
    return {'catalog_pairs':len(catalog),
            'discovered_24h':min(len(catalog),int(discovery.get('coverage') or 0)),
            'seen_research_pairs':len(last.get('reviews') or []),
            'qualifying_buy_ideas':int(last.get('qualified',0) or 0) if 'qualified' in last else len(last.get('signals') or []),
            'handoffs':len(raw_handoffs),
            'hold_switch_routes':len(ai.get('ideas') or []),
            'fee_tier_fresh':bool(fee.get('fresh')),
            'usd_portfolio_complete':bool(portfolio.get('complete')),
            'fresh_scan':bool(scan_ts and mono-scan_ts<=180),
            'fresh_portfolio':bool(balance_ts and mono-balance_ts<=300),
            'confirmed_usd_feedback':feedback,
            'historical_gpu_warmup':gpu,
            'live_order_post_enabled':False,
            'production_multi_quote_settlement_verified':False,
            'prediction_net_usd_validated':False}

def status_line(s):
    feed=s['confirmed_usd_feedback']
    return (f'PORTFOLIO → AI LAB → TRADER → P&L  |  {s["catalog_pairs"]} catalog pairs '
            f'| {s["seen_research_pairs"]} focused | {s["handoffs"]} candidate handoffs '
            f'| closed USD outcomes {feed["wins"]+feed["losses"]} '
            f'| {"fresh" if s["fee_tier_fresh"] else "WAIT"} fees '
            '| LIVE POST BLOCKED')

def report(app):
    s=snapshot(app)
    feed=s['confirmed_usd_feedback'];warm=s['historical_gpu_warmup']
    lines=['CoinCat v50.5 • SINGLE-SNAPSHOT READ-ONLY COMMUNICATION AUDIT',
           'Catalog markets available to research: '+str(s['catalog_pairs']),
           'Markets observed in last 24h (may be less): '+str(s['discovered_24h']),
           'Focused bid/ask market reviews in last completed cycle: '+str(s['seen_research_pairs']),
           'AI-to-Auto candidate handoffs this cycle: '+str(s['handoffs']),
           'HOLD/SWITCH route comparisons in this cycle: '+str(s['hold_switch_routes']),
           'Coinbase fee-tier evidence: '+('FRESH' if s['fee_tier_fresh'] else 'WAIT'),
           'Independent complete portfolio USD marks: '+str(s['usd_portfolio_complete']),
           'Fresh market/portfolio: '+str(s['fresh_scan'])+'/'+str(s['fresh_portfolio']),
           'Confirmed previous USD-quoted SELL feedback (local ledger only): '+
             f'wins={feed["wins"]}, losses-or-flat={feed["losses"]}, basis/FX unknown={feed["unknown"]}',
           'Confirmed-trade evidence independently validated for multi-quote neural training: NO',
           'Historical candle GPU warmup status: '+str(warm.get('status','NOT_TRAINED')),
           'Historical GPU warmup gross-direction held-out result: '+str(warm.get('better_than_baseline','NOT VERIFIED')),
           'Running EXE PyTorch/CUDA runtime probe: '+str(getattr(app,'_gpu_runtime_info',{}).get('status','NOT PROBED')),
           'Runtime GPU allocation confirmed: '+str(getattr(app,'_gpu_runtime_info',{}).get('cuda',False)),
           'Historical warmup affects live orders or preferred trading budget: NO',
           'Entire portfolio net USD vs frozen HOLD benchmark verified: NO',
           'Independent real Coinbase pair-specific preview/fees: NOT VERIFIED BY THIS BUTTON',
           'Unified multi-quote production FIFO: NOT CERTIFIED',
           'Durable live ambiguous-POST recovery: NOT CERTIFIED',
           'All-spot new order POST: DISABLED (no legacy USD-only bypass)',
           'The displayed handoffs require fresh qualified market signals; zero is valid HOLD.',
           'Local UI refresh is not an authorization for Coinbase order submission.',
           'NO ORDER SUBMISSIONS • END V50.5 COMMUNICATION AUDIT']
    return '\n'.join(lines)+'\n'
