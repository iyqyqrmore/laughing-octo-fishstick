"""Offline lifecycle proof using declared toy events, not market-derived fills."""
import argparse
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sys


def run_synthetic(emit=print):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
    from coincat_adaptive_eth import Frame,recoverable_inventory
    from coincat_paper_engine import PaperEngine,PaperLimits,ReplayDriver
    pairs=('ETH-BTC','SOL-BTC','SOL-ETH');start=1800000000
    rules={p:dict(product_id=p,product_type='SPOT',status='online',view_only=False,
        base_increment='.1',quote_increment='.00000001',price_increment='.0001',
        base_min_size='.1',quote_min_size='.00000001') for p in pairs}
    rules['ETH-BTC'].update(base_min_size='.5',price_increment='.001')
    rules['SOL-BTC']['base_min_size']='1'
    def observation(at):
        quotes={'ETH-BTC':(D('1.009'),D('1.01'),at),
            'SOL-BTC':(D('.495'),D('.4954'),at),'SOL-ETH':(D('.4495'),D('.45'),at)}
        # These are expressly fictitious fee inputs, not a cached account tier.
        return Frame(at,pairs,rules,quotes,dict(fresh=True,captured_at=at,maker=D('.01'),taker=D('.01')))

    # Every execution below is declared before the run. The driver never derives
    # a fill from its planned receipt, price touch, time elapsed or final return.
    deliveries=(
        ('ACK','seed',1,dict(venue_order_id='toy_seed')),
        ('FILL','seed',2,dict(fill_id='toy_fill_1',venue_order_id='toy_seed',price='1.01',size='.4',
            size_in_quote=False,commission='.00404',fee_currency='BTC',liquidity='MAKER')),
        ('CANCEL_REQUEST','seed',3,{}),
        ('FILL','seed',4,dict(fill_id='toy_fill_2',venue_order_id='toy_seed',price='1.01',size='.6',
            size_in_quote=False,commission='.00606',fee_currency='BTC',liquidity='MAKER')),
        ('CANCEL_ACK','seed',5,dict(venue_order_id='toy_seed',cumulative_base='1')),
        ('ACK','sol',6,dict(venue_order_id='toy_sol')),
        ('FILL','sol',7,dict(fill_id='toy_fill_3',venue_order_id='toy_sol',price='.495',size='.2475',
            size_in_quote=True,commission='.002475',fee_currency='BTC',liquidity='MAKER')),
        ('FILL','sol',8,dict(fill_id='toy_fill_4',venue_order_id='toy_sol',price='.495',size='.7425',
            size_in_quote=True,commission='.007425',fee_currency='BTC',liquidity='MAKER')))
    emit('CoinCat v1.04 — SYNTHETIC PAPER REPLAY / SIMULATED_ASSUMPTION')
    emit('Fictitious prices, amounts and 1% fees. No Coinbase connection or private account data.')
    with TemporaryDirectory(prefix='CoinCat_Paper_Replay_') as folder:
        engine=PaperEngine.create(Path(folder)/'paper.sqlite3',initial_eth=D(1),at=start,
            limits=PaperLimits(pairs,{'ETH':D(1),'BTC':D(1),'SOL':D(2)},1,2,start+600,D('.02')),
            simulation_ack='SIMULATION_ONLY')
        driver=ReplayDriver(engine,(dict(reference='seed',pair='ETH-BTC',side='SELL'),
            dict(reference='sol',pair='SOL-BTC',side='BUY')),order_lifetime_s=120)
        engine.start('explicit_session_start',at=start)
        decisions=[driver.advance(observation(start))]
        emit('One paper-session start; scripted ETH → BTC → SOL intents run inside explicit limits.')
        for index,(kind,ref,offset,data) in enumerate(deliveries):
            now=start+offset
            for command in engine.pending_commands():
                grant=engine.mark_dispatched('dispatch_'+str(index)+'_'+command['command_id'],command['command_id'],at=now)
                if not grant.get('dispatch_permitted'):raise AssertionError('REPLAY_DISPATCH_GRANT_MISSING')
            if kind=='CANCEL_REQUEST':engine.request_cancel('cancel_seed','seed')
            else:engine.ingest(dict(event_id='delivery_'+str(index),kind=kind,reference=ref,
                source='SIMULATED_REPLAY',at=now,data=data))
            decision=driver.advance(observation(now));decisions.append(decision)
            state=engine.private_state()
            emit(kind+' '+ref+' → '+state['orders'][ref]['state']+'; '+decision['decision'])
        # Duplicate delivery with a new transport ID must not earn more inventory.
        kind,ref,offset,data=deliveries[-1]
        duplicate=engine.ingest(dict(event_id='redelivery',kind=kind,reference=ref,
            source='SIMULATED_REPLAY',at=start+offset,data=data))
        emit('Duplicate fill: '+duplicate['result'])
        engine.tick('session_expired',at=start+600)
        before=engine.private_state();wallet=before['wallet']
        emit('Simulated wallet after fees: '+str(wallet)+'; HOLD retains SOL through session expiry.')
        valuation=recoverable_inventory(wallet,observation(start+600))
        emit('After-cost recoverable ETH: UNKNOWN (no sized exit-depth/fee-unit evidence).')
        restored=PaperEngine.restore(engine.path)
        if restored.status()['mode']!='RECONCILIATION_REQUIRED' or restored.pending_commands():
            raise AssertionError('REPLAY_RESTART_GUARD_FAILED')
        emit('Restart: '+restored.status()['mode']+'; commands available '+str(len(restored.pending_commands())))
        restored.reconcile('explicit_reconciliation',wallet=wallet,orders={},at=start+601,source='SIMULATED_REPLAY')
        emit('Matched explicit replay snapshot: '+restored.status()['mode']+'; no automatic resume.')
        status=restored.status()
        if (wallet!={'ETH':D(0),'BTC':D(0),'SOL':D(2)} or
                len(before['orders'])!=2 or any(o['state']!='FILLED' for o in before['orders'].values()) or
                status['simulated_fills']!=4 or status['real_orders']!=0 or status['mode']!='PAUSED' or
                status['verified_exchange_fills']!=0 or duplicate['result']!='DUPLICATE_FILL_IGNORED' or
                valuation['recoverable_eth'] is not None):
            raise AssertionError('REPLAY_EXPECTATIONS_FAILED')
        emit('PASS: 2 terminal paper orders, 4 simulated fills, 0 real orders, 0 verified exchange fills.')
        emit('NO DEMONSTRATED EDGE. Actual profit NOT ESTABLISHED. Live submission remains blocked.')
        return dict(wallet=wallet,decisions=decisions,status=status,valuation=valuation,
            orders=before['orders'],duplicate=duplicate)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic',action='store_true',required=True,
        help='Acknowledge all executions are expressly declared fictitious replay events')
    parser.parse_args();run_synthetic()
    return 0


if __name__=='__main__':raise SystemExit(main())
