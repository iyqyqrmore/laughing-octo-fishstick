"""Per-observation deadlines and explicit, quantity-private working allocation."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
import json
import unittest

from coincat_eth_farmer import measure_eth, measure_working_eth, eth_quote_plan
from coincat_eth_diagnostics import structural_details
from coincat_working_allocation import (AllocationRow,OwnerAuthorization,ReconciliationEvidence,
    assess_allocation,allocation_keys,allocation_diagnostics)
from coincat_v80_discovery import select_books
from coincat_passive_lab import PassiveLab,HORIZONS
from offline_tests.test_v91_full_balance import market,NOW
from offline_tests.test_research_scheduler import isolated_jobs
from offline_tests import test_v91_scanner_gui as gui


def deadline_fixture(planner=select_books):
    """Eight independent deadline-contention episodes, not the uploaded misses.

    Six 15m and two 60m observations have 10s remaining. A competing horizon
    has aging priority but 120s remaining. Both fit over two 12s turns, never
    together in six books. No candidate is admitted during the fixture.
    """
    outcomes={'completed':0,'missed':0,'max_requests':0,'all_jobs_completed':0}
    for horizon in (900,)*6+(3600,)*2:
        lab,rules=isolated_jobs();other=300
        lab.pending={k:r for k,r in lab.pending.items() if k in (f'{horizon}_0',f'{other}_0')}
        lab.pending[f'{horizon}_0']['at']=NOW-horizon-110
        lab.pending[f'{other}_0']['at']=NOW-other
        lab.service_wait[other]=2
        quotes={}
        for at in (NOW,NOW+12):
            plan=planner(list(rules),rules,set(),quotes=quotes,now=at,
                priority_groups=lab.quote_groups(now=at))
            assert plan['endpoint_requests']<=6 and len(plan['books'])<=16
            outcomes['max_requests']=max(outcomes['max_requests'],len(plan['books']))
            incoming={p:(D(100),D('100.01'),at) for p in plan['books']}
            quotes.update(incoming);lab.record_service(plan,incoming,{},now=at)
            lab.observe({'ranked':[]},quotes,now=at)
        outcomes['completed']+=lab.counts[f'{horizon}_NOT_ABOVE_HOLD']+lab.counts[f'{horizon}_ABOVE_HOLD']
        outcomes['missed']+=lab.counts[f'{horizon}_MISSED']
        outcomes['all_jobs_completed']+=sum(lab.counts[f'{h}_NOT_ABOVE_HOLD']+lab.counts[f'{h}_ABOVE_HOLD'] for h in HORIZONS)
        assert lab.admission['admitted_distinct']==0
    return outcomes


class ObservationDeadlines(unittest.TestCase):
    def test_eight_individual_deadlines_are_met_without_more_books_or_admissions(self):
        result=deadline_fixture()
        self.assertEqual(result,{'completed':8,'missed':0,'max_requests':5,'all_jobs_completed':16})
        baseline=json.loads(Path(__file__).with_name('deadline_contention_baseline.json').read_text())
        self.assertLess(result['missed'],baseline['baseline']['missed'])
        self.assertEqual(result['max_requests'],baseline['baseline']['max_requests'])

    def test_deferral_explains_competition_limit_and_remaining_time_per_observation(self):
        lab,rules=isolated_jobs();quotes={}
        # Both jobs are urgent; the earlier deadline must get the single turn.
        lab.pending={k:r for k,r in lab.pending.items() if k in ('900_0','3600_0')}
        lab.pending['900_0']['at']=NOW-900-115
        lab.pending['3600_0']['at']=NOW-3600-110
        plan=select_books(list(rules),rules,set(),quotes=quotes,now=NOW,priority_groups=lab.quote_groups(now=NOW))
        incoming={p:(D(100),D('100.01'),NOW) for p in plan['books']}
        lab.record_service(plan,incoming,{},now=NOW);lab.observe({'ranked':[]},incoming,now=NOW)
        lab.observe({'ranked':[]},incoming,now=NOW+13)
        event=lab.diagnostics()['capacity_miss_records'][0]
        self.assertEqual(event['horizon_s'],3600)
        self.assertEqual(event['required_books'],5)
        self.assertEqual(event['remaining_s'],10)
        self.assertEqual(event['competing_groups'],1)
        self.assertEqual(set(event['blockers']),{'SIX_BOOK_RESEARCH_LIMIT','COMPETING_DEADLINE_GROUPS','NO_CONSERVATIVE_RETRY_WINDOW'})
        self.assertEqual(event['observation_deferral_passes'],1)
        self.assertNotIn('deadline',event)

    def test_oversized_dependency_group_is_distinguished_from_competing_groups(self):
        q,rules=market()
        names=tuple(f'AA{i}-USD' for i in range(7))
        rules={p:dict(next(iter(rules.values())),product_id=p) for p in names}
        job=('PRIVATE_OBSERVATION_ID',900)
        plan=select_books(names,rules,set(),quotes={},now=NOW,priority_groups=[
            {'books':names,'earliest':NOW,'deadline':NOW+3,'jobs':[job]}])
        detail=plan['_research_evidence'][job]
        self.assertIn('DEPENDENCIES_CANNOT_FIT_TOGETHER',detail['blockers'])
        self.assertIn('LESS_THAN_COLLECTION_WINDOW_REMAINING',detail['blockers'])
        self.assertNotIn('COMPETING_DEADLINE_GROUPS',detail['blockers'])
        self.assertEqual(plan['endpoint_requests'],0)

    def test_shared_dependency_union_fits_without_counting_jobs_as_requests(self):
        _,rules=isolated_jobs();sample=next(iter(rules.values()))
        names=tuple(f'SH{i}-USD' for i in range(6));rules={p:dict(sample,product_id=p) for p in names}
        groups=[dict(books=names[:5],earliest=NOW,deadline=NOW+9,jobs=[('one',900)]),
                dict(books=names[1:],earliest=NOW,deadline=NOW+10,jobs=[('two',3600)])]
        plan=select_books(names,rules,set(),quotes={},now=NOW,priority_groups=groups)
        self.assertEqual(plan['endpoint_requests'],6)
        self.assertEqual(set(plan['_research_scheduled']),{('one',900),('two',3600)})

    def test_actual_late_collection_is_reported_without_claiming_estimated_service(self):
        lab,rules=isolated_jobs();lab.pending={k:r for k,r in lab.pending.items() if k=='900_0'}
        lab.pending['900_0']['at']=NOW-900-115
        plan=select_books(list(rules),rules,set(),quotes={},now=NOW,priority_groups=lab.quote_groups(now=NOW))
        incoming={p:(D(100),D('100.01'),NOW+6) for p in plan['books']}
        lab.record_service(plan,incoming,{},now=NOW+6);lab.observe({'ranked':[]},incoming,now=NOW+6)
        event=lab.diagnostics()['capacity_miss_records'][0]
        self.assertTrue(event['collection_finished_after_deadline'])
        self.assertEqual(event['terminal_cause'],'COLLECTION_FINISHED_AFTER_DEADLINE')
        self.assertEqual(lab.counts['900_MISSED'],1)
        self.assertEqual(lab.counts['900_NOT_ABOVE_HOLD'],0)

    def test_miss_records_are_bounded_and_have_no_observation_ids_or_amounts(self):
        lab,_=isolated_jobs();row=deepcopy(lab.pending['900_0']);lab.pending={}
        row['at']=NOW-900-121;row['blocked'][900]='RESEARCH_SHARE_DEFERRED'
        row['spent']=D('9876543.2109876')
        for n in range(260):lab.pending[f'PRIVATE_OBSERVATION_ID_{n}']=deepcopy(row)
        lab.observe({'ranked':[]},{},now=NOW)
        data=lab.diagnostics()
        self.assertEqual(len(data['capacity_miss_records']),256)
        self.assertEqual(data['capacity_miss_records_dropped'],4)
        self.assertNotIn('PRIVATE_OBSERVATION_ID',str(data))
        self.assertNotIn('9876543.2109876',str(data))


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
        self.assertIsNotNone(editor.authorization)
        editor.fields['working'].set('2');editor.apply_selected();self.assertIsNone(editor.authorization)
        editor.confirmed.set(True);editor.authorize()
        editor.snapshot({'ETH':D('3.1'),'BTC':D('.002')},NOW+1,NOW+1)
        self.assertIsNone(editor.authorization)
        editor.clear();self.assertEqual(editor.draft,{})

    def test_editor_fits_minimum_window_and_cannot_authorize_stale_snapshot_or_override_exclusion(self):
        editor=self.prepare();self.root.geometry('1040x780')
        editor.master.master.select(editor.master);self.root.update()
        editor.canvas.yview_moveto(1);self.root.update()
        self.assertGreater(editor.canvas.yview()[0],0)
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

    def test_draft_does_not_change_v91_full_available_sizing_or_export_native_amounts(self):
        app=self.app;client=gui.FakeClient()
        from coincat_scanner import Scanner
        from coincat_simple_diagnostics import make_report
        app.scanner=Scanner(app.ledger,client,app.fees,app.market);app.scanner.refresh(now=NOW)
        original=app.scanner.scan(now=NOW,collect=gui.collector(client))
        editor=app.allocation_editor;editor.clock=lambda:NOW
        editor.snapshot(app.scanner.balances,NOW,NOW)
        editor.tree.selection_set('BTC');editor._select();editor.fields['working'].set('.001')
        editor.fields['manual'].set('.001');editor.apply_selected();editor.confirmed.set(True);editor.authorize()
        result=app.scanner.scan(now=NOW,collect=gui.collector(client),**editor.parameters())
        self.assertEqual(original['ranked'],result['ranked'])
        self.assertEqual(result['best']['available'],D('.002'))
        self.assertEqual(result['working_allocation']['eligible_working_balances'],{})
        app.last_result=result;app._render(result)
        # Inject a sentinel into private/local views; exports must project only roles/reasons.
        editor.draft['BTC']=AllocationRow('BTC',D('.00098765432109876'),D('.00101234567890124'))
        report=make_report(app,now=NOW)
        self.assertIn('COMPLETE (8/8)',report)
        self.assertIn('eth_conversion_blockers',report);self.assertIn('working_allocation',report)
        self.assertNotIn('0.00098765432109876',report)
        self.assertNotIn(str(app.ledger.path),report)
        self.assertFalse(result['live_order_permission'])
