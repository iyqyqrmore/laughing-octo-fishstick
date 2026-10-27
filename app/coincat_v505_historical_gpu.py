"""Experimental chronological historical-price GPU warm-up, observe only.

This model predicts NEXT-HOUR price direction in the pair's QUOTE currency.
It is NOT a forecast of total-portfolio USD outperformance, is never read by
Coinbase submission, and cannot change AI Lab's preferred broker budget.
It must not be mixed into real forward trials or confirmed execution outcomes.
"""
from __future__ import annotations
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
import importlib.util,json,math,sqlite3,time

MODEL_REPORT='CoinCat_GPU_Historical_Warmup_v505.json'

def probe_gpu():
    """Run in existing background worker, never GUI thread or diagnostic export."""
    if importlib.util.find_spec('torch') is None:
        return {'status':'MISSING_TORCH','cuda':False,'device':'NONE','training_ready':False}
    try:
        import torch
        cuda=bool(torch.cuda.is_available())
        return {'status':'CUDA_READY' if cuda else 'CPU_ONLY',
                'cuda':cuda,'device':torch.cuda.get_device_name(0) if cuda else 'CPU',
                'torch_version':str(torch.__version__), 'training_ready':True}
    except Exception as exc:
        return {'status':'TORCH_IMPORT_ERROR','error_type':type(exc).__name__,
                'cuda':False,'device':'NONE','training_ready':False}

def historical_examples(path,*,max_rows=120000):
    """Bounded, read-only Coinbase hourly OHLCV pairs with time-aligned next-hour label.

    Avoids look-ahead by using only previous closed candles as model inputs and
    requires consecutive hourly closes; one shared time boundary across pairs.
    """
    path=Path(path)
    if not path.is_file():return []
    uri=path.resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        rows=db.execute('''SELECT pair,at_utc,close FROM research_history_hourly
                           ORDER BY at_utc DESC LIMIT ?''',(int(max_rows),)).fetchall()
    pairs=defaultdict(list)
    for pair,ts,close in rows:
        try:
            v=float(close);t=int(ts)
            if '-' in pair and v>0 and math.isfinite(v):pairs[pair].append((t,v))
        except (TypeError,ValueError,OverflowError):continue
    out=[]
    for pair,pts in pairs.items():
        pts=sorted(set(pts))
        if len(pts)<16:continue
        for i in range(4,len(pts)-1):
            window=pts[i-4:i+2]
            if any(window[j+1][0]-window[j][0]!=3600 for j in range(5)):continue
            # Exclude last two hours to avoid partially formed candles and revisions.
            if window[-1][0] >= time.time()-7200:continue
            values=[p for _,p in window]
            r1=math.log(values[4]/values[3]);r4=math.log(values[4]/values[0]);
            drift=[math.log(values[j+1]/values[j]) for j in range(4)]
            volatility=math.sqrt(sum((a-sum(drift)/4)**2 for a in drift)/4)
            dt=datetime.fromtimestamp(pts[i][0],timezone.utc)
            x=[r1,r4,volatility,math.sin(2*math.pi*dt.hour/24),
               math.cos(2*math.pi*dt.hour/24)]
            outcome=1 if values[5]>values[4] else 0
            if all(math.isfinite(v) for v in x):out.append((pts[i][0],x,outcome))
    # Split by timestamp across ALL pairs to avoid cross-market future leakage.
    return sorted(out,key=lambda r:r[0])

def warmup(path,folder,*,minimum=400,epochs=30,now=None):
    rows=historical_examples(path)
    times=sorted({r[0] for r in rows})
    report={'kind':'HISTORICAL_GROSS_PAIR_PRICE_DIRECTION_ONLY',
            'status':'WAIT','examples':len(rows),'independent_hours':len(times),
            'learned_from_actual_fills':False,'account_fees_applied':False,
            'affects_budget':False,'affects_orders':False,
            'message':'Historical candles are contextual research, never authenticated fill or net USD profitability evidence.'}
    if len(rows)<minimum or len(times)<90 or times[-1]-times[0]<7*86400:
        report['reason']='INSUFFICIENT_CHRONOLOGICAL_HISTORY'
        return report
    cutoff=times[int(len(times)*.75)]
    train=[row for row in rows if row[0]+3600<cutoff]
    test=[row for row in rows if row[0]>=cutoff]
    if len(train)<200 or len(test)<80:
        report['reason']='TIME_SPLIT_UNDERSAMPLED';return report
    tr=sum(r[2] for r in train);te=sum(r[2] for r in test)
    if min(tr,len(train)-tr,te,len(test)-te)<15:
        report['reason']='ONE_SIDED_LABELS';return report
    env=probe_gpu()
    report['environment']=env
    if not env['training_ready']:
        report['reason']='PYTORCH_UNAVAILABLE';return report
    import numpy as np,torch
    torch.manual_seed(505)
    dev=torch.device('cuda' if env['cuda'] else 'cpu')
    a=np.asarray([x for _,x,_ in train],dtype='float32')
    b=np.asarray([x for _,x,_ in test],dtype='float32')
    mu=a.mean(0);sigma=np.maximum(a.std(0),1e-4)
    xtr=torch.tensor((a-mu)/sigma,device=dev)
    xte=torch.tensor((b-mu)/sigma,device=dev)
    ytr=torch.tensor([[y] for _,_,y in train],dtype=torch.float32,device=dev)
    yte=torch.tensor([[y] for _,_,y in test],dtype=torch.float32,device=dev)
    network=torch.nn.Sequential(torch.nn.Linear(5,12),torch.nn.ReLU(),torch.nn.Linear(12,1)).to(dev)
    opt=torch.optim.Adam(network.parameters(),lr=.002,weight_decay=.02)
    for _ in range(int(epochs)):
        opt.zero_grad();loss=torch.nn.functional.binary_cross_entropy_with_logits(network(xtr),ytr)
        loss.backward();opt.step()
    network.eval()
    with torch.no_grad():
        prob=torch.sigmoid(network(xte));brier=float(((prob-yte)**2).mean())
        baseline_p=ytr.mean();baseline=float(((yte-baseline_p)**2).mean())
    improvement=(baseline-brier)/baseline if baseline else 0.0
    report.update(status='EVALUATED',train=len(train),test=len(test),
                  embargo_seconds=3600,split_utc=cutoff,device=str(dev),
                  heldout_brier=brier,baseline_brier=baseline,
                  heldout_improvement_fraction=improvement,
                  better_than_baseline=bool(improvement>.05),
                  message='Gross next-hour quote-price direction only. Observe-only; NOT a net USD advantage or live trade signal.')
    out=Path(folder);out.mkdir(parents=True,exist_ok=True)
    (out/MODEL_REPORT).write_text(json.dumps(report,indent=2),encoding='utf-8')
    # Deliberately no loadable live order model or execution-side checkpoint.
    return report

def saved_warmup_summary(folder):
    report=Path(folder)/MODEL_REPORT
    if not report.is_file() or report.stat().st_size>20000:return {'status':'NOT_TRAINED'}
    try:
        r=json.loads(report.read_text(encoding='utf-8'))
        return {k:r.get(k) for k in ('status','examples','train','test','device',
                 'better_than_baseline','heldout_improvement_fraction','kind')}
    except (OSError,ValueError,TypeError):return {'status':'UNAVAILABLE'}
