"""Exact, read-only allocation contract. No persistence or execution interface.

An account AVAILABLE snapshot is not a settled/authorized working allocation.
The GUI can record a RAM draft and owner authorization, but has no provider of
verified settlement/cashflow evidence. All live permissions remain false.
"""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, localcontext, Inexact
import hashlib
import json
import math
import re

from coincat_v80_immediate import exact

D = Decimal


@dataclass(frozen=True)
class AllocationRow:
    asset: str
    working: D = D(0)
    manual: D = D(0)
    protected: D = D(0)


@dataclass(frozen=True)
class OwnerAuthorization:
    snapshot_key: str
    draft_key: str
    confirmed: bool = False


@dataclass(frozen=True)
class ReconciliationEvidence:
    snapshot_key: str
    draft_key: str
    at: float
    settlement_reference: str
    cashflow_reference: str
    settled_verified: bool = False
    external_flows_reconciled: bool = False
    no_unresolved_orders: bool = False
    snapshot_at: float | None = None


def quantity(raw):
    value=exact(raw)
    if value<0:
        raise ValueError('NEGATIVE_ALLOCATION')
    return value


def public_asset(asset):
    """Only public ticker syntax; never echo arbitrary imported text."""
    return asset if isinstance(asset,str) and re.fullmatch(r'[A-Z0-9]{1,24}',asset) else 'UNRECOGNIZED_ASSET'


def _digest(values):
    return hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).hexdigest()


def allocation_keys(balances, draft=(), excluded=()):
    with localcontext() as ctx:
        ctx.prec=60;ctx.traps[Inexact]=True
        snapshot=_digest([(a,str(quantity(q).normalize()),a in excluded) for a,q in sorted(balances.items())])
        proposal=_digest([(r.asset,*(str(quantity(q).normalize()) for q in
            (r.working,r.manual,r.protected))) for r in sorted(draft,key=lambda r:r.asset)])
    return snapshot,proposal


def _recent(stamp,now):
    try:
        return (not isinstance(stamp,bool) and math.isfinite(float(stamp)) and
                math.isfinite(float(now)) and 0<=float(now)-float(stamp)<=120)
    except (TypeError,ValueError,OverflowError):
        return False


def assess_allocation(*, balances, balances_at, now, excluded=(), draft=(),
                      authorization=None, reconciliation=None):
    """Disjoint native buckets, exact snapshot binding, explicit evidence.

    Reconciliation evidence must come from a separately verified provider; a
    balanced worksheet or an authorization checkbox cannot create it. The
    application intentionally supplies none. No balance is automatically manual,
    working, settled, earned, or protected by the reserve calculator.
    """
    out={'state':'UNRECONCILED','rows':[],'blockers':[],
         'eligible_working_balances':{},'owner_authorized':False,'reconciled':False,
         'live_order_permission':False,'eth_profit_selection_enabled':False,
         'scope':'RAM_DRAFT_NOT_FINANCIAL_LEDGER','snapshot_key':None,'draft_key':None}
    try:
        with localcontext() as ctx:
            ctx.prec=60;ctx.traps[Inexact]=True
            wallet={a:quantity(q) for a,q in balances.items()}
            snapshot,proposal=allocation_keys(wallet,draft,excluded)
            out.update(snapshot_key=snapshot,draft_key=proposal)
            assigned={}
            for row in draft:
                if row.asset in assigned or row.asset not in wallet:
                    raise ValueError('DUPLICATE_OR_UNKNOWN_ALLOCATION_ASSET')
                values=tuple(quantity(q) for q in (row.working,row.manual,row.protected))
                if row.asset!='ETH' and values[2]:
                    raise ValueError('PROTECTED_RESERVE_MUST_BE_ETH')
                if sum(values)>wallet[row.asset]:
                    raise ValueError('ALLOCATION_EXCEEDS_AVAILABLE')
                if row.asset in excluded and any(values):
                    raise ValueError('EXCLUDED_ASSET_CANNOT_BE_ASSIGNED')
                assigned[row.asset]=values
            for asset,available in sorted(wallet.items()):
                working,manual,protected=assigned.get(asset,(D(0),D(0),D(0)))
                excluded_quantity=available if asset in excluded else D(0)
                unassigned=available-working-manual-protected-excluded_quantity
                out['rows'].append(dict(asset=asset,available=available,working=working,manual=manual,
                    protected=protected,excluded=excluded_quantity,unassigned=unassigned))
    except (ValueError,TypeError,AttributeError,ArithmeticError):
        out['state']='INVALID_DRAFT';out['blockers']=['INVALID_NATIVE_ALLOCATION']
        return out
    if not _recent(balances_at,now):
        out['blockers'].append('AVAILABLE_SNAPSHOT_STALE_OR_UNOBSERVED')
    if any(row['unassigned'] for row in out['rows']):
        out['blockers'].append('UNASSIGNED_FUNDS')
    approved=(isinstance(authorization,OwnerAuthorization) and authorization.confirmed is True and
              authorization.snapshot_key==snapshot and authorization.draft_key==proposal)
    out['owner_authorized']=approved
    if not approved:
        out['blockers'].append('EXACT_DRAFT_OWNER_AUTHORIZATION_MISSING')
    reconciled=(isinstance(reconciliation,ReconciliationEvidence) and
        reconciliation.snapshot_key==snapshot and reconciliation.draft_key==proposal and
        reconciliation.snapshot_at==balances_at and not isinstance(reconciliation.snapshot_at,bool) and
        reconciliation.settled_verified is True and reconciliation.external_flows_reconciled is True and
        reconciliation.no_unresolved_orders is True and
        isinstance(reconciliation.settlement_reference,str) and bool(reconciliation.settlement_reference.strip()) and
        isinstance(reconciliation.cashflow_reference,str) and bool(reconciliation.cashflow_reference.strip()) and
        _recent(reconciliation.at,now))
    out['reconciled']=reconciled
    if not reconciled:
        out['blockers'].append('VERIFIED_SETTLEMENT_AND_CASHFLOW_RECONCILIATION_MISSING')
    if not any(row['working'] for row in out['rows']):
        out['blockers'].append('NO_EXPLICIT_WORKING_FUNDS')
    if not out['blockers']:
        out['state']='AUTHORIZED_RECONCILED_MODEL_ONLY'
        out['eligible_working_balances']={r['asset']:r['working'] for r in out['rows'] if r['working']}
    return out


def allocation_diagnostics(value):
    """A strict export projection; no quantities, fingerprints or evidence refs."""
    roles=Counter();rows=[]
    for row in value.get('rows',()):
        assigned=[role.upper() for role in ('working','manual','protected','excluded','unassigned') if row[role]]
        roles.update(assigned)
        rows.append({'asset':public_asset(row['asset']),'roles':assigned,
                     'working_model_eligible':row['asset'] in value.get('eligible_working_balances',{})})
    return {'state':value['state'],'scope':value['scope'],'blockers':list(value['blockers']),
            'owner_authorized':value['owner_authorized'],'reconciled':value['reconciled'],
            'role_asset_counts':dict(roles),'assets':rows,
            'eth_profit_selection_enabled':False,'live_order_permission':False}
