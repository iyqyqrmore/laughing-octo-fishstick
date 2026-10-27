"""v60.3 single-pipeline research-data audit; read-only and redacted.

One authoritative REST bid/ask store supplies signals and two-way outcomes.
Other caches retain distinct roles: USD cross-asset outcomes, actual fee
observations, and historical source-compatible signal labels. We neither copy,
repair, migrate, delete nor attach these DBs as part of this audit.
"""
from __future__ import annotations
from pathlib import Path
from contextlib import closing
import sqlite3

# Compatibility filenames are intentional: renaming would orphan prior history.
STORE_ROLES=(
    ('market','research_data/CoinCat_Forward_Market.sqlite3',
        {'market_quotes':('pair','at_utc'),
         'catalog_discovery_latest':('pair',),
         'research_history_hourly':('pair','at_utc'),
         'v607_strategy_trials':('strategy','pair','decision_bucket'),
         'v608_strategy_horizons':('strategy','pair','decision_bucket','horizon_s'),
         'directional_trials':('pair','observed_at')}),
    ('relative_usd','research_data/CoinCat_Public_Relative_USD_v502.sqlite3',
         {'public_marks':('bucket','asset')}),
    ('fee_evidence','research_data/CoinCat_Fee_Evidence_v502.sqlite3',
         {'account_fee_tier':(), 'fee_pair_evidence':()}),
    ('historic_buy_labels','CoinCat_Live_Orders.sqlite3',
         {'forward_signals':('pair','at_utc')}),
)

def audit(root):
    """Query existing SQLite files ONLY in mode=ro. Missing is NOT zero rows."""
    base=Path(root)
    result={'stores':{},'issues':[],'status':'PASS','shared_quote_source':'market.market_quotes',
            'active_rotation_planners':1,'automatic_exchange_submissions':False}
    for role,relative,tables in STORE_ROLES:
        path=base/relative
        row={'present':path.is_file(),'healthy':False,'tables':{},'distinct_purpose':role}
        result['stores'][role]=row
        if not path.is_file():
            result['issues'].append(role+':MISSING');continue
        try:
            uri=path.resolve().as_uri()+'?mode=ro'
            with closing(sqlite3.connect(uri,uri=True,timeout=2)) as db:
                db.execute('PRAGMA query_only=ON')
                health=db.execute('PRAGMA quick_check(1)').fetchone()
                row['healthy']=bool(health and health[0]=='ok')
                if not row['healthy']:
                    result['issues'].append(role+':SQLITE_CHECK_FAILED')
                    continue
                names={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table,keys in tables.items():
                    if table not in names:
                        # New additive derived evidence tables are created when
                        # their optional study is first initialized. A fresh
                        # fixture without strategy research is not corrupt.
                        optional=table in ('v607_strategy_trials','v608_strategy_horizons')
                        row['tables'][table]={'state':'NOT_CREATED_YET' if optional else 'MISSING'}
                        if not optional:result['issues'].append(role+':'+table+':MISSING')
                        continue
                    count=int(db.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0])
                    # All listed time-series tables have primary/unique keys.
                    # Report whether the key actually holds, not guessed counts.
                    duplicate=False
                    if keys:
                        key_sql=','.join('"'+k+'"' for k in keys)
                        duplicate=bool(db.execute('SELECT 1 FROM "'+table+'" GROUP BY '+key_sql+
                            ' HAVING COUNT(*)>1 LIMIT 1').fetchone())
                        if duplicate:result['issues'].append(role+':'+table+':DUPLICATE_KEYS')
                    row['tables'][table]={'state':'OK' if not duplicate else 'DUPLICATES',
                                          'rows':count,'duplicate_keys':duplicate}
        except (sqlite3.Error,OSError,ValueError):
            result['issues'].append(role+':READ_ERROR')
    result['status']='PASS' if not result['issues'] else 'REVIEW'
    return result

def report(root):
    r=audit(root)
    lines=['AI LAB DATAFLOW AND RESEARCH DATABASE AUDIT — READ ONLY',
      'Audit status: '+r['status']+' (research-store availability/integrity, NOT trading readiness)',
      'ACTIVE PIPELINE: Coinbase enrolled portfolio (private ledger) -> shared USD marks -> '+
       'ONE AI Lab spot-market scan -> ONE unified rotation planner -> Auto Trader / SHADOW -> P&L and combined report',
      'AUTHORITATIVE REST bid/ask database: market (deep market_quotes + latest-only catalog_discovery_latest); recent_bid_ask merges by pair/most recent timestamp; no competing research-price database',
      'Market discovery uses latest-only observations, not artificial forward-history samples.',
      'Distinct labels: forward_signals=BUY-gated trials; directional_trials=BUY and SELL/rebuy outcomes; '+
       'public_marks=asset USD HOLD/SWITCH windows. These are NOT duplicate fills, and must NOT be combined as independent labels.',
      'Fee tier/pair evidence stored separately from market research; GPU files are optional observe-only models; '+
       'WebSocket trade tickers are in-memory, NOT a second bid/ask source.',
      'Original historical database filenames retained; new v608 horizon rows are additive in the SAME market DB, not a second feed.',
      'Existing financial ledger rows are not touched by this audit; NO Coinbase GET/POST, no ARMs, no live orders.']
    for role,row in r['stores'].items():
        lines.append('STORE '+role+': '+('SQLITE CHECK PASS' if row['healthy'] else 'UNAVAILABLE/NOT VERIFIED'))
        for name,part in row['tables'].items():
            lines.append('  '+name+': '+part['state']+
                         ('; rows='+str(part['rows'])+'; duplicate logical keys='+str(part['duplicate_keys'])
                          if 'rows' in part else ''))
    if r['issues']:
        lines.append('CAUTION: '+', '.join(r['issues'])+'; do not treat missing research evidence as zero trades.')
    lines.append('No duplication detected in checked logical keys is NOT a claim that all research methods are independent or predictive.')
    return '\n'.join(lines)
