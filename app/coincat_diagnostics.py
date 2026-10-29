"""Shareable READ-ONLY CoinCat v40 diagnostic report; deliberately redacted.

No CDP key, account ID, private key, raw order/fill IDs, account balances,
raw logs, or complete holdings are copied into this report. Writes ONLY to
user-chosen export path, never to a trading database. All SQLite access read-only.
"""
from __future__ import annotations
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import os, platform, sqlite3, sys, time, shutil, subprocess, re
from importlib.metadata import version, PackageNotFoundError
from coincat_storage import storage_health
from coincat_version import DISPLAY
from coincat_portfolio_objective import quote_mix


def _redact(value):
    # Defensive redaction of free-text API error/detail fields; not a substitute
    # for reviewing exports. Never include raw order event/log payloads.
    s=str(value)
    s=re.sub(r'-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----',
             '[REDACTED PRIVATE KEY]',s,flags=re.DOTALL)
    s=re.sub(r'organizations/[^\s/]+/apiKeys/[^\s/]+','[REDACTED CDP KEY]',s)
    s=re.sub(r'[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}',
             '[REDACTED ID]',s)
    s=re.sub(r'(?i)(api[_ -]?key|secret|token|password)\s*[=:]\s*\S+',r'\1=[REDACTED]',s)
    return s[:180]


def _safe_query(path, statement, params=()):
    path = Path(path)
    if not path.exists():return []
    try:
        uri = path.resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=3)) as conn:
            conn.execute('PRAGMA query_only=ON')
            return conn.execute(statement,params).fetchall()
    except (sqlite3.Error, OSError):
        return []


def _scalar(path, sql, params=()):
    data = _safe_query(path, sql, params)
    return data[0][0] if data and data[0][0] is not None else 0


def _hardware_report():
    out=[]
    try:
        import psutil
        ram=psutil.virtual_memory()
        out.append(f'Physical RAM GB: {ram.total/1073741824:.1f} | Available GB: {ram.available/1073741824:.1f}')
    except ImportError:
        out.append('Physical RAM: optional psutil unavailable')
    try:
        out.append('PyTorch installed version: '+version('torch'))
    except PackageNotFoundError:
        out.append('PyTorch: not installed')
    # Query GPU capability without requiring torch/CUDA initialization on the UI thread.
    smi=shutil.which('nvidia-smi')
    if smi:
        try:
            result=subprocess.run([smi,'--query-gpu=name,memory.total,driver_version',
                          '--format=csv,noheader,nounits'],capture_output=True,
                          text=True,timeout=3,check=False)
            if result.returncode==0:
                out.append('GPU / VRAM MiB / driver: '+result.stdout.strip()[:180])
            else:out.append('GPU: NVIDIA diagnostic unavailable')
        except (OSError,subprocess.TimeoutExpired):out.append('GPU: NVIDIA diagnostic timed out')
    else:out.append('GPU: nvidia-smi not on PATH (does not prove CUDA unavailable)')
    return out


