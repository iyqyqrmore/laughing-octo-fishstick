"""Forward observed bid/ask research and fill-feedback live policy.
No historical backfills and no simulated order ledger.
"""
from __future__ import annotations
from decimal import Decimal
import time
from coincat_live import sql,dec

class LiveSignalLab:
    def __init__(self,forward_store,ledger,fee_learning=None):
        self.store=forward_store;self.ledger=ledger;self.fee_learning=fee_learning
        with sql(ledger.path) as c:
            c.executescript('''
             CREATE TABLE IF NOT EXISTS forward_signals(id INTEGER PRIMARY KEY, pair TEXT NOT NULL,
               at_utc INTEGER NOT NULL,entry_ask TEXT NOT NULL,fee_rate TEXT NOT NULL,
               evaluate_after INTEGER NOT NULL, exit_bid TEXT,observed_return_pct TEXT,
               UNIQUE(pair,at_utc));
             CREATE INDEX IF NOT EXISTS idx_forward_pending ON forward_signals(evaluate_after);
            ''')
            cols={r[1] for r in c.execute('PRAGMA table_info(forward_signals)')}
            for field in ('momentum_pct','spread_bps','sample_count','outcome_state','fee_evidence_source'):
                if field not in cols:c.execute(f'ALTER TABLE forward_signals ADD COLUMN {field} TEXT')
    def observations(self,pair,now=None):
        now=int(now or time.time())
        with self.store._db() as c:
            rows=c.execute('SELECT at_utc,bid,ask FROM market_quotes WHERE pair=? AND at_utc>=? ORDER BY at_utc LIMIT 80',(pair,now-3600)).fetchall()
        return [(int(t),dec(b),dec(a)) for t,b,a in rows]
    def signal(self,pair,now=None):
        now=int(now or time.time());rows=self.observations(pair,now)
        if len(rows)<8 or rows[-1][0]-rows[0][0]<720 or now-rows[-1][0]>180:
            return {'action':'WAIT','reason':'Need 8 current quotes spanning 12+ minutes'}
        t,bid,ask=rows[-1]
        if bid<=0 or ask<=0 or bid>ask:return {'action':'WAIT','reason':'Bad quote'}
        spread=(ask-bid)/ask*10000
        if spread>25:return {'action':'WAIT','reason':'Spread >25 bps'}
        mids=[(b+a)/2 for _,b,a in rows]
        momentum=(mids[-1]/mids[0]-1)*100
        if momentum<Decimal('.35') or mids[-1]<=mids[-4]:
            return {'action':'WAIT','reason':f'Observed trend {momentum:.2f}% too weak'}
        recent=self.forward_scores(pair)
        if len(recent)>=8 and (sum(1 for x in recent if x>0)/len(recent)<.40 or sum(recent)<0):
            return {'action':'WAIT','reason':'Weak forward market outcome history after fees'}
        trades=self.ledger.pair_performance(pair)
        if len(trades)>=5 and sum(trades[-15:])<0:
            return {'action':'WAIT','reason':'Recent actual filled trades unprofitable after fees'}
        return {'action':'BUY','pair':pair,'bid':bid,'ask':ask,'spread_bps':spread,
                 'momentum_pct':momentum,'reason':'Current observed momentum; profit NOT predicted'}
    def forward_scores(self,pair):
        with sql(self.ledger.path) as c:
            rows=c.execute('SELECT observed_return_pct FROM forward_signals WHERE pair=? AND observed_return_pct IS NOT NULL AND fee_evidence_source=? ORDER BY at_utc DESC LIMIT 30',(pair,'ACCOUNT_TIER_NOT_PAIR_PREVIEW')).fetchall()
        return [Decimal(x[0]) for x in rows]
    def prune_forward_trials(self,now=None,keep_days=180):
        """Bound research label growth; NEVER touch Coinbase orders or fills."""
        now=int(now if now is not None else time.time())
        with sql(self.ledger.path) as c:
            c.execute('DELETE FROM forward_signals WHERE at_utc<?', (now-keep_days*86400,))

    def update_trials(self,pairs,now=None):
        """Label 30-minute shadow outcomes ONLY from actually observed future quotes.

        If the app was closed at evaluation time, expire that shadow outcome;
        an unrelated price after reopening is NOT a 30-minute observation.
        """
        now=int(now if now is not None else time.time())
        with sql(self.ledger.path) as c:
            pending=c.execute(
                'SELECT id,pair,entry_ask,fee_rate,evaluate_after FROM forward_signals '
                "WHERE exit_bid IS NULL AND (outcome_state IS NULL OR outcome_state='PENDING') "
                'AND evaluate_after<=? ORDER BY evaluate_after LIMIT 150',(now,)).fetchall()
        labeled=0;expired=0
        for row in pending:
            # Quote has to be timestamped AFTER target and WITHIN next 20 minutes.
            # Never use the present-day quote as an offline gap substitute.
            with self.store._db() as c:
                found=c.execute('SELECT at_utc,bid FROM market_quotes WHERE pair=? AND at_utc>=? '
                    'AND at_utc<=? ORDER BY at_utc LIMIT 1',
                    (row['pair'],row['evaluate_after'],row['evaluate_after']+1200)).fetchone()
            if found:
                bid=dec(found[1]);fee=dec(row['fee_rate'])
                pct=((bid*(1-fee))/(dec(row['entry_ask'])*(1+fee))-1)*100
                with sql(self.ledger.path) as c:
                    c.execute("UPDATE forward_signals SET exit_bid=?,observed_return_pct=?,outcome_state='OBSERVED' "
                        'WHERE id=? AND exit_bid IS NULL', (str(bid),str(pct),row['id']))
                labeled+=1
            elif now>row['evaluate_after']+1200:
                with sql(self.ledger.path) as c:
                    c.execute("UPDATE forward_signals SET outcome_state='MISSED_OFFLINE' "
                              'WHERE id=? AND exit_bid IS NULL', (row['id'],))
                expired+=1
        recorded=0
        for pair in pairs:
            sig=self.signal(pair,now=now)
            if sig['action']!='BUY':continue
            block=now-now%1800
            # Snapshot the authenticated *account tier* at signal entry, not
            # after the result is known. Do not retroactively rewrite outcomes.
            # Never create new cost-adjusted forward scores from invented fees.
            tier=(self.fee_learning.latest_tier(now=now)
                  if self.fee_learning is not None else {'fresh':False})
            if not tier['fresh']:
                continue
            fee=tier['taker']
            source='ACCOUNT_TIER_NOT_PAIR_PREVIEW'
            with sql(self.ledger.path) as c:
                r=c.execute('INSERT OR IGNORE INTO forward_signals(pair,at_utc,entry_ask,fee_rate,evaluate_after,momentum_pct,spread_bps,sample_count,outcome_state,fee_evidence_source) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (pair,block,str(sig['ask']),str(fee),now+1800,
                       str(sig['momentum_pct']),str(sig['spread_bps']),str(len(self.observations(pair,now))),'PENDING',source))
                recorded+=r.rowcount
        return {'new_signals':recorded,'evaluated':labeled,'missed_offline':expired}
    def recommendation(self,pair,bid,*,target_net=Decimal('.0075'),sell_fee=None,target_net_usd=None,planned_quote_value=None):
        if sell_fee is None:
            return {'action':'HOLD','reason':'Authenticated fee tier missing; cannot project net SELL return'}
        sell_fee=dec(sell_fee)
        if not 0<=sell_fee<Decimal('.05'):
            return {'action':'HOLD','reason':'Fee evidence outside safety limits'}
        base=pair.split('-')[0]
        asset=self.ledger.asset(base)
        if not asset or asset.get('trading_basis_unit_quote') is None or dec(asset['remaining_qty'])<=0:
            return {'action':'HOLD','reason':'No complete approved, lot-by-lot trading performance basis'}
        # Research-only weighted mark; broker checks exact FIFO lots at execution.
        basis=dec(asset['trading_basis_unit_quote'])
        estimated_net=(bid*(1-sell_fee)-basis)/basis
        # On a mixed personal+bot lot, use the FIFO basis for the PLANNED
        # partial SELL, not the all-holdings weighted research mark. Exact
        # Coinbase increments/fees still require a separate broker preview.
        expected_net_dollars=None
        if target_net_usd is not None:
            gross=dec(planned_quote_value or '0')
            if gross<=0:return {'action':'HOLD','reason':'No positive planned exit size'}
            try:
                planned_qty=gross/bid
                basis_value=self.ledger.sale_basis(base,planned_qty,pair.split('-')[1])['performance_basis']
            except (ValueError,TypeError) as exc:
                detail=str(exc)
                if 'Unverified USD/USDC cost currency mix' in detail:
                    detail='Recorded lot cost currency differs from candidate SELL pair (USD vs USDC); select a matching verified quote or reconcile lots. Not a slow balance refresh.'
                return {'action':'HOLD','reason':'Lot verification pending: '+detail[:190]}
            expected_net_dollars=gross*(1-sell_fee)-basis_value
            if basis_value>0: estimated_net=expected_net_dollars/basis_value
        if expected_net_dollars is not None and expected_net_dollars>=dec(target_net_usd):
            return {'action':'SELL','reason':'Estimated SELL net dollars meet requested target; preview and actual fills may differ',
                    'net_pct':estimated_net*100,'net_usd':expected_net_dollars}
        if expected_net_dollars is None and estimated_net>=target_net:
            return {'action':'SELL','reason':'Expected exit exceeds basis and target after estimated sell fee', 'net_pct':estimated_net*100}
        if estimated_net<=Decimal('-.03'):
            return {'action':'SELL','reason':'Loss stop at -3% versus recorded basis (fills may be worse)', 'net_pct':estimated_net*100}
        return {'action':'HOLD','reason':
                f'Net sell profit estimate ${expected_net_dollars:.2f} below requested ${dec(target_net_usd):.2f}'
                if expected_net_dollars is not None else 'Hold until net target or risk stop'}
