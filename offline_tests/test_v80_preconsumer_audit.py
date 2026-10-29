"""Queued candidates remain explainable when upstream guards reject them."""
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from offline_tests import test_v80_discovery as discovery
from offline_tests.v80_fixtures import NOW


class PreconsumerAudit(unittest.TestCase):
    def run_case(self, change, reason):
        with TemporaryDirectory() as folder:
            app,clock,quotes,rules,fetch=discovery.StaticDiscovery.fixture(self,folder)
            with patch('coincat_app.time.time',side_effect=lambda:clock[0]),patch('coincat_app.fetch_snapshot',fetch):
                payload=app._fast_cycle()
                count=len(payload['plan']['ideas'])
                self.assertGreater(count,0)
                balances=dict(app.experimental_shadow.model_balances())
                change(app,clock,payload)
                self.assertEqual(app._apply_fast_experimental(payload),0)
                model=app.experimental_shadow
                funnel=model.immediate_funnel
                self.assertEqual(funnel['submitted_sizes'],count)
                self.assertEqual(funnel['preconsumer_rejected_sizes'],count)
                self.assertEqual(funnel['preconsumer_rejections'],{reason:count})
                self.assertEqual(funnel['reviewed_sizes'],0)
                self.assertEqual(funnel['unpriced'],0)
                self.assertEqual(funnel['negative_after_cost'],0)
                self.assertEqual(model.model_balances(),balances)
                self.assertEqual(model.immediate_blockers[reason],count)
                model.disarm(now=clock[0]+1)
                self.assertEqual(model.snapshot(now=clock[0]+1)['immediate_funnel'],funnel)
                app.broker.submit.assert_not_called()

    def test_delayed_positive_candidate_is_reported_without_economic_loss(self):
        self.run_case(lambda app,clock,payload:clock.__setitem__(0,NOW+31),
                      'ROUTE_MARK_COVERAGE_INCOMPLETE')

    def test_changed_inventory_is_reported_without_reviewing_stale_plan(self):
        self.run_case(lambda app,clock,payload:payload.__setitem__('experimental_model_snapshot',{'BTC':'.001'}),
                      'QUEUED_MODEL_INVENTORY_CHANGED')

    def test_removed_catalog_products_are_reported(self):
        self.run_case(lambda app,clock,payload:app.catalog.clear(),'PRODUCT_NO_LONGER_APPROVED')

    def test_missing_manual_budget_is_reported(self):
        with patch('coincat_app.effective_manual_budgets',return_value=None):
            self.run_case(lambda *args:None,'MANUAL_BUDGET_UNAVAILABLE')

    def test_non_single_order_is_reported(self):
        def malformed(app,clock,payload):
            for idea in payload['plan']['ideas']:idea['shadow_fifo_steps']=[]
        self.run_case(malformed,'NOT_SINGLE_RESEARCH_ORDER')

    def test_consumer_funding_guard_has_latest_and_session_counts(self):
        from offline_tests.v80_fixtures import annotated
        with TemporaryDirectory() as folder:
            app,clock,quotes,rules,fetch=discovery.StaticDiscovery.fixture(self,folder)
            idea,quotes,rules,proof=annotated()
            idea['source']='UNFUNDED'
            model=app.experimental_shadow
            model.observe(now=NOW,quotes=quotes,usd_rates={'BTC':'50000','USD':'1'},
                route_ideas=[idea],approved_catalog=list(quotes),strict_quotes=True)
            self.assertEqual(model.immediate_funnel['submitted_sizes'],1)
            self.assertEqual(model.immediate_funnel['preconsumer_rejected_sizes'],1)
            self.assertEqual(model.immediate_funnel['preconsumer_rejections'],{'NO_CURRENT_RAM_FUNDING':1})
            self.assertEqual(model.immediate_funnel['reviewed_sizes'],0)
            self.assertEqual(model.fifo_posted,0)
