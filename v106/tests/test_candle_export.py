from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch,Mock
from decimal import Decimal as D
import csv,json,unittest
from v106.export_candles import Exporter,FRAMES,parse_page,stamp,missing_ranges
from coincat_forecast_history import candle_rows
from coincat_candle_cache import closed_candles

NOW = 1794312000


def candle(t, close="10"):
    return dict(start=str(t),open=close,high=close,low=close,close=close,volume="1")


class Public:
    def __init__(self): self.calls=[]; self.gap=None; self.conflict=False; self.fail=None
    def get_public_candles(self, **kw):
        self.calls.append(kw)
        if self.fail: raise self.fail
        step=3600 if kw['granularity']=='ONE_HOUR' else 300
        rows=[candle(t) for t in range(int(kw['start']),int(kw['end'])+step,step) if t!=self.gap]
        if self.conflict and rows: rows.insert(1,candle(int(rows[0]['start']),"11"))
        return dict(candles=list(reversed(rows)))


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)
        self.client=Public()
    def exporter(self):return Exporter(self.client,self.out,pause=0,clock=lambda:NOW,sleeper=lambda _:None,progress=lambda _:None)
    def test_inclusive_old_endpoint_no_longer_rejects_valid_hour_minute_or_five_minute_page(self):
        for step,gran in ((3600,None),(60,'ONE_MINUTE'),(300,'FIVE_MINUTE')):
            end=NOW-7200;raw=dict(candles=[candle(end-step),candle(end)])
            if gran:result=closed_candles(raw,'ETH-USD',gran,NOW,end-step,end)
            else:result=candle_rows(raw,'ETH-USD',NOW,end-step,end)
            self.assertEqual(len(result),1);self.assertEqual(result[0]['at'],end)
            self.assertEqual(len(parse_page(raw,end-step,end,step,NOW)),1)
    def test_closed_only_and_invalid_interior_values_remain_rejected(self):
        end=NOW-3600
        for change in (dict(start=str(end+3600)),dict(start=str(end-3599)),dict(close='NaN'),dict(low='11')):
            raw=dict(candles=[dict(candle(end-3600),**change),candle(end)])
            with self.subTest(change=change),self.assertRaises(ValueError):candle_rows(raw,'ETH-USD',NOW,end-3600,end)
            with self.assertRaises((ValueError,KeyError)):parse_page(raw,end-3600,end,3600,NOW)
    def test_six_streams_full_day_and_repeat_is_byte_identical_with_no_extra_gets(self):
        result=self.exporter().run(days=1)
        self.assertEqual(result['status'],'COMPLETE');self.assertEqual([r['rows'] for r in result['streams']],[24,288]*3)
        first={p.name:p.read_bytes() for p in self.out.glob('*.csv')};calls=len(self.client.calls)
        again=self.exporter().run(days=1)
        self.assertEqual(again['requests_this_run'],0);self.assertEqual(len(self.client.calls),calls)
        self.assertEqual(first,{p.name:p.read_bytes() for p in self.out.glob('*.csv')})
        self.assertTrue(all(k['limit']==350 for k in self.client.calls));self.assertEqual({k['product_id'] for k in self.client.calls},{'ETH-BTC','BTC-USD','ETH-USD'})
    def test_missing_bar_is_logged_without_synthesis_and_conflicts_keep_first(self):
        self.client.gap=NOW-3600;self.client.conflict=True
        result=self.exporter().run(days=1)
        self.assertGreater(result['conflicting_versions'],0)
        with (self.out/'ETH-BTC_1h.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),23);self.assertFalse(any(int(r['start'])==self.client.gap for r in rows))
        # Response order is reversed; its first occurrence is authoritative.
        with (self.out/'conflicts.csv').open(newline='') as f:conflicts=list(csv.DictReader(f))
        self.assertTrue(all(r['first_ohlcv'].startswith('11|') for r in conflicts))
        with (self.out/'gaps.csv').open(newline='') as f:missing=list(csv.DictReader(f))
        self.assertTrue(any(r['kind']=='NO_CANDLE_RETURNED' for r in missing))
        old=(self.out/'conflicts.csv').read_bytes();self.exporter().run(days=1);self.assertEqual((self.out/'conflicts.csv').read_bytes(),old)
    def test_failed_network_has_unknown_coverage_not_fake_market_gaps_then_resumes(self):
        self.client.fail=OSError('PRIVATE_PROXY_DETAILS')
        result=self.exporter().run(days=1)
        self.assertEqual(result['status'],'INCOMPLETE');self.assertTrue(all(r['rows']==0 and r['missing_bars']==0 and r['unfetched_bars']>0 for r in result['streams']))
        self.assertNotIn('PRIVATE',json.dumps(result))
        with (self.out/'gaps.csv').open(newline='') as f:self.assertTrue(all(r['kind']=='NOT_FETCHED' for r in csv.DictReader(f)))
        self.client.fail=None;self.assertEqual(self.exporter().run(days=1)['status'],'COMPLETE')
    def test_multiple_pages_go_backwards_and_existing_rows_survive_lost_coverage(self):
        self.exporter().run(days=3);requests=self.client.calls
        pages=[r for r in requests if r['product_id']=='ETH-BTC' and r['granularity']=='FIVE_MINUTE']
        self.assertGreater(len(pages),1)
        self.assertTrue(all(0<int(r['end'])-int(r['start'])<=349*300 for r in pages))
        self.assertTrue(all(int(a['start'])==int(b['end']) for a,b in zip(pages,pages[1:])))
        before=(self.out/'ETH-BTC_5m.csv').read_bytes();(self.out/'export_state.json').unlink()
        self.exporter().run(days=3);self.assertEqual((self.out/'ETH-BTC_5m.csv').read_bytes(),before)
    def test_rate_limit_stops_further_gets(self):
        error=OSError('rate limit');error.response=type('Response',(),{'status_code':429})()
        self.client.fail=error;result=self.exporter().run(days=1)
        self.assertEqual(len(self.client.calls),1);self.assertEqual(result['status'],'INCOMPLETE')
    def test_explicit_utc_and_two_year_bound(self):
        self.assertEqual(stamp('2026-11-10'),stamp('2026-11-10T00:00:00Z'))
        with self.assertRaises(ValueError):stamp('2026-11-10T01:00:00')
        with self.assertRaises(ValueError):self.exporter().run(days=731)
        with self.assertRaises(ValueError):self.exporter().run(end=NOW+3600)

    def test_resume_coverage_outside_an_older_window_cannot_expand_its_requests(self):
        self.assertEqual(missing_ranges(100,600,[[1000,1200],[-300,0]]),[(100,600)])
        self.assertEqual(missing_ranges(100,600,[[0,200],[400,800],[1000,1200]]),[(200,400)])

    def test_legacy_inclusive_pages_can_finish_2400_hours_instead_of_stalling_at_349(self):
        from coincat_forecast_history import ForecastHistory
        from coincat_candle_cache import CandleCache
        from coincat_history_backfill import HistoryBackfill
        from coincat_spot_market import SpotReader
        from offline_tests.multi_fixtures import Clock
        from offline_tests.test_spot_manual import Venue
        c=Clock();venue=Venue(c);venue.get_candles=self.client.get_public_candles
        reader=SpotReader(venue,clock=c.wall,monotonic=c.monotonic,budget=None)
        source=HistoryBackfill(reader,ForecastHistory(self.out/'hours.sqlite3'),CandleCache(self.out/'minutes.sqlite3'),monotonic=c.monotonic)
        for _ in range(60):source.collect();c.tick(10)
        progress=source.progress(c.wall())
        self.assertEqual(progress['failures'],0);self.assertEqual(progress['granularities']['ONE_HOUR']['aligned'],2400)
        self.assertFalse(venue.posts);self.assertFalse(venue.cancels)

    def test_key_import_rebinds_the_same_fair_history_source_and_bundle_without_live_dispatch(self):
        from coincat_spot_app import SpotApp
        from coincat_forecast_history import ForecastHistory
        from coincat_candle_cache import CandleCache
        from coincat_history_backfill import HistoryBackfill
        app=object.__new__(SpotApp);app.root=object();app.busy=False;app.engine=Mock();app.engine.public.return_value={'unresolved':0}
        app.status=Mock();app.blocked=Mock();app.refresh_controls=Mock();app.panels={};app.clock=lambda:NOW
        app.intelligent=Mock();app.multihorizon=Mock()
        app.forecast_history=ForecastHistory(self.out/'hour.sqlite3');app.minute_history=CandleCache(self.out/'minute.sqlite3')
        key=self.out/'test_key.json';key.write_text(json.dumps(dict(name='organizations/test/apiKeys/test',privateKey='TEST_ONLY_NOT_A_REAL_KEY'*3)))
        with patch('coincat_spot_app.filedialog.askopenfilename',return_value=str(key)),patch('coincat_spot_app.save_encrypted') as save:
            app.import_key()
        save.assert_called_once();self.assertIsInstance(app.history_source,HistoryBackfill)
        self.assertIs(app.history_source.reader,app.reader);self.assertIs(app.forecast_bundle.backfill,app.history_source)
        self.assertIs(app.intelligent_source.forecast_bundle,app.forecast_bundle)
        app.engine.set_blocked.assert_called_once_with(True)
        app.intelligent.pause.assert_called_once();app.multihorizon.pause.assert_called_once()

    def test_source_package_includes_new_tools_but_no_private_or_exported_data(self):
        from tools.BUILD_SOURCE_PACKAGE import source_files
        files=source_files()
        for name in ('v106/export_candles.py','v106/backtest.py','v106/simulator.py','v106/preregistered.py','README_V106.md'):
            self.assertIn(name,files)
        self.assertNotIn('v106_out/fees.json',files)
        self.assertFalse(any(n.startswith('v106_out/data/') or n.endswith('.sqlite3') or '__pycache__' in n for n in files))


if __name__=='__main__':unittest.main()
