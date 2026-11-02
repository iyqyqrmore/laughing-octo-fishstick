"""Per-observation deadlines and explicit, quantity-private working allocation."""
from copy import deepcopy
from decimal import Decimal as D
import json
import unittest

from coincat_eth_farmer import measure_eth, measure_working_eth, eth_quote_plan
from coincat_eth_diagnostics import structural_details
from coincat_working_allocation import (AllocationRow,OwnerAuthorization,ReconciliationEvidence,
    assess_allocation,allocation_keys,allocation_diagnostics)
from offline_tests.test_native_receipts import market,NOW
from offline_tests import gui_fixtures as gui


def allocation_fixture():
    balances={'ETH':D(3),'BTC':D('.2'),'USD':D(100),'EUR':D(2)}
    rows=(AllocationRow('ETH',D(1),D(1),D(1)),AllocationRow('BTC',D('.2')),
          AllocationRow('USD',manual=D(100)))
    keys=allocation_keys(balances,rows,{'EUR'})
    approval=OwnerAuthorization(*keys,True)
    evidence=ReconciliationEvidence(*keys,NOW,'PRIVATE_SETTLEMENT_REFERENCE','PRIVATE_CASHFLOW_REFERENCE',True,True,True,snapshot_at=NOW)
    return dict(balances=balances,balances_at=NOW,now=NOW,excluded={'EUR'},draft=rows,
                authorization=approval,reconciliation=evidence)


