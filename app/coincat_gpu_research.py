"""Observe-only GPU research on TRUE future Coinbase bid/ask snapshots.

One market observation yields both BUY-now/SELL-later and SELL-now/REBUY-later
outcomes. SELL_REBUY is a counterfactual for *already owned* inventory, NOT
permission to short or proof of profitable liquidation. No broker imported,
no Coinbase orders, and no model promotion to the trading engine.
"""
from __future__ import annotations
import json,math,os
from datetime import datetime,timezone
from pathlib import Path
from coincat_live import sql

FEATURE_NAMES=('spread_bps','hour_sin','hour_cos','week_sin','week_cos','spot_taker_fee_bps_at_entry')
TARGETS={'BUY':'buy_net_pct','SELL_REBUY':'sell_rebuy_net_pct'}

def _features(at, bid,ask,spot_taker_fee=None):
    bid=float(bid);ask=float(ask)
    if not (0<bid<=ask):raise ValueError('Invalid recorded entry bid/ask')
    if spot_taker_fee is None:raise ValueError('Fee feature must be verified at entry')
    rate=float(spot_taker_fee)
    if not math.isfinite(rate) or not 0<=rate<.2:raise ValueError('Invalid authenticated fee feature')
    # All inputs were knowable at/before entry; NO future price used in features.
    t=datetime.fromtimestamp(int(at),timezone.utc)
    hour=t.hour+t.minute/60
    return [10000*(ask-bid)/ask,math.sin(2*math.pi*hour/24),
            math.cos(2*math.pi*hour/24),math.sin(2*math.pi*t.weekday()/7),
            math.cos(2*math.pi*t.weekday()/7),rate*10000]

def collect_two_way_examples(db_path):
    with sql(db_path) as conn:
        exists=conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='directional_trials'").fetchone()
        if not exists:return []
        cols={r[1] for r in conn.execute('PRAGMA table_info(directional_trials)')}
        if not {'fee_taker_at_entry','fee_source_at_entry'}.issubset(cols):return []
        rows=conn.execute("""SELECT observed_at,entry_bid,entry_ask,buy_net_pct,sell_rebuy_net_pct,fee_taker_at_entry
          FROM directional_trials WHERE state='OBSERVED'
            AND buy_net_pct IS NOT NULL AND sell_rebuy_net_pct IS NOT NULL
            AND fee_source_at_entry='AUTHENTICATED_ACCOUNT_TIER_AT_ENTRY'
            AND fee_taker_at_entry IS NOT NULL
          ORDER BY observed_at,id""").fetchall()
    out=[]
    for row in rows:
        try:
            x=_features(row['observed_at'],row['entry_bid'],row['entry_ask'],row['fee_taker_at_entry'])
            ys={key:float(row[name]) for key,name in TARGETS.items()}
            if all(math.isfinite(v) for v in x+list(ys.values())):
                out.append((int(row['observed_at']),x,{k:int(v>0) for k,v in ys.items()}))
        except (ValueError,TypeError,OverflowError):continue
    return out

