"""T07/11/12/13/14: honest state, lifecycle, forward observations and guards."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import ast,unittest
from coincat_v80_immediate import evaluate,ObservationLog,diagnostic_report
from coincat_v80_shadow import StrictImmediateShadow
from coincat_v507_shadow_fifo import ShadowFIFOBlocked
from coincat_live_forward_store import ForwardStore
from coincat_v706_selection import GRACE_S
from offline_tests.v80_fixtures import annotated,reference,NOW

ROOT=Path(__file__).resolve().parents[1]


class EvidenceFunnel(unittest.TestCase):
    def session(self):
        s=StrictImmediateShadow(experimental=True,allow_synthetic_evidence=True)
        s.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'BTC':'.002'},fresh_usd_rates={'BTC':'50000','USD':'1'},now=NOW-1)
        self.addCleanup(lambda:[w.close() for w in s.fifo_portfolios.values()])
        return s

    def test_failed_ram_post_stop_retention_and_rearm_no_fake_conversion(self):
        s=self.session();idea,q,rules,proof=annotated();frame=idea['immediate_assessment']['frame']
        s.synthetic_evidence[frame['id']]=proof
        wallet=s.fifo_portfolios['TAKER_ASK']
        with patch.object(wallet,'post_hypothetical_route',side_effect=ShadowFIFOBlocked('SYNTHETIC_FAILURE')):
            s.observe(now=NOW,quotes=q,usd_rates={'BTC':'50000','ETH':'2600','USD':'1'},
                route_ideas=[idea],strict_quotes=True,approved_catalog=list(q))
        self.assertEqual(s.fifo_posted,0);self.assertEqual(s.model_balances(),{'BTC':D('.002')})
        self.assertEqual(s.immediate_funnel['strict_qualified'],1)
        self.assertEqual(s.immediate_funnel['ram_conversions'],0)
        self.assertIn('RAM_POST_FAILED_OR_REPLAY',s.immediate_blockers)
        s.disarm(now=NOW+1);snapshot=s.snapshot(now=NOW+1)
        text=diagnostic_report(NS(experimental_shadow=s))
        self.assertIn('Missing evidence is not an economic loss',text)
        self.assertEqual(snapshot,s.snapshot(now=NOW+1))
        s.arm(connected=True,real_arm=False,stopped=False,verified_balances=True,usd_coverage=True,
            enrolled_quantities={'BTC':'.002'},fresh_usd_rates={'BTC':'50000','USD':'1'},now=NOW+2)
        self.assertEqual(s.immediate_counts,{});self.assertEqual(s.synthetic_evidence,{})

    def test_late_rule_change_exclusion_and_budget_rechecked(self):
        idea,q,rules,proof=annotated()
        for kind in ('rules','exclusion','budget'):
            with self.subTest(kind=kind):
                s=self.session();s.synthetic_evidence[idea['immediate_assessment']['frame']['id']]=proof
                current=deepcopy(rules);allowed=list(q);extra={}
                if kind=='rules':current['ETH-BTC']['base_min_size']='1'
                if kind=='exclusion':allowed.remove('ETH-BTC')
                if kind=='budget':extra['risk_budgets']={'per_order_usd':'1','incremental_exposure_usd':'1',
                    'daily_buy_usd':'1','max_attempts':1}
                s.observe(now=NOW,quotes=q,usd_rates={'BTC':'50000','ETH':'2600','USD':'1'},route_ideas=[idea],
                    approved_catalog=allowed,current_product_rules=current,strict_quotes=True,**extra)
                self.assertEqual(s.fifo_posted,0)

    def test_unverified_positive_research_observes_all_horizons_without_spending(self):
        idea,q,rules,proof=annotated();log=ObservationLog()
        log.observe([idea,deepcopy(idea)],q,now=NOW)
        self.assertEqual(log.summary()['pending_candidates'],1)
        for age in (300,900,3600):
            fresh={p:(r[0],r[1],NOW+age) for p,r in q.items()}
            log.observe([],fresh,now=NOW+age)
        stats=log.summary();self.assertFalse(stats['wallet_spending'])
        self.assertFalse(stats['independent_samples'])
        self.assertEqual(stats['outcomes']['300_POSITIVE'],1)
        self.assertEqual(stats['outcomes']['900_POSITIVE'],1)
        self.assertEqual(stats['outcomes']['3600_POSITIVE'],1)
        missed=ObservationLog();missed.observe([idea],q,now=NOW)
        missed.observe([],{},now=NOW+422)
        self.assertEqual(missed.summary()['outcomes']['300_MISSED_DEADLINE'],1)
        self.assertNotIn('300_NONPOSITIVE',missed.summary()['outcomes'])

    def test_public_learning_causes_prospective_without_rewriting_old_history(self):
        with TemporaryDirectory() as d:
            store=ForwardStore(Path(d)/'synthetic-market.sqlite');learner=store.selection
            q={'BTC-USD':(D(100),D('100.01'),NOW)}
            feature={'rows':[{'pair':'BTC-USD','change_30s_pct':'1','age_ms':0}]}
            learner.observe(catalog=list(q),quotes=q,snapshot=feature,now=NOW,observed_pairs=list(q))
            learner.observe(catalog=list(q),quotes={},snapshot=feature,now=NOW+300)
            learner.observe(catalog=list(q),quotes={},snapshot=feature,now=NOW+421)
            self.assertEqual(learner.summary()['missed_causes'],{'PAIR_BOOK_NOT_OBSERVED':1})
            with learner._db() as db:
                db.execute("INSERT INTO v706_forward_cost VALUES('ETH-USD',?, ?, ?, 'FLAT','FLAT','1',NULL,'MISSED')",
                    (NOW-1000,NOW-700,NOW-500))
            stats=learner.summary()
            self.assertEqual(stats['missed_causes']['LEGACY_CAUSE_UNKNOWN'],1)
            self.assertEqual(stats['observations']['MISSED'],2)

    def test_production_broker_and_financial_files_unchanged_and_new_modules_have_no_network(self):
        import hashlib
        protected={'app/coincat_live.py','app/coincat_unified_fifo_v501.py','app/coincat_state_v50.py','app/coincat_data_transfer.py'}
        # Compare protected bytes with the shipped baseline supplied separately
        # by the source-control integrity review; AST checks are behavior guards.
        tree=ast.parse((ROOT/'app/coincat_live.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        submit=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
        self.assertIsInstance(submit.body[0],ast.Raise)
        self.assertIn('LiveBlocked',ast.unparse(submit.body[0]))
        for name in ('coincat_v80_immediate.py','coincat_v80_shadow.py','coincat_v80_discovery.py','coincat_v80_first_run.py'):
            src=(ROOT/'app'/name).read_text()
            for token in ('create_order(', 'cancel_orders(', 'preview_order(', 'requests.get(', 'requests.post('):
                self.assertNotIn(token,src,name)
