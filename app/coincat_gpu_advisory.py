"""GPU-trained research advisory -- never live order authorization.

Consumes explicitly time-split validated saved model candidates and a currently
observed bid/ask; this is analysis-only. No broker imports, ledger modification,
API client, order sizing, or order call exists in this module.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import json,math,time
from functools import lru_cache
from pickle import UnpicklingError


@lru_cache(maxsize=3)
def _load_validated_checkpoint(path,modified_ns):
    import torch
    return torch.load(path,map_location='cpu',weights_only=True)

def advisory(folder, bid, ask, at=None, spot_taker_fee=None):
    at=int(time.time() if at is None else at)
    folder=Path(folder)
    report_file=folder/'CoinCat_GPU_Two_Way_Research_Report.json'
    model_file=folder/'CoinCat_GPU_Two_Way_ObserveOnly.pt'
    if not report_file.is_file() or not model_file.is_file():
        return {'status':'WAIT','reason':'No validated saved GPU research model; forward learning continues',
                'affects_live_orders':False}
    try:
        report=json.loads(report_file.read_text(encoding='utf-8'))
        if report.get('status')!='EVALUATED':
            return {'status':'WAIT','reason':'Saved GPU evaluation not completed','affects_live_orders':False}
        validated=[s for s in ('BUY','SELL_REBUY')
                   if report.get(s,{}).get('better_than_baseline') is True]
        if not validated:
            return {'status':'WAIT','reason':'No model beat its out-of-sample baseline','affects_live_orders':False}
        import torch
        from coincat_gpu_research import _features,FEATURE_NAMES
        # Only trusted, locally produced weights; weights_only forbids loading
        # arbitrary user-supplied Python objects from a model artifact.
        checkpoint=_load_validated_checkpoint(str(model_file),model_file.stat().st_mtime_ns)
        if checkpoint.get('observe_only') is not True or tuple(checkpoint.get('features',()))!=FEATURE_NAMES:
            raise ValueError('Research checkpoint schema mismatch')
        mean=checkpoint['mean'];sd=checkpoint['std']
        x=_features(at,bid,ask,spot_taker_fee)
        if len(mean)!=len(x) or len(sd)!=len(x):raise ValueError('Normalization schema mismatch')
        device=torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        features=torch.tensor([[float((v-m)/max(float(d),.001)) for v,m,d in zip(x,mean,sd)]],
                              dtype=torch.float32,device=device)
        values={}
        for direction in validated:
            state=checkpoint.get('models',{}).get(direction)
            if state is None:continue
            net=torch.nn.Sequential(torch.nn.Linear(len(FEATURE_NAMES),12),torch.nn.ReLU(),torch.nn.Linear(12,1))
            net.load_state_dict(state,strict=True);net.to(device).eval()
            with torch.no_grad():prob=float(torch.sigmoid(net(features)).item())
            if math.isfinite(prob):values[direction]=round(prob,4)
        return {'status':'ADVISORY' if values else 'WAIT','probabilities':values,'device':str(device),
                'reason':'Observed quote + model trained on past forward labels; experimental, not calibrated for real fills',
                'affects_live_orders':False}
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,ImportError,UnpicklingError) as exc:
        return {'status':'WAIT','reason':'Research model unavailable: '+type(exc).__name__,
                'affects_live_orders':False}
