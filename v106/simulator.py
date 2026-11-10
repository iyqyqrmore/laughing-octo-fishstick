"""Conditional next-bar maker execution, with inventory/fees and stuck cycles."""
from collections import deque
from copy import deepcopy
from decimal import Decimal as D
from datetime import datetime,timezone
from v106.fee_check import exact
from coincat_execution_limits import native_math
from v106 import strategies as policy
from v106.preregistered import MAKER,CAPITAL_USD,SOURCE_FRACTION,ENTRY_MINUTES,MAX_SPREAD,ROUNDTRIPS


class Simulator:
    @native_math
    def __init__(self,name,frame,rules,*,params=None,fee=MAKER,capital=CAPITAL_USD,record=False,fraction=SOURCE_FRACTION):
        if not 0<fraction<=D('.5') or not 0<=fee<1: raise ValueError('Invalid simulation funding/fee')
        self.name,self.params,self.rules,self.fee=name,deepcopy(params or {}),rules,fee
        self.seed=frame
        self.wallet={'ETH':capital/2/frame['eth_usd'],'BTC':capital/2/frame['btc_usd']}
        self.original=deepcopy(self.wallet);self.capital=capital;self.fraction=fraction
        self.order=None;self.cycle=None;self.trail=deque(maxlen=288);self.last=None;self.started=frame['at']
        self.records=[] if record else None;self.serial=0
        self.metrics=dict(orders=0,filled_orders=0,fills=0,partials=0,misses=0,cancels=0,entry_cancels=0,
            entry_replaces=0,gaps=0,cycles=0,fees_btc=D(0),fees_usd=D(0),cycle_profit_btc=D(0),
            cycle_profit_usd=D(0),cycle_seconds=D(0),max_stuck_seconds=0,max_drawdown=D(0),cycles_by_day={})
        self.by_entry_side={side:dict(started=0,entered=0,completed=0,exit_seconds=0,max_stuck_seconds=0,
            net_btc=D(0),net_usd=D(0),fees_btc=D(0),fees_usd=D(0)) for side in ('BUY','SELL')}
        self.peak=capital

    def emit(self,event,frame,**details):
        if self.records is not None:self.records.append(dict(at=frame['at'],event=event,**details))

    @native_math
    def value(self,frame):
        nav=sum(self.wallet[a]*frame[a.lower()+'_usd'] for a in ('ETH','BTC'))
        hold=sum(self.original[a]*frame[a.lower()+'_usd'] for a in ('ETH','BTC'))
        return dict(value_usd=nav,hold_usd=hold,advantage_usd=nav-hold,advantage_btc=(nav-hold)/frame['btc_usd'])

    def cancel(self,frame,reason):
        if self.order is None:return
        o=self.order;self.metrics['cancels']+=1
        if not o['filled']:self.metrics['misses']+=1
        if o['phase']=='ENTRY':self.metrics['entry_cancels']+=1
        self.emit('CANCEL_NO_FEE',frame,order=o['id'],reason=reason,remaining=o['remaining'])
        self.order=None

    def place(self,frame,side,q,p,phase):
        tick=exact(self.rules['price_increment'])
        if not policy.valid_size(q,p,self.rules) or p%tick or p<=0:return
        if (side=='BUY' and p>=frame['ask']) or (side=='SELL' and p<=frame['bid']):return
        required=q*p*(1+self.fee) if side=='BUY' else q
        if required>self.wallet['BTC' if side=='BUY' else 'ETH']:return
        self.serial+=1;self.metrics['orders']+=1
        self.order=dict(id='SIM-'+str(self.serial),side=side,price=p,quantity=q,remaining=q,filled=D(0),created=frame['at'],phase=phase)
        self.emit('LIMIT_GTC_POST_ONLY',frame,**self.order)

    @native_math
    def fill(self,frame):
        o=self.order
        if o is None or o['created']>frame['start']:return
        tick=exact(self.rules['price_increment']);p=o['price'];side=o['side']
        through=frame['low']<=p-tick if side=='BUY' else frame['high']>=p+tick
        if not through:return
        q=policy.snap(min(o['remaining'],frame['volume']),exact(self.rules['base_increment']))
        if q<=0:return
        commission=q*p*self.fee;change=-(q*p+commission) if side=='BUY' else q*p-commission
        self.wallet['BTC']+=change;self.wallet['ETH']+=q if side=='BUY' else -q
        if any(q<0 for q in self.wallet.values()):raise ValueError('Simulation overspent inventory')
        self.metrics['fills']+=1
        if not o['filled']:self.metrics['filled_orders']+=1
        if q<o['remaining']:self.metrics['partials']+=1
        o['filled']+=q;o['remaining']-=q
        self.metrics['fees_btc']+=commission;self.metrics['fees_usd']+=commission*frame['btc_usd']
        self.emit('CONDITIONAL_BAR_FILL',frame,order=o['id'],side=side,quantity=q,price=p,fee_btc=commission,
            remaining=o['remaining'],entry_side=self.cycle['side'] if self.cycle else None,
            quote_fee_assumption='BTC_NOT_EXCHANGE_SETTLEMENT_PROOF')
        if self.name not in ROUNDTRIPS:
            if not o['remaining']:self.order=None
            return
        c=self.cycle;c['pnl_btc']+=change;group=self.by_entry_side[c['side']]
        group['fees_btc']+=commission;group['fees_usd']+=commission*frame['btc_usd']
        if o['phase']=='ENTRY':
            group['entered']+=1
            c.update(side=side,entry_price=p,entry_fee=self.fee,quantity=q,remaining=q,entered_at=frame['at'],phase='EXIT')
            if o['remaining']:self.cancel(frame,'PARTIAL_ENTRY_CANCEL_REMAINDER_EXIT_FILLED_SIZE_ONLY')
            else:self.order=None
        else:
            self.stuck(frame)
            c['remaining']-=q
            if not c['remaining']:
                self.metrics['cycles']+=1;self.metrics['cycle_profit_btc']+=c['pnl_btc']
                day=datetime.fromtimestamp(frame['at'],timezone.utc).date().isoformat()
                self.metrics['cycles_by_day'][day]=self.metrics['cycles_by_day'].get(day,0)+1
                self.metrics['cycle_profit_usd']+=c['pnl_btc']*frame['btc_usd'];self.metrics['cycle_seconds']+=frame['at']-c['started_at']
                group['completed']+=1;group['exit_seconds']+=frame['at']-c['entered_at']
                group['net_btc']+=c['pnl_btc'];group['net_usd']+=c['pnl_btc']*frame['btc_usd']
                self.emit('CYCLE_COMPLETE',frame,entry_side=c['side'],net_btc=c['pnl_btc'],net_usd=c['pnl_btc']*frame['btc_usd'])
                self.cycle=None;self.order=None
            elif not o['remaining']:self.order=None

    def stuck(self,frame):
        c=self.cycle;age=frame['at']-c['entered_at'];group=self.by_entry_side[c['side']]
        group['max_stuck_seconds']=max(group['max_stuck_seconds'],age)
        self.metrics['max_stuck_seconds']=max(self.metrics['max_stuck_seconds'],age)

    def roundtrip(self,frame):
        c=self.cycle;tick=exact(self.rules['price_increment'])
        if c and c['phase']=='EXIT':
            age=frame['at']-c['entered_at'];self.stuck(frame)
            hold=c['params'].get('max_hold_days');expired=hold is not None and age>=hold*86400
            margin=D(0) if expired else c['params'].get('profit_margin',D('.003'))
            if self.order is not None and expired and not c.get('breakeven_only'):
                self.cancel(frame,'MAX_HOLD_SWITCH_TO_BREAK_EVEN_NOT_LIQUIDATION')
            c['breakeven_only']=expired
            if self.order is None:
                p=policy.exit_price(c['side'],c['entry_price'],c['entry_fee'],self.fee,margin,tick)
                side='SELL' if c['side']=='BUY' else 'BUY'
                p=max(p,frame['ask']) if side=='SELL' else min(p,frame['bid'])
                self.place(frame,side,c['remaining'],p,'EXIT')
            return
        if self.order:
            n=(c['params'] if c else self.params).get('reprice_ticks',3)
            touch=frame['bid'] if self.order['side']=='BUY' else frame['ask']
            if policy.spread(frame)>MAX_SPREAD:self.cancel(frame,'SPREAD_WIDE_WAIT')
            elif abs(touch-self.order['price'])>n*tick or frame['at']-self.order['created']>=ENTRY_MINUTES*60:
                self.cancel(frame,'ENTRY_REPRICE_OR_AGE')
        if self.order is None and policy.spread(frame)<=MAX_SPREAD:
            if c:side=c['side']
            elif self.name=='ROUNDTRIP_ALTERNATING':side='BUY' if self.metrics['cycles']%2==0 else 'SELL'
            else:side=policy.side_for('ROUNDTRIP',self.params,self.wallet,frame,self.trail)
            if side:
                p=frame['bid'] if side=='BUY' else frame['ask']
                q=policy.quantity_for('ROUNDTRIP',side,self.wallet,frame,p,self.fee,self.rules,self.fraction)
                old=c is not None
                self.place(frame,side,q,p,'ENTRY')
                if c is None and self.order:
                    self.cycle=dict(started_at=frame['at'],side=side,phase='ENTRY',pnl_btc=D(0),params=deepcopy(self.params))
                    self.by_entry_side[side]['started']+=1
                    self.emit('CYCLE_START',frame,entry_side=side,total_eth_btc_weight=policy.eth_btc_weight(self.wallet,frame))
                if old and self.order:self.metrics['entry_replaces']+=1

    @native_math
    def step(self,frame,params=None):
        if params is not None:self.params=deepcopy(params)
        frame=dict(frame,fee_rate=self.fee)
        if self.last is not None and frame['start']!=self.last['at']:
            self.metrics['gaps']+=1;self.cancel(frame,'MISSING_BAR_NO_DOWNTIME_FILL');self.trail.clear()
        else:self.fill(frame)
        self.trail.append(frame['close'])
        if self.name in ROUNDTRIPS:self.roundtrip(frame)
        elif self.name!='HOLD50':
            if self.order and frame['at']-self.order['created']>=600:self.cancel(frame,'TWO_BAR_EXPIRY')
            if self.order is None:
                side=policy.side_for(self.name,self.params,self.wallet,frame,self.trail)
                if side:
                    p=frame['bid'] if side=='BUY' else frame['ask']
                    q=policy.quantity_for(self.name,side,self.wallet,frame,p,self.fee,self.rules,self.fraction)
                    self.place(frame,side,q,p,'REBALANCE')
        v=self.value(frame);self.peak=max(self.peak,v['value_usd'])
        self.metrics['max_drawdown']=max(self.metrics['max_drawdown'],1-v['value_usd']/self.peak)
        self.last=frame

    @native_math
    def snapshot(self):
        v=self.value(self.last or self.seed);m=deepcopy(self.metrics);days=max(D(1)/288,D((self.last or self.seed)['at']-self.started)/86400)
        groups=deepcopy(self.by_entry_side)
        for side,g in groups.items():
            active=self.cycle if self.cycle and self.cycle['side']==side else None
            g.update(average_days_to_exit=D(g['exit_seconds'])/g['completed']/86400 if g['completed'] else None,
                max_stuck_days=D(g['max_stuck_seconds'])/86400,open_entry=int(bool(active and active['phase']=='ENTRY')),
                open_exit=int(bool(active and active['phase']=='EXIT')),
                current_stuck_days=D((self.last or self.seed)['at']-active['entered_at'])/86400 if active and active['phase']=='EXIT' else D(0))
        return dict(**v,**m,trades=m['filled_orders'],wallet=deepcopy(self.wallet),original=deepcopy(self.original),
            by_entry_side=groups,
            fees_pct_initial_portfolio=100*m['fees_usd']/self.capital,
            cycles_per_day=D(m['cycles'])/days,average_days_per_cycle=m['cycle_seconds']/m['cycles']/86400 if m['cycles'] else None,
            max_stuck_days=D(m['max_stuck_seconds'])/86400,open_cycle=bool(self.cycle and self.cycle['phase']=='EXIT'),
            pending_orders=int(self.order is not None),time_in_market_pct=D(100),
            fill_rate=D(m['filled_orders'])/m['orders'] if m['orders'] else D(0))
