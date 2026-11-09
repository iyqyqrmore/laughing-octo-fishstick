"""Rejection counts never become policy settings, financial values or raw errors."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from coincat_opportunity_rejections import CATEGORIES,REASONS,category,histogram,record,summary,validate,validate_detail,diagnostic_lines
from coincat_opportunity_public import project,validate as public_validate
from coincat_opportunity_trader import OpportunityTrader
from coincat_beta_store import pack
from coincat_opportunity_policy import OpportunityConfig
from offline_tests.test_opportunity_policy import market
from offline_tests.test_resumable_trial import Clock

def rejected(reason,**kw):return dict(state='HOLD',reason=reason,**kw)
def modeled(edge,forecast,execution='0'):
    return rejected('NO_COST_RISK_JUSTIFIED_ADVANTAGE',projected_advantage_usd=D(edge),
        forecast_uncertainty_usd=D(forecast),execution_uncertainty_usd=D(execution))
def add(metrics,rows):
    record(metrics,rows)
    for row in rows:
        if row['state']=='QUALIFIED':continue
        metrics['rejected_checks']+=1;r=row['reason'];metrics['rejections'][r]=metrics['rejections'].get(r,0)+1

class ReasonAggregation(unittest.TestCase):
    def test_existing_projection_distinguishes_binding_uncertainty_without_an_admission_change(self):
        self.assertEqual(category(modeled('-.01','.02')),'UNCERTAINTY')
        self.assertEqual(category(modeled('-.03','.02')),'INSUFFICIENT_EXPECTED_ADVANTAGE')
        self.assertEqual(category(modeled('-.02','.02')),'INSUFFICIENT_EXPECTED_ADVANTAGE')
        self.assertEqual(category(rejected('NO_COST_RISK_JUSTIFIED_ADVANTAGE')),'ADVANTAGE_OR_UNCERTAINTY_UNSPLIT')
        self.assertEqual(category(modeled('-.01','NaN')),'ADVANTAGE_OR_UNCERTAINTY_UNSPLIT')
    def test_data_liquidity_warmup_rules_and_unknown_reasons_are_distinct(self):
        expected={'PARTIAL_OR_UNVERIFIED_INPUTS':'UNAVAILABLE_DATA','SIZED_FUTURE_EXIT_COST_UNKNOWN':'UNAVAILABLE_DATA',
            'SIZED_NATIVE_DEPTH_UNAVAILABLE':'UNAVAILABLE_DATA','SIZED_NATIVE_DEPTH_INSUFFICIENT':'LIQUIDITY_LIMITATION',
            'WARMING_RISK_OBSERVATIONS_HOLD':'MODEL_WARMUP','RISK_RETURN_OUTLIER_REVIEW_REQUIRED':'UNCERTAINTY',
            'INSUFFICIENT_SIMULATED_SOURCE_INCLUDING_NATIVE_FEE':'MARKET_RULES_OR_FUNDING',
            'SHADOW_BOOK_CROSSED_OR_WIDE':'SPREAD_OR_CROSSED_BOOK','private /path quantity 9.123':'OTHER_OR_UNCLASSIFIED'}
        for reason,group in expected.items():
            with self.subTest(reason=reason):self.assertEqual(category(rejected(reason)),group)
    def test_known_legacy_histogram_exports_immediately_without_writing_or_guessing_old_causes(self):
        m=dict(rejected_checks=100,rejections={'WARMING_RISK_OBSERVATIONS_HOLD':14,'NO_COST_RISK_JUSTIFIED_ADVANTAGE':80,'private amount 3.14159':6})
        saved=deepcopy(m);value=summary(m);self.assertEqual(m,saved);validate(value,100)
        self.assertEqual(value['coverage'],'LEGACY_AGGREGATES_ONLY');self.assertEqual(value['categories']['MODEL_WARMUP'],14)
        self.assertEqual(value['categories']['ADVANTAGE_OR_UNCERTAINTY_UNSPLIT'],80)
        raw=json.dumps(value);self.assertNotIn('3.14159',raw);self.assertEqual(value['reasons']['OTHER_UNCLASSIFIED'],6)
    def test_upgrade_keeps_old_counts_and_adds_future_splits_once_with_matching_totals(self):
        m=dict(rejected_checks=7,rejections={'NO_COST_RISK_JUSTIFIED_ADVANTAGE':7})
        add(m,[modeled('-.01','.02'),modeled('-.03','.02'),rejected('SIZED_NATIVE_DEPTH_INSUFFICIENT'),dict(state='QUALIFIED',reason='POSITIVE_MODEL_LOWER_BOUND')])
        value=summary(m);validate_detail(m['rejection_detail'],10);validate(value,10)
        self.assertEqual(value['coverage'],'SPLIT_SINCE_UPGRADE');self.assertEqual(value['history_before_split'],7);self.assertEqual(value['split_checks'],3)
        self.assertEqual(value['categories']['ADVANTAGE_OR_UNCERTAINTY_UNSPLIT'],7)
        for group in ('UNCERTAINTY','INSUFFICIENT_EXPECTED_ADVANTAGE','LIQUIDITY_LIMITATION'):self.assertEqual(value['categories'][group],1)
        self.assertEqual(value['reasons']['NO_COST_RISK_JUSTIFIED_ADVANTAGE'],9)
    def test_missing_or_malformed_history_never_exports_its_values_as_counts(self):
        for raw in ({}, {'fee in BTC':D('.123')},{'path':True},{'unknown':-1},{'unknown':99}):
            value=summary(dict(rejected_checks=12,rejections=raw));validate(value,12)
            self.assertEqual(value['reasons']['UNRECORDED_HISTORY'],12)
            self.assertNotIn('.123',pack(value))
    def test_public_nested_schema_rejects_private_keys_types_and_inconsistent_totals_but_accepts_old_exports(self):
        value=summary(dict(rejected_checks=0,rejections={}));base=project();public_validate(base)
        extended=project(dict(base,rejection_breakdown=value));public_validate(extended)
        for mutate in (lambda x:x.update(wallet='private'),lambda x:x['categories'].update(ETH=D('.1')),
                lambda x:x['reasons'].update(account_id=1),lambda x:x['categories'].update(UNAVAILABLE_DATA=True),
                lambda x:x.update(total=1),lambda x:x.update(history_before_split=1),
                lambda x:x.update(coverage=['private raw failure']),
                lambda x:x.update(coverage='private raw failure')):
            bad=deepcopy(value);mutate(bad)
            with self.assertRaises(ValueError):public_validate(dict(base,rejection_breakdown=bad))
        self.assertEqual(set(value['categories']),set(CATEGORIES));self.assertEqual(set(value['reasons']),set(REASONS))
    def test_diagnostic_text_has_fixed_labels_reasons_and_no_amounts(self):
        m=dict(rejected_checks=0,rejections={});add(m,[rejected('SIZED_NATIVE_DEPTH_INSUFFICIENT'),modeled('-.123456789','.223456789')])
        text='\n'.join(diagnostic_lines(summary(m)))
        self.assertIn('Insufficient sized liquidity: 1',text);self.assertIn('Uncertainty blocks admission: 1',text)
        self.assertIn('SIZED_NATIVE_DEPTH_INSUFFICIENT: 1',text);self.assertNotIn('123456789',text)
        self.assertIn('not rejected exchange orders',text)

class DurableRejectionCounts(unittest.TestCase):
    def test_current_review_duplicate_frame_partial_and_restart_preserve_counts_without_resetting_trial(self):
        with TemporaryDirectory() as data:
            c=Clock();path=Path(data)/'trial.sqlite3';e=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns);e.start()
            f=market(c);e.review(f);first=e.state();out=e.public()['rejection_breakdown']
            self.assertEqual(out['categories']['MODEL_WARMUP'],14);self.assertEqual(out['coverage'],'COMPLETE_SINCE_TRIAL_START')
            e.review(f);self.assertEqual(e.public()['rejection_breakdown'],out)
            c.tick(30);partial=market(c);del partial['books']['ADA-BTC'];e.review(partial)
            self.assertEqual(e.public()['rejection_breakdown']['categories']['UNAVAILABLE_DATA'],14)
            e.shutdown();saved=e.state();before=e.public()['rejection_breakdown'];c.tick(3600)
            restored=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns)
            self.assertFalse(restored.load_error);self.assertEqual(restored.public()['rejection_breakdown'],before)
            for k in ('original','wallet','fees_native','config','trial_id'):self.assertEqual(restored.state()[k],saved[k])
            self.assertEqual(restored.state()['metrics']['rejected_checks'],28)
    def test_existing_checkpoint_gets_reporting_only_upgrade_and_keeps_legacy_coverage(self):
        with TemporaryDirectory() as data:
            c=Clock();path=Path(data)/'trial.sqlite3';e=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns);e.start()
            with patch('coincat_opportunity_trader.record_rejections'):e.review(market(c))
            self.assertNotIn('rejection_detail',e.state()['metrics']);e.shutdown();saved=e.state();c.tick(3600)
            e=OpportunityTrader(path,clock=c.wall,monotonic_ns=c.ns);self.assertEqual(e.public()['rejection_breakdown']['coverage'],'LEGACY_AGGREGATES_ONLY')
            e.review(market(c));value=e.public()['rejection_breakdown'];self.assertEqual(value['history_before_split'],14);self.assertEqual(value['split_checks'],14)
            for k in ('trial_id','original','wallet','fees_native','config'):self.assertEqual(e.state()[k],saved[k])
