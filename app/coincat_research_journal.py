"""Prospective conditional experiments in a separate local research database.

No client, financial database, credentials, order channel or paper settlement.
Registration is explicit; existing observations can update registered comparisons.
Closed experiments remain recorded, including unknown/late/adverse outcomes.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import fields
from decimal import Decimal as D
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from coincat_adaptive_eth import Frame, ForwardStudy, ResearchFunds

APP_ID = 0x4343524A
MAX_ACTIVE = 32
MAX_CASES = 256
MAX_BYTES = 32*1024*1024
MAX_PAYLOAD = 131072
MAX_DETAILS = 512
STATES = ('WAITING','CONDITIONAL_OUTCOME','UNKNOWN_AT_HORIZON','MISSED_HORIZON')
COUNTS = ('registered','waiting','conditional_outcomes','adverse','favorable','no_fill',
          'unknown','missed_horizons','underwater_cases','unpriced_open_cases','gap_episodes','truncated_cases')


class JournalError(ValueError):
    pass


def _encode(value):
    if isinstance(value, D):
        if not value.is_finite():raise JournalError('INVALID_JOURNAL_NUMBER')
        return {'decimal':str(value)}
    if isinstance(value, Frame):
        return {'frame':_encode({f.name:getattr(value,f.name) for f in fields(Frame)})}
    if isinstance(value, dict):
        return {'mapping':[[_encode(k),_encode(v)] for k,v in value.items()]}
    if isinstance(value, tuple):return {'tuple':[_encode(x) for x in value]}
    if isinstance(value, list):return [_encode(x) for x in value]
    if value is None or type(value) in (str,bool,int):return value
    if type(value) is float and math.isfinite(value):return value
    raise JournalError('UNSUPPORTED_JOURNAL_VALUE')


def _decode(value):
    if isinstance(value,list):return [_decode(x) for x in value]
    if not isinstance(value,dict):return value
    if set(value)=={'decimal'}:
        out=D(value['decimal'])
        if not out.is_finite():raise JournalError('INVALID_JOURNAL_NUMBER')
        return out
    if set(value)=={'tuple'}:return tuple(_decode(x) for x in value['tuple'])
    if set(value)=={'mapping'}:
        out={}
        for key,raw in value['mapping']:
            key=_decode(key)
            if key in out:raise JournalError('DUPLICATE_JOURNAL_KEY')
            out[key]=_decode(raw)
        return out
    if set(value)=={'frame'}:
        raw=_decode(value['frame'])
        if set(raw)!={f.name for f in fields(Frame)}:raise JournalError('INVALID_JOURNAL_FRAME')
        return Frame(**raw)
    raise JournalError('INVALID_JOURNAL_ENCODING')


def _dump(value):
    raw=json.dumps(_encode(value),separators=(',',':'),allow_nan=False)
    if len(raw.encode('utf-8'))>MAX_PAYLOAD:raise JournalError('JOURNAL_PAYLOAD_LIMIT')
    return raw


def _reject_constant(value):
    raise JournalError('INVALID_JOURNAL_NUMBER')


def _load(raw):
    if len(raw.encode('utf-8'))>MAX_PAYLOAD:raise JournalError('JOURNAL_PAYLOAD_LIMIT')
    try:
        return _decode(json.loads(raw,parse_constant=_reject_constant))
    except (ValueError,TypeError,KeyError,ArithmeticError,RecursionError):
        raise JournalError('INVALID_JOURNAL_RECORD') from None


def _study(case):
    """Version-1 research cache; no persisted Python objects or code execution."""
    if (not isinstance(case,dict) or case.get('state') not in STATES or
            not isinstance(case.get('frame'),Frame) or case.get('confidence')!='UNVALIDATED'):
        raise JournalError('INVALID_JOURNAL_CASE')
    study=ForwardStudy()
    study._cases['case']=deepcopy(case)
    return study


def public_status(value=None):
    """Fixed fields and counts only; never names, IDs, inputs, frames or amounts."""
    value=value if isinstance(value,dict) else {}
    out={k:value.get(k,0) if type(value.get(k,0)) is int and 0<=value.get(k,0)<=1000000000 else 0 for k in COUNTS}
    out.update(state=value.get('state') if value.get('state') in
        ('READY','EMPTY','CANCELLED','STORAGE_LIMIT','UNAVAILABLE') else 'UNAVAILABLE',
        edge='NO_DEMONSTRATED_EDGE',paper_trades=0,verified_fills=0)
    return out


def validate_public(value):
    if not isinstance(value,dict) or set(value)!=set(COUNTS)|{'state','edge','paper_trades','verified_fills'}:
        raise JournalError('INVALID_JOURNAL_PUBLIC_SCHEMA')
    if any(type(value[k]) is not int for k in (*COUNTS,'paper_trades','verified_fills')) or value!=public_status(value):
        raise JournalError('INVALID_JOURNAL_PUBLIC_VALUE')
    return value


class ResearchJournal:
    def __init__(self,path,*,clock=time.time,max_bytes=MAX_BYTES):
        self.path=Path(path);self.clock=clock;self.max_bytes=max_bytes
        if self.path.is_symlink() or self.path.parent.is_symlink():raise JournalError('JOURNAL_SYMLINK_REJECTED')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self._db()) as db, db:
            identity=db.execute('PRAGMA application_id').fetchone()[0]
            tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity not in (0,APP_ID) or (identity==0 and tables):
                raise JournalError('WRONG_RESEARCH_JOURNAL_FILE')
            if identity==0:
                db.execute('PRAGMA application_id='+str(APP_ID))
                db.execute('CREATE TABLE experiment_meta(version INTEGER NOT NULL)')
                db.execute('INSERT INTO experiment_meta VALUES(1)')
                db.execute('''CREATE TABLE experiments(
                    reference TEXT PRIMARY KEY,registered_at REAL NOT NULL,horizon_at REAL NOT NULL,
                    state TEXT NOT NULL,registration TEXT NOT NULL,latest TEXT NOT NULL,
                    last_detail_at REAL NOT NULL,details INTEGER NOT NULL DEFAULT 0,
                    gap_episodes INTEGER NOT NULL DEFAULT 0,truncated INTEGER NOT NULL DEFAULT 0)''')
                db.execute('''CREATE TABLE experiment_events(
                    sequence INTEGER PRIMARY KEY,reference TEXT NOT NULL,observed_at REAL NOT NULL,
                    kind TEXT NOT NULL,payload TEXT NOT NULL,
                    FOREIGN KEY(reference) REFERENCES experiments(reference))''')
            if db.execute('SELECT version FROM experiment_meta').fetchall()!=[(1,)]:
                raise JournalError('UNSUPPORTED_RESEARCH_JOURNAL_VERSION')

    def _db(self):
        db=sqlite3.connect(self.path,timeout=1)
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def _capacity(self):
        if self.path.stat().st_size>=self.max_bytes:raise JournalError('JOURNAL_STORAGE_LIMIT')

    def register(self,reference,*,funds,leg,quantity,frame,horizon_s,signal_id,
                 fill_state,slippage_bps=D(15)):
        if not isinstance(reference,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',reference):
            raise JournalError('INVALID_EXPERIMENT_REFERENCE')
        if not isinstance(signal_id,str) or not re.fullmatch(r'[A-Z0-9_]{1,48}',signal_id):
            raise JournalError('EXPLICIT_SIGNAL_ID_REQUIRED')
        # Registration uses wall-clock time, not a retrospective quote timestamp.
        now=float(self.clock())
        if not math.isfinite(now) or not 0<=now-frame.at<=1:
            raise JournalError('REGISTRATION_MUST_BE_PROSPECTIVE')
        frozen=Frame(now,frame._catalog,frame._rules,frame._quotes,frame._tier,
                     frame._excluded,frame._depth,frame._fee_units)
        study=ForwardStudy()
        case=study.freeze('case',funds=funds,leg=leg,quantity=quantity,frame=frozen,
            horizon_s=horizon_s,signal=dict(id=signal_id,prediction='TARGET_OUTPERFORMS_SOURCE',
            validation='UNVALIDATED_MANUAL_HYPOTHESIS'),exit_condition='FIXED_HORIZON_NO_POSITION_CLOSE',
            fill_state=fill_state,slippage_bps=slippage_bps)
        # Store provenance separately; the source-HOLD experiment never settles it.
        registration=dict(case=case,initial_eth=funds.initial_eth,
            supplied_simulated_inventory=funds.inventory(),simulated_event_count=len(funds._events),
            independent_counterfactual=True)
        payload=_dump(registration);latest=_dump(case)
        self._capacity()
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0]>=MAX_CASES:
                raise JournalError('JOURNAL_CASE_LIMIT')
            if db.execute("SELECT COUNT(*) FROM experiments WHERE state='WAITING'").fetchone()[0]>=MAX_ACTIVE:
                raise JournalError('JOURNAL_ACTIVE_LIMIT')
            if db.execute('SELECT 1 FROM experiments WHERE reference=?',(reference,)).fetchone():
                raise JournalError('EXPERIMENT_ALREADY_REGISTERED')
            db.execute('INSERT INTO experiments VALUES(?,?,?,?,?,?,?,0,0,0)',
                (reference,now,case['horizon_at'],'WAITING',payload,latest,now))
            db.execute('INSERT INTO experiment_events(reference,observed_at,kind,payload) VALUES(?,?,?,?)',
                (reference,now,'REGISTERED',_dump(dict(signal_id=signal_id,fill_state=fill_state))))
        return self.case(reference)

    def case(self,reference):
        with closing(self._db()) as db:
            row=db.execute('SELECT registration,latest,gap_episodes,truncated FROM experiments WHERE reference=?',
                           (reference,)).fetchone()
        if row is None:raise JournalError('EXPERIMENT_NOT_FOUND')
        return dict(registration=_load(row[0]),latest=_load(row[1]),gap_episodes=row[2],detail_truncated=bool(row[3]))

    def events(self,reference):
        with closing(self._db()) as db:
            rows=db.execute('SELECT observed_at,kind,payload FROM experiment_events WHERE reference=? ORDER BY sequence',
                            (reference,)).fetchall()
        return [dict(at=at,kind=kind,payload=_load(payload)) for at,kind,payload in rows]

    def list_cases(self):
        """Local-only view. Signal IDs and native results never enter public_status."""
        with closing(self._db()) as db:
            rows=db.execute('SELECT reference,registered_at,horizon_at,latest FROM experiments '
                            'ORDER BY registered_at,reference LIMIT ?',(MAX_CASES,)).fetchall()
        result=[]
        for reference,registered,horizon,raw in rows:
            case=_load(raw);receipt=case['entry']['receipts'][0];outcome=case.get('outcome') or {}
            result.append(dict(reference=reference,signal=case['signal']['id'],
                source=receipt['input_asset'],target=receipt['output_asset'],
                registered_at=registered,horizon_at=horizon,state=case['state'],
                observed_holding_s=max(0,case['last_at']-registered),relative_eth=outcome.get('relative_eth'),
                reasons=outcome.get('reasons',case.get('last_quality_reasons',[]))))
        return result

    def observe(self,frame,*,cancel=None):
        stopped=lambda:cancel is not None and cancel.is_set()
        if stopped():return dict(self.summary(),state='CANCELLED')
        self._capacity()
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT reference,latest,last_detail_at,details,gap_episodes,truncated FROM experiments "
                            "WHERE state='WAITING' ORDER BY registered_at,reference LIMIT ?",(MAX_ACTIVE,)).fetchall()
            for reference,raw,last_detail,details,gaps,truncated in rows:
                if stopped():db.rollback();return dict(self.summary(),state='CANCELLED')
                old=_load(raw)
                if frame.at<=old['last_at']:continue
                study=_study(old);case=study.observe('case',frame)
                gap=frame.at-old['last_at']>30
                reasons=case.get('last_quality_reasons',[])
                quality_changed=reasons!=old.get('last_quality_reasons',[])
                terminal=case['state']!='WAITING'
                save_detail=terminal or gap or quality_changed or frame.at-last_detail>=60
                kinds=[]
                if gap:kinds.append('OBSERVATION_GAP');gaps+=1
                if terminal:kinds.append(case['state'])
                elif quality_changed:kinds.append('QUALITY_CHANGED')
                elif save_detail:kinds.append('OBSERVED')
                if save_detail and (details<MAX_DETAILS or terminal):
                    payload=dict(state=case['state'],reasons=reasons,outcome=case.get('outcome'),
                        adverse_vs_hold_eth=case['adverse_vs_hold_eth'],last_value_eth=case['last_value_eth'])
                    for kind in kinds:
                        db.execute('INSERT INTO experiment_events(reference,observed_at,kind,payload) VALUES(?,?,?,?)',
                            (reference,frame.at,kind,_dump(payload)))
                    last_detail=frame.at;details+=1
                elif save_detail and not truncated:
                    db.execute('INSERT INTO experiment_events(reference,observed_at,kind,payload) VALUES(?,?,?,?)',
                        (reference,frame.at,'DETAIL_HISTORY_LIMIT_REACHED',_dump({'reason':'BOUNDED_DETAIL_HISTORY'})))
                    truncated=1
                # Latest state remains exact even after detailed history is capped.
                db.execute('UPDATE experiments SET state=?,latest=?,last_detail_at=?,details=?,gap_episodes=?,truncated=? '
                           'WHERE reference=?',(case['state'],_dump(case),last_detail,details,gaps,truncated,reference))
            if stopped():db.rollback();return dict(self.summary(),state='CANCELLED')
            # Context commits only after the final cancellation check.
        return self.summary()

    def summary(self):
        out=dict.fromkeys(COUNTS,0)
        with closing(self._db()) as db:
            rows=db.execute('SELECT latest,gap_episodes,truncated FROM experiments ORDER BY registered_at LIMIT ?',
                            (MAX_CASES,)).fetchall()
        out['registered']=len(rows)
        for raw,gaps,truncated in rows:
            case=_load(raw);summary=_study(case).summary()
            out['waiting']+=case['state']=='WAITING'
            out['conditional_outcomes']+=case['state']=='CONDITIONAL_OUTCOME'
            out['adverse']+=summary['adverse'];out['favorable']+=summary['favorable']
            out['no_fill']+=summary['no_fill'];out['unknown']+=summary['unknown']
            out['missed_horizons']+=case['state']=='MISSED_HORIZON'
            out['underwater_cases']+=summary['underwater_open']
            out['unpriced_open_cases']+=case['state']=='WAITING' and case['last_value_eth'] is None
            out['gap_episodes']+=gaps;out['truncated_cases']+=bool(truncated)
        out['state']='READY' if rows else 'EMPTY'
        return public_status(out)


def register_from_eth(journal,reference,*,frame,initial_eth,source,target,horizon_s,
                      signal_id,fill_state,explicit_assumption,slippage_bps=D(15)):
    """Manual conditional branch: optional ETH→source assumption, never real funds.

    This makes no allocation decision. The caller must supply and confirm the
    exact ETH what-if size; no saved funds, automatic seed or reusable wallet.
    """
    if explicit_assumption is not True:raise JournalError('EXPLICIT_CONDITIONAL_ASSUMPTION_REQUIRED')
    funds=ResearchFunds(initial_eth)
    if source!='ETH':
        seed=next((a for a in frame.graph('ETH')['actions'] if a['target']==source),None)
        if seed is None:raise JournalError('SOURCE_ASSUMPTION_MARKET_UNAVAILABLE')
        result=funds.reserve('explicit-source-assumption',leg=seed['leg'],quantity=funds.initial_eth,
                             frame=frame,slippage_bps=slippage_bps)
        r=result['receipts'][0]
        funds.assume_fill('explicit-source-assumption',classification='SIMULATED_ASSUMPTION',
            input_quantity=r['input_quantity'],output_quantity=r['output_quantity'],
            fee_quantity=r['fee_amount_estimate'],fee_currency=r['assumed_fee_currency_for_research'])
    action=next((a for a in frame.graph(source)['actions'] if a['target']==target and a['leg']),None)
    if action is None:raise JournalError('CONDITIONAL_MARKET_UNAVAILABLE')
    return journal.register(reference,funds=funds,leg=action['leg'],quantity=funds.available(source),
        frame=frame,horizon_s=horizon_s,signal_id=signal_id,fill_state=fill_state,slippage_bps=slippage_bps)
