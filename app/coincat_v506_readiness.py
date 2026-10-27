"""v50.6 complete-report evidence for capital, SDK GET and FIFO journal.

Reports are local, sanitized, fail-closed. No runtime SDK call or ledger write.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import sqlite3
from coincat_v506_capital import capital_rehearsal
from coincat_v506_coinbase_evidence import evidence_rehearsal
from coincat_v506_reconciliation import integrated_12_order_rehearsal

def _live_db_status(db_path):
    path=Path(db_path)
    if not path.is_file():return 'NOT VERIFIED: live source ledger not found'
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            versions=('unified_v501_wallets','unified_v501_lots','unified_v502_intents')
            exists=[name for name in versions if name in tables]
        if exists:
            return ('UNVERIFIED: source contains '+str(len(exists))+'/'+str(len(versions))+
                    ' unified table names; not evidence of production migration')
        return 'BLOCKED: canonical production ledger lacks unified FIFO + intent journal integration'
    except (sqlite3.Error,OSError):return 'NOT VERIFIED: cannot read canonical financial ledger'

def report(app=None):
    lines=['CoinCat v50.6R — CAPITAL RESERVE / REAL SDK EVIDENCE / ATOMIC FIFO RECOVERY',
      'ONE DIAGNOSTIC SECTION; NO CREDENTIALS / NETWORK / REAL ORDER / LEDGER WRITE.',
      'Capital sizing is an advisory only, NOT proof of custody, liquid reserves or permission to trade.',
      'Full available enrolled balance may be considered for RESEARCH when manual limits and true liquidity allow.',
      'Quarterly baseline ratchets require explicit operator confirmation; AI cannot raise a loss floor or free protected funds.',
      'A doubled trading stake is not evidence of realized, withdrawable winnings.',
      '0.55 USD projected complete-route advantage is a research preference, distinct from the $0.55 ordinary SELL profit-taking threshold; neither guarantees profit.']
    try:
        a=capital_rehearsal()
        lines.append('[PASS / FAKE] Portfolio doubling, reserved original stake, quarter label and verified spendable sizing: '+str(len(a))+' checks')
    except Exception as exc:lines.append('[BLOCKED] Capital scenario exercise: '+type(exc).__name__)
    try:
        e=evidence_rehearsal()
        lines.append(f'[PASS / FAKE] SDK read-only GET contract: {e["mock_pages"]} pages, {e["mock_fills"]} fills; no POST.')
    except Exception as exc:lines.append('[BLOCKED] SDK mock contract: '+type(exc).__name__)
    try:
        x=integrated_12_order_rehearsal()
        lines.append('[PASS / FAKE] Atomic intent + FIFO: '+str(x['fake_orders'])+
           ' orders, '+str(x['fake_split_fills'])+' split fills, '+str(x['fee_quote_assets'])+' quote assets')
        lines.append('[PASS / FAKE] Reopen/uncertain-order recovery '+str(x['recovered_after_restart'])+
           ', double-POST claim refusals '+str(x['duplicate_post_claim_refusals'])+
           ', duplicate settlement refusals '+str(x['double_settlement_refusals'])+
           ', injected transaction rollback '+str(x['crash_rollbacks']))
    except Exception as exc:lines.append('[BLOCKED] Unified fake-ledger integration: '+type(exc).__name__)
    if app is not None:
        lines.append('Canonical source ledger migration: '+_live_db_status(app.ledger.path))
    lines += ['Real Coinbase order+fill GET against authenticated account: NOT TESTED BY EXPORT',
       'Complete pagination/fill fee currency and fill-time USD marks: NOT VERIFIED AGAINST LIVE SDK',
       'Exchange POST & canonical ledger journal: NOT CONNECTED; automatic LIVE execution DISABLED',
       'Independent portfolio-wide loss floor: NOT CERTIFIED',
       '12 real orders with automated execution: NOT APPROVED',
       'Packaged application: offline_tests/ and test assets should remain source-only; not deliberately added to EXE.',
       'END V50.6R CAPITAL + RECOVERY AUDIT']
    return '\n'.join(lines)+'\n'
