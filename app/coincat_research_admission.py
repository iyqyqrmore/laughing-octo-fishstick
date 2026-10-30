"""Conservative RAM-only quote-capacity forecast. No financial authority."""
import math

HORIZONS = (300, 900, 3600)
GRACE_S = 120
RESEARCH_BOOKS = 6


def service_period(scan_interval_s):
    pause=float(scan_interval_s)
    if not math.isfinite(pause) or not 5<=pause<=60:
        raise ValueError('SCAN_INTERVAL_OUT_OF_BOUNDS')
    # Full 6s collection deadline plus 1s scheduling margin, even if the
    # latest collection was faster. This is a forecast, not a service guarantee.
    return pause+7


class AdmissionCalendar:
    """One fair turn per horizon per three service slots; atomic reservations.

    All three jobs must fit their [horizon, horizon+120s] windows. Charge the
    union of required products in each slot, never assumed quote prices.
    """
    def __init__(self, *, now, period):
        self.now=now
        self.period=period
        self.slots={}
        self.overloaded=False

    def reserve(self, row):
        trial=dict(self.slots)
        for index,horizon in enumerate(HORIZONS):
            if horizon in row['done']:
                continue
            due=row['at']+horizon
            deadline=due+GRACE_S
            start=max(self.now,due,row.get('retry_after',{}).get(horizon,0))
            # Leave a turn of slack on both sides for scan alignment. Never
            # claim an observation fits by reserving after its expiry.
            slot=math.ceil((start+self.period)/self.period)
            slot+=(index-slot)%len(HORIZONS)
            accepted=False
            while slot*self.period<=deadline-self.period:
                existing=trial.get(slot,frozenset())
                merged=existing|frozenset(row['books'])
                if len(merged)<=RESEARCH_BOOKS:
                    trial[slot]=merged
                    accepted=True
                    break
                slot+=len(HORIZONS)
            if not accepted:
                return False,'NO_SERVICE_CAPACITY_'+str(horizon)
        self.slots=trial
        return True,None