def _utc(ts):
    try:return datetime.fromtimestamp(int(ts),timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if ts else 'none'
    except (OverflowError,ValueError,TypeError):return 'invalid'


def make_report(app,kind,now=None):
    """Generate diagnostics with only aggregate, non-credential data.

    Does not trigger Coinbase network calls, live orders, or write to DBs.
    """
    if kind not in ('AI_Lab','Auto_Trader'):raise ValueError('Invalid report kind')
    now = int(time.time() if now is None else now)
    research = app.forward.path
    ledger = app.ledger.path
    lines = [f'{DISPLAY} — {kind.replace("_"," ")} DIAGNOSTICS',
             f'Captured {_utc(now)}',
             'READ ONLY / NO ORDER SUBMISSIONS',
             'Privacy: no API keys, account identifiers, order IDs, complete balances, or raw log entries.',
             'These numbers are NOT proof of profitability or real-time execution accuracy.',
             '-'*72,
             f'Python: {sys.version.split()[0]} | OS: {platform.system()} {platform.release()}',
             f'CPU: {platform.processor() or platform.machine()} | Logical cores: {os.cpu_count()}',
             *_hardware_report(),
             f'Authenticated Coinbase catalog pairs: {len(getattr(app,"catalog",[]))}',
             'ACTIVE V60.10: ALL VERIFIED SPOT QUOTE CURRENCIES • one listed order maximum • NO mandatory conversion bridge',
             f'Authenticated catalog last verified age: {int(time.time()-app.catalog_at) if getattr(app,"catalog_at",0) else "never"}s • >7200s blocks live arming',
             f'AI scan interval: {getattr(app,"loop_secs",0)}s',
             f'Authenticated catalog quote mix: {quote_mix(getattr(app,"catalog",[]))}',
             f'Deep-study focused quote mix: {quote_mix(getattr(app,"_last_research_watch",[]))}',
             f'Real-order arm status: {"ARMED" if getattr(app,"broker",None) and app.broker.armed else "DISARMED"}',
             f'Worker busy: {bool(getattr(app,"worker_busy",False))}',
             f'Last Coinbase portfolio verification age: {int(time.monotonic()-app._last_portfolio_sync_monotonic) if getattr(app,"_last_portfolio_sync_monotonic",0) else "none"}s',
             'Balance refresh may auto-enroll NEW spot-available assets under prior user authorization, with unknown external tax basis; existing lots, excluded coins, and prior approved quantities remain unchanged; shortfall mismatch disarms.',
             f'Last completed REST market scan age: {int(time.monotonic()-app._last_scan_at) if getattr(app,"_last_scan_at",0) else "none"}s',
             f'CoinCat current live preflight summary (cached): {getattr(getattr(app,"v30_readiness_status",None),"get",lambda:"unavailable")()}',
             'Live scope: ALL spot quote currencies are research/review only; no legacy dollar-only live pilot, new Coinbase POST blocked pending production FIFO/recovery.',
             ]
    registry=dict(getattr(getattr(app,'broker',None),'catalog_registry_audit',{}) or {})
    lines.extend([
        'AUTHENTICATED SPOT ELIGIBILITY • listing does not prove account fillability',
        f'Raw paginated products: {registry.get("raw_count","NOT VERIFIED")}; eligible unique: {registry.get("eligible_count","NOT VERIFIED")}; rejected/duplicate: {registry.get("filtered_count","NOT VERIFIED")}',
        'Restricted/rejected reasons (aggregate): '+str(registry.get('reject_reasons',{}))[:130],
        f'Catalog pages complete: {registry.get("complete_pages","UNKNOWN")}; state: {registry.get("status","UNVERIFIED")}',
        'Eligible market quote mix: USD/USDC='+str(registry.get('usd_usdc','?'))+
        ' USDT/DAI='+str(registry.get('usdt_dai','?'))+
        ' other='+str(registry.get('other_quoted','?')),
        'WebSocket broad ticker_batch + heartbeat: observation-only; additional level2/trade-flow not used to authorize fills.',
    ])
    probe=dict(getattr(app,'_depth_probe_result',{}) or {})
    lines.append('Optional asynchronous product-book advisory: '+str(probe.get('state','NOT_OBSERVED'))+
                 ' • max 1 pair per 10min; never used as executable price or a stall on SHADOW scan')
    if probe.get('state')=='READ_ONLY_EVIDENCE':
        top=probe.get('top') or {};depth=probe.get('depth') or {}
        lines.append('Research liquidity sample: pair='+str(probe.get('pair','UNAVAILABLE'))+
                     ' top spread bps='+str(top.get('spread_bps','UNAVAILABLE'))[:22]+
                     ' 10-level depth imbalance='+str(depth.get('imbalance','UNAVAILABLE'))[:24]+
                     ' • DESCRIPTIVE_ONLY, not a verified future predictor or order slippage guarantee')
    # Re-evaluate actual timestamp ages NOW. A Tk status StringVar may remain
    # green if its periodic callback stopped, especially during long runs.
    from coincat_v40_1_safety import live_data_health
    mono=time.monotonic()
    live_health=live_data_health(
        connected=bool(getattr(app,'broker',None)),
        catalog_age_s=time.time()-app.catalog_at if getattr(app,'catalog_at',0) else None,
        portfolio_age_s=mono-app._last_portfolio_sync_monotonic if getattr(app,'_last_portfolio_sync_monotonic',0) else None,
        scan_age_s=mono-app._last_scan_at if getattr(app,'_last_scan_at',0) else None,
        valuation_age_s=time.time()-app._portfolio_quote_at if getattr(app,'_portfolio_quote_at',0) else None,
        poll_age_s=mono-app._last_poll_heartbeat if getattr(app,'_last_poll_heartbeat',0) else None,
        tick_age_s=mono-app._last_tick_heartbeat if getattr(app,'_last_tick_heartbeat',0) else None,
        history_in_progress=getattr(app,'_history_in_progress',False),
        scan_processing=getattr(app,'_scan_processing',False),
        portfolio_sync_running=getattr(app,'_portfolio_sync_running',False))
    lines.append('INDEPENDENT LIVE DATA HEALTH (not cached UI): '+
        ('FRESHNESS PASS • still no crypto-quote live permission' if live_health['ready']
         else 'STALE/BLOCKED • '+'; '.join(live_health['blockers'])))
    lines.append('Background state: history='+str(live_health['history_in_progress'])+
                 ' | scan='+str(live_health['scan_processing'])+
                 ' | portfolio_sync='+str(live_health['portfolio_sync_running']))
    lines.append('Background elapsed seconds: history='+str(int(mono-app._history_started_at) if getattr(app,'_history_in_progress',False) and getattr(app,'_history_started_at',0) else 'none')+
                 ' | market_scan='+str(int(mono-app._scan_started_at) if getattr(app,'_scan_processing',False) and getattr(app,'_scan_started_at',0) else 'none'))
    lines.append('Last UI callback error type: '+
                 str(getattr(app,'_last_ui_callback_error_type',None) or 'none observed'))
    coverage = getattr(app,'_portfolio_coverage',{}) or {}
    missing = coverage.get('missing',{}) or {}
    types = Counter(missing.values())
    lines.extend([
        f'Portfolio USD valuation coverage: {coverage.get("priced_count",0)}/{coverage.get("held_count",0)} liquid currencies; complete: {bool(coverage.get("complete"))}',
        f'Latest authenticated Coinbase portfolio pricing result: {_redact(getattr(app,"_portfolio_quote_error","not fetched"))}',
        f'Portfolio pricing request age: {int(time.time()-app._portfolio_price_at) if getattr(app,"_portfolio_price_at",0) else "never"}s',
        'Unpriced reason categories (asset symbols/amounts not exported): '+(
            ', '.join(f'{k}={v}' for k,v in sorted(types.items())) or 'none'),
        'Portfolio → AI Lab → Auto Trader USD coverage is a shared READ-ONLY observation and ARM preflight; not a market prediction or broker instruction.',
    ])
    try:
        sections=storage_health(app.ledger.path.parent)
        for name,item in sections.items():
            lines.append(f'Active storage {name}: {item["used_mb"]:.3f}/{item["limit_mb"]} MB • ' +
                         ('LIMIT (new orders blocked)' if item['over'] and name in ('ledger','research')
                          else 'warning' if item['warning'] else 'normal'))
    except (OSError,ValueError):
        lines.append('Storage health: unable to measure; review manually')
    if kind == 'AI_Lab':
        lines.append('Research data provenance: ONE canonical REST bid/ask journal, distinct future-outcome, public USD and fee stores; database health in the combined AI LAB RESEARCH DATABASE section.')
        db_bytes = research.stat().st_size if research.exists() else 0
        # Parameterized SQL protects both SQLite quoting and Python 3.11 f-strings.
        history_rows = _scalar(research, 'SELECT COUNT(*) FROM research_history_hourly')
        history_pairs = _scalar(research, 'SELECT COUNT(DISTINCT pair) FROM research_history_hourly')
        live_last_hour = _scalar(research, 'SELECT COUNT(*) FROM market_quotes WHERE at_utc>=?', (now-3600,))
        live_pairs_24h = _scalar(research, 'SELECT COUNT(DISTINCT pair) FROM market_quotes WHERE at_utc>=?', (now-86400,))
        last_live = _scalar(research, 'SELECT MAX(at_utc) FROM market_quotes')
        history_10d = _scalar(research, 'SELECT COUNT(*) FROM research_history_hourly WHERE at_utc>=?', (now-864000,))
        direction_observed = _scalar(research, 'SELECT COUNT(*) FROM directional_trials WHERE state=?', ('OBSERVED',))
        direction_missed = _scalar(research, 'SELECT COUNT(*) FROM directional_trials WHERE state=?', ('MISSED_OFFLINE',))
        buy_observed = _scalar(ledger, 'SELECT COUNT(*) FROM forward_signals WHERE outcome_state=?', ('OBSERVED',))
        buy_missed = _scalar(ledger, 'SELECT COUNT(*) FROM forward_signals WHERE outcome_state=?', ('MISSED_OFFLINE',))
        lines.extend([
            f'Market DB physical size MB: {db_bytes/1048576:.2f}',
            'Research storage quota covers all AI Lab SQLite caches (market, fee, relative USD) including WAL files.',
            f'AI Lab aggregate soft limit MiB: {getattr(app.forward.retention, "max_mb", "?")}',
            f'Historical candle count: {history_rows}',
            f'Historical pair count: {history_pairs}',
            f'Live quote rows in last hour: {live_last_hour}',
            f'Distinct live quote pairs (24h): {live_pairs_24h}',
            f'Last observed live quote: {_utc(last_live)}',
            f'Hourly historical candles (10d): {history_10d}',
            f'Directional verified outcomes: {direction_observed} market intervals • {direction_observed} BUY + {direction_observed} SELL/REBUY labels (correlated, NOT independent observations)',
            f'Directional missed offline: {direction_missed}',
            f'Forward BUY labels evaluated: {buy_observed}',
            f'Forward BUY labels missed offline: {buy_missed}',
            f'Forward readiness coverage: {getattr(app, "research_pct", 0)}% (NOT win probability)',
            f'GPU status in AI Lab: {getattr(getattr(app, "gpu_status", None), "get", lambda: "not provided")()}',
            'GPU model controls orders: NO (observe only)',
        ])
        stream = getattr(app, 'stream', None)
        if stream:
            st = stream.status(now)
            lines.extend([
                f'Public WebSocket status: {"CONNECTED" if st["connected"] else "OFFLINE"}',
                f'Full-catalog stream scope: {st["pairs"]} | Subscription IDs requested (not acked): {st.get("requested",0)} | Seen trade ticks: {st.get("observed",0)} | Fresh trade tickers: {st["fresh"]}',
                f'Ticker events: {st["ticks"]} | Last event age: {st["last_message_age"]}s',
                f'Changed-trade fresh within 15s: {st.get("fresh",0)} | unique observed: {st.get("observed_unique_products",0)} | subscription requests are not acknowledgments',
                f'Heartbeat age: {st["heartbeat_age"]}s',
                f'WebSocket status detail: {_redact(st["error"]) if st["error"] else "none"}',
                'Public ticker prices are informational; order previews still require current authenticated REST bid/ask.',
            ])
        cycle = getattr(app, 'last_cycle', None) or {}
        if cycle:
            quote_counts={'USD/USDC':0,'USDT/DAI':0,'crypto/other':0}
            for item in cycle.get('reviews',[]):
                pair=str(item.get('pair',''))
                if '-' not in pair:continue
                quote=pair.rsplit('-',1)[1]
                key=('USD/USDC' if quote in ('USD','USDC') else
                     'USDT/DAI' if quote in ('USDT','DAI') else 'crypto/other')
                quote_counts[key]+=1
            lines.append('Last deep-study REAL quote mix: '+', '.join(f'{key}={n}' for key,n in quote_counts.items()))
            lines.extend([
                f'Last completed scan valid bid/ask pairs: {cycle.get("quotes", 0)}',
                f'Last scan quote errors: {cycle.get("failures", 0)}',
                f'Legacy advisory BUY candidates (not strict immediate qualification): {len(cycle.get("signals", []))}',
                f'Live sell evaluations: {len(cycle.get("sell_reviews", []))}',
                f'AI-to-trader handoffs: {len(cycle.get("handoffs", []))}',
                'AI BUY candidate -> broker order requires independent arming, authenticated fresh bid/ask, fee/risk checks, and confirmed fills.',
            ])
            # Aggregate the read-only execution handoff outcomes. Preview
            # validation is not execution permission. Redact all free text.
            pair_reviews=cycle.get('broker_pair_reviews') or []
            passed=sum(bool(r.get('candidate')) for r in pair_reviews)
            lines.append(f'Unified spot read-only currency-aware intents: {passed}/{len(pair_reviews)} candidates pass • no orders')
            for r in pair_reviews[:12]:
                lines.append(f'  candidate {r.get("pair","?")}: {r.get("state","?")} • {_redact(r.get("reason", ""))}')
            lines.append('Unified broker settlement ready: NO • historical dollar-quote ledger is reconciliation-only; all-spot LIVE POST disabled')
            # Coinbase Preview endpoints are authenticated but DO NOT create orders.
            # Fees require explicit currency, never assume BTC=USD or USDC=USD.
            previews=cycle.get('cross_spot_previews') or []
            lines.append(f'Bounded live Coinbase CROSS-QUOTE PREVIEW (NO POST): {len(previews)} checked')
            for p in previews[:2]:
                lines.append(f'  preview {p.get("pair","?")}: {p.get("state","?")} • {_redact(p.get("reason",""))}')
            lines.append('Crypto-quote live settlement: BLOCKED pending durable verified USD FIFO tax/performance ledger and safe recovery')
            exits=cycle.get('full_exit_reviews') or []
            live_marks=sum(r.get('state')=='RESEARCH ONLY' for r in exits)
            lines.append(f'Whole-holding read-only USD-marked exits: {live_marks}/{len(exits)} • separate from live SELL eligibility')
            shadow=cycle.get('auto_rotation') or {}
            lines.append(f'Shadow rotation proposals: {len(shadow.get("ideas") or [])} • NO CROSS-QUOTE ORDERS')
            lines.append('V60.10 ACTIVE ROUTE POLICY: '+str(shadow.get('route_policy','UNKNOWN'))+
                ' • authenticated one-order spot products='+str(shadow.get('one_order_eligible_spot_products',0))+
                ' • successful one-order research checks='+str(shadow.get('one_order_routes_evaluated',0))+
                ' • USD P&L marks independent of route; no mandatory intermediary trade')
            lines.append('AUTO-ENROLLMENT POLICY: new verified AVAILABLE spot assets, preserving existing exclusions; original external acquisition basis UNKNOWN; no POST')

            lines.append('ONE UNIFIED ROTATION PLANNER: multi-funding research baskets=' +
                str(shadow.get('multi_source_research',0)) +
                '; portfolio-valued enrolled funding assets=' + str(shadow.get('funding_assets',0)) +
                '; no live order or jointly validated basket implied')
            floors=shadow.get('threshold_research') or {}
            eligibility=cycle.get('research_funding_eligibility') or {}
            excludes=eligibility.get('reasons') or {}
            lines.append('RESEARCH FUNDING CHAIN: enrolled rows checked='+str(eligibility.get('considered',0))+
                '; strict-price eligible='+str(eligibility.get('eligible',0))+
                '; excluded from route research='+str(eligibility.get('excluded',0))+
                '; PARTIAL_OK='+str(bool(eligibility.get('partial'))) +
                '; specific source assets and amounts REDACTED')
            lines.append('Funding eligibility rejection counts: '+
                ', '.join(str(k)+'='+str(excludes.get(k,0)) for k in
                  ('STALE_OR_WIDE_USD_BOOK','INVALID_QUANTITY','NO_VERIFIED_AVAILABLE_BALANCE','ZERO_QUANTITY')))
            explorer=cycle.get('exploratory_market_research') or {}
            lines.append('AI MARKET EXPLORATION (NOT BUY): spread/momentum usable markets='+str(explorer.get('eligible_markets',0))+
                '; ranked targets='+str(explorer.get('ranked',0))+
                '; no predictor, no broker permissions')
            lines.append('ONE-PLANNER PREQUALIFICATION: explored targets='+str(shadow.get('exploratory_targets',0))+
                '; independently priced route-size checks='+str(shadow.get('exploratory_route_attempts',0))+
                '; feasible cost-estimated research routes='+str(shadow.get('exploratory_viable_routes',0))+
                '; non-actionable exploratory ideas='+str(shadow.get('exploratory_shortlist',0))+
                '; modeled SHADOW FIFO requires separately qualified forward evidence')
            lines.append('Legacy validated-track threshold sweep (not Experimental immediate policy): '+str(floors.get('range_usd','0.10-100.00'))+
                ' at $0.01 resolution; status='+str(floors.get('state','NOT VERIFIED'))+
                '; genuinely held-out qualified predictions='+str(floors.get('qualified_predictions',0))+
                '; no automatic action permission')
            lines.append('Validated-track manual floor (not Experimental immediate policy): '+str(getattr(getattr(app,'switch_floor_mode',None),'get',lambda:'UNAVAILABLE')())+
                '; floor USD='+str(getattr(app,'switch_minimum_usd','UNAVAILABLE'))+
                '; saved separately from financial ledger')
            funding=cycle.get('funding_size_observations') or {}
            lines.append('Independent dynamic funding-size observations: '+str(funding.get('size_scenarios',0)) +
                ' possible sizes across '+str(funding.get('source_assets',0))+' verified enrolled assets; '+
                str(funding.get('at_least_100_usd',0))+' examples $100 or more. '+
                'Research only; no BUY qualification or order.')
            for r in (cycle.get('reviews') or [])[:30]:
                lines.append(f'  {r.get("pair", "?")}: {r.get("action", "?")} • quotes={r.get("count", 0)} • {_redact(r.get("reason", ""))}')
    else:
        states = _safe_query(ledger, 'SELECT side,state,COUNT(*) FROM orders GROUP BY side,state ORDER BY side,state')
        lines.append('Coinbase submission/order states (counts only):')
        for side, state, n in states:
            lines.append(f'  {side} {state}: {n}')
        # Count ALL nonterminal statuses, including PARTIALLY_FILLED and
        # RECONCILE_ERROR; showing zero here would mislead a pilot decision.
        pending = _scalar(ledger, "SELECT COUNT(*) FROM orders WHERE state NOT IN ('FILLED','COMPLETED','REJECTED','CANCELLED','EXPIRED','FAILED')")
        buy_fills = _scalar(ledger, 'SELECT COUNT(*) FROM fills WHERE side=?', ('BUY',))
        sell_fills = _scalar(ledger, 'SELECT COUNT(*) FROM fills WHERE side=?', ('SELL',))
        signal_audits = _scalar(ledger, 'SELECT COUNT(*) FROM signal_audit')
        enrolled = _scalar(ledger, 'SELECT COUNT(*) FROM enrollment WHERE enabled=1')
        unknown_basis = _scalar(ledger, "SELECT COUNT(*) FROM enrollment WHERE enabled=1 AND (basis_unit_quote IS NULL OR basis_source IN ('LEGACY','USER_REPORTED_ORIGINAL','MIXED_LOTS'))")
        snapshots = _scalar(ledger, 'SELECT COUNT(*) FROM enrollment WHERE enabled=1 AND snapshot_unit_usd IS NOT NULL')
        total_buys = _scalar(ledger, 'SELECT ROUND(SUM(CAST(base_qty AS REAL)*CAST(price AS REAL)),4) FROM fills WHERE side=?', ('BUY',))
        total_fees = _scalar(ledger, 'SELECT ROUND(SUM(CAST(fee_quote AS REAL)),4) FROM fills')
        total_performance = _scalar(ledger, 'SELECT ROUND(SUM(CAST(performance_realized_quote AS REAL)),4) FROM fills WHERE side=?', ('SELL',))
        win_sells = _scalar(ledger, 'SELECT COUNT(*) FROM fills WHERE side=? AND CAST(performance_realized_quote AS REAL)>0', ('SELL',))
        loss_sells = _scalar(ledger, 'SELECT COUNT(*) FROM fills WHERE side=? AND performance_realized_quote IS NOT NULL AND CAST(performance_realized_quote AS REAL)<=0', ('SELL',))
        lines.extend([
            f'Potentially unresolved orders: {pending}',
            'Pending order/fill check: ~5s when idle; independent of 120s AI scan',
            f'Pending fill monitor paused on uncertainty: {bool(getattr(app, "_fill_sync_faulted", False))}',
            f'Last fill monitor status: {_redact(getattr(app, "fill_sync_status").get()) if getattr(app, "fill_sync_status", None) is not None else "not available"}',
            f'Confirmed BUY fills: {buy_fills}',
            'Externally executed Coinbase trades are not assumed to be CoinCat fills or tax lots.',
            f'Confirmed SELL fills: {sell_fills}',
            f'AI signal audit rows: {signal_audits}',
            f'Enrolled asset count: {enrolled}',
            f'Unknown/unverified original tax-basis count: {unknown_basis}',
            f'Approved market snapshot count: {snapshots}',
            f'Capacity approved stage: {getattr(app, "capacity_stage", 0)}',
            f'Aggregate confirmed buy amount before fees USD: {total_buys}',
            f'Aggregate confirmed fill fees in quote units: {total_fees}',
            f'Aggregate realized bot performance USD: {total_performance}',
            f'Profit-taking winning SELL fills: {win_sells}',
            f'Losing/breakeven SELL fills: {loss_sells}',
            'See Coinbase for real-order reconciliation; this report does not unlock pending orders.',
        ])
        cycle = getattr(app, 'last_cycle', None) or {}
        if cycle:
            handoffs = cycle.get('handoffs') or []
            lines.append(f'Last cycle AI-to-trader handoff states: {dict(Counter(x.get("state", "?") for x in handoffs))}')
            for h in handoffs[:25]:
                lines.append(f'  {h.get("pair", "?")}: {h.get("state", "?")} • {_redact(h.get("reason", ""))}')
        lines.append('Live software-managed stops depend on app/network uptime; not exchange-native stops.')
    lines.extend(['-'*72,'END OF REPORT',''])
    return '\n'.join(lines)