class WorkingAllocation(unittest.TestCase):
    def test_available_account_and_reserve_proposal_cannot_authorize_any_funds(self):
        value=assess_allocation(balances={'ETH':D(3)},balances_at=NOW,now=NOW)
        self.assertEqual(value['rows'][0]['unassigned'],D(3))
        self.assertEqual(value['rows'][0]['protected'],0)
        self.assertEqual(value['eligible_working_balances'],{})
        self.assertFalse(value['live_order_permission'])
        self.assertFalse(value['eth_profit_selection_enabled'])

    def test_disjoint_native_buckets_require_both_exact_owner_and_reconciliation_evidence(self):
        args=allocation_fixture();original=deepcopy(args)
        value=assess_allocation(**args)
        self.assertEqual(value['eligible_working_balances'],{'ETH':D(1),'BTC':D('.2')})
        self.assertEqual(value['state'],'AUTHORIZED_RECONCILED_MODEL_ONLY')
        for row in value['rows']:
            self.assertEqual(row['available'],sum(row[k] for k in ('working','manual','protected','excluded','unassigned')))
        self.assertEqual(args,original)
        for change in ({'authorization':None},{'reconciliation':None},{'balances_at':NOW-121}):
            refused=assess_allocation(**dict(args,**change))
            self.assertEqual(refused['eligible_working_balances'],{})
            self.assertFalse(refused['live_order_permission'])

    def test_changed_draft_available_snapshot_and_exclusions_invalidate_authorization(self):
        args=allocation_fixture()
        for change in ({'balances':dict(args['balances'],ETH=D('3.1'))},
                       {'draft':(AllocationRow('ETH',D(2),protected=D(1)),)+args['draft'][1:]},
                       {'excluded':set()}):
            value=assess_allocation(**dict(args,**change))
            self.assertFalse(value['owner_authorized'])
            self.assertEqual(value['eligible_working_balances'],{})
        fresh_snapshot=assess_allocation(**dict(args,balances_at=NOW+1,now=NOW+1))
        self.assertTrue(fresh_snapshot['owner_authorized'])  # Unchanged exact native draft.
        self.assertFalse(fresh_snapshot['reconciled'])  # Evidence must bind the particular snapshot.

    def test_unassigned_funds_and_invalid_overlapping_negative_float_or_protected_allocations_fail_closed(self):
        args=allocation_fixture()
        for draft in ((AllocationRow('ETH',D(4)),),(AllocationRow('BTC',protected=D('.1')),),
                      (AllocationRow('ETH',D(-1)),),(AllocationRow('ETH',.1),),
                      (AllocationRow('EUR',D(1)),),(AllocationRow('ETH'),AllocationRow('ETH'))):
            value=assess_allocation(**dict(args,draft=draft))
            self.assertEqual(value['state'],'INVALID_DRAFT')
            self.assertEqual(value['eligible_working_balances'],{})
        self.assertIn('UNASSIGNED_FUNDS',assess_allocation(**dict(args,draft=()))['blockers'])

    def test_stale_or_incomplete_settlement_flow_and_order_evidence_cannot_reconcile(self):
        from dataclasses import replace
        args=allocation_fixture()
        for change in ({'at':NOW-121},{'at':NOW+1},{'at':None},{'at':float('nan')},{'settled_verified':False},
                       {'external_flows_reconciled':False},{'no_unresolved_orders':False},
                       {'settlement_reference':''},{'cashflow_reference':''}):
            value=assess_allocation(**dict(args,reconciliation=replace(args['reconciliation'],**change)))
            self.assertFalse(value['reconciled']);self.assertEqual(value['eligible_working_balances'],{})

    def test_export_separates_roles_without_native_amounts_hashes_or_evidence_references(self):
        args=allocation_fixture();value=assess_allocation(**args);data=allocation_diagnostics(value)
        self.assertEqual(set(data['role_asset_counts']),{'WORKING','MANUAL','PROTECTED','EXCLUDED'})
        text=json.dumps(data)
        for raw in ('PRIVATE_SETTLEMENT_REFERENCE','PRIVATE_CASHFLOW_REFERENCE',value['snapshot_key'],value['draft_key']):
            self.assertNotIn(raw,text)
        for row in data['assets']:
            self.assertEqual(set(row),{'asset','roles','working_model_eligible'})

    def test_working_eth_never_falls_back_to_account_assets_or_manual_protected_amounts(self):
        q,rules=market();args=allocation_fixture()
        args['draft']=(AllocationRow('ETH',D(1),D(1),D(1)),AllocationRow('BTC',manual=D('.2')),args['draft'][2])
        keys=allocation_keys(args['balances'],args['draft'],args['excluded'])
        args['authorization']=OwnerAuthorization(*keys,True)
        args['reconciliation']=ReconciliationEvidence(*keys,NOW,'test settlement','test flows',True,True,True,snapshot_at=NOW)
        allocation=assess_allocation(**args)
        observation=dict(balances=args['balances'],balances_at=NOW,now=NOW,excluded=args['excluded'],
            catalog=list(q),rules=rules,quotes=q,fee_rate=D('.009'))
        value=measure_working_eth(allocation=allocation,observation=observation)
        self.assertEqual(value['estimated_recoverable_eth'],D(1))
        self.assertFalse(value['eth_profit_selection_enabled']);self.assertFalse(value['live_order_permission'])
        no_evidence=assess_allocation(**dict(args,reconciliation=None))
        self.assertIsNone(measure_working_eth(allocation=no_evidence,observation=observation)['estimated_recoverable_eth'])
        conflict=measure_working_eth(allocation=allocation,observation=dict(observation,balances={'ETH':D(300)}))
        self.assertEqual(conflict['reason'],'WORKING_ALLOCATION_SNAPSHOT_CONFLICT')


