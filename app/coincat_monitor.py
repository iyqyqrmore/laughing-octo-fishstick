"""Opt-in, quantity-free local heartbeat. No database, broker or network access."""
import hashlib
import json
import math
import os
from pathlib import Path
from queue import Empty,Full,Queue
import re
import stat
import threading
import time
import uuid

from coincat_version import DISPLAY
from coincat_paper_public import public_status as paper_public,validate_public as validate_paper_public
from coincat_adaptive_eth import public_summary as adaptive_public,validate_public
from coincat_research_journal import public_status as journal_public,validate_public as validate_journal_public
from coincat_beta_public import project as beta_project,validate as beta_validate

SCHEMA='coincat-monitor/v3'
MAX_SNAPSHOT=32768
HISTORY_BYTES=2*1024*1024
HISTORY_FILES=4
COUNTS=('setups','invalidated','unpriced_episodes','resumed_episodes','fee_changes',
        'expired','entry_touches_uncertain','target_touches_uncertain')
STATES={'STOPPED','RUNNING','RETRYING','PAUSED_NEEDS_ATTENTION','UNKNOWN'}
SETUP_STATES={'NO_SETUP_UNPRICED','UNOBSERVED','SETUP_ACTIVE_OBSERVABLE','SETUP_ACTIVE_UNPRICED','SETUP_EXPIRED','UNKNOWN'}
STAGES={'PERMISSIONS','BALANCES','CATALOG','FEE_TIER','PUBLIC_QUOTE','LOCAL_PUBLIC_QUOTE_STORE','UNKNOWN'}
ERRORS={'Timeout','ReadTimeout','ConnectTimeout','SSLError','ConnectionError','HTTPError',
        'SQLiteError','ValueError','LiveBlocked','QuoteUnavailable','QuoteDeferred','FeeRefreshDeferred','UnexpectedError','UNKNOWN'}
REASONS={'QUOTE_NOT_RETURNED','QUOTE_STALE','QUOTE_WIDE','QUOTE_INVALID','QUOTE_FUTURE',
    'CONNECTION_ERROR','READ_TIMEOUT','GET_DEFERRED','PUBLIC_QUOTE_ERROR','MODEL_UNPRICED',
    'ACCOUNT_FEE_TIER_UNAVAILABLE','FEE_RATE_UNSUPPORTED_NO_REBATE_ASSUMPTION',
    'TAKER_PRODUCT_SIZE_BLOCK','POST_ONLY_ENTRY_WOULD_CROSS','MAKER_ENTRY_PRODUCT_SIZE_BLOCK',
    'MAKER_EXIT_PRODUCT_SIZE_BLOCK','TARGET_PRICE_BELOW_TICK','TARGET_NOT_MET_AFTER_NATIVE_ROUNDING',
    'NO_EXPLICIT_ETH_PROPOSAL','ETH_PROPOSAL_EXCEEDS_WORKING_OR_UNAVAILABLE',
    'QUOTE_TIME_MOVED_BACKWARDS','QUOTE_DECISION_SPAN_EXCEEDS_12S','FEE_REFRESH_DEFERRED',
    'INVALID_DATA_OR_SETTINGS','TLS_ERROR','HTTP_ERROR',
    'LOCAL_STATE_ERROR','PERMISSION_OR_DATA_REJECTED','UNEXPECTED_ERROR','UNKNOWN'}


def monitor_directory():
    return Path(__file__).resolve().parents[1]/'support_monitor'


