from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from coincat_beta_store import BetaBlocked
from coincat_candle_cache import CandleCache,closed_candles,REFERENCES
from coincat_forecast_history import ForecastHistory
from coincat_history_backfill import HistoryBackfill
from coincat_history_public import validate
from coincat_horizon_forecast import ForecastBundle
from coincat_spot_market import SpotReader
from offline_tests.multi_fixtures import Clock
from offline_tests.test_spot_manual import Venue
from offline_tests.trial_sqlite_resources import trial_sqlite_probe

class Backfill(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Clock();self.venue=Venue(self.c);self.requests=[];self.failed=None
        def candles(**kw):
            self.requests.append(kw)
            if kw['product_id']==self.failed:raise ValueError('PRIVATE_ACCOUNT_ERROR_NOT_EXPORTED')
            seconds={'ONE_MINUTE':60,'FIVE_MINUTE':300,'ONE_HOUR':3600}[kw['granularity']]
            return dict(candles=[dict(start=str(t),open='10',high='10',low='10',close='10',volume='1') for t in range(int(kw['start']),int(kw['end']),seconds)])
        self.venue.get_candles=candles;self.hourly=ForecastHistory(Path(self.tmp.name)/'hourly.sqlite3');self.minute=CandleCache(Path(self.tmp.name)/'minute.sqlite3')
        self.reader=SpotReader(self.venue,clock=self.c.wall,monotonic=self.c.monotonic,budget=None);self.source=HistoryBackfill(self.reader,self.hourly,self.minute,monotonic=self.c.monotonic)
    def test_latest_pages_reach_all_five_references_before_deep_history_and_never_write_orders(self):
        for i in range(5):
            result=self.source.collect(include_short=True);self.assertEqual(result['state'],'COLLECTING');self.assertLessEqual(self.reader.calls,2)
        self.assertEqual([r['product_id'] for r in self.requests],list(REFERENCES));self.assertTrue(all(r['granularity']=='ONE_MINUTE' for r in self.requests))
        p=self.source.progress(self.c.wall());validate(p);self.assertEqual(p['granularities']['ONE_MINUTE']['aligned'],349)
        self.assertTrue(all(r['bars']==349 for r in p['granularities']['ONE_MINUTE']['products'].values()))
        f=ForecastBundle(self.hourly,self.minute,self.source).estimate(self.c.wall())
        self.assertEqual(f['IMMEDIATE']['state'],'READY');self.assertEqual(f['M5']['state'],'HOLD');self.assertEqual(f['H24']['state'],'HOLD')
        self.assertEqual(self.venue.posts,[]);self.assertEqual(self.venue.cancels,[])
    def test_failed_first_reference_cannot_hold_up_the_other_four_and_errors_are_fixed_codes(self):
        self.failed=REFERENCES[0]
        self.assertEqual(self.source.collect(include_short=True)['state'],'BACKOFF')
        for i in range(4):self.assertEqual(self.source.collect(include_short=True)['state'],'COLLECTING')
        p=self.source.progress(self.c.wall());self.assertEqual(p['failures'],1);self.assertNotIn('PRIVATE',str(p))
        self.assertEqual(sum(r['bars']>0 for r in p['granularities']['ONE_MINUTE']['products'].values()),4)
        self.assertEqual(p['granularities']['ONE_MINUTE']['aligned'],0)
    def test_sliding_latest_window_cannot_starve_bulk_backfill(self):
        anchor=int(self.c.wall())//3600*3600
        for i in range(25):self.source.collect();self.c.tick(7200)
        first=min(int(r['start']) for r in self.requests if r['product_id']==REFERENCES[0])
        self.assertLess(first,anchor-2*349*3600)
        self.assertTrue(any(int(r['end'])>anchor for r in self.requests))
    def test_history_completion_reuses_durable_pages_across_restart_without_resetting_them(self):
        self.source.collect(include_short=True);path=self.minute.path;raw=path.read_bytes()
        restored=HistoryBackfill(self.reader,self.hourly,CandleCache(path),monotonic=self.c.monotonic)
        p=restored.progress(self.c.wall());self.assertEqual(p['granularities']['ONE_MINUTE']['products'][REFERENCES[0]]['pages'],1)
        self.assertEqual(path.read_bytes(),raw);self.assertEqual(p['attempts'],0)
    def test_closed_candle_parser_rejects_open_future_invalid_and_unaligned_prices(self):
        end=int(self.c.wall())//60*60;raw=dict(candles=[dict(start=str(end-60),open='10',high='10',low='10',close='10',volume='1'),dict(start=str(end))])
        rows=closed_candles(raw,REFERENCES[0],'ONE_MINUTE',self.c.wall(),end-60,end);self.assertEqual(len(rows),1)
        for update in (dict(close='NaN'),dict(close='11'),dict(start=str(end+60)),dict(start=str(end-59))):
            bad=deepcopy(raw);bad['candles'][0].update(update)
            with self.subTest(update=update),self.assertRaises(BetaBlocked):closed_candles(bad,REFERENCES[0],'ONE_MINUTE',self.c.wall(),end-60,end)
    def test_cache_handles_close_on_success_conflicting_closed_price_and_metadata_failure(self):
        with trial_sqlite_probe() as probe:
            self.source.collect(include_short=True);path=self.minute.path;probe.assert_released(self,path)
            end=int(self.c.wall())//60*60;row=dict(pair=REFERENCES[0],at=end,open=D(11),high=D(11),low=D(11),close=D(11),volume=D(1))
            before=self.minute.panel('ONE_MINUTE',self.c.wall(),4320)
            with self.assertRaises(BetaBlocked):self.minute.append('ONE_MINUTE',REFERENCES[0],end-60,end,self.c.wall(),[row])
            self.assertEqual(self.minute.panel('ONE_MINUTE',self.c.wall(),4320),before);probe.assert_released(self,path)
            def fault(sql):
                if 'application_id' in sql:raise sqlite3.OperationalError('SYNTHETIC_METADATA_READ_FAILURE')
            probe.fault=fault
            with self.assertRaises(sqlite3.OperationalError):self.minute.intervals('ONE_MINUTE',REFERENCES[0])
            probe.fault=None;probe.assert_released(self,path)
    def test_contradictory_resolutions_are_reviewed_without_manufacturing_alignment(self):
        for i in range(5):self.source.collect(include_short=True)
        end=int(self.c.wall())//300*300
        for pair in REFERENCES:
            rows=[dict(pair=pair,at=end-i*300,open=D(20),high=D(20),low=D(20),close=D(20),volume=D(1)) for i in reversed(range(349))]
            self.minute.append('FIVE_MINUTE',pair,rows[0]['at']-300,end,self.c.wall(),rows)
        f=ForecastBundle(self.hourly,self.minute,self.source).estimate(self.c.wall())
        self.assertEqual(f['IMMEDIATE']['state'],'HOLD');self.assertEqual(f['IMMEDIATE']['reason'],'HORIZON_HISTORY_REVIEW_REQUIRED')
        self.assertTrue(self.source.reviewed('ONE_MINUTE'));self.assertTrue(self.source.reviewed('FIVE_MINUTE'))
        self.assertFalse(self.source.reviewed('ONE_HOUR'));self.assertEqual(f['H24']['state'],'HOLD')
