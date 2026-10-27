"""Synthetic-only chronological validation, pure budget advice and UI contract."""
import tempfile,sqlite3,unittest
from pathlib import Path
from contextlib import closing
from decimal import Decimal
from coincat_v502_relative_learning import RelativeUSDLab, evaluate_hold_switch
from coincat_v503_lab_evidence import grade_lab,budget_text,diagnostic_text,saved_gpu_heldout_status

class EvidenceContract(unittest.TestCase):
    def test_held_out_study_uses_only_matured_nonoverlapping_earlier_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            lab=RelativeUSDLab(Path(tmp)/'public.sqlite3')
            start=1800000000//300*300
            # 72 independent one-hour outcomes spaced 3h apart across 9 days.
            with closing(sqlite3.connect(lab.path)) as db:
                for i in range(72):
                    t=start+i*10800
                    for at,eth in ((t,'1'),(t+3600,'1.02')):
                        db.execute('INSERT INTO public_marks VALUES(?,?,?,?)',(at,'SOURCE','1','VERIFIED_ACCOUNT_TIER'))
                        db.execute('INSERT INTO public_marks VALUES(?,?,?,?)',(at,'TARGET',eth,'VERIFIED_ACCOUNT_TIER'))
                db.commit()
            middle=lab.paired_outcomes('SOURCE','TARGET',now=start+12*10800)
            self.assertFalse(middle['oos_validated'])
            result=lab.paired_outcomes('SOURCE','TARGET',now=start+72*10800+3600)
            self.assertTrue(result['oos_validated'],result)
            self.assertGreaterEqual(result['oos_train_windows'],24)
            self.assertGreaterEqual(result['oos_test_windows'],8)
            self.assertGreater(result['oos_improvement'],Decimal('.05'))
            idea={'initial_wallet_usd_mark':'100','post_route_wallet_usd_mark':'99.8',
                  'source_units':'1','input_units_planned':'1'}
            route=evaluate_hold_switch(idea,result)
            self.assertEqual(route['research_decision'],'SWITCH_WORTH_RESEARCH')
            self.assertGreater(route['net_p10_usd'],0)
            result['oos_validated']=False
            route2=evaluate_hold_switch(idea,result)
            self.assertEqual(route2['research_decision'],'HOLD_UNTIL_VERIFIED')

    def test_no_lookahead_when_future_holdout_reverses(self):
        with tempfile.TemporaryDirectory() as tmp:
            lab=RelativeUSDLab(Path(tmp)/'marks.sqlite3')
            start=1800000000//300*300
            with closing(sqlite3.connect(lab.path)) as db:
                for i in range(72):
                    t=start+i*10800
                    net='1.02' if i<54 else '.97'
                    for at,eth in ((t,'1'),(t+3600,net)):
                        for asset,rate in (('A','1'),('B',eth)):
                            db.execute('INSERT INTO public_marks VALUES(?,?,?,?)',(at,asset,rate,'VERIFIED_ACCOUNT_TIER'))
                db.commit()
            r=lab.paired_outcomes('A','B',now=start+73*10800)
            self.assertFalse(r['oos_validated'])
            self.assertEqual(r['oos_state'],'HELD_OUT_BASELINE_NOT_BEAT')

    def test_fee_or_oos_missing_makes_preferred_budget_zero(self):
        idea={'research_decision':'SWITCH_WORTH_RESEARCH','oos_validated':True,
              'net_p10_usd':Decimal('2'),'net_mean_usd':Decimal('2'),'initial_wallet_usd_mark':'100',
              'source_units':'2','input_units_planned':'1'}
        values=dict(catalog_total=100,catalog_seen=100,focused_total=64,
                    focused_mature=64,verified_forward_labels=280,
                    route_ideas=[idea],fee_fresh=True,usd_complete=True,
                    scan_fresh=True,current_order_budget='12')
        yes=grade_lab(**values)
        self.assertTrue(yes['budget_eligible'])
        self.assertEqual(yes['research_preferred_order_usd'],Decimal('50'))
        self.assertFalse(yes['changes_broker_limits'])
        self.assertFalse(yes['authorizes_order'])
        self.assertEqual(len(yes['cards']),6)
        no=grade_lab(**dict(values,fee_fresh=False))
        self.assertFalse(no['budget_eligible'])
        self.assertEqual(no['research_preferred_order_usd'],0)
        self.assertIn('FEE UNVERIFIED',diagnostic_text(no))
        no2=grade_lab(**dict(values,route_ideas=[dict(idea,oos_validated=False)]))
        self.assertFalse(no2['budget_eligible'])
        self.assertIn('preferred candidate size: $0.00',budget_text(no2).lower())
        no3=grade_lab(**dict(values,usd_complete=False))
        self.assertEqual(no3['research_preferred_order_usd'],0)

    def test_saved_gpu_evaluation_requires_both_heldout_baselines(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'CoinCat_GPU_Two_Way_ObserveOnly.pt').write_bytes(b'FAKE NO EXECUTION')
            body={'status':'EVALUATED','labeled':280,
                  'BUY':{'better_than_baseline':True},
                  'SELL_REBUY':{'better_than_baseline':False}}
            file=folder/'CoinCat_GPU_Two_Way_Research_Report.json'
            file.write_text(json.dumps(body))
            self.assertFalse(saved_gpu_heldout_status(folder))
            body['SELL_REBUY']['better_than_baseline']=True
            file.write_text(json.dumps(body))
            self.assertTrue(saved_gpu_heldout_status(folder))
            file.unlink()
            self.assertFalse(saved_gpu_heldout_status(folder))

    def test_no_price_appreciation_is_promised_by_raw_coverage(self):
        d=grade_lab(catalog_total=809,catalog_seen=809,focused_total=64,focused_mature=64,
              verified_forward_labels=250,fee_fresh=True,usd_complete=True,
              current_order_budget='10',scan_fresh=True,route_ideas=[])
        self.assertEqual(d['research_preferred_order_usd'],0)
        self.assertIn('data',diagnostic_text(d).lower())

if __name__=='__main__':unittest.main()