class ConversionBlockers(unittest.TestCase):
    def measure(self,**changes):
        q,rules=market()
        args=dict(result={'ranked':[]},balances={'BTC':D('.002')},quotes=q,rules=rules,
            catalog=list(q),now=NOW,balances_at=NOW,fee_rate=D('.009'))
        args.update(changes);return measure_eth(**args)

    def test_unknown_asset_and_two_leg_bound_are_explained_in_catalog_scope(self):
        q,rules=market()
        detail=structural_details('MYST',catalog=list(q),rules=rules)
        self.assertIn('NO_ETH_ROUTE_WITHIN_TWO_LEGS_IN_CATALOG',detail['blockers'])
        self.assertEqual(detail['evidence_scope'],'SUPPLIED_AUTHENTICATED_CATALOG_ONLY')
        plan=eth_quote_plan(balances={'MYST':D(1)},catalog=list(q),rules=rules)
        self.assertEqual(plan['structural_blockers'][0]['asset'],'MYST')
        self.assertFalse(plan['all_paths_supported']);self.assertIsNone(plan['account_required_books'])

    def test_restricted_products_and_missing_usd_marks_are_individual_structural_reasons(self):
        _,rules=market();sample=next(iter(rules.values()))
        catalog=['AAA-ETH','ETH-USD'];rules={p:dict(sample,product_id=p) for p in catalog}
        rules['AAA-ETH']['trading_disabled']=True
        detail=structural_details('AAA',catalog=catalog,rules=rules)
        self.assertIn('PRODUCT_RESTRICTED',detail['rejected_products'][0]['blockers'])
        catalog=['AAA-BBB','BBB-ETH','ETH-USD'];rules={p:dict(sample,product_id=p) for p in catalog}
        self.assertIn('USD_MARK_ROUTE_NOT_LISTED',structural_details('AAA',catalog=catalog,rules=rules)['blockers'])

    def test_missing_wide_stale_future_and_invalid_quotes_are_not_called_missing_routes(self):
        q,rules=market();catalog=['BTC-USD','ETH-USD']
        for book,reason in ((None,'QUOTE_UNOBSERVED'),((D(100),D(110),NOW),'QUOTE_WIDE'),
            ((D(100),D('100.01'),NOW-31),'QUOTE_STALE'),((D(100),D('100.01'),NOW+1),'QUOTE_FUTURE'),
            ((D(-1),D(2),NOW),'QUOTE_INVALID')):
            books={'ETH-USD':q['ETH-USD']}
            if book is not None:books['BTC-USD']=book
            value=self.measure(quotes=books,catalog=catalog)
            row=value['conversion_diagnostics']['holdings'][0]
            self.assertIn(reason,row['blockers'])
            self.assertIsNone(value['hold']['estimated_recoverable_eth'])
        # Age-invalid books are retained only as diagnostic observations. The
        # scanner's pricing cache has already removed them, not their evidence.
        stale=dict(q,**{'BTC-USD':(*q['BTC-USD'][:2],NOW-31)})
        value=self.measure(quotes={'ETH-USD':q['ETH-USD']},catalog=catalog,observed_quotes=stale)
        self.assertIn('QUOTE_STALE',value['conversion_diagnostics']['holdings'][0]['blockers'])
        self.assertEqual(value['hold']['orders'],[])
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])

    def test_base_quote_minima_maxima_and_precision_are_verified_without_fitting(self):
        for changed,reason,amount in (({'base_max_size':'.0001'},'ABOVE_BASE_MAXIMUM',D('.002')),
            ({'quote_max_size':'.0001'},'ABOVE_QUOTE_MAXIMUM',D('.002')),
            ({'base_min_size':'1'},'BELOW_BASE_MINIMUM',D('.002')),
            ({'quote_min_size':'1'},'BELOW_QUOTE_MINIMUM',D('.002')),
            ({},'PRECISION_BELOW_BASE_INCREMENT',D('.000000000000001'))):
            q,rules=market();rules['ETH-BTC'].update(changed)
            value=self.measure(balances={'BTC':amount},rules=rules)
            self.assertIn(reason,value['conversion_diagnostics']['holdings'][0]['blockers'])
            self.assertEqual(value['hold']['orders'],[])
            self.assertEqual(value['hold']['unconverted_native']['BTC'],amount)

    def test_rounding_residue_and_account_skew_do_not_become_complete_totals(self):
        q,rules=market();q['ETH-BTC']=(*q['ETH-BTC'][:2],NOW-17)
        value=self.measure(quotes=q,rules=rules)
        reasons=value['conversion_diagnostics']['holdings'][0]['blockers']
        self.assertIn('CANONICAL_ROUNDING_RESIDUE',reasons)
        self.assertIn('ETH_MEASUREMENT_PRICE_SKEW',reasons)
        self.assertFalse(value['conversion_diagnostics']['complete_total_available'])
        self.assertIsNone(value['hold']['estimated_recoverable_eth'])

    def test_reference_or_balance_unavailability_still_explains_every_holding_without_quantities(self):
        q,rules=market();q.pop('ETH-USD')
        value=self.measure(balances={'BTC':D('.002'),'MYST':D('9876543.2109876')},quotes=q)
        rows=value['conversion_diagnostics']['holdings']
        self.assertEqual({r['asset'] for r in rows},{'BTC','MYST'})
        self.assertTrue(all('ETH_REFERENCE_UNOBSERVED' in r['blockers'] for r in rows))
        self.assertNotIn('9876543.2109876',str(value['conversion_diagnostics']))
        self.assertTrue(all('AVAILABLE_SNAPSHOT_STALE_OR_UNOBSERVED' in r['blockers'] for r in
            self.measure(balances_at=NOW-121)['conversion_diagnostics']['holdings']))


