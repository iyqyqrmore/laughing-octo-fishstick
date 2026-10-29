"""Passive fixed-proposal observations and deadline-only quote requirements.

No winner, sizing, settings, financial writes, forecasts or execution authority.
"""
from collections import Counter
from decimal import Decimal, localcontext
from coincat_cross_quote import usd_conversion
from coincat_v701_quotes import valid_book
from coincat_v80_discovery import book_status

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

    def quote_groups(self, *, now, listed=()):
        """Pure requirements, earliest deadline first; never inspect gains/sizes.

        These groups compete within the scanner's existing GET budget. Quota
        and fair discovery are scanner policy, not Lab recommendations.
        """
        grouped={}
        for row in self.pending.values():
            for horizon in HORIZONS:
                earliest=row['at']+horizon
                deadline=earliest+ENDPOINT_GRACE_S
                if horizon in row['done'] or not earliest<=now<=deadline:
                    continue
                books=set(row['source_path'])|set(row['target_path'])
                if 'ETH-USD' in listed:
                    books.add('ETH-USD')
                key=tuple(sorted(books))
                if key in grouped:
                    grouped[key]['earliest']=max(grouped[key]['earliest'],earliest)
                    grouped[key]['deadline']=min(grouped[key]['deadline'],deadline)
                else:
                    grouped[key]={'books':key,'earliest':earliest,'deadline':deadline}
        return sorted(grouped.values(),key=lambda g:(g['deadline'],g['books']))

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

    def observe(self, result, quotes, *, now):
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
                    row['blocked'][horizon]=reason
                    continue
                self.counts[f'{horizon}_'+('ABOVE_HOLD' if advantage>0 else 'NOT_ABOVE_HOLD')]+=1
                ref=valid_book(quotes.get('ETH-USD'),now,30,Decimal('.0025'))
                if (ref is None or ref[2]<row['at']+horizon or
                        (stamps and max(stamps+[ref[2]])-min(stamps+[ref[2]])>12)):
                    self.eth_counts[f'{horizon}_UNPRICED']+=1
                else:
                    self.eth_counts[f'{horizon}_'+('ABOVE_HOLD' if advantage/ref[0]>0 else 'NOT_ABOVE_HOLD')]+=1
                row['done'].add(horizon)
            if len(row['done'])==len(HORIZONS):
                del self.pending[key]
        # One retained proposal per direction per five minutes. Frozen paths
        # and quantities are RAM-only observations, never a simulated wallet.
        self.seen={key:stamp for key,stamp in self.seen.items() if 0<=now-stamp<=300}
        for candidate in result.get('ranked',()):
            direction=(candidate['pair'],candidate['side'])
            self.counts['reviewed_sizes']+=1
            self.counts['positive_sizes' if candidate['w']>0 else 'nonpositive_sizes']+=1
            if direction in self.seen:
                continue
            if len(self.pending)>=self.capacity:
                self.counts['CAPACITY_DEFERRED']+=1
                continue
            frame=candidate['frame'];key=frame['id']
            if key in self.pending:
                continue
            pair=candidate['pair']
            self.pending[key]={'at':now,'source':candidate['source'],'target':candidate['target'],
                'spent':candidate['spent'],'received':candidate['received'],'done':set(),'blocked':{},
                'source_path':tuple(frame['source_path']),'target_path':tuple(frame['target_path']),
                'excluded':() if 'USD' in pair.split('-') else (pair,)}
            self.seen[direction]=now
            self.counts['recorded_proposals']+=1
        if self.last_report_at is not None and now-self.last_report_at<self.report_interval_s:
            return None
        self.last_report_at=now
        outcomes={key:value for key,value in self.counts.items() if key[0].isdigit()}
        completion={h:{'completed':self.counts[f'{h}_ABOVE_HOLD']+self.counts[f'{h}_NOT_ABOVE_HOLD'],
                       'missed':self.counts[f'{h}_MISSED']} for h in HORIZONS}
        text=(f"Passive AI Lab - {self.counts['reviewed_sizes']} full-balance estimates reviewed; "
            f"{self.counts['positive_sizes']} positive at observation. "
            f"{result.get('priced_directions',0)}/{result.get('eligible_directions',0)} directions priced in the latest pass.\n"
            f"Later comparisons with HOLD (5/15/60 min): {outcomes or 'waiting for future quotes'}. "
            f"Pending {len(self.pending)}; capacity deferred {self.counts['CAPACITY_DEFERRED']}.\n"
            f"Completed versus missed by horizon: {completion}. Missed causes: {dict(self.missed_causes)}. "
            'Missing endpoints are not losses; bounded scheduling cannot guarantee every observation.\n'
            f"Same comparisons expressed in ETH at each endpoint (not return-to-ETH proceeds): {dict(self.eth_counts)}.\n"
            'These are correlated, hypothetical price comparisons, not fills or realized profit. '
            'I do not select trades, change sizes or impose portfolio limits.')
        self.notes.append((now,text));self.notes=self.notes[-100:]
        return text