def _number(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (ValueError,TypeError,OverflowError):return None
    return value if math.isfinite(value) and abs(value)<=1e15 else None


def _count(value):
    return value if type(value) is int and 0<=value<=2**53 else None


def _enum(value,values):
    return value if isinstance(value,str) and value in values else 'UNKNOWN'


def _reason(value):
    return value if isinstance(value,str) and (value in REASONS or re.fullmatch(r'HTTP_[45][0-9]{2}',value)) else 'UNKNOWN'


def _asset(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Z0-9]{1,16}',value) is not None


def _pair(value):
    if not isinstance(value,str):return False
    parts=value.split('-')
    return len(parts)==2 and all(_asset(p) for p in parts) and parts.count('ETH')==1


def capture(app,*,session,sequence,manifest_sha256=None,now=None,lifecycle='OPEN'):
    """Copy only controlled fields on the Tk thread, without reading any ledger."""
    now=time.time() if now is None else now
    if getattr(app,'manual_workspace',False):
        from types import SimpleNamespace
        from coincat_spot_public import validate as manual_validate
        account_at=(app.account or {}).get('at');tier=app.reader.tier or {}
        state='RUNNING' if app.connected and not app.last_error else 'RETRYING' if app.last_error else 'STOPPED'
        legacy=SimpleNamespace(last_result=dict(at=app.last_read_at,scan=app.reads,fee_evidence=dict(
            captured_at=tier.get('at'),fresh=bool(tier and 0<=now-tier['at']<=3600))),
            scanner=SimpleNamespace(account_at=account_at),recovery=SimpleNamespace(diagnostics=lambda:dict(connection_state=state)),
            companions=[],running=bool(app.connected),busy=bool(app.busy),applied_config=None,
            connected=bool(app.connected),last_error='READ_FAILED' if app.last_error else None,
            manual_public=getattr(app,'history_public',None))
        snapshot=capture(legacy,session=session,sequence=sequence,manifest_sha256=manifest_sha256,now=now,lifecycle=lifecycle)
        snapshot['manual_execution']=manual_validate(dict(app.manual_public))
        from coincat_shadow_public import project as trial_project
        snapshot['shadow_trial']=trial_project(getattr(app,'shadow_public',None));validate(snapshot);return snapshot
    result=app.last_result or {};scanner=app.scanner;tier=result.get('fee_evidence',{})
    recovery=app.recovery.diagnostics();failure=recovery.get('last_failure')
    last_failure=None if not failure else dict(stage=_enum(failure.get('stage'),STAGES),
        category=_reason(failure.get('category')),error_class=_enum(failure.get('error_class'),ERRORS),
        status=failure.get('status') if type(failure.get('status')) is int and 400<=failure['status']<=599 else None)
    products=[]
    for row in result.get('rows',())[:4]:
        pair=row.get('market',{}).get('pair')
        if not _pair(pair):continue
        hypothesis=row.get('hypothesis') or {}
        products.append(dict(pair=pair,quote_at=_number(row.get('quote_observed_at')),
            setup_state=_enum(row.get('observation_state','UNOBSERVED'),SETUP_STATES),
            entry_at=_number(hypothesis.get('entry_at')),expiry_at=_number(hypothesis.get('expiry_at')),
            reasons=list(dict.fromkeys(_reason(r) for r in row.get('blockers',())[:16]))))
    account_at=_number(None if scanner is None else scanner.account_at)
    account_age=None if account_at is None else now-account_at
    snapshot=dict(schema=SCHEMA,version=DISPLAY,session=session,sequence=sequence,
        manifest_sha256=manifest_sha256,captured_at=now,lifecycle=lifecycle,
        companions=list(dict.fromkeys(v.get() for v in app.companions if _asset(v.get())))[:4],
        health=dict(running=bool(app.running),busy=bool(app.busy),plan_applied=bool(app.applied_config is not None or getattr(app,'paper_observe',False) or getattr(app,'live_observe',False)),
            connected=bool(app.connected and account_age is not None and 0<=account_age<=120 and
                app.last_error is None and recovery.get('connection_state')!='RETRYING'),
            connection_state=_enum(recovery.get('connection_state'),STATES),
            scan_number=_count(result.get('scan')),last_good_scan_at=_number(result.get('at')),
            account_at=account_at,fee_at=_number(tier.get('captured_at')),fee_fresh_then=bool(tier.get('fresh')),
            retry_attempt=_count(recovery.get('retry_attempt')),retry_in_s=_number(recovery.get('retry_in_s')),
            interruptions=_count(recovery.get('scan_interruptions')),recoveries=_count(recovery.get('recovered_periods')),
            last_failure=last_failure),products=products,
        adaptive=adaptive_public(result.get('adaptive')),
        prospective_journal=journal_public(result.get('prospective_journal',getattr(app,'journal_status',None))),
        auto_paper=paper_public(getattr(app,'paper_public',None)),
        beta=beta_project(getattr(app,'live_public',None),getattr(app,'manual_public',None),getattr(app,'book_public',None)),
        observations={k:_count(result.get('study_counts',{}).get(k,0)) for k in COUNTS})
    validate(snapshot)
    return snapshot


def validate(value):
    """Reject unknown keys/types instead of trusting a file's redaction claim."""
    def exact(obj,keys):
        if not isinstance(obj,dict) or set(obj)!=set(keys.split()):raise ValueError('INVALID_MONITOR_SCHEMA')
    def number(raw):
        if raw is not None and (type(raw) not in (int,float) or _number(raw) is None):raise ValueError('INVALID_MONITOR_NUMBER')
    def count(raw):
        if raw is not None and _count(raw) is None:raise ValueError('INVALID_MONITOR_COUNT')
    # v3's one known optional extension remains strict. Older v3 snapshots may
    # omit it; arbitrary root or nested keys are still rejected.
    fields='schema version session sequence manifest_sha256 captured_at lifecycle companions health products observations adaptive prospective_journal'
    exact(value,fields+(' auto_paper' if isinstance(value,dict) and 'auto_paper' in value else '')+
        (' beta' if isinstance(value,dict) and 'beta' in value else '')+
        (' manual_execution' if isinstance(value,dict) and 'manual_execution' in value else '')+
        (' shadow_trial' if isinstance(value,dict) and 'shadow_trial' in value else ''))
    if value['schema']!=SCHEMA or value['version']!=DISPLAY:raise ValueError('INVALID_MONITOR_VERSION')
    if not isinstance(value['session'],str) or not re.fullmatch(r'[0-9a-f]{32}',value['session']):raise ValueError('INVALID_MONITOR_SESSION')
    if type(value['sequence']) is not int or not 1<=value['sequence']<=2**53:raise ValueError('INVALID_MONITOR_SEQUENCE')
    digest=value['manifest_sha256']
    if digest is not None and (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest)):raise ValueError('INVALID_MONITOR_HASH')
    number(value['captured_at'])
    if value['captured_at'] is None or value['lifecycle'] not in ('OPEN','DISABLED','CLOSED'):raise ValueError('INVALID_MONITOR_LIFECYCLE')
    companions=value['companions']
    if not isinstance(companions,list) or len(companions)>4 or not all(_asset(a) for a in companions):raise ValueError('INVALID_MONITOR_COMPANIONS')
    health=value['health']
    exact(health,'running busy plan_applied connected connection_state scan_number last_good_scan_at account_at fee_at fee_fresh_then retry_attempt retry_in_s interruptions recoveries last_failure')
    for key in ('running','busy','plan_applied','connected','fee_fresh_then'):
        if type(health[key]) is not bool:raise ValueError('INVALID_MONITOR_BOOLEAN')
    if health['connection_state'] not in STATES:raise ValueError('INVALID_MONITOR_STATE')
    for key in ('scan_number','retry_attempt','interruptions','recoveries'):count(health[key])
    for key in ('last_good_scan_at','account_at','fee_at','retry_in_s'):number(health[key])
    failure=health['last_failure']
    if failure is not None:
        exact(failure,'stage category error_class status')
        if (failure['stage'] not in STAGES or failure['error_class'] not in ERRORS or
                failure['category']!=_reason(failure['category'])):raise ValueError('INVALID_MONITOR_FAILURE')
        if failure['status'] is not None and (type(failure['status']) is not int or not 400<=failure['status']<=599):raise ValueError('INVALID_MONITOR_STATUS')
    if not isinstance(value['products'],list) or len(value['products'])>4:raise ValueError('INVALID_MONITOR_PRODUCTS')
    for product in value['products']:
        exact(product,'pair quote_at setup_state entry_at expiry_at reasons')
        if not _pair(product['pair']) or product['setup_state'] not in SETUP_STATES:raise ValueError('INVALID_MONITOR_PRODUCT')
        for key in ('quote_at','entry_at','expiry_at'):number(product[key])
        reasons=product['reasons']
        if not isinstance(reasons,list) or len(reasons)>16 or any(r!=_reason(r) for r in reasons):raise ValueError('INVALID_MONITOR_REASONS')
    validate_public(value['adaptive'])
    validate_journal_public(value['prospective_journal'])
    if 'auto_paper' in value:validate_paper_public(value['auto_paper'])
    if 'beta' in value:beta_validate(value['beta'])
    if 'manual_execution' in value:
        from coincat_spot_public import validate as manual_validate
        manual_validate(value['manual_execution'])
    if 'shadow_trial' in value:
        from coincat_shadow_public import validate as trial_validate
        trial_validate(value['shadow_trial'])
    exact(value['observations'],' '.join(COUNTS))
    for raw in value['observations'].values():count(raw)
    return value


