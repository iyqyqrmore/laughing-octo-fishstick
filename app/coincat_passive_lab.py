"""Passive fixed-proposal observations and deadline-only quote requirements.

No winner, sizing, settings, financial writes, forecasts or execution authority.
"""
from collections import Counter
from decimal import Decimal, localcontext
from coincat_cross_quote import usd_conversion
from coincat_v701_quotes import valid_book
from coincat_v80_discovery import book_status
from coincat_research_admission import AdmissionCalendar, service_period

HORIZONS = (300, 900, 3600)
ENDPOINT_GRACE_S = 120


class PassiveLab:
    def __init__(self, *, report_interval_s=180, capacity=512):
        self.report_interval_s=report_interval_s
        self.capacity=capacity
        self.pending={}
        self.seen={}
        self.counts=Counter()
        self.last_report_at=None
        self.notes=[]
        self.eth_counts=Counter()
        self.missed_causes=Counter()
        self.admission=Counter();self.admission_reasons=Counter()
        self.decisions={};self.period=12
        self.admission_cursor=0
        self.horizon_stats={h:Counter() for h in HORIZONS}
        self.failure_causes={h:Counter() for h in HORIZONS}
        self.eth_failure_causes={h:Counter() for h in HORIZONS}
        self.service_wait={h:0 for h in HORIZONS}

    def quote_groups(self, *, now, listed=()):
        """Pure fixed-path requirements; horizon debt protects hourly service."""
        grouped={}
        for key,row in self.pending.items():
            for horizon in HORIZONS:
                earliest=row['at']+horizon
                deadline=earliest+ENDPOINT_GRACE_S
                if (horizon in row['done'] or not earliest<=now<=deadline or
                        now<row.get('retry_after',{}).get(horizon,0)):
                    continue
                books=tuple(row['books'])
                identity=(horizon,books)
                if identity not in grouped:
                    grouped[identity]={'books':books,'earliest':earliest,'deadline':deadline,
                        'horizon':horizon,'wait_passes':self.service_wait[horizon],'jobs':[]}
                group=grouped[identity]
                group['earliest']=max(group['earliest'],earliest)
                group['deadline']=min(group['deadline'],deadline)
                group['jobs'].append((key,horizon))
        return sorted(grouped.values(),key=lambda g:(g['deadline'],g['books']))

    def record_service(self, plan, incoming, errors, *, now):
        """Commit scheduling evidence only after the collector's STOP check."""
        due=set(plan.get('_research_due',()))
        scheduled=set(plan.get('_research_scheduled',()))
        deferred=set(plan.get('_research_deferred',()))
        unavailable=set(plan.get('_research_unavailable',()))
        for horizon in HORIZONS:
            active=any(h==horizon for key,h in due)
            served=any(h==horizon for key,h in scheduled)
            if served:
                stats=self.horizon_stats[horizon]
                stats['max_wait_before_service_passes']=max(stats['max_wait_before_service_passes'],self.service_wait[horizon])
            self.service_wait[horizon]=0 if served or not active else self.service_wait[horizon]+1
        by_product=getattr(errors,'by_product',{})
        for key,horizon in due:
            row=self.pending.get(key)
            if row is None or horizon in row['done']:
                continue
            stats=self.horizon_stats[horizon]
            if (key,horizon) in unavailable:
                row['blocked'][horizon]='PRODUCT_UNAVAILABLE'
                stats['unavailable_attempts']+=1
                continue
            if (key,horizon) in deferred:
                stats['request_deferral_attempts']+=1
                if horizon not in row['deferred']:
                    stats['distinct_deferred_observations']+=1
                    row['deferred'].add(horizon)
                row['blocked'][horizon]='RESEARCH_SHARE_DEFERRED'
                continue
            if (key,horizon) not in scheduled:
                continue
            stats['scheduled_attempts']+=1
            if horizon not in row['scheduled']:
                stats['distinct_scheduled_observations']+=1
                row['scheduled'].add(horizon)
            row['attempted_at'][horizon]=now
            row['transport_failure'].pop(horizon,None)
            row.setdefault('reference_failure',{}).pop(horizon,None)
            missing=[p for p in row['books'] if p in plan['books'] and p not in incoming]
            if missing:
                reasons={by_product.get(p,'NO_ON_TIME_QUOTE') for p in missing}
                cause='REQUEST_'+sorted(reasons)[0]
                row['transport_failure'][horizon]=cause
                if 'ETH-USD' in missing:
                    row['reference_failure'][horizon]='REQUEST_'+by_product.get('ETH-USD','NO_ON_TIME_QUOTE')

    def diagnostics(self):
        """Only counts/reasons; observation IDs, products and quantities stay private."""
        horizons={}
        done_snapshot=[frozenset(row['done']) for row in list(self.pending.values())]
        missed_snapshot=dict(self.missed_causes)
        for h in HORIZONS:
            values=dict(self.horizon_stats[h])
            for field in ('scheduled_attempts','distinct_scheduled_observations','request_deferral_attempts',
                          'distinct_deferred_observations','unavailable_attempts','failed_attempts',
                          'max_wait_before_service_passes'):
                values.setdefault(field,0)
            values.update(admitted=self.admission['admitted_distinct'],
                not_admitted=self.admission['not_admitted_distinct'],
                completed=self.counts[f'{h}_ABOVE_HOLD']+self.counts[f'{h}_NOT_ABOVE_HOLD'],
                missed=self.counts[f'{h}_MISSED'],
                pending=sum(h not in done for done in done_snapshot),
                terminal_missed_causes={k[len(str(h))+1:]:v for k,v in missed_snapshot.items() if k.startswith(str(h)+'_')},
                attempt_failure_causes=dict(self.failure_causes[h]),
                eth_unpriced=self.eth_counts[f'{h}_UNPRICED'],
                eth_unpriced_causes=dict(self.eth_failure_causes[h]),
                waiting_service_passes=self.service_wait[h])
            horizons[str(h)]=values
        admission={field:self.admission[field] for field in ('considered_distinct','admitted_distinct',
            'not_admitted_distinct','repeated_review_attempts','repeated_not_admitted_review_attempts',
            'forecast_guard_passes','decision_tracking_overflow_attempts')}
        admission['not_admitted_review_attempts']=admission['not_admitted_distinct']+admission['repeated_not_admitted_review_attempts']
        return {'admission':admission,'not_admitted_reasons':dict(self.admission_reasons),
            'distinct_definition':'ONE_DIRECTION_REVIEW_PER_300_SECONDS; CORRELATED_NOT_INDEPENDENT',
            'forecast_service_period_s':self.period,'horizons':horizons}

    @staticmethod
    def _comparison(row, quotes, *, now, earliest):
        paths=[];stamps=[]
        for asset,path in ((row['source'],row['source_path']),(row['target'],row['target_path'])):
            books={}
            for pair in path:
                state=book_status(quotes.get(pair),now)
                if state!='FRESH':
                    return None,'BOOK_'+state,[]
                book=valid_book(quotes[pair],now,30,Decimal('.0025'))
                if book[2]<earliest:
                    return None,'BOOK_BEFORE_HORIZON',[]
                books[pair]=book;stamps.append(book[2])
            fx=usd_conversion(asset,books,now=now,max_age=30,excluded_pairs=row['excluded'])
            if fx is None or tuple(fx['path'])!=tuple(path):
                return None,'FIXED_MARK_PATH_UNAVAILABLE',[]
            paths.append(fx)
        if stamps and max(stamps)-min(stamps)>12:
            return None,'PRICE_SKEW',[]
        with localcontext() as ctx:
            ctx.prec=60
            advantage=row['received']*paths[1]['rate']-row['spent']*paths[0]['rate']
        return advantage,None,stamps

    def observe(self, result, quotes, *, now, scan_interval_s=5, listed=None):
        self.period=service_period(scan_interval_s)
        for key,row in list(self.pending.items()):
            elapsed=now-row['at']
            for horizon in HORIZONS:
                if horizon in row['done'] or elapsed<horizon:
                    continue
                if elapsed>horizon+ENDPOINT_GRACE_S:
                    self.counts[f'{horizon}_MISSED']+=1
                    self.eth_counts[f'{horizon}_MISSED']+=1
                    cause=row['blocked'].get(horizon,'NOT_OBSERVED_WITHIN_WINDOW')
                    self.missed_causes[f'{horizon}_'+cause]+=1
                    row['done'].add(horizon)
                    continue
                advantage,reason,stamps=self._comparison(row,quotes,now=now,earliest=row['at']+horizon)
                if reason:
                    prior=row['blocked'].get(horizon)
                    cause=row['transport_failure'].get(horizon)
                    if cause is None and reason in ('BOOK_STALE','BOOK_UNOBSERVED','BOOK_BEFORE_HORIZON'):
                        cause=prior if prior in ('RESEARCH_SHARE_DEFERRED','PRODUCT_UNAVAILABLE') else reason
                    cause=cause or reason
                    row['blocked'][horizon]=cause
                    if row['attempted_at'].get(horizon)==now:
                        self.failure_causes[horizon][cause]+=1
                        self.horizon_stats[horizon]['failed_attempts']+=1
                        row['retry_after'][horizon]=now+self.period
                    continue
                self.counts[f'{horizon}_'+('ABOVE_HOLD' if advantage>0 else 'NOT_ABOVE_HOLD')]+=1
                stats=self.horizon_stats[horizon]
                stats['max_completion_lag_s']=max(stats['max_completion_lag_s'],elapsed-horizon)
                stats['max_completion_quote_span_s']=max(stats['max_completion_quote_span_s'],max(stamps)-min(stamps) if stamps else 0)
                ref=valid_book(quotes.get('ETH-USD'),now,30,Decimal('.0025'))
                if (ref is None or ref[2]<row['at']+horizon or
                        (stamps and max(stamps+[ref[2]])-min(stamps+[ref[2]])>12)):
                    self.eth_counts[f'{horizon}_UNPRICED']+=1
                    cause=row.get('reference_failure',{}).get(horizon)
                    if cause is None:
                        cause=('REFERENCE_'+book_status(quotes.get('ETH-USD'),now) if ref is None else
                               'REFERENCE_BEFORE_HORIZON' if ref[2]<row['at']+horizon else 'REFERENCE_PRICE_SKEW')
                    self.eth_failure_causes[horizon][cause]+=1
                else:
                    self.eth_counts[f'{horizon}_'+('ABOVE_HOLD' if advantage/ref[0]>0 else 'NOT_ABOVE_HOLD')]+=1
                row['done'].add(horizon)
            if len(row['done'])==len(HORIZONS):
                del self.pending[key]
        # Reforecast remaining commitments at the actual manual cadence. Existing
        # observations are never reclassified as not admitted if cadence/transport changes.
        calendar=AdmissionCalendar(now=now,period=self.period)
        for row in sorted(self.pending.values(),key=lambda r:r['at']):
            if not calendar.reserve(row)[0]:
                calendar.overloaded=True
        if calendar.overloaded:
            self.admission['forecast_guard_passes']+=1
        self.decisions={d:v for d,v in self.decisions.items() if 0<=now-v['at']<600}
        self.seen={d:v['at'] for d,v in self.decisions.items()}
        listed=set(quotes if listed is None else listed)
        candidates=sorted(result.get('ranked',()),key=lambda c:(c['pair'],c['side']))
        if candidates:
            offset=self.admission_cursor%len(candidates)
            candidates=candidates[offset:]+candidates[:offset]
        considered_before=self.admission['considered_distinct']
        admitted_before=self.admission['admitted_distinct']
        for candidate in candidates:
            direction=(candidate['pair'],candidate['side'])
            self.counts['reviewed_sizes']+=1
            self.counts['positive_sizes' if candidate['w']>0 else 'nonpositive_sizes']+=1
            previous=self.decisions.get(direction)
            if previous is not None and now-previous['at']<300:
                self.admission['repeated_review_attempts']+=1
                if previous['decision']=='not_admitted':
                    self.admission['repeated_not_admitted_review_attempts']+=1
                    if len(self.pending)>=self.capacity:
                        self.counts['CAPACITY_DEFERRED']+=1
                continue
            # Bound the distinct-decision ledger without pretending untracked
            # review attempts are known-distinct observations.
            if direction not in self.decisions and len(self.decisions)>=4096:
                self.admission['decision_tracking_overflow_attempts']+=1
                continue
            self.admission['considered_distinct']+=1
            frame=candidate['frame'];key=frame['id'];pair=candidate['pair']
            books=set(frame['source_path'])|set(frame['target_path'])
            if 'ETH-USD' in listed:
                books.add('ETH-USD')
            row={'at':now,'source':candidate['source'],'target':candidate['target'],
                'spent':candidate['spent'],'received':candidate['received'],'done':set(),'blocked':{},
                'source_path':tuple(frame['source_path']),'target_path':tuple(frame['target_path']),
                'excluded':() if 'USD' in pair.split('-') else (pair,), 'books':tuple(sorted(books)),
                'scheduled':set(),'deferred':set(),'attempted_at':{},'transport_failure':{},
                'reference_failure':{},'retry_after':{}}
            reason=None
            if len(self.pending)>=self.capacity:
                reason='RAM_CAPACITY';self.counts['CAPACITY_DEFERRED']+=1
            elif key in self.pending:
                reason='DUPLICATE_FRAME'
            elif not 0<=now-frame['at']<=30:
                reason='STALE_PROPOSAL'
            elif not books or len(books)>6:
                reason='DEPENDENCIES_EXCEED_RESEARCH_SHARE'
            elif result.get('quote_errors'):
                reason='TRANSPORT_ERRORS_OR_BACKOFF'
            elif any(book_status(quotes.get(p),now)!='FRESH' for p in books):
                reason='DEPENDENCIES_NOT_CURRENTLY_USABLE'
            elif calendar.overloaded:
                reason='CONSERVATIVE_FORECAST_FULL'
            else:
                accepted,reason=calendar.reserve(row)
            decision='not_admitted' if reason else 'admitted'
            self.decisions[direction]={'at':now,'decision':decision,'reason':reason}
            self.seen[direction]=now
            if reason:
                self.admission['not_admitted_distinct']+=1
                self.admission_reasons[reason]+=1
                continue
            self.pending[key]=row
            self.admission['admitted_distinct']+=1
            self.counts['recorded_proposals']+=1
        if self.admission['considered_distinct']>considered_before:
            self.admission_cursor+=max(1,self.admission['admitted_distinct']-admitted_before)
        if self.last_report_at is not None and now-self.last_report_at<self.report_interval_s:
            return None
        self.last_report_at=now
        evidence=self.diagnostics()
        completion='; '.join(
            f"{h//60}m: {evidence['horizons'][str(h)]['completed']} completed, "
            f"{evidence['horizons'][str(h)]['missed']} missed, "
            f"{evidence['horizons'][str(h)]['pending']} pending" for h in HORIZONS)
        text=(f"Passive AI Lab - {self.counts['reviewed_sizes']} full-balance estimates reviewed; "
            f"{self.counts['positive_sizes']} positive at observation. "
            f"{result.get('priced_directions',0)}/{result.get('eligible_directions',0)} directions priced in the latest pass.\n"
            f"Later hypothetical comparisons with HOLD: {completion}.\n"
            f"Pending {len(self.pending)}; distinct not admitted {self.admission['not_admitted_distinct']}; "
            f"repeated refused reviews {self.admission['repeated_not_admitted_review_attempts']}.\n"
            'Detailed per-horizon admissions, retries and failure causes are in Export diagnostics. '
            'Missing endpoints are not losses; bounded scheduling cannot guarantee every observation.\n'
            'ETH endpoint comparisons require a synchronized reference and are not return-to-ETH proceeds.\n'
            'These are correlated, hypothetical price comparisons, not fills or realized profit. '
            'I do not select trades, change sizes or impose portfolio limits.')
        self.notes.append((now,text));self.notes=self.notes[-100:]
        return text
