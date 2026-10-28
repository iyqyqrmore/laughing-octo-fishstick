"""CoinCat v50.7 independently ARMED SHADOW session (NO ORDER API or ledger).

Read-only, in-memory what-if research. Every simulated fill is counterfactual:
quotes cannot establish queue priority, actual execution, depth or future profit.
Only snapshots gathered AFTER a decision may be used to evaluate that decision.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from coincat_v507_shadow_fifo import ShadowFIFOPortfolio, ShadowFIFOBlocked
import time, math
from coincat_v703_chain import experimental_score, step_input_usd, decision_key
from coincat_multicurrency import RotationContext

PRICE_BANDS_BPS = (("TAKER_ASK", Decimal('0')), ("LIMIT_ASK_MINUS_5BPS", Decimal('5')),
                   ("LIMIT_ASK_MINUS_20BPS", Decimal('20')), ("LIMIT_ASK_MINUS_50BPS", Decimal('50')))
DEFAULT_MARK_HORIZON_S=300
MAX_TRACKED=144
MAX_EXPERIMENTAL_TRACKED=4096
OUTCOME_TOLERANCE_S=120


def _decimal(raw):
    try:
        val=Decimal(str(raw))
        return val if val.is_finite() else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def _book(raw,now):
    try:
        bid,ask,stamp=raw[:3]
        bid,ask,stamp=_decimal(bid),_decimal(ask),float(stamp)
        if bid is None or ask is None or bid<=0 or ask<bid or not 0<=float(now)-stamp<=180:
            return None
        return (bid,ask,stamp)
    except (ValueError, TypeError, IndexError, OverflowError):
        return None


class ShadowArmedResearch:
    """A completely disconnected speculative ledger. Never accesses a Coinbase client."""
    def __init__(self, *, mark_horizon_s=DEFAULT_MARK_HORIZON_S, experimental=False):
        self.experimental=bool(experimental)
        self.armed=False
        self.started_at=None
        self.stop_at=None
        self.scans=0
        self.market_snapshots=0
        self.target_reviews=0
        self.ideas_reviewed=0
        self.validated_ideas=0
        self.rejected=0
        self.would_submit=0
        self.touch_only=0
        self.matured=0
        self.marked_positive=0
        self.marked_negative=0
        self.marked_usd_total=Decimal('0')
        self.entries=[]
        self.prices=[]
        self.last_observation=None
        self.mark_horizon_s=mark_horizon_s
        self.missing_usd_marks=0
        self.stale_books=0
        self.screened_price_bands={label:0 for label,_ in PRICE_BANDS_BPS}
        self.price_touch_bands={label:0 for label,_ in PRICE_BANDS_BPS}
        self.notes=[]
        self.last_usd_rates={}
        self.mark_problems={}
        self.fifo_portfolios={}   # IN-MEMORY per-price-band wallets only
        self.fifo_posted=0
        self.fifo_rejected=0
        self.fifo_posted_legs=0
        self.last_selected_at={}
        self.seen_market_decisions={}
        self.hourly_model_fills=[]
        self.entry_sequence=0
        self.duplicate_decisions=0
        self.expired_outcome_entries=0
        self.experimental_snowball_posted=0
        self.rejected_budget=0
        self.rejected_quote=0
        self.shadow_model_source='TAKER_ASK'
        self.rolling_model_attempts=[]
        self.daily_model_buys=[]
        self.experimental_candidates=0
        self.experimental_screened=0
        self.experimental_heuristic_rejected=0
        self.experimental_marks=[]
        self.experimental_horizons={300:{'matured':0,'positive':0,'negative':0},
                                    900:{'matured':0,'positive':0,'negative':0},
                                    3600:{'matured':0,'positive':0,'negative':0}}

    def arm(self, *, connected, real_arm, stopped, verified_balances, usd_coverage,
            enrolled_quantities=None, fresh_usd_rates=None, now=None):
        if real_arm or stopped:
            raise ValueError('Real ARM or emergency STOP prevents ARM SHADOW')
        if not connected or not verified_balances or not usd_coverage:
            raise ValueError('Fresh Coinbase read-only balances and complete USD coverage required')
        if self.armed:
            return False
        if not enrolled_quantities or not fresh_usd_rates:
            raise ValueError('ARM SHADOW requires verified enrolled quantities and fresh USD rates')
        wallets={}
        try:
            for band,_ in PRICE_BANDS_BPS:
                if self.experimental and band!='TAKER_ASK':continue
                wallets[band]=ShadowFIFOPortfolio(enrolled_quantities,fresh_usd_rates,label=('EXPERIMENTAL_'+band if self.experimental else band))
        except BaseException:
            for wallet in wallets.values():wallet.close()
            raise
        for wallet in self.fifo_portfolios.values():wallet.close()
        self.fifo_portfolios=wallets
        self.entries=[]
        self.prices=[]
        # A second shadow session must not inherit earlier hypothetical trades
        # or counters and misrepresent an elapsed-time performance comparison.
        self.scans=self.market_snapshots=self.target_reviews=self.ideas_reviewed=0
        self.validated_ideas=self.rejected=self.would_submit=self.touch_only=0
        self.matured=self.marked_positive=self.marked_negative=0
        self.marked_usd_total=Decimal('0')
        self.fifo_posted=self.fifo_posted_legs=self.fifo_rejected=0
        self.last_selected_at={}
        self.seen_market_decisions={}
        self.hourly_model_fills=[]
        self.entry_sequence=0
        self.duplicate_decisions=0
        self.expired_outcome_entries=0
        self.experimental_snowball_posted=0
        self.rejected_budget=0
        self.rejected_quote=0
        self.rolling_model_attempts=[]
        self.daily_model_buys=[]
        self.experimental_candidates=0
        self.experimental_screened=0
        self.experimental_heuristic_rejected=0
        self.experimental_marks=[]
        self.experimental_horizons={300:{'matured':0,'positive':0,'negative':0},
                                    900:{'matured':0,'positive':0,'negative':0},
                                    3600:{'matured':0,'positive':0,'negative':0}}
        self.last_observation=None
        self.last_usd_rates={}
        self.mark_problems={}
        self.stale_books=self.missing_usd_marks=0
        self.screened_price_bands={label:0 for label,_ in PRICE_BANDS_BPS}
        self.price_touch_bands={label:0 for label,_ in PRICE_BANDS_BPS}
        self.armed=True
        self.started_at=float(time.time() if now is None else now)
        self.stop_at=None
        return True

    def model_balances(self):
        """Actual evolving simulated inventory in the primary taker band."""
        wallet=self.fifo_portfolios.get(self.shadow_model_source)
        return wallet.balances() if wallet else {}

    def disarm(self, now=None):
        self.armed=False
        self.stop_at=float(time.time() if now is None else now)

    def _post_fifo(self,entry,usd_rates,now):
        wallet=self.fifo_portfolios.get(entry['band'])
        if wallet is None:
            entry['fifo_state']='NOT_AVAILABLE'
            self.fifo_rejected+=1
            return False
        try:
            data=wallet.post_hypothetical_route(
                session_id=entry['shadow_id'],steps=entry['fifo_steps'],
                usd_rates=usd_rates,at_utc=int(now))
        except (ShadowFIFOBlocked, ValueError, KeyError, TypeError, IndexError) as exc:
            entry['fifo_state']='BLOCKED_'+type(exc).__name__
            self.fifo_rejected+=1
            return False
        entry['fifo_state']=data['state']
        entry['fifo_legs']=data['steps']
        if data['state']!='SHADOW_FIFO_POSTED':return False
        self.hourly_model_fills.append((now,data['steps']))
        self.hourly_model_fills=[(t,n) for t,n in self.hourly_model_fills if now-t<3600]
        self.fifo_posted+=1
        self.fifo_posted_legs+=data['steps']
        return True

    def _experimental_score(self, idea, usd_rates):
        return experimental_score(idea) if self.experimental else None

    def observe(self, *, now, quotes, usd_rates, researched_reviews=(), route_ideas=(),
                minimum_advantage='0.10', max_ideas=12,
                strict_quotes=False, risk_budgets=None,approved_catalog=None):
        """One fresh completed market scan; NO network requests and NO order creation.

        `usd_rates` must be externally verified fresh mark inputs, not trade ticks.
        A price touch is *not* an exchange fill, even if seen later.
        """
        if not self.armed:
            return False
        now=float(now)
        if not math.isfinite(now):return False
        if self.last_observation is not None and now<=self.last_observation:
            return False
        # Outcome storage must not become a lifetime trading quota. Retain an
        # hour of experimental observations, with missing windows explicit.
        retained=[]
        for entry in self.entries:
            age=now-entry['created_at']
            completed=(entry.get('matured') and (not self.experimental or
                all(h in entry.get('experimental_future_marks',{}) for h in self.experimental_horizons)))
            expired=age>max(3600,self.mark_horizon_s)+OUTCOME_TOLERANCE_S
            if completed:continue
            if expired:
                self.expired_outcome_entries+=1;continue
            retained.append(entry)
        self.entries=retained
        if self.experimental:
            self.seen_market_decisions={k:t for k,t in self.seen_market_decisions.items() if 0<=now-t<=180}
        self.last_usd_rates=dict(usd_rates or {})
        books={name:book for name,raw in (quotes or {}).items()
               if (book:=_book(raw,now)) is not None}
        allowed=None if approved_catalog is None else set(approved_catalog)
        # Portfolio marking can retain a wider conservative bid. Order budgets
        # always use independent narrow, current, approved source-currency FX.
        budget_context=RotationContext(approved_catalog if approved_catalog is not None else books,
                                       books,now)
        self.scans+=1
        self.market_snapshots+=len(books)
        self.target_reviews+=len(researched_reviews or ())
        self.last_observation=now
        price_view={pair:(bid,ask) for pair,(bid,ask,_) in books.items()}
        self.prices.append((now,price_view))
        if len(self.prices)>MAX_TRACKED:self.prices=self.prices[-MAX_TRACKED:]
        for entry in self.entries:
            if entry['state']=='PRICE_WAIT':
                bidask=books.get(entry['entry_pair'])
                if bidask and now>entry['created_at'] and bidask[1] <= entry['limit_price']:
                    entry['state']='TOUCHED_UNVERIFIED'
                    entry['touched_at']=now
                    # A price touch is NOT Coinbase queue/fill evidence.
                    # Conditional FIFO is isolated and clearly hypothetical.
                    if not strict_quotes:
                        self._post_fifo(entry,usd_rates,now)
                    else:
                        entry['fifo_state']='TOUCH_ONLY_NO_FILL_PROOF'
                    self.touch_only+=1
                    self.price_touch_bands[entry['band']]+=1
            if entry['state'] in ('MODEL_TAKER_FILL','TOUCHED_UNVERIFIED') and not entry['matured']:
                observed_start=entry['touched_at'] if entry['state']=='TOUCHED_UNVERIFIED' else entry['created_at']
                if now-observed_start >= self.mark_horizon_s:
                    if self.experimental and now-observed_start>self.mark_horizon_s+OUTCOME_TOLERANCE_S:
                        continue  # A late price cannot stand in for a missed 5m mark.
                    dst=_decimal((usd_rates or {}).get(entry['target']))
                    inputs=entry.get('funding_inputs') or {entry['source']:entry['source_units']}
                    sources=[(_decimal((usd_rates or {}).get(asset)), _decimal(qty))
                             for asset,qty in inputs.items()]
                    if dst is None or dst<=0 or not sources or any(
                         rate is None or qty is None or rate<=0 or qty<=0 for rate,qty in sources):
                        self.missing_usd_marks+=1
                        continue
                    # Directly compare the changed slice of the same portfolio;
                    # unrotated coins cancel. Quote conversion and fees were
                    # included in the source route proposal's dest qty, but
                    # passive price-touch scenarios add extra fill uncertainty.
                    delta=entry['target_units']*dst-sum((qty*rate for rate,qty in sources),Decimal(0))
                    entry['mark_delta_usd']=delta
                    entry['matured']=True
                    self.matured+=1
                    self.marked_usd_total+=delta
                    if delta>0:self.marked_positive+=1
                    else:self.marked_negative+=1
        if self.experimental:
            # Future observations are recorded AFTER the hypothetical decision.
            # They are not reusable as proof to authorize the decision already made.
            for entry in self.entries:
                if entry.get('fifo_state')!='SHADOW_FIFO_POSTED':continue
                marks=entry.setdefault('experimental_future_marks',{})
                for horizon in self.experimental_horizons:
                    if horizon in marks or now-entry['created_at']<horizon:continue
                    if now-entry['created_at']>horizon+OUTCOME_TOLERANCE_S:
                        marks[horizon]='NOT_OBSERVED_IN_WINDOW';continue
                    destination=_decimal((usd_rates or {}).get(entry['target']))
                    inputs=entry.get('funding_inputs') or {}
                    src_marks=[(_decimal((usd_rates or {}).get(asset)),_decimal(qty))
                               for asset,qty in inputs.items()]
                    if destination is None or destination<=0 or not src_marks or any(
                        px is None or qty is None or px<=0 or qty<=0 for px,qty in src_marks):
                        continue
                    delta=entry['target_units']*destination-sum((px*qty for px,qty in src_marks),Decimal(0))
                    marks[horizon]=str(delta)
                    summary=self.experimental_horizons[horizon]
                    summary['matured']+=1
                    summary['positive' if delta>0 else 'negative']+=1
        # Select one coherent funding plan per scan. Do not post a dozen
        # overlapping proposals against the same simulated wallet balance.
        # All below-threshold candidates are still counted as reviews.
        if self.experimental:
            from coincat_v703_chain import ranked_one_order_ideas
            candidates=ranked_one_order_ideas(route_ideas or (),max_ideas)
        else:
            candidates=sorted(list(route_ideas or ())[:max_ideas],
                key=lambda x:(_decimal(x.get('net_p10_usd')) or Decimal('-1e99')),
                reverse=True)
        selected=False
        self.rolling_model_attempts=[(t,n) for t,n in self.rolling_model_attempts if now-t<86400]
        self.daily_model_buys=[(t,v) for t,v in self.daily_model_buys if now-t<86400]
        for idea in candidates:
            self.ideas_reviewed+=1
            ordinary=(idea.get('research_decision')=='SWITCH_WORTH_RESEARCH'
                      and idea.get('oos_validated') is True)
            # Basket scenarios are NOT joint-portfolio validated predictions.
            basket=(idea.get('source')=='MULTI'
                    and idea.get('shadow_simulation_eligible') is True
                    and idea.get('joint_heldout_portfolio_validated') is False)
            score=self._experimental_score(idea,usd_rates) if self.experimental else None
            if self.experimental:
                self.experimental_screened+=1
                if score is None:self.experimental_heuristic_rejected+=1
                else:self.experimental_candidates+=1
            if not (score is not None if self.experimental else (ordinary or basket)):
                self.rejected+=1
                continue
            net=score if self.experimental else _decimal(idea.get('net_p10_usd'))
            floor=_decimal(minimum_advantage)
            src=str(idea.get('source','')).upper()
            dst=str(idea.get('target','')).upper()
            pair=str(idea.get('trigger_pair','')).upper()
            book=books.get(pair)
            source_units=_decimal(idea.get('input_units_planned'))
            target_units=_decimal(idea.get('destination_units_estimate'))
            inputs=(idea.get('funding_inputs') or
                    ({src:source_units} if source_units is not None else {}))
            inputs={str(k).upper():_decimal(v) for k,v in inputs.items()}
            if (net is None or floor is None or net<floor or
                target_units is None or target_units<=0 or not inputs or
                any(v is None or v<=0 for v in inputs.values()) or
                not book or not src or not dst or src==dst):
                self.rejected+=1
                if not book:self.stale_books+=1
                continue
            # Every modeled leg needs a fresh executable-side book, and we
            # refuse to reuse old routed prices after a material book change.
            steps=idea.get('shadow_fifo_steps') or ()
            if allowed is not None and any(step.get('pair') not in allowed for step in steps):
                self.rejected+=1;continue
            if strict_quotes:
                if not steps or not all((b:=_book(quotes.get(s.get('pair')),now)) is not None
                                        and now-b[2]<=120 for s in steps):
                    self.rejected_quote+=1;self.rejected+=1;continue
                mismatched=False
                for s in steps:
                    b=books[s['pair']]
                    side=str(s['side']).upper()
                    expected=b[1] if side=='BUY' else b[0]
                    try:
                        gross=_decimal(s['gross_base_quantity'])
                        spent=_decimal(s['input_quantity'])
                        received=_decimal(s['output_quantity'])
                        fee=_decimal(s['fee_rate_used'])
                        if None in (gross,spent,received,fee) or gross<=0 or fee>=Decimal('.05'):
                            mismatched=True;break
                        implied=(spent/(Decimal(1)+fee)/gross if side=='BUY'
                                 else received/(Decimal(1)-fee)/gross)
                        if expected<=0 or abs(implied/expected-1)>Decimal('.02'):
                            mismatched=True;break
                    except (KeyError,TypeError,ZeroDivisionError,InvalidOperation):
                        mismatched=True;break
                if mismatched:
                    self.rejected_quote+=1;self.rejected+=1;continue
            budget=risk_budgets or {}
            if budget:
                planned=_decimal(idea.get('research_size_cap_usd'))
                max_exposure=_decimal(budget.get('incremental_exposure_usd'))
                daily_buy=_decimal(budget.get('daily_buy_usd'))
                max_orders=int(budget.get('max_attempts',0))
                per_order=_decimal(budget.get('per_order_usd'))
                # Spend-and-redeploy over multiple routes is controlled by
                # an incremental exposure/day budget; no extra 'free' money.
                new_buys=Decimal(0)
                over_order=False
                try:
                    for step in steps:
                        base,quote=str(step['pair']).split('-')
                        asset=quote if str(step['side']).upper()=='BUY' else base
                        fx=budget_context.usd(asset)
                        if fx is None:raise ValueError('Missing strict source-currency FX')
                        value=step_input_usd(step,{asset:fx['rate']})
                        if per_order is None or per_order<=0 or value>per_order:
                            over_order=True
                        # One-order conversions consume turnover regardless of
                        # whether Coinbase calls their side BUY or SELL.
                        if len(steps)==1 or str(step['side']).upper()=='BUY':
                            new_buys+=value
                except (KeyError,ValueError,TypeError,InvalidOperation):
                    self.rejected_budget+=1;self.rejected+=1;continue
                used_attempts=sum(n for t,n in self.rolling_model_attempts)
                spent_daily=sum((v for t,v in self.daily_model_buys),Decimal(0))
                if (planned is None or max_exposure is None or daily_buy is None or
                        planned>max_exposure or new_buys+spent_daily>daily_buy or over_order or
                        max_orders<=0 or used_attempts+len(steps)>max_orders):
                    self.rejected_budget+=1;self.rejected+=1;continue
            if not self.experimental:self.validated_ideas+=1
            # Never duplicate the same live proposal on each GUI refresh or
            # repeat an unclosed scenario for the same source/destination.
            if selected:continue
            if self.experimental:
                market_key=decision_key(idea,books)
                if market_key in self.seen_market_decisions:
                    self.duplicate_decisions+=1;continue
            else:
                # Validated research keeps its independent evidence horizon.
                if any(e['source']==src and e['target']==dst and not e['matured'] for e in self.entries):continue
                key=(tuple(sorted(inputs)),dst)
                if now-self.last_selected_at.get(key,-1e12)<self.mark_horizon_s:continue
                self.last_selected_at[key]=now
                selected=True
            for band,bps in PRICE_BANDS_BPS:
                if self.experimental and band!='TAKER_ASK':continue
                self.screened_price_bands[band]+=1
                if len(self.entries)>=(MAX_EXPERIMENTAL_TRACKED if self.experimental else MAX_TRACKED):
                    continue
                ask=book[1]
                limit_price=ask*(Decimal(1)-bps/Decimal(10000))
                self.entry_sequence+=1
                new={
                    'source':src,'target':dst,'entry_pair':pair,'band':band,
                    'limit_price':limit_price,'created_at':now,
                    'source_units':source_units,'funding_inputs':dict(inputs),'target_units':target_units,
                    'state':'MODEL_TAKER_FILL' if bps==0 else 'PRICE_WAIT',
                    'touched_at':None,'mark_delta_usd':None,'matured':False,
                    'projected_net_p10_usd':None if self.experimental else net,
                    'experimental_repeat_trend_score_usd':str(net) if self.experimental else None,
                    'experimental_unvalidated':bool(self.experimental),
                    'experimental_decision_basis':('SNOWBALL_IMMEDIATE_ESTIMATE' if
                        self.experimental and idea.get('snowball_state')=='IMMEDIATE_ESTIMATE'
                        and _decimal(idea.get('snowball_immediate_usd')) is not None
                        and net==_decimal(idea.get('snowball_immediate_usd'))
                        else 'UNVALIDATED_MOMENTUM' if self.experimental else 'HELD_OUT_REVIEW'),
                    'joint_heldout_portfolio_validated':False,
                    'fifo_steps':idea.get('shadow_fifo_steps') or (),
                    'shadow_id':f'SHADOW-{int(now)}-{self.entry_sequence:08d}-{band}',
                    'fifo_state':'PRICE_WAIT' if bps else 'PENDING',
                }
                self.entries.append(new)
                if bps==0:
                    self.would_submit+=1
                    posted=self._post_fifo(new,usd_rates,now)
                    if self.experimental:
                        if posted:
                            selected=True;self.seen_market_decisions[market_key]=now
                            if new['experimental_decision_basis']=='SNOWBALL_IMMEDIATE_ESTIMATE':
                                self.experimental_snowball_posted+=1
                        else:
                            new['state']='MODEL_REJECTED'
                            self.entries.remove(new)
                    if posted and risk_budgets:
                        self.rolling_model_attempts.append((now,len(steps)))
                        self.daily_model_buys.append((now,new_buys))
        return True

    def snapshot(self,now=None):
        now=time.time() if now is None else float(now)
        hour=[n for t,n in self.hourly_model_fills if 0<=now-t<3600]
        counts={key:sum(e['band']==key for e in self.entries) for key,_ in PRICE_BANDS_BPS}
        pending=sum(e['state']=='PRICE_WAIT' for e in self.entries)
        fifo_bands={}
        for label,wallet in self.fifo_portfolios.items():
            try:
                fifo_bands[label]={'scenarios':wallet.scenarios,
                    'legs':wallet.legs, 'estimated_fees_usd':str(wallet.fees_estimated_usd),
                    'verified_quantity_parity':wallet.quantity_parity(),
                    'hold_relative_usd':'NOT VERIFIED WITHOUT FRESH USD MARKS'}
                try:
                    value=wallet.mark_vs_hold(self.last_usd_rates)
                    fifo_bands[label]['counterfactual_portfolio_vs_hold_usd']=str(value['delta_usd'])
                except (KeyError,ValueError,ShadowFIFOBlocked):
                    problems=wallet.mark_problems(self.last_usd_rates)
                    problems.update(getattr(self,'mark_problems',{}))
                    fifo_bands[label]['mark_problem_counts']={reason:list(problems.values()).count(reason)
                        for reason in sorted(set(problems.values()))}
                    reason=('FX SNAPSHOT UNSYNCHRONIZED' if 'UNSYNCHRONIZED_USD_PATHS' in problems.values()
                            else 'FX MARK INVALID' if 'INVALID_USD_MARK' in problems.values()
                            else 'FX MARK MISSING')
                    fifo_bands[label]['counterfactual_portfolio_vs_hold_usd']='NOT VERIFIED - '+reason
            except Exception:
                fifo_bands[label]={'status':'NOT VERIFIED'}
        return {'modeled_conversions_last_hour':len(hour),'modeled_legs_last_hour':sum(hour),
                'frequency_goal_per_hour':10,'duplicate_market_decisions':self.duplicate_decisions,
                'last_mark_observed_at':self.last_observation,'retained_outcome_entries':len(self.entries),
                'expired_outcome_entries':self.expired_outcome_entries,
                'armed':self.armed,'started_at':self.started_at,'stop_at':self.stop_at,
                'completed_fresh_scans':self.scans,'observed_book_snapshots':self.market_snapshots,
                'markets_reviewed':self.target_reviews,'ideas_reviewed':self.ideas_reviewed,
                'historically_qualified_route_reviews':self.validated_ideas,
                'unqualified_rejections':self.rejected,
                'model_taker_intents':self.would_submit,
                'passive_price_touches_without_fill_proof':self.touch_only,
                'pending_limit_price_scenarios':pending,
                'marked_counterfactuals':self.matured,
                'marked_positive':self.marked_positive,'marked_nonpositive':self.marked_negative,
                'aggregate_counterfactual_vs_hold_usd':str(self.marked_usd_total),
                'band_scenarios':counts,
                'band_reviews':dict(self.screened_price_bands),
                'band_touches':dict(self.price_touch_bands),
                'missing_future_usd_marks':self.missing_usd_marks,
                'stale_or_unavailable_books':self.stale_books,
                'real_order_submissions':0,'real_fill_confirmations':0,
                'execution_certified':False,'estimated_actual_live_result_available':False,
                'shadow_fifo_posted_routes':self.fifo_posted,
                'shadow_fifo_posted_legs':self.fifo_posted_legs,
                'shadow_fifo_rejected':self.fifo_rejected,
                'shadow_fifo_bands':fifo_bands,
                'modeled_current_balances':{k:str(v) for k,v in self.model_balances().items()},
                'modeled_basket_scenarios':sum(e['source']=='MULTI' for e in self.entries),
                'rejected_quote_freshness_or_drift':self.rejected_quote,
                'rejected_shadow_budget':self.rejected_budget,
                'rolling_24h_model_attempts':sum(n for t,n in self.rolling_model_attempts if 0<=now-t<86400),
                'rolling_24h_modeled_buy_usd':str(sum((v for t,v in self.daily_model_buys if 0<=now-t<86400),Decimal(0))),
                'rolling_24h_modeled_turnover_usd':str(sum((v for t,v in self.daily_model_buys if 0<=now-t<86400),Decimal(0))),
                'not_live_equivalent_without_depth_partial_fill_recovery':True,
                'shadow_fifo_uses_production_db':False,
                'experimental':self.experimental,
                'experimental_snowball_fifo_count':self.experimental_snowball_posted,
                'experimental_screened':self.experimental_screened,
                'experimental_heuristic_accepted':self.experimental_candidates,
                'experimental_heuristic_rejected':self.experimental_heuristic_rejected,
                'experimental_forward_horizons':{str(h):dict(v) for h,v in self.experimental_horizons.items()}}


def shadow_report(app):
    shadow=getattr(app,'shadow_pilot',None)
    if shadow is None:
        return 'ARM SHADOW component missing • NOT VERIFIED'
    s=shadow.snapshot()
    lines=[
        'CoinCat v60.7.1 • EVOLVING PORTFOLIO SHADOW / PRICE-BAND RESEARCH',
        'REAL Coinbase read-only snapshots when connected; MODELLED orders and fills ONLY.',
        'NO Coinbase POST, NO financial/tax ledger writes, NO real ARM, NO change to broker caps.',
        'SHADOW STATE: '+('ARMED SHADOW — LIVE ORDERS DISABLED' if s['armed'] else 'DISARMED SHADOW'),
        'SHADOW STOP REASON: '+('RUNNING' if s['armed'] else str(getattr(app,'_shadow_stop_reason','UNKNOWN'))),
        f'Completed independent new market scans: {s["completed_fresh_scans"]}',
        f'Fresh book snapshots observed: {s["observed_book_snapshots"]}',
        f'AI research items reviewed: {s["markets_reviewed"]}',
        'SHADOW budget mode: '+str(getattr(app,'_manual_budget_saved',{}).get('mode','MANUAL'))+' (no LIVE authorization)',
        f'HOLD/SWITCH route ideas reviewed: {s["ideas_reviewed"]}',
        f'Held-out qualifying route reviews: {s["historically_qualified_route_reviews"]}',
        f'Rejected/insufficient evidence: {s["unqualified_rejections"]}',
        'Scenario price bands: market ask (model taker), ask -5bps, ask -20bps, ask -50bps',
    ]
    for band,_ in PRICE_BANDS_BPS:
        lines.append(f'  {band}: reviews={s["band_reviews"][band]}, '
                     f'scenarios={s["band_scenarios"][band]}, price_touches={s["band_touches"][band]}')
    lines+= [
        f'Model taker-entry intents (NOT real fills): {s["model_taker_intents"]}',
        f'Passive quote-price touches (NOT proof of fills): {s["passive_price_touches_without_fill_proof"]}',
        f'SHADOW ONLY, isolated in-memory FIFO modeled routes: {s["shadow_fifo_posted_routes"]}',
        f'SHADOW ONLY, isolated in-memory FIFO modeled legs: {s["shadow_fifo_posted_legs"]}',
        f'FIFO blocked/refused candidate routes: {s["shadow_fifo_rejected"]}',
        f'Modeled multi-source baskets: {s["modeled_basket_scenarios"]} (joint portfolio edge NOT CERTIFIED)',
        'CURRENT EVOLVED SHADOW INVENTORY: REDACTED • currencies in wallet='+
            str(len(s['modeled_current_balances']))+' • exact assets/quantities excluded from shared report',
        f'24h modeled attempts: {s["rolling_24h_model_attempts"]}',
        f'24h modeled BUY notional USD: {s["rolling_24h_modeled_buy_usd"]}',
        f'SHADOW risk/budget rejects: {s["rejected_shadow_budget"]}',
        f'SHADOW stale/drift quote rejects: {s["rejected_quote_freshness_or_drift"]}',
        'SHADOW simulated market-taker fills only; passive touches NEVER create strict-mode FIFO fills.',
        'Decisions after simulated fills use EVOLVED inventory, not the original real-wallet asset mix.',
        'FIFO price-band states: '+str(s['shadow_fifo_bands']),
        'Simulated FIFO reuses currency-neutral lot rules; tax basis remains UNKNOWN. NO real financial records touched.',
        f'Matured later-market-mark counterfactuals: {s["marked_counterfactuals"]}',
        f'Counterfactual positive/nonpositive: {s["marked_positive"]}/{s["marked_nonpositive"]}',
        f'Aggregate scenario USD difference vs unrotated HOLD (NOT actual P&L): {s["aggregate_counterfactual_vs_hold_usd"]}',
        'NO CLAIM of how many real Coinbase orders WOULD have filled: depth, queue position, latency, partial fills, cancellation and slippage not measured.',
        'UI fast review reuses the most recent actual completed market scan; it creates NO new independent prices, no synthetic trade repetitions.',
        '[NOT VERIFIED] Actual live outcome, true price improvement, realized fees, whole-portfolio performance and predictive advantage.',
        '[BLOCKED] Production multi-quote FIFO, atomic exchange order recovery and certified portfolio loss floor.',
        '[PASS / CODE DESIGN] Shadow component contains NO exchange SDK, live broker or order-submission method.',
        'END ARM SHADOW RESEARCH',
    ]
    return '\n'.join(lines)


def experimental_shadow_report(app):
    """Session-only, redacted non-executable experiment accounting evidence."""
    obj=getattr(app,'experimental_shadow',None)
    if obj is None:return 'EXPERIMENTAL SHADOW: NOT INSTALLED'
    s=obj.snapshot()
    value=(s.get('shadow_fifo_bands') or {}).get('TAKER_ASK',{})
    stamp=s.get('last_mark_observed_at')
    mark_age=max(0,int(time.time()-stamp)) if stamp else None
    from coincat_v606_budgets import DEFAULT
    settings=getattr(app,'_manual_budget_saved',DEFAULT)
    attempts=int(settings.get('attempts_24h',DEFAULT['attempts_24h']))
    return '\n'.join([
        'CoinCat v60.17 • EXPERIMENTAL SHADOW (UNVALIDATED WHAT-IF)',
        'SEPARATE IN-MEMORY FIFO • independently ARMED • NO financial/tax ledger writes',
        'No real Coinbase order POST and NO permissions to the validated SHADOW or LIVE path.',
        'Experimental mode: '+('ARMED' if s['armed'] else 'DISARMED'),
        'Completed market scan observations: '+str(s['completed_fresh_scans']),
        'Costed one-order ideas screened: '+str(s['experimental_screened']),
        'Hypothetical repeat-observed-momentum scores clearing provisional filter: '+str(s['experimental_heuristic_accepted']),
        'Rejected by provisional filter: '+str(s['experimental_heuristic_rejected']),
        'Simulated taker FIFO routes: '+str(s['shadow_fifo_posted_routes']),
        'Simulated taker FIFO legs: '+str(s['shadow_fifo_posted_legs']),
        'Modeled conversions / legs in the last rolling hour: '+str(s['modeled_conversions_last_hour'])+'/'+str(s['modeled_legs_last_hour']),
        'Frequency goal: 10 conversions/hour; no forced fills or guaranteed live frequency.',
        'Saved conversion limit / 24h: '+str(attempts)+
            (' — below 240 needed to permit 10/hour for a full day' if attempts<240 else ' (capacity only)'),
        '24h modeled conversion turnover USD / saved limit: '+s['rolling_24h_modeled_turnover_usd']+'/'+str(settings.get('daily_buy_usd','UNAVAILABLE')),
        'One-leg turnover counts BUY and SELL input value; order/exposure caps remain limited by verified fuel.',
        'Last wallet mark age seconds: '+str(mark_age if mark_age is not None else 'UNAVAILABLE')+
            (' — STALE' if mark_age is not None and mark_age>30 else ''),
        'Duplicate same-market-observation decisions suppressed: '+str(s['duplicate_market_decisions']),
        'Retained outcome entries / expired without complete marks: '+str(s['retained_outcome_entries'])+'/'+str(s['expired_outcome_entries']),
        'Of these, Snowball immediate-estimate experimental FIFO: '+str(s['experimental_snowball_fifo_count']),
        'Estimated modeled exchange fees USD: '+str(value.get('estimated_fees_usd','NOT VERIFIED')),
        'Evolving experimental wallet vs same-time frozen HOLD USD: '+str(value.get('counterfactual_portfolio_vs_hold_usd','NOT VERIFIED')),
        '5-minute matured entry-slice counterfactuals: '+str(s['marked_counterfactuals']),
        'Experiment independently observed 5/15/60m slices (not predictive): '+
            str(s['experimental_forward_horizons']),
        'Outcome windows permit at most 120s observation delay; missing windows are not backfilled as later wins.',
        'Matured outcomes positive/nonpositive: '+str(s['marked_positive'])+'/'+str(s['marked_nonpositive']),
        'Budget and market-quote rejects: '+str(s['rejected_shadow_budget'])+'/'+str(s['rejected_quote_freshness_or_drift']),
        'Existing validated SHADOW FIFO: STRICT HELD-OUT RULES UNCHANGED',
        'Experimental routing uses provisional momentum OR strict synchronized immediate-USD estimates; neither is certified execution or a forecast.',
        'No guarantee of real execution, fees, liquidity, partial fills or profitable forward outcomes.',
        'Experiment is not trained execution evidence and cannot authorize real Coinbase orders.',
        'END EXPERIMENTAL SHADOW',
    ])
