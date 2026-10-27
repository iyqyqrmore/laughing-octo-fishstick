"""Read-only automatic portfolio rotation handoff from AI Lab to Auto Trader.

Screens every scan: research candidates are NOT execution directives or
predicted gains. Shared results may be rendered in both Tkinter tabs, but this
module has NO authenticated client, no submit interface and no ledger writes.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from coincat_multicurrency import evaluate_rotation
from coincat_cross_quote import split_spot, usd_conversion
from coincat_v502_relative_learning import evaluate_hold_switch
from coincat_v60_research_sizing import funding_inventory_snapshot

MAX_TARGETS = 12

def threshold_sweep(ideas):
    """Cent-resolution sensitivity on distinct OOS-screened route families.

    This is NOT model selection, out-of-sample optimizer certification, or
    independent realized Coinbase profit. Dedup the same source->destination
    hypothesis evaluated at many funding sizes in the SAME scan.
    """
    ceilings={}
    for idea in ideas or ():
        if idea.get('source')=='MULTI' or idea.get('oos_validated') is not True:
            continue
        if idea.get('research_decision')!='SWITCH_WORTH_RESEARCH':continue
        edge=_positive(idea.get('net_p10_usd'))
        if edge<=0:continue
        key=(idea.get('source'),idea.get('target'),idea.get('trigger_pair'))
        ceilings[key]=max(edge,ceilings.get(key,Decimal(0)))
    output={'state':'NO_HELD_OUT_EVIDENCE' if not ceilings else 'EXPLORATORY_ONLY_NOT_OPTIMIZED',
        'range_usd':'0.10-100.00','resolution_usd':'0.01','comparison_floors':9991,
        'qualified_route_families':len(ceilings),'qualified_predictions':len(ceilings),
        'selection_authorized':False,'recommended_floor_usd':None,
        'counts_at_floors':{}}
    # A cumulative histogram gives every cent's count in O(9991 + routes)
    # without re-running Coinbase evaluation 9991 times.
    hist=[0]*10002
    for value in ceilings.values():
        cents=max(0,min(10000,int(value*100)))
        if cents>=10:hist[cents]+=1
    curve=[0]*10002
    count=0
    for cents in range(10000,9,-1):
        count+=hist[cents];curve[cents]=count
    output['counts_at_floors']={format(Decimal(x)/100,'.2f'):curve[x]
        for x in (10,14,35,55,100,10000)}
    return output


def _positive(value):
    try:
        d = Decimal(str(value))
        return d if d.is_finite() and d > 0 else Decimal(0)
    except (ValueError, InvalidOperation, TypeError):
        return Decimal(0)


def _failure_category(plan):
    """Count typed blockers, never classify generic route failure as FX loss.

    A v60.5 generic message contained 'currency conversion' even when the
    strict USD books were valid, overstating MISSING_USD_CONVERSION counts.
    """
    reason=str((plan or {}).get('reason','')).lower()
    rejected=(plan or {}).get('route_rejections') or {}
    if 'fresh conservative usd conversion' in reason or 'missing quote currency usd mark' in rejected or 'missing residual asset usd conversion' in rejected:
        return 'MISSING_USD_CONVERSION'
    if 'listed coinbase' in reason:return 'NO_FRESH_LISTED_ROUTE'
    if 'excluded asset' in reason:return 'EXCLUDED_ASSET'
    if 'product rules' in reason or 'increments' in reason or any(
            'minimum/maximum' in key or 'product increments' in key for key in rejected):
        return 'PRODUCT_RULES_OR_MINIMUMS'
    if any('per-order usd cap' in key or 'funding balance' in key for key in rejected):
        return 'CAP_SIZE_QUOTE_OR_ROUTE_BLOCK'
    return 'LIQUIDITY_QUOTE_OR_ROUTE_BLOCK'


def sell_first_exit_screen(*, inventory, catalog, quotes, now, balance_age_s,
                           product_rules, fee_rates_by_pair, excluded_assets, direct_only=False):
    """Evaluate existing holdings for SELL-first exit feasibility independently of BUY.

    Uses the ONE verified currency-aware planner, never a new trader. An exit
    route is NOT a forecast of profit, SELL instruction, or order authorization.
    For SHADOW the inventory is always the newly evolved modeled wallet.
    """
    state={'screened':0,'feasible_exit_routes':0,'wait_routes':0,
           'cost_drag_exits':0,'positive_future_usd_edge_verified':0,
           'reasons':{},'order_authorized':False}
    from coincat_v6010_registry import one_order_catalog,STABLE_AND_FIAT
    direct=one_order_catalog(catalog,product_rules) if direct_only else ()
    for source,qty,usd_value in inventory:
        if source in STABLE_AND_FIAT or source in excluded_assets:
            continue
        state['screened']+=1
        found=False
        destinations=(sorted({p.split('-')[1] if p.split('-')[0]==source else p.split('-')[0]
                 for p in direct if source in p.split('-')})[:24] if direct_only else ('USD','USDC'))
        for target in destinations:
            plan=evaluate_rotation(source=source,target=target,
                authorized_qty=qty,verified_available_qty=qty,
                balance_age_s=balance_age_s,catalog=(direct if direct_only else catalog),quotes=quotes,
                now=now,usd_per_order_cap=usd_value,
                product_rules=product_rules,excluded_assets=excluded_assets,
                fee_rates_by_pair=fee_rates_by_pair,
                max_legs=1 if direct_only else 2,crypto_only=False)
            if plan.get('state')=='RESEARCH ONLY' and plan.get('routes'):
                found=True
                state['feasible_exit_routes']+=1
                if plan['routes'][0]['immediate_change_usd']<0:
                    state['cost_drag_exits']+=1
                break
            reason=_failure_category(plan)
            state['reasons'][reason]=state['reasons'].get(reason,0)+1
        if not found:state['wait_routes']+=1
    return state


def auto_rotation_screen(*, buy_signals, holdings, verified_balances,
                         balance_age_s, catalog, quotes, product_rules,
                         usd_per_order_cap, now, stats_for_pair=None, fee_rates_by_pair=None,
                         max_targets=MAX_TARGETS, relative_evidence=None, minimum_net_advantage_usd='0.10',
                         exploratory_candidates=(), strategy_candidates=(), gpu_advisories=None,
                         direct_only=False):
    """Build bounded, continuously refreshed two-way coin rotation *research*.

    Holdings fund proposals but do not bias the underlying market scan. An
    authorized holding can be fully liquidated only by later confirmed,
    size-capped, multi-leg executions. No candidate means HOLD, not a trade.
    Independent USD time-matched forward labels, fee preview, risk/ledger
    approval and separate ARM are still REQUIRED before automated execution.
    """
    outcome = {'state': 'WAIT', 'status': 'NO ORDERS • autonomous rotation research only',
               'ideas': [], 'considered': 0, 'scanned_sources': 0,
               'route_policy':'AUTHENTICATED_SPOT_ONE_ORDER' if direct_only else 'LEGACY_RESEARCH_UP_TO_TWO',
               'direct_crypto_pairs_authenticated':0,'one_order_eligible_spot_products':0,'one_order_routes_evaluated':0,
               'route_attempts': 0, 'viable_routes': 0, 'size_candidates_tested': 0, 'route_blockers': {},
               'funding_inventory_usd':Decimal(0),'funding_assets':0,'multi_source_research':0,
               'threshold_research':threshold_sweep([]),
               'sell_first':{'screened':0,'feasible_exit_routes':0,'wait_routes':0,'order_authorized':False},
               'funding_partial':False,'funding_unpriceable':0,'funding_rejection_counts':{},
               'strategy_targets':0,'strategy_route_reviews':0,'strategy_routes_feasible':0,
               'strategy_forward_portfolio_validated':0,
               'exploratory_targets':0,'exploratory_route_attempts':0,'exploratory_viable_routes':0,
               'exploratory_shortlist':0,
               'hold_preferred':0,'switch_worth_research':0,'forward_unverified':0,
               'reason': 'No safely valued opportunity yet'}
    try:
        age = float(balance_age_s)
        if not 0 <= age <= 300:
            outcome['reason'] = 'Coinbase available balances stale or unverified'; return outcome
        if not 0 < _positive(usd_per_order_cap):
            outcome['reason'] = 'No strict-price enrolled research funding available'; return outcome
        if not isinstance(catalog, (list, tuple, set)) or not catalog:
            outcome['reason'] = 'No authenticated Coinbase spot catalog'; return outcome
    except (ValueError, TypeError, OverflowError):
        outcome['reason'] = 'Balance age unavailable'; return outcome
    from coincat_v6010_registry import one_order_catalog
    direct_products=one_order_catalog(catalog,product_rules) if direct_only else []
    outcome['direct_crypto_pairs_authenticated']=len(direct_products)  # legacy schema alias
    outcome['one_order_eligible_spot_products']=len(direct_products)
    if direct_only and not direct_products:
        outcome['reason']='Authenticated Coinbase catalog has no eligible one-order spot products';return outcome
    enabled = []
    excluded = set()
    for asset in holdings or []:
        name = str(asset.get('asset', '')).upper()
        if not name: continue
        if not asset.get('enabled', 1):
            excluded.add(name)
        else:
            qty = min(_positive(asset.get('remaining_qty')), _positive((verified_balances or {}).get(name)))
            if qty > 0:
                enabled.append((name, qty))
    # Inventory value is not a market-research ranking input. Examine EVERY
    # enrolled verified funding asset, not merely the first N owned coins.
    enabled = sorted(enabled, key=lambda x: x[0])
    outcome['scanned_sources'] = len(enabled)
    # Strict trading-price eligibility is PER HOLDING. An unpriceable dust
    # balance no longer erases the usable USD or BTC funding capacity.
    snapshot=funding_inventory_snapshot(holdings,verified_balances,quotes,catalog,now=now)
    outcome['funding_partial']=snapshot['partial']
    outcome['funding_unpriceable']=snapshot['ineligible_count']
    outcome['funding_rejection_counts']=snapshot['ineligible_reasons']
    enabled=[(x['asset'],x['quantity']) for x in snapshot['eligible']]
    outcome['funding_assets']=len(enabled)
    outcome['funding_inventory_usd']=sum((x['usd_value'] for x in snapshot['eligible']),Decimal(0))
    if not enabled:
        outcome['reason']='No enrolled funding with fresh, strict Coinbase USD conversion; other assets remain unaltered';return outcome
    inventory=[(x['asset'],x['quantity'],x['usd_value']) for x in snapshot['eligible']]
    from coincat_multicurrency import _snapshots
    books=_snapshots(catalog,quotes,now,max_age=120)
    # Source-first SELL feasibility is evaluated regardless of whether any
    # destination has a qualified BUY signal. NEVER convert SELL feasibility
    # into a broker order or a fabricated positive future USD forecast.
    outcome['sell_first']=sell_first_exit_screen(inventory=inventory,
        catalog=catalog,quotes=quotes,now=now,balance_age_s=age,
        product_rules=product_rules,fee_rates_by_pair=fee_rates_by_pair,
        excluded_assets=excluded,direct_only=direct_only)
    outcome['funding_size_observations']={
        'state':'OBSERVATIONS ONLY','source_assets':len(inventory),
        'size_scenarios':len(inventory)*9,'partial':snapshot['partial'],
        'excluded_from_research':snapshot['ineligible_count'], 'at_least_100_usd':sum(x[2]>=100 for x in inventory),
        'full_holding_scenarios':len(inventory),'aggregate_portfolio_usd':outcome['funding_inventory_usd'],
        'reason':'Uncapped native-quantity inventory; no trade permission'}
    targets = {}
    for sig in buy_signals or []:
        try:
            if sig.get('action') != 'BUY': continue
            pair = str(sig['pair']).upper()
            if pair not in catalog or (direct_only and pair not in direct_products): continue
            base, _ = split_spot(pair)
            if base in excluded: continue
            momentum = Decimal(str(sig['momentum_pct']))
            if not momentum.is_finite(): continue
            # Competing quoted markets for the same asset represent ONE target.
            if base not in targets or momentum > targets[base][0]:
                targets[base] = (momentum, pair)
        except (ValueError, KeyError, TypeError, InvalidOperation):
            continue
    # Strategy patterns feed the SAME currency-aware funding planner, even if
    # legacy momentum BUY signals are absent. Crucially this is research-only:
    # no unconditioned source->target OOS result is a strategy-conditioned
    # portfolio advantage, and neither these targets nor the GPU create BUY.
    strategy_bases=set()
    strategy_evidence_by_target={}
    for item in strategy_candidates or ():
        try:
            if item.get('action')!='EXPLORE_ONLY' or item.get('sends_orders') is not False:continue
            pair=str(item['pair']).upper()
            if pair not in catalog or (direct_only and pair not in direct_products):continue
            base,quote=split_spot(pair)
            score=Decimal(str(item.get('observed_pct',0)))
            if direct_only and score<0:base=quote  # a falling base may suggest the quote asset for research
            if base in excluded or base in targets:continue
            if not score.is_finite():continue
            if base not in strategy_bases:
                strategy_bases.add(base)
                targets[base]=(score,pair)
                strategy_evidence_by_target[base]={
                    'observed_hourly':int(item.get('forward_observed_hourly',0)),
                    'positive_cash_after_cost':int(item.get('forward_positive_cash_after_cost',0)),
                    'maturity':str(item.get('forward_maturity','NOT_YET_OBSERVED'))}
        except (KeyError,ValueError,TypeError,InvalidOperation):continue
    outcome['strategy_targets']=len(strategy_bases)
    # v60.14: the strongest directly observed rising markets MUST NOT disappear
    # just because unrelated research patterns or one legacy BUY signal exist.
    # These are still EXPLORE_ONLY, never a trade authorization. No extra
    # Coinbase calls; all price/size/cost checks occur in the SAME planner.
    ranked_observation_bases=set()
    if targets:
        for item in exploratory_candidates or ():
            try:
                if item.get('action')!='EXPLORE_ONLY':continue
                pair=str(item['pair']).upper()
                if pair not in catalog or (direct_only and pair not in direct_products):continue
                base,quote=split_spot(pair)
                momentum=Decimal(str(item['momentum_pct']))
                if not momentum.is_finite():continue
                target=quote if direct_only and momentum<0 else base
                if target in excluded or target in targets:continue
                targets[target]=(momentum,pair)
                ranked_observation_bases.add(target)
            except (KeyError,ValueError,TypeError,InvalidOperation):continue
    outcome['exploratory_targets']=len(ranked_observation_bases)
    # A validated neural-network advisory may prioritize evaluation of an
    # already-reviewed target; it cannot create a BUY or touch the broker.
    def gpu_priority(pair):
        obj=(gpu_advisories or {}).get(pair) or {}
        prob=(obj.get('probabilities') or {}).get('BUY') if obj.get('status')=='ADVISORY' else None
        try:
            score=Decimal(str(prob))
            if score.is_finite() and Decimal(0)<=score<=Decimal(1):return score
        except (ValueError,TypeError,InvalidOperation):pass
        return Decimal('-1')
    ranked = sorted(targets.items(), key=lambda kv: (-gpu_priority(kv[1][1]),-kv[1][0],kv[0]))[:min(MAX_TARGETS, max(0, int(max_targets)))]
    outcome['considered'] = len(ranked)
    if not ranked:
        # DO NOT convert prequalification exploratory market rankings into BUY.
        # They are separately labeled and never get time-separated alpha credit.
        exploratory=[]
        for item in (exploratory_candidates or ()):
            try:
                pair=str(item['pair']).upper()
                if pair not in catalog or (direct_only and pair not in direct_products):continue
                target,quote=split_spot(pair)
                if direct_only and Decimal(str(item.get('momentum_pct',0)))<0:target=quote
                if target in excluded:continue
                momentum=Decimal(str(item['momentum_pct']))
                if not momentum.is_finite():continue
                if target not in {x[0] for x in exploratory}:
                    exploratory.append((target,momentum,pair))
            except (KeyError,TypeError,ValueError,InvalidOperation):continue
            if len(exploratory)>=min(8,max(1,int(max_targets))):break
        outcome['exploratory_targets']=len(exploratory)
        # Evaluate the same verified inventory and listed spot routes, at
        # bounded full/half/tenth sizes; never inject into the BUY signal list.
        blockers={}
        for target,momentum,trigger_pair in exploratory:
            for source,qty in enabled:
                if source==target:continue
                fx=usd_conversion(source,books,now=now,max_age=120,max_legs=2)
                if fx is None:continue
                cap=min(qty*fx['rate'],_positive(usd_per_order_cap))
                for part in (Decimal(1),Decimal('.5'),Decimal('.1')):
                    size=cap*part
                    if size<=0:continue
                    outcome['exploratory_route_attempts']+=1
                    outcome['size_candidates_tested']+=1
                    plan=evaluate_rotation(source=source,target=target,
                        authorized_qty=qty,verified_available_qty=qty,
                        balance_age_s=age,catalog=(direct_products if direct_only else catalog),quotes=quotes,
                        now=now,usd_per_order_cap=size,product_rules=product_rules,
                        excluded_assets=excluded,fee_rates_by_pair=fee_rates_by_pair,
                        max_legs=1 if direct_only else 2,crypto_only=False)
                    if plan['state']!='RESEARCH ONLY' or not plan['routes']:
                        key=_failure_category(plan)
                        blockers[key]=blockers.get(key,0)+1
                        continue
                    outcome['exploratory_viable_routes']+=1
                    if direct_only:outcome['one_order_routes_evaluated']+=1
                    if outcome['exploratory_shortlist']<6:
                        best=plan['routes'][0]
                        outcome['ideas'].append(dict(source=source,target=target,trigger_pair=trigger_pair,
                            route=best['route'],shadow_fifo_steps=best['steps'],source_units=qty,
                            input_units_planned=best['input_units_planned'],
                            destination_units_estimate=best['destination_units_estimate'],
                            initial_wallet_usd_mark=best['initial_wallet_usd_mark'],
                            post_route_wallet_usd_mark=best['post_route_wallet_usd_mark'],
                            immediate_change_usd=best['immediate_change_usd'],
                            research_size_cap_usd=size,observed_momentum_pct=momentum,
                            state='EXPLORATORY ONLY',research_decision='NOT_BUY_QUALIFIED',
                            net_p10_usd=None,oos_validated=False,sends_live_orders=False,
                            reason='Observed relative-strength ranking, not BUY or forward USD evidence'))
                        outcome['exploratory_shortlist']+=1
        outcome['route_blockers']=blockers
        outcome['threshold_research']=threshold_sweep(outcome['ideas'])
        outcome['state']='WAIT'
        outcome['reason']=('Exploratory funding routes observed; no BUY signal or verified USD advantage'
                           if outcome['ideas'] else 'No BUY signals; exploratory route checks could not clear fees, spreads or product rules')
        return outcome
    # Multiple read-only funding size candidates: compare $5/$10/$25/$100 with
    # fractional and full pool sizes, constrained by independently verified
    # available enrolled holdings. These are not broker limits or order sizes.
    route_blockers = {}
    # The same per-asset planner supplies multi-source bundles; there is no
    # independent competing planner with different fee/route assumptions.
    funding_components = {}
    for target, (momentum, trigger_pair) in ranked:
        from_strategy=target in strategy_bases
        from_observed_rank=target in ranked_observation_bases
        for source, qty in enabled:
            if source == target: continue
            fx=usd_conversion(source,books,now=now,max_age=120,max_legs=2)
            if fx is None:
                route_blockers['MISSING_USD_CONVERSION']=route_blockers.get('MISSING_USD_CONVERSION',0)+1
                continue
            available_usd=qty*fx['rate']
            full_cap=min(available_usd,_positive(usd_per_order_cap))
            if full_cap<=0:continue
            # No $100 maximum. Search scalable size fractions up to the full
            # native holding, while bounding per-scan CPU work. Actual product
            # minimums and quote depth remain independent constraints.
            candidates=sorted(set(x for x in
                (full_cap, full_cap*Decimal('.75'), full_cap*Decimal('.5'),
                 full_cap*Decimal('.25'),full_cap*Decimal('.10'),
                 Decimal('5'),Decimal('10'),Decimal('25'),Decimal('100'))
                if x>0 and x<=full_cap),reverse=True)[:9]
            for candidate_cap in candidates:
                outcome['route_attempts'] += 1
                if from_strategy:outcome['strategy_route_reviews']+=1
                if from_observed_rank:outcome['exploratory_route_attempts']+=1
                outcome['size_candidates_tested'] += 1
                # Purely read-only route evaluation; no broker, no order-post.
                plan = evaluate_rotation(source=source, target=target,
                    authorized_qty=qty, verified_available_qty=qty,
                    balance_age_s=age, catalog=catalog, quotes=quotes, now=now,
                    usd_per_order_cap=candidate_cap,
                    product_rules=product_rules, excluded_assets=excluded,
                    fee_rates_by_pair=fee_rates_by_pair,
                    max_legs=1 if direct_only else 2,crypto_only=False)
                if plan['state'] != 'RESEARCH ONLY' or not plan['routes']:
                    category=_failure_category(plan)
                    route_blockers[category] = route_blockers.get(category, 0) + 1
                    continue
                outcome['viable_routes'] += 1
                if direct_only:outcome['one_order_routes_evaluated']+=1
                if from_strategy:outcome['strategy_routes_feasible']+=1
                if from_observed_rank:outcome['exploratory_viable_routes']+=1
                best = plan['routes'][0]
                # Pool only one fully-sized feasible plan per distinct funding
                # coin; never sum multiple sizes of the SAME coins as fresh money.
                if candidate_cap == full_cap and not from_strategy:
                    funding_components.setdefault(target,{})[source]=(best,qty,candidate_cap,trigger_pair)
                summary = 'Observed momentum; independent forward USD advantage vs HOLD NOT established'
                history_gap = None
                if stats_for_pair is not None:
                    try:
                        target_stats = stats_for_pair(trigger_pair)
                        if target_stats['n'] < 24:
                            history_gap = f'only {target_stats["n"]} target forward labels'
                        else:
                            history_gap = 'relative USD comparison not independently validated'
                    except (KeyError, ValueError, TypeError):
                        history_gap = 'target forward history unavailable'
                if history_gap: summary += ' • ' + history_gap
                result = dict(source=source, target=target, trigger_pair=trigger_pair,
                    route=best['route'], shadow_fifo_steps=best['steps'], source_units=qty,
                    input_units_planned=best['input_units_planned'],
                    destination_units_estimate=best['destination_units_estimate'],
                    initial_wallet_usd_mark=best['initial_wallet_usd_mark'],
                    post_route_wallet_usd_mark=best['post_route_wallet_usd_mark'],
                    immediate_change_usd=best['immediate_change_usd'],
                    research_size_cap_usd=candidate_cap,
                    observed_momentum_pct=momentum,
                    gpu_buy_probability=(gpu_priority(trigger_pair) if gpu_priority(trigger_pair)>=0 else None),
                    state='SHADOW ONLY', reason=summary,
                    source_signal=('STRATEGY_RESEARCH_ONLY' if from_strategy else
                                   'RANKED_OBSERVATION_ONLY' if from_observed_rank else 'LEGACY_BUY_RESEARCH'),
                    sends_live_orders=False)
                try:
                    evidence=(relative_evidence(source,target,now=now) if relative_evidence is not None else
                              {'state':'INSUFFICIENT_FORWARD_USD_EVIDENCE','n':0})
                except Exception:
                    evidence={'state':'RELATIVE_EVIDENCE_ERROR','n':0}
                result.update(evaluate_hold_switch(result,evidence,minimum_net_advantage_usd=minimum_net_advantage_usd))
                if from_observed_rank:
                    # Rankings merely describe past movement: even an unrelated
                    # asset-relative OOS study cannot authorize the conditioned
                    # ranked-entry time. Experimental RAM-only track may test.
                    result['research_decision']='RANKED_OBSERVATION_PORTFOLIO_OOS_REQUIRED'
                    result['oos_validated']=False
                    result['net_p10_usd']=None
                    result['reason']='Rising-price ranked research, not a forecast; conditioned portfolio HOLD advantage unverified'
                if from_strategy:
                    # Conditional strategy timing vs funded source HOLD was NOT
                    # independently backtested; costed exploratory routes are
                    # valuable research but may NEVER populate SHADOW FIFO.
                    result['research_decision']='STRATEGY_CONDITIONAL_PORTFOLIO_OOS_REQUIRED'
                    result['oos_validated']=False
                    result['strategy_forward_observations']=strategy_evidence_by_target.get(target,{})
                    result['reason']='Strategy-aware after-cost portfolio route examined; pair forward evidence is descriptive only; conditional held-out advantage NOT validated'
                if result['research_decision']=='HOLD_PREFERRED':outcome['hold_preferred']+=1
                elif result['research_decision']=='SWITCH_WORTH_RESEARCH':outcome['switch_worth_research']+=1
                else:outcome['forward_unverified']+=1
                outcome['ideas'].append(result)
    # Multi-source whole-portfolio counterfactuals are assembled by the ONE
    # rotation planner from independently routed native units. They are NOT a
    # single pooled Coinbase order; each resulting step is a distinct spot leg.
    # Conservative: lacking JOINT held-out portfolio evidence, they cannot
    # qualify for SHADOW FIFO or actual trading, even if leg-level OOS passed.
    # Only exact FULL-size independently validated candidates may support a
    # full-size multi-source SHADOW scenario. Evidence for a $5 slice must
    # never be extrapolated as proof for selling an entire holding.
    validated_by_target={}
    for candidate in outcome['ideas']:
        if (candidate.get('research_decision')=='SWITCH_WORTH_RESEARCH'
                and candidate.get('oos_validated') is True):
            key=(candidate.get('target'),candidate.get('source'),
                 candidate.get('research_size_cap_usd'),candidate.get('input_units_planned'))
            validated_by_target[key]=candidate
    for target, parts in funding_components.items():
        if len(parts)<2:continue
        steps=[];routes=[];inputs={};before=Decimal(0);after=Decimal(0);notional=Decimal(0)
        for source in sorted(parts):
            best,qty,cap,trigger=parts[source]
            steps.extend(best['steps']);routes.extend(best['route'])
            inputs[source]=best['input_units_planned']
            before+=best['initial_wallet_usd_mark']
            after+=best['post_route_wallet_usd_mark']
            notional+=cap
        # Do not count existing target holdings as new funded source inventory.
        projected_outputs=sum((parts[src][0]['destination_units_estimate'] for src in parts),Decimal(0))
        # SHADOW can exercise a multi-source plan when EVERY independently
        # routed component has held-out evidence. The sum of component P10s is
        # a scenario screen, NOT a statistically validated JOINT portfolio P10.
        components=[validated_by_target.get((target,source,parts[source][2],
                     parts[source][0]['input_units_planned'])) for source in sorted(parts)]
        simulation_ready=bool(components) and all(c is not None for c in components)
        modeled_edge=sum((_positive(c['net_p10_usd']) for c in components),Decimal(0)) if simulation_ready else None
        basket=dict(source='MULTI',target=target,trigger_pair=next(iter(parts.values()))[3],
            funding_inputs=inputs,funding_source_count=len(inputs),
            route=tuple(routes),shadow_fifo_steps=tuple(steps),source_units=Decimal(0),
            input_units_planned=Decimal(0),destination_units_estimate=projected_outputs,
            initial_wallet_usd_mark=before,post_route_wallet_usd_mark=after,
            immediate_change_usd=after-before,research_size_cap_usd=notional,
            observed_momentum_pct=Decimal(0),
            state='SHADOW ONLY',research_decision=('SHADOW_COMPONENT_SCREENED' if simulation_ready
                         else 'JOINT_FORWARD_EVIDENCE_REQUIRED'),
            net_p10_usd=modeled_edge,oos_validated=False,
            shadow_simulation_eligible=simulation_ready,
            joint_heldout_portfolio_validated=False,
            reason='Multi-coin modeled legs; individual evidence screened, JOINT portfolio predictive edge NOT validated',
            sends_live_orders=False)
        outcome['ideas'].append(basket)
        outcome['multi_source_research']+=1
    outcome['threshold_research']=threshold_sweep(outcome['ideas'])
    # The account-tier cost screen and assumed slippage often produce negative immediate
    # conversion P&L. Do not mislabel a less-negative mark as actual profit.
    outcome['ideas'].sort(key=lambda x:(
        0 if x['research_decision']=='SWITCH_WORTH_RESEARCH' else
        1 if x['research_decision']=='HOLD_PREFERRED' else 2,
        -(x['net_p10_usd'] if x['net_p10_usd'] is not None else Decimal('-1e9')),
        -(x.get('gpu_buy_probability') if x.get('gpu_buy_probability') is not None else Decimal('-1')),
        -x['immediate_change_usd'], x['source'], x['target']))
    # Reserve a visible research row for a genuinely multi-source plan even
    # when 12 single-source HOLD ideas sort ahead of it; do not call it approved.
    baskets=[i for i in outcome['ideas'] if i.get('source')=='MULTI']
    singles=[i for i in outcome['ideas'] if i.get('source')!='MULTI']
    outcome['ideas'] = singles[:10]+baskets[:2] if baskets else singles[:12]
    outcome['route_blockers'] = route_blockers
    outcome['state'] = 'SHADOW ONLY' if outcome['ideas'] else 'WAIT'
    outcome['reason'] = ('USD HOLD vs SWITCH reviewed using only historical paired observations; no proven predictive net edge or certified execution'
                         if outcome['ideas'] else 'No authorized, fresh, Coinbase-routable inventory for current AI targets')
    return outcome