def encode(snapshot):
    validate(snapshot)
    raw=(json.dumps(snapshot,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')
    if len(raw)>MAX_SNAPSHOT:raise ValueError('MONITOR_SNAPSHOT_TOO_LARGE')
    return raw


def read_snapshot(directory):
    directory=Path(directory);path=directory/'latest.json'
    if directory.is_symlink() or path.is_symlink():raise ValueError('MONITOR_SYMLINK_REJECTED')
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
    with os.fdopen(os.open(path,flags),'rb') as handle:
        info=os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_SNAPSHOT:raise ValueError('MONITOR_FILE_REJECTED')
        raw=handle.read(MAX_SNAPSHOT+1)
    if len(raw)>MAX_SNAPSHOT:raise ValueError('MONITOR_FILE_TOO_LARGE')
    def pairs(items):
        result={}
        for key,item in items:
            if key in result:raise ValueError('MONITOR_DUPLICATE_KEY')
            result[key]=item
        return result
    return validate(json.loads(raw,object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('MONITOR_NONFINITE_NUMBER'))))


def status(directory,*,now=None):
    now=time.time() if now is None else now
    try:snapshot=read_snapshot(directory)
    except FileNotFoundError:return dict(state='WAITING_FOR_APP',served_at=now,snapshot=None,ages=None)
    except OSError:return dict(state='MONITOR_READ_FAILED',served_at=now,snapshot=None,ages=None)
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):return dict(state='INVALID_SNAPSHOT',served_at=now,snapshot=None,ages=None)
    def age(at):return None if at is None else now-at
    heartbeat=age(snapshot['captured_at']);health=snapshot['health']
    active=0<=heartbeat<=15 and snapshot['lifecycle']=='OPEN'
    state=('APP_CLOSED' if snapshot['lifecycle']=='CLOSED' else 'MONITOR_DISABLED' if snapshot['lifecycle']=='DISABLED'
        else 'APP_REPORTING' if active else 'APP_NOT_REPORTING')
    fee_age=age(health['fee_at']);account_age=age(health['account_at'])
    products=[]
    for item in snapshot['products']:
        quote_age=age(item['quote_at']);expiry=item['expiry_at']
        quote_current=bool(active and quote_age is not None and 0<=quote_age<=30)
        expired=bool(expiry is not None and now>=expiry)
        setup=item['setup_state']
        if expired:setup='SETUP_EXPIRED'
        elif setup in ('SETUP_ACTIVE_OBSERVABLE','SETUP_ACTIVE_UNPRICED') and (
                not quote_current or not health['running'] or health['connection_state'] in ('RETRYING','PAUSED_NEEDS_ATTENTION')):
            setup='SETUP_ACTIVE_UNPRICED'
        products.append(dict(pair=item['pair'],quote_age_s=quote_age,
            quote_within_age_limit=quote_current,expired=expired,current_setup_state=setup))
    return dict(state=state,served_at=now,snapshot=snapshot,ages=dict(heartbeat_s=heartbeat,
        last_good_scan_s=age(health['last_good_scan_at']),account_s=account_age,
        authenticated_fresh=bool(active and health['connected'] and account_age is not None and 0<=account_age<=120),
        fee_s=fee_age,fee_valid_now=bool(active and health['fee_fresh_then'] and fee_age is not None and 0<=fee_age<=7200),
        products=products))