def train_observe_only(db_path,output_folder,minimum=240,epochs=45):
    rows=collect_two_way_examples(db_path)
    n=len(rows)
    if n<minimum:
        return {'status':'WAIT','labeled':n,'required':minimum,
                'BUY_labels':n,'SELL_REBUY_labels':n,
                'message':f'Need {minimum} genuinely observed forward MARKET intervals for both BUY and SELL/rebuy; currently {n}. No Coinbase trades required.'}
    times=sorted({r[0] for r in rows})
    if len(times)<35 or times[-1]-times[0]<7*86400:
        return {'status':'WAIT','labeled':n,'required':minimum,
                'message':'Require at least 35 distinct observed time blocks spanning 7 days for honest forward testing.'}
    cutoff=times[int(len(times)*.8)]
    # 50-minute embargo to exclude evaluations overlapping the split boundary.
    train=[r for r in rows if r[0]+3000<cutoff]
    test=[r for r in rows if r[0]>=cutoff]
    if len(train)<max(40,minimum//2) or len(test)<20:
        return {'status':'WAIT','labeled':n,'required':minimum,
                'message':'Not enough time-separated observations after the 50-minute leakage embargo.'}
    for target in TARGETS:
        counts=(sum(r[2][target] for r in train),sum(r[2][target] for r in test))
        if min(counts[0],len(train)-counts[0],counts[1],len(test)-counts[1])<10:
            return {'status':'WAIT','labeled':n,'required':minimum,
                    'message':f'{target} needs at least 10 positive and 10 negative outcomes in BOTH train/test periods.'}
    try:import torch
    except ImportError:return {'status':'ERROR','labeled':n,'message':'PyTorch unavailable in this CoinCat v60 environment. CUDA installation optional.'}
    import numpy as np
    torch.manual_seed(20)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    a=np.asarray([r[1] for r in train],dtype='float32')
    b=np.asarray([r[1] for r in test],dtype='float32')
    mu=a.mean(axis=0);sd=np.maximum(a.std(axis=0),.001)
    xtr=torch.tensor((a-mu)/sd,dtype=torch.float32,device=device)
    xte=torch.tensor((b-mu)/sd,dtype=torch.float32,device=device)
    reports={};states={}
    for target in TARGETS:
        ytr=torch.tensor([[r[2][target]] for r in train],dtype=torch.float32,device=device)
        yte=torch.tensor([[r[2][target]] for r in test],dtype=torch.float32,device=device)
        network=torch.nn.Sequential(torch.nn.Linear(len(FEATURE_NAMES),12),torch.nn.ReLU(),torch.nn.Linear(12,1)).to(device)
        optimizer=torch.optim.Adam(network.parameters(),lr=.003,weight_decay=.02)
        for _ in range(epochs):
            network.train();optimizer.zero_grad()
            loss=torch.nn.functional.binary_cross_entropy_with_logits(network(xtr),ytr)
            loss.backward();optimizer.step()
        network.eval()
        with torch.no_grad():
            pred=torch.sigmoid(network(xte))
            score=float(torch.mean((pred-yte)**2))
            prior=float(torch.mean(ytr))
            baseline=float(torch.mean((yte-prior)**2))
        improvement=(baseline-score)/baseline if baseline else 0
        reports[target]={'brier':score,'baseline_brier':baseline,'improvement':improvement,
                         'better_than_baseline':improvement>.05,
                         'positive_train':int(ytr.sum().item()),'positive_test':int(yte.sum().item())}
        if improvement>.05:
            states[target]=network.cpu().state_dict()
    result={'status':'EVALUATED','device':str(device),'labeled':n,
            'train':len(train),'test':len(test),'features':FEATURE_NAMES,
            'BUY':reports['BUY'],'SELL_REBUY':reports['SELL_REBUY'],
            'message':'Two independent, chronologically held-out market-direction models with authenticated entry-time account fee estimates; experimental observe-only. '
                      'SELL_REBUY is a counterfactual, NOT actual profitable selling or shorting. '
                      'Neither model may place or influence Coinbase orders.'}
    folder=Path(output_folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'CoinCat_GPU_Two_Way_Research_Report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    # Save validated diagnostic candidates only; never loaded by order engine.
    if states:
        torch.save({'models':states,'features':FEATURE_NAMES,'mean':mu.tolist(),'std':sd.tolist(),
                    'cutoff_utc':cutoff,'observe_only':True},folder/'CoinCat_GPU_Two_Way_ObserveOnly.pt')
    return result

if __name__=='__main__':
    base=Path(os.environ.get('COINCAT_DATA_DIR') or Path(os.environ.get('APPDATA') or Path.home())/'CoinCatV70')
    print(json.dumps(train_observe_only(base/'research_data'/'CoinCat_Forward_Market.sqlite3',base/'gpu_research'),indent=2))