class AllocationGUI(unittest.TestCase):
    setUp=gui.SimpleGUI.setUp

    def prepare(self):
        editor=self.app.allocation_editor;editor.clock=lambda:NOW
        editor.snapshot({'ETH':D(3),'BTC':D('.002')},NOW,NOW)
        self.root.update();editor.tree.selection_set('ETH');editor._select()
        return editor

    def test_local_draft_authorization_requires_action_and_reconciliation_remains_missing(self):
        editor=self.prepare();before=gui.ledger_dump(self.app.ledger)
        for name,value in {'working':'1','manual':'1','protected':'1'}.items():editor.fields[name].set(value)
        editor.apply_selected();editor.confirmed.set(True)
        self.assertIsNone(editor.authorization)
        editor.authorize();value=editor.assessment()
        self.assertTrue(value['owner_authorized']);self.assertFalse(value['reconciled'])
        self.assertEqual(value['eligible_working_balances'],{})
        self.assertEqual(before,gui.ledger_dump(self.app.ledger))
        self.assertIn('remain ineligible',editor.message.get())

    def test_invalid_entry_keeps_prior_draft_and_changes_revoke_exact_authorization(self):
        editor=self.prepare();editor.fields['working'].set('1');editor.apply_selected()
        editor.confirmed.set(True);editor.authorize();before=deepcopy(editor.draft)
        editor.fields['working'].set('NaN');editor.apply_selected()
        self.assertEqual(editor.draft,before)
        self.assertIsNone(editor.authorization)  # An edit revokes authorization even if it is later rejected.
        editor.fields['working'].set('2');editor.apply_selected();self.assertIsNone(editor.authorization)
        editor.confirmed.set(True);editor.authorize()
        editor.snapshot({'ETH':D('3.1'),'BTC':D('.002')},NOW+1,NOW+1)
        self.assertIsNone(editor.authorization)
        editor.clear();self.assertEqual(editor.draft,{})

    def test_full_available_defaults_are_proposals_and_manual_carveout_survives_live_refresh(self):
        editor=self.prepare()
        self.assertEqual(editor.draft['ETH'],AllocationRow('ETH',D(3)))
        self.assertEqual(editor.draft['BTC'],AllocationRow('BTC',D('.002')))
        self.assertEqual(editor.fields['working'].get(),'3')
        self.assertFalse(editor.assessment()['owner_authorized'])
        self.assertEqual(editor.assessment()['eligible_working_balances'],{})
        editor.fields['manual'].set('1')
        self.assertEqual(editor.fields['working'].get(),'2')
        editor.clock=lambda:NOW+12
        editor.snapshot({'ETH':D(3),'BTC':D('.002')},NOW+12,NOW+12)
        self.root.update()  # Deliver queued selection/theme events, as in a real refresh.
        self.assertEqual(editor.tree.selection(),('ETH',))
        self.assertEqual(editor.fields['manual'].get(),'1')
        self.assertEqual(editor.fields['working'].get(),'2')
        editor.apply_selected()
        self.assertEqual(editor.draft['ETH'],AllocationRow('ETH',D(2),D(1)))
        editor.fields['working'].set('.5')
        editor.clock=lambda:NOW+24
        editor.snapshot({'ETH':D(3),'BTC':D('.002')},NOW+24,NOW+24);self.root.update()
        self.assertEqual(editor.fields['working'].get(),'.5')
        editor.apply_selected();self.assertEqual(editor.draft['ETH'].working,D('.5'))
        self.assertEqual(editor.assessment()['rows'][1]['unassigned'],D('1.5'))
        editor.clear();editor.snapshot({'ETH':D(3),'BTC':D('.002')},NOW+25,NOW+25)
        self.assertEqual(editor.draft,{})  # Refresh cannot undo an explicit Clear.
        editor.reset_full();self.assertEqual(editor.draft['ETH'].working,D(3))

    def test_selected_asset_changes_load_correct_native_units_and_overallocation_remains_editable(self):
        editor=self.prepare();editor.tree.selection_set('BTC');self.root.update()
        self.assertEqual(editor.fields['working'].get(),'0.002')
        editor.fields['working'].set('.001');editor.apply_selected()
        editor.clock=lambda:NOW+1
        editor.snapshot({'ETH':D(3),'BTC':D('.0005')},NOW+1,NOW+1);self.root.update()
        self.assertEqual(editor.draft['BTC'].working,D('.001'))  # No silent resizing.
        self.assertTrue(editor.tree.exists('BTC'))
        self.assertIn('OVERALLOCATED',editor.tree.item('BTC')['values'])
        editor.fields['working'].set('.0005');editor.apply_selected()
        self.assertEqual(editor.assessment()['state'],'UNRECONCILED')
        editor.confirmed.set(True);editor.authorize();self.assertIsNotNone(editor.authorization)
        editor.fields['manual'].set('.0001')
        self.assertIsNone(editor.authorization)
        editor.confirmed.set(True);editor.authorize();self.assertIsNone(editor.authorization)

    def test_editor_fits_minimum_window_and_cannot_authorize_stale_snapshot_or_override_exclusion(self):
        editor=self.prepare();self.root.geometry('1040x780')
        editor.master.master.select(editor.master);self.root.update()
        editor.canvas.yview_moveto(1);self.root.update()
        self.assertGreater(editor.canvas.yview()[1],editor.canvas.yview()[0])
        buttons=[]
        def visit(widget):
            if widget.winfo_class()=='TButton':buttons.append(widget)
            for child in widget.winfo_children():visit(child)
        visit(editor)
        for button in buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
            self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
        editor.fields['working'].set('1');editor.apply_selected();editor.confirmed.set(True)
        editor.clock=lambda:NOW+121;editor.authorize();self.assertIsNone(editor.authorization)
        editor.clock=lambda:NOW
        editor.clear();editor.snapshot({'ETH':D(3),'BTC':D('.002')},NOW,NOW,{'BTC'})
        editor.tree.selection_set('BTC');editor._select();editor.fields['working'].set('.001')
        editor.apply_selected();self.assertNotIn('BTC',editor.draft)
        editor.clear();editor.snapshot({f'ASSET{i}':D(1) for i in range(27)},NOW,NOW)
        editor.tree.yview_moveto(1);self.root.update()
        self.assertGreater(editor.tree.yview()[0],0)
        self.assertEqual(len(editor.tree.get_children()),27)

    def test_draft_cannot_mutate_private_ledger_or_leak_native_amounts_in_v95_export(self):
        app=self.app;editor=self.prepare();before=gui.ledger_dump(app.ledger)
        editor.fields['working'].set('1');editor.fields['protected'].set('2');editor.apply_selected()
        self.assertEqual(before,gui.ledger_dump(app.ledger))
        self.assertEqual(editor.assessment()['eligible_working_balances'],{})
        editor.draft['ETH']=AllocationRow('ETH',D('.00098765432109876'),protected=D('2'))
        from coincat_simple_diagnostics import make_report
        report=make_report(app,now=NOW)
        self.assertIn('COMPLETE (8/8)',report)
        self.assertIn('ETH MAKER RESEARCH',report);self.assertIn('working_allocation',report)
        self.assertNotIn('0.00098765432109876',report)
        self.assertNotIn(str(app.ledger.path),report)
