from copy import deepcopy
from decimal import Decimal as D
import unittest
from coincat_beta_store import BetaBlocked
from coincat_forecast_24h import forecast,HORIZON,HOUR,ForecastConfig
from offline_tests.intelligent_fixtures import Clock,history

class DirectDailyForecast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clock=Clock();cls.rows=history(cls.clock);cls.result=forecast(cls.rows,cls.clock.wall())
    def test_direct_24_hour_outcomes_and_real_daily_training_horizon(self):
        f=self.result;self.assertEqual(f['horizon_s'],86400);self.assertEqual(f['forecast_end_at']-f['decision_at'],86400)
        actual=(D(1)/D('.999'))**24-1
        self.assertAlmostEqual(f['mean']['BTC'],actual,places=24)
        self.assertEqual(f['mean']['ETH'],0);self.assertGreater(f['provenance']['training_labels'],60)
        self.assertEqual(f['forecast_validation'],'UNVALIDATED_RESEARCH_ESTIMATE')
    def test_every_walk_forward_training_label_ends_before_its_decision(self):
        for row in self.result['provenance']['evaluation_origins']:
            self.assertLessEqual(row['max_training_end'],row['at']);self.assertEqual(row['end']-row['at'],HORIZON)
        p=self.result['provenance'];self.assertEqual(p['validation']['count'],14);self.assertEqual(p['holdout']['count'],14)
        for key in ('prediction_mae','naive_mae','hold_mae'):self.assertIn(key,p['holdout'])
    def test_future_rows_and_mutated_future_prices_cannot_leak_into_forecast(self):
        future=deepcopy(self.rows[-1]);future['at']+=HOUR;future['marks']['BTC']=D('999999999')
        self.assertEqual(forecast(self.rows+[future],self.clock.wall()),self.result)
        # A full earlier window is constructed before appending its unseen tail.
        earlier=history(self.clock,count=2448);at=earlier[-49]['at']
        first=forecast(earlier,at);changed=deepcopy(earlier)
        for r in changed:
            if r['at']>at:r['marks']['ETH']*=D(100)
        self.assertEqual(forecast(changed,at),first)
    def test_missing_stale_duplicate_and_outlier_observations_hold(self):
        cases=[];cases.append((self.rows[:-1],self.clock.wall()))
        gap=deepcopy(self.rows);gap[100]['at']+=1;cases.append((gap,self.clock.wall()))
        duplicate=deepcopy(self.rows);duplicate[100]['at']=duplicate[99]['at'];cases.append((duplicate,self.clock.wall()))
        cases.append((self.rows,self.clock.wall()+HOUR*2))
        shock=deepcopy(self.rows);shock[-1]['marks']['BTC']*=2;cases.append((shock,self.clock.wall()))
        for rows,at in cases:
            with self.subTest(at=at),self.assertRaises(BetaBlocked):forecast(rows,at)
    def test_horizon_does_not_change_or_extrapolate_when_decision_is_between_hours(self):
        at=self.clock.wall()+1700;f=forecast(self.rows,at)
        self.assertEqual(f['mean'],self.result['mean']);self.assertEqual(f['forecast_end_at'],at+HORIZON)
        self.assertEqual(f['feature_at'],self.result['feature_at'])
        with self.assertRaises(BetaBlocked):ForecastConfig(history_hours=20).checked()
    def test_noisy_holdout_keeps_errors_and_naive_hold_comparisons(self):
        f=forecast(history(self.clock,mode='noisy'),self.clock.wall());h=f['provenance']['holdout']
        self.assertGreater(h['prediction_mae'],0);self.assertGreater(h['hold_mae'],0)
        self.assertNotEqual(h['prediction_mae'],h['naive_mae']);self.assertEqual(f['forecast_validation'],'UNVALIDATED_RESEARCH_ESTIMATE')