class MonitorPublisher:
    """One bounded background writer. The GUI never waits for normal file IO."""
    def __init__(self,directory=None,*,history_bytes=HISTORY_BYTES):
        self.directory=monitor_directory() if directory is None else Path(directory)
        self.history_bytes=history_bytes;self.enabled=False;self.thread=None
        self.error=None;self.last_written_at=None;self.session=None;self.sequence=0
        self.manifest_sha256=None;self._lock=threading.Lock()

    def start(self):
        if self.thread is not None and self.thread.is_alive():return False
        self.queue=Queue(maxsize=1);self.stopping=threading.Event();self.final=None
        self.session=uuid.uuid4().hex;self.sequence=0;self.error=None;self.last_written_at=None
        try:self.manifest_sha256=hashlib.sha256((Path(__file__).resolve().parents[1]/'SHA256_MANIFEST.json').read_bytes()).hexdigest()
        except OSError:self.manifest_sha256=None
        self.enabled=True
        self.thread=threading.Thread(target=self._run,name='CoinCat-redacted-monitor',daemon=True)
        try:self.thread.start()
        except RuntimeError:
            self.enabled=False;self.thread=None;self.error='MONITOR_START_FAILED';return False
        return True

    def sample(self,app,*,now=None,lifecycle='OPEN'):
        self.sequence+=1
        return capture(app,session=self.session,sequence=self.sequence,manifest_sha256=self.manifest_sha256,
            now=now,lifecycle=lifecycle)

    def publish(self,snapshot):
        if not self.enabled:return False
        raw=encode(snapshot)
        try:self.queue.put_nowait((snapshot,raw))
        except Full:
            try:self.queue.get_nowait()
            except Empty:pass
            try:self.queue.put_nowait((snapshot,raw))
            except Full:pass
        return True

    def stop(self,final=None,*,timeout=1):
        if self.thread is None:return
        # Validate and freeze before the worker sees it; no Tk object crosses threads.
        final=None if final is None else (final,encode(final))
        with self._lock:self.final=final;self.enabled=False;self.stopping.set()
        self.thread.join(timeout)

    def diagnostics(self):
        return dict(enabled=self.enabled,state='WRITE_FAILED' if self.error else
            'RECORDING' if self.enabled and self.last_written_at is not None else
            'WAITING' if self.enabled else 'OFF',last_written_at=self.last_written_at,error=self.error)

    def _write(self,snapshot,raw,*,history=False):
        root=self.directory
        if root.is_symlink():raise ValueError('MONITOR_SYMLINK_REJECTED')
        root.mkdir(parents=True,exist_ok=True)
        latest=root/'latest.json';temporary=root/('latest-'+self.session+'.tmp')
        if latest.is_symlink():raise ValueError('MONITOR_SYMLINK_REJECTED')
        created=False
        try:
            descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created=True
            with os.fdopen(descriptor,'wb') as out:out.write(raw)
            for attempt in range(4):
                try:os.replace(temporary,latest);break
                except PermissionError:
                    if attempt==3:raise
                    time.sleep(.025*2**attempt)  # Brief Windows reader/antivirus sharing locks.
        finally:
            if created and temporary.exists():temporary.unlink()
        if history:
            files=[root/'snapshots.jsonl']+[root/f'snapshots.{i}.jsonl' for i in range(1,HISTORY_FILES)]
            if any(p.is_symlink() or (p.exists() and not stat.S_ISREG(p.stat().st_mode)) for p in files):
                raise ValueError('MONITOR_FILE_REJECTED')
            if files[0].exists() and files[0].stat().st_size+len(raw)>self.history_bytes:
                for i in range(len(files)-1,0,-1):
                    if files[i-1].exists():os.replace(files[i-1],files[i])
            with os.fdopen(os.open(files[0],os.O_WRONLY|os.O_CREAT|os.O_APPEND|getattr(os,'O_NOFOLLOW',0),0o600),'ab') as out:out.write(raw)
        self.last_written_at=snapshot['captured_at'];self.error=None

    def _run(self):
        last_history=None
        while True:
            try:item=self.queue.get(timeout=.1)
            except Empty:item=None
            with self._lock:
                stopping=self.stopping.is_set()
                if stopping:item=self.final
            if item is not None:
                snapshot,raw=item
                try:
                    monotonic=time.monotonic()
                    history=stopping or last_history is None or monotonic-last_history>=60
                    self._write(snapshot,raw,history=history)
                    if history:last_history=monotonic
                except Exception:self.error='MONITOR_WRITE_FAILED'
            if stopping:return
