from copy import deepcopy
from decimal import Decimal as D
import unittest
from coincat_beta_store import BetaBlocked
from coincat_horizon_forecast import HORIZONS,short_forecast,immediate_inputs
from offline_tests.multi_fixtures import Clock,series

class DirectHorizons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=Clock();cls.minute=series(cls.c,60,4320);cls.five=series(cls.c,300,2880)
    def test_each_short_horizon_uses_its_actual_direct_forward_outcome(self):
        for name in ('M5','M15','M30','H2'):
            f=short_forecast(self.minute if name in ('M5','M15') else self.five,self.c.wall(),name)
            with self.subTest(horizon=name):
                self.assertEqual(f['horizon_s'],HORIZONS[name]);self.assertEqual(f['forecast_end_at']-f['decision_at'],HORIZONS[name])
                self.assertAlmostEqual(f['mean']['BTC'],D('1.0015')**(HORIZONS[name]//60)-1,places=20)
                self.assertEqual(f['provenance']['validation']['count'],16);self.assertEqual(f['provenance']['holdout']['count'],16)
                for origin in f['provenance']['evaluation_origins']:
                    self.assertLessEqual(origin['max_training_end'],origin['at']);self.assertEqual(origin['end']-origin['at'],HORIZONS[name])
    def test_future_rows_cannot_change_an_existing_recommendation(self):
        original=short_forecast(self.minute,self.c.wall(),'M5');future=deepcopy(self.minute[-1]);future['at']+=600;future['marks']['BTC']*=100
        self.assertEqual(short_forecast(self.minute+[future],self.c.wall(),'M5'),original)
    def test_gap_stale_insufficient_and_outlier_data_never_become_supported(self):
        for kind in ('gap','stale','few','outlier'):
            rows=deepcopy(self.minute);now=self.c.wall()
            if kind=='gap':rows[-2]['at']-=1
            elif kind=='stale':now+=1000
            elif kind=='few':rows=rows[-30:]
            else:rows[-10]['marks']['BTC']*=3
            with self.subTest(kind=kind),self.assertRaises(BetaBlocked):short_forecast(rows,now,'M5')
    def test_immediate_is_a_current_mark_calculation_not_a_short_return_prediction(self):
        f=immediate_inputs(self.minute[-61:],self.c.wall());self.assertEqual(f['horizon_s'],0)
        self.assertTrue(all(x==0 for x in f['mean'].values()));self.assertGreater(f['return_covariance']['BTC']['BTC'],0)
        self.assertEqual(f['forecast_validation'],'CURRENT_MARK_CALCULATION_NOT_RETURN_FORECAST')
        with self.assertRaises(BetaBlocked):immediate_inputs(self.minute[-60:],self.c.wall())
