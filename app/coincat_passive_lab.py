"""Passive observations of fixed proposals. No gates, forecasts or wallet posts."""
from collections import Counter
from decimal import Decimal
from coincat_cross_quote import usd_conversion


class PassiveLab:
    def __init__(self, *, report_interval_s=180, capacity=512):
        self.report_interval_s=report_interval_s
        self.capacity=capacity
        self.pending={}
        self.seen={}
        self.counts=Counter()
        self.last_report_at=None
        self.notes=[]

    def observe(self, result, quotes, *, now):
        for key,row in list(self.pending.items()):
            elapsed=now-row['at']
            for horizon in (300,900,3600):
                if horizon in row['done'] or elapsed<horizon:continue
                if elapsed>horizon+120:
                    self.counts[f'{horizon}_MISSED']+=1;row['done'].add(horizon);continue
                paths=[]
                for asset in (row['source'],row['target']):
                    fx=usd_conversion(asset,quotes,now=now,max_age=30)
                    if fx is None or any(p in row['excluded'] for p in fx['path']):break
                    paths.append(fx)
                if len(paths)!=2:continue
                stamps=[quotes[p][2] for fx in paths for p in fx['path']]
                if stamps and max(stamps)-min(stamps)>12:continue
                advantage=row['received']*paths[1]['rate']-row['spent']*paths[0]['rate']
                self.counts[f'{horizon}_'+('ABOVE_HOLD' if advantage>0 else 'NOT_ABOVE_HOLD')]+=1
                row['done'].add(horizon)
            if len(row['done'])==3:del self.pending[key]
        # At most one observed proposal per direction in a five-minute bin.
        # Records stay in RAM; quantities are never written into market tables.
        self.seen={key:stamp for key,stamp in self.seen.items() if now-stamp<=300}
        for candidate in result.get('ranked',()):
            direction=(candidate['pair'],candidate['side'])
            self.counts['reviewed_sizes']+=1
            self.counts['positive_sizes' if candidate['w']>0 else 'nonpositive_sizes']+=1
            if direction in self.seen:continue
            if len(self.pending)>=self.capacity:
                self.counts['CAPACITY_DEFERRED']+=1;continue
            key=candidate['frame']['id']
            if key in self.pending:continue
            pair=candidate['pair']
            self.pending[key]={'at':now,'source':candidate['source'],'target':candidate['target'],
                'spent':candidate['spent'],'received':candidate['received'],'done':set(),
                'excluded':() if 'USD' in pair.split('-') else (pair,)}
            self.seen[direction]=now
            self.counts['recorded_proposals']+=1
        if self.last_report_at is not None and now-self.last_report_at<self.report_interval_s:return None
        self.last_report_at=now
        outcomes={key:value for key,value in self.counts.items() if key[0].isdigit()}
        text=(f"Passive AI Lab - {self.counts['reviewed_sizes']} full-balance estimates reviewed; "
            f"{self.counts['positive_sizes']} positive at observation. "
            f"{result.get('priced_directions',0)}/{result.get('eligible_directions',0)} directions priced in the latest pass.\n"
            f"Later comparisons with HOLD (5/15/60 min): {outcomes or 'waiting for future quotes'}. "
            f"Pending {len(self.pending)}; deferred {self.counts['CAPACITY_DEFERRED']}.\n"
            'These are correlated, hypothetical price comparisons, not fills or realized profit. '
            'I do not select trades, change sizes or impose portfolio limits.')
        self.notes.append((now,text));self.notes=self.notes[-100:]
        return text
