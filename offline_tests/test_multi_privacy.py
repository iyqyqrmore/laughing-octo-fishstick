from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from coincat_multi_trader import MultiTrader
from coincat_multi_public import validate
from coincat_monitor import capture,encode,validate as validate_snapshot
from coincat_history_public import validate as validate_history
from offline_tests.multi_fixtures import Clock,predictions,observed
from offline_tests import test_multi_backfill as backfill_fixture

class Privacy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Clock();cls.forecasts=predictions(cls.c)
    def public(self):
        with TemporaryDirectory() as tmp:
            engine=MultiTrader(Path(tmp)/'trial.sqlite3',clock=self.c.wall,monotonic_ns=self.c.ns);engine.start();engine.review(observed(self.c,self.forecasts))
            return engine.public(),engine.state()['trial_id']
    def test_only_fixed_codes_integer_counts_and_declared_enums_leave_multi_projection(self):
        p,secret=self.public();validate(p);raw=json.dumps(p)
        for text in (secret,'OPP-','wallet','native_price','source_budget','forecast_provenance','fee_currency','projected_advantage_usd'):self.assertNotIn(text,raw)
        for location in ((),('horizons',),('horizons','M5'),('horizons','M5','rejections'),('horizons','M5','rejections','reasons')):
            bad=deepcopy(p);node=bad
            for part in location:node=node[part]
            node['private_amount']='SECRET'
            with self.subTest(location=location),self.assertRaises(ValueError):validate(bad)
        for key,value in (('live_order_authority',True),('selected_policy','REAL'),('orders',True)):
            bad=deepcopy(p);bad[key]=value
            with self.assertRaises(ValueError):validate(bad)
    def test_horizon_counts_and_selection_totals_cannot_be_forged(self):
        p,_=self.public()
        for key in ('checks','rejected','selected_orders'):
            bad=deepcopy(p);bad['horizons']['M5'][key]+=1
            with self.subTest(key=key),self.assertRaises(ValueError):validate(bad)
    def test_history_progress_allows_only_known_references_and_bar_counts(self):
        fixture=backfill_fixture.Backfill();fixture.setUp()
        try:
            fixture.source.collect(include_short=True);p=fixture.source.progress(fixture.c.wall());validate_history(p)
            for location in ((),('granularities','ONE_MINUTE'),('granularities','ONE_MINUTE','products','ETH-USD')):
                bad=deepcopy(p);node=bad
                for part in location:node=node[part]
                node['balance']='SECRET'
                with self.subTest(location=location),self.assertRaises(ValueError):validate_history(bad)
        finally:fixture.doCleanups()
