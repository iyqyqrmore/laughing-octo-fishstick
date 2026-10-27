"""Pure, bounded Coinbase full-spot catalog discovery selector.

Discovery is observational ONLY: it never produces live BUY/SELL orders or
forward results. Real buy/sell signals continue to require focused fresh quotes.
"""
from __future__ import annotations

def choose_discovery(catalog,focused,cursor=0,limit=12):
    universe=sorted(set(catalog)-set(focused))
    if not universe or limit<=0:return [],0
    start=max(0,int(cursor))%len(universe)
    count=min(int(limit),len(universe))
    return [universe[(start+i)%len(universe)] for i in range(count)],(start+count)%len(universe)
