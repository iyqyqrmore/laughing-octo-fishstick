"""Prospective counts, conditional costs and no-trade completion; fake time only."""
from copy import deepcopy
from decimal import Decimal as D,localcontext
import unittest
from coincat_beta_store import BetaBlocked,unpack
from coincat_trial_clock import NS,TARGET_NS,advance,prime_quality
from coincat_trial_evidence import new_metrics,observe,validate_metrics
from coincat_shadow_public import validate as validate_public
from coincat_portfolio_policy import DIRECTIONS,usd_marks
from offline_tests import test_resumable_trial as fixtures

class TrialEvidence(unittest.TestCase):
    setUp=fixtures.Recovery.setUp
    review=fixtures.Recovery.review
    restart=fixtures.Recovery.restart
    proposal=fixtures.Recovery.proposal
    event=fixtures.Recovery.event
    def test_qualification_is_not_realistic_fill_or_charged_commission(self):
        ref=self.proposal();s=self.e.state();evidence=self.e.research_summary()
        self.assertGreater(evidence['opportunity_episodes'],0);self.assertIsNone(evidence['realistically_fillable_count'])
        self.assertEqual(evidence['fill_feasibility'],'UNKNOWN_NO_CALIBRATED_MAKER_MODEL')
        self.assertEqual(evidence['replay_filled_orders'],0);self.assertEqual(evidence['modeled_fees_native'],{})
        self.assertEqual(evidence['net_marked_outperformance_usd'],0);self.assertEqual(s['wallet'],s['original'])
        self.assertEqual(evidence['strategy_evidence'],'UNPROVEN_NO_SIMULATED_FILLS')
        order=s['orders'][ref];decision=order['decision'];quote=order['pair'].split('-')[1]
        events=self.e.store.events(256);market=[v['payload'] for v in events if v['kind']=='MARKET_REVIEW']
        event=next(v for v in market if v['input']['frame']['at']==order['created_at'])
        marks,_=usd_marks(event['input']['frame'])
        with localcontext() as context:
            context.prec=80
            self.assertEqual(decision['projected_fee_usd'],decision['receipt']['fee_amount_estimate']*marks[quote])
        self.assertEqual(len(event['evidence']['directions']),14)
        self.assertTrue(any(r['fill_feasibility'].startswith('UNKNOWN') for r in event['evidence']['directions']))
    def test_episodes_not_scan_counts_and_survive_gap_restart(self):
        rows=[dict(**v,state='HOLD',reason='SYNTHETIC_HOLD') for v in DIRECTIONS]
        rows[0].update(state='SHADOW_CANDIDATE',reason='SYNTHETIC_CONDITIONAL_QUALIFICATION')
        def record(s):observe(s['research_metrics'],rows,self.c.wall())
        self.e._change('SYNTHETIC_EVIDENCE',{},record);self.c.tick(30);self.e._change('SYNTHETIC_EVIDENCE',{},record)
        saved=deepcopy(self.e.state()['research_metrics']);self.assertEqual(saved['opportunity_episodes'],1)
        self.assertEqual(saved['qualifying_checks'],2);self.restart();self.assertEqual(self.e.state()['research_metrics'],saved)
        self.e._change('SYNTHETIC_EVIDENCE',{},record);self.assertEqual(self.e.state()['research_metrics']['opportunity_episodes'],1)
        rows[0]['state']='HOLD';self.e._change('SYNTHETIC_EVIDENCE',{},record)
        rows[0]['state']='SHADOW_CANDIDATE';self.e._change('SYNTHETIC_EVIDENCE',{},record)
        self.assertEqual(self.e.state()['research_metrics']['opportunity_episodes'],2)
    def test_168_valid_hours_with_no_qualification_completes_across_28_sessions(self):
        # Integrate the separately tested clock reducer/checkpoints across full
        # synthetic sessions. Real market monitoring for 168 h is not claimed.
        original=self.e.state()['original'];trial=self.e.state()['trial_id']
        for session in range(28):
            self.review();clock=self.e.store.clock;prime_quality(clock,valid=True,coverage=7)
            for _ in range(719):
                self.c.tick(30);advance(clock,wall=self.c.wall(),mono_ns=self.c.ns(),valid=True,coverage=7,run_id=clock['run_id'])
            self.c.tick(20);advance(clock,wall=self.c.wall(),mono_ns=self.c.ns(),valid=True,coverage=7,run_id=clock['run_id'])
            self.review();self.c.tick(10);self.e.heartbeat(persist=True)
            if session<27:self.restart(10*3600)
        s=self.e.state();report=self.e.research_summary()
        self.assertEqual(self.e.progress()['valid_seconds'],168*3600);self.assertEqual(s['mode'],'COMPLETE')
        self.assertEqual(s['orders'],{});self.assertEqual(s['fills'],{});self.assertEqual(s['wallet'],original)
        self.assertEqual(s['trial_id'],trial);self.assertEqual(report['opportunity_episodes'],0)
        self.assertEqual(report['monitoring_outcome'],'COMPLETE_168_VALID_HOURS')
        self.assertEqual(report['strategy_evidence'],'UNPROVEN_NO_QUALIFYING_TRADES')
        self.assertEqual(report['portfolio_vs_hold'],'EQUAL_AS_MARKED');self.assertEqual(report['net_marked_outperformance_usd'],0)
        self.assertEqual(report['modeled_fees_native'],{});self.assertEqual(report['predictive_edge'],'NOT_DEMONSTRATED')
        output=unpack(self.e.write_report().read_text());self.assertEqual(output['research_summary'],report)
    def test_completed_summary_survives_restart_without_losing_hold_valuation(self):
        self.review();self.e.store.clock['valid_ns']=TARGET_NS-10*NS;self.e.store.flush_clock()
        self.c.tick(10);self.e.heartbeat(persist=True);state=self.e.state();summary=self.e.research_summary()
        self.restart(86400)
        self.assertEqual(self.e.state(),state);self.assertEqual(self.e.research_summary(),summary)
        self.assertIsNotNone(self.e.state()['last_performance']['portfolio_usd'])
    def test_older_trials_do_not_invent_historical_zero_opportunities(self):
        self.review();self.e._change('LEGACY_FIXTURE',{},lambda s:s.pop('research_metrics'));self.restart()
        summary=self.e.research_summary();self.assertEqual(summary['opportunity_history'],'SINCE_UPGRADE')
        self.assertIsNone(summary['realistically_fillable_count'])
        self.assertEqual(summary['strategy_evidence'],'UNPROVEN_INCOMPLETE_OPPORTUNITY_HISTORY')
        self.assertEqual(self.e.state()['research_metrics']['prior_reviews'],1)
    def test_unsettled_fees_and_cancellation_block_claimed_net_performance(self):
        ref=self.proposal();order=self.e.state()['orders'][ref];venue=fixtures.cid(800)
        self.e.replay(self.event(ref,'DISPATCH'),'d');self.e.replay(self.event(ref,'ACK',venue_id=venue),'a')
        q=order['size']/2;raw=dict(trade_id=fixtures.cid(801),size=str(q),price=str(order['price']),
            commission=str(q*order['price']*D('.005')),size_in_quote=False,liquidity_indicator='M')
        self.e.replay(self.event(ref,'FILL',venue_id=venue,fill=raw),'f')
        r=self.e.research_summary();self.assertFalse(r['modeled_costs_complete']);self.assertIsNone(r['net_marked_outperformance_usd'])
        self.assertEqual(r['strategy_evidence'],'UNPROVEN_UNRECONCILED_OUTCOMES')
        raw['fee_currency']='BTC';self.e.replay(self.event(ref,'FEE_EVIDENCE',venue_id=venue,fill=raw),'fee')
        self.assertFalse(self.e.research_summary()['modeled_costs_complete'])
        self.e.replay(self.event(ref,'CANCEL_ACK',venue_id=venue),'cancel');s=self.e.state()
        event=self.event(ref,'RECONCILE',venue_id=venue,fill_ids=[fixtures.cid(801)],filled_base=q,complete=True,
            order_hold_released=True,inventory=s['wallet'],status='CANCELED')
        self.e.replay(event,'recon');self.e.replay(event,'recon')
        r=self.e.research_summary();self.assertEqual(r['modeled_fees_native'],{'BTC':D(raw['commission'])})
        self.assertEqual(r['replay_fill_events'],1);self.assertEqual(r['replay_filled_orders'],1)
        self.e.start(fixtures.account(self.c),self.config);self.c.tick(30);self.review()
        r=self.e.research_summary();self.assertEqual(r['portfolio_vs_hold'],'BELOW_AS_MARKED')
        self.assertLess(r['net_marked_outperformance_usd'],0);self.assertEqual(r['predictive_edge'],'NOT_DEMONSTRATED')
    def test_evidence_write_failure_rolls_back_the_model_and_counters(self):
        self.review();state=self.e.state()
        def fail(s):raise BetaBlocked('SYNTHETIC_EVIDENCE_FAILURE')
        with self.assertRaises(BetaBlocked):self.e._change('FAIL',{},lambda s:s.update(reason='NOT_COMMITTED'),evidence=fail)
        self.assertEqual(self.e.state(),state)
    def test_public_evidence_rejects_financial_fields_and_accepts_older_snapshots(self):
        self.review();public=self.e.public();validate_public(public)
        legacy=deepcopy(public);del legacy['evidence'];validate_public(legacy)
        for key,value in (('projected_fee_usd',D(1)),('trial_id','private'),('price','private')):
            changed=deepcopy(public);changed['evidence'][key]=value
            with self.assertRaises(ValueError):validate_public(changed)
        changed=deepcopy(public);changed['evidence']['qualifying_checks']=True
        with self.assertRaises(ValueError):validate_public(changed)
        for malformed in (True,'private',[],None):
            changed=deepcopy(public);changed['evidence']=malformed
            with self.assertRaises(ValueError):validate_public(changed)
