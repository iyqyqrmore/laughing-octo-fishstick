from contextlib import closing
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch
from coincat_forecast_history import ForecastHistory,ForecastHistorySource,candle_rows,REFERENCES
from coincat_forecast_24h import HOUR
from coincat_beta_store import BetaBlocked
from coincat_spot_market import SpotReader
from offline_tests.intelligent_fixtures import Clock,history
from offline_tests.trial_sqlite_resources import trial_sqlite_probe
from offline_tests.test_spot_manual import Venue

def candles(rows,pair):
    asset=pair.split('-')[0]
    return [dict(start=str(r['at']-HOUR),open=str(r['marks'][asset]),high=str(r['marks'][asset]),low=str(r['marks'][asset]),close=str(r['marks'][asset]),volume='1') for r in rows]

def load(store,rows):
    for pair in REFERENCES:
        records=[dict(pair=pair,at=r['at'],open=r['marks'][pair.split('-')[0]],high=r['marks'][pair.split('-')[0]],
            low=r['marks'][pair.split('-')[0]],close=r['marks'][pair.split('-')[0]],volume=D(1)) for r in rows]
        store.append(pair,rows[0]['at']-HOUR,rows[-1]['at'],rows[-1]['at'],records)

class HourlyHistory(unittest.TestCase):
    def test_only_closed_native_candles_are_used_and_open_endpoint_is_ignored(self):
        c=Clock();rows=history(c,count=3);raw=dict(candles=candles(rows,'ETH-USD')+[dict(start=str(rows[-1]['at']))])
        parsed=candle_rows(raw,'ETH-USD',c.wall(),rows[0]['at']-HOUR,rows[-1]['at'])
        self.assertEqual(len(parsed),3);self.assertTrue(all(r['at']<=c.wall() for r in parsed))
        for update in (dict(close='NaN'),dict(close='0'),dict(start=str(rows[0]['at']-HOUR+1))):
            bad=deepcopy(raw);bad['candles'][0].update(update)
            with self.subTest(update=update),self.assertRaises(BetaBlocked):candle_rows(bad,'ETH-USD',c.wall(),rows[0]['at']-HOUR,rows[-1]['at'])
    def test_bounded_get_collector_reads_only_reference_candles_and_does_not_write_orders(self):
        c=Clock();venue=Venue(c);calls=[]
        def get(**kw):
            calls.append(kw);return dict(candles=candles(history(c,count=349),kw['product_id']))
        venue.get_candles=get
        with TemporaryDirectory() as tmp:
            store=ForecastHistory(Path(tmp)/'history.sqlite3');reader=SpotReader(venue,clock=c.wall,monotonic=c.monotonic,budget=None);source=ForecastHistorySource(reader,store)
            result=source.collect();self.assertEqual(result['state'],'COLLECTING');self.assertLessEqual(reader.calls,2)
            self.assertIn(calls[0]['product_id'],REFERENCES);self.assertEqual(calls[0]['granularity'],'ONE_HOUR');self.assertEqual(calls[0]['limit'],350)
            self.assertEqual(venue.posts,[]);self.assertEqual(venue.cancels,[])
    def test_full_cache_survives_restart_and_hourly_refresh_does_not_redownload_all_history(self):
        c=Clock();rows=history(c)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'history.sqlite3';store=ForecastHistory(path);load(store,rows);f=store.estimate(c.wall())
            self.assertEqual(f['state'],'READY');self.assertEqual(store.last_status['aligned_observations'],2400)
            restored=ForecastHistory(path);self.assertEqual(restored.estimate(c.wall()),f)
            reader=SpotReader(Venue(c),clock=c.wall,monotonic=c.monotonic,budget=None);source=ForecastHistorySource(reader,restored)
            self.assertIsNone(source.next_request(c.wall()));pair,start,end=source.next_request(c.wall()+HOUR)
            self.assertEqual(end-start,2*HOUR)
    def test_sqlite_handles_release_on_success_correction_rollback_and_corruption(self):
        with TemporaryDirectory() as tmp,trial_sqlite_probe() as probe:
            c=Clock();path=Path(tmp)/'history.sqlite3';store=ForecastHistory(path);rows=history(c,count=3);load(store,rows)
            probe.assert_released(self,path);before=store.panel(c.wall());different=deepcopy(rows);different[-1]['marks']['ETH']*=2
            with self.assertRaises(BetaBlocked):load(store,different)
            self.assertEqual(store.panel(c.wall()),before);probe.assert_released(self,path)
            with closing(sqlite3.connect(path)) as db,db,closing(db.cursor()) as cur:cur.execute("UPDATE hourly SET digest='changed'")
            raw=path.read_bytes();self.assertEqual(store.estimate(c.wall())['state'],'HOLD');self.assertEqual(path.read_bytes(),raw)
            probe.assert_released(self,path)
    def test_missing_reference_and_sparse_or_stale_history_remain_explained_hold(self):
        c=Clock()
        with TemporaryDirectory() as tmp:
            store=ForecastHistory(Path(tmp)/'history.sqlite3');load(store,history(c,count=72))
            self.assertEqual(store.estimate(c.wall())['reason'],'FORECAST_HISTORY_INSUFFICIENT')
            self.assertEqual(store.last_status['reference_count'],5)
