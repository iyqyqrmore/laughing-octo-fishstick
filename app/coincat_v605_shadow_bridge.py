"""v60.5 single-planner SHADOW bridge: alternative in-memory funding inventory.

Only the SHADOW funding inputs differ. A normal live read-only research screen
continues to show original enrolled Coinbase balances. No order API, ledger
writes or other execution path exists in this bridge.
"""
from __future__ import annotations
from coincat_rotation_autopilot import auto_rotation_screen

def shadow_screen(*, balances, excluded, buy_signals, age_s, catalog, quotes,
                  product_rules, portfolio_usd_cap, now, fee_rates_by_pair,
                  relative_evidence, exploratory_candidates=(), strategy_candidates=(), gpu_advisories=None,
                  direct_only=False,max_targets=12,urgent=False,experimental=False,budget_settings=None,budget_usage=None,forward_evidence=None,primary_immediate=False):
    if not balances:return {'state':'WAIT','ideas':[], 'reason':'No current modeled SHADOW inventory'}
    wallets=[{'asset':asset,'remaining_qty':str(qty),'enabled':1}
             for asset,qty in sorted(balances.items()) if str(qty)!='0'
             and asset not in set(excluded)]
    wallets.extend({'asset':asset,'remaining_qty':'0','enabled':0}
                   for asset in sorted(set(excluded)))
    result=auto_rotation_screen(buy_signals=buy_signals,holdings=wallets,
        verified_balances={str(k):str(v) for k,v in balances.items()},
        balance_age_s=age_s,catalog=catalog,quotes=quotes,
        product_rules=product_rules,usd_per_order_cap=portfolio_usd_cap,
        now=now,fee_rates_by_pair=fee_rates_by_pair,
        relative_evidence=relative_evidence,
        minimum_net_advantage_usd='0.10',
        exploratory_candidates=exploratory_candidates,strategy_candidates=strategy_candidates,
        gpu_advisories=gpu_advisories,direct_only=direct_only,max_targets=max_targets,urgent=urgent,budget_settings=budget_settings,budget_usage=budget_usage,
        forward_evidence=forward_evidence,primary_immediate=primary_immediate)
    if experimental:result['ideas']=result.get('experimental_ideas',result.get('ideas',[]))
    return result
