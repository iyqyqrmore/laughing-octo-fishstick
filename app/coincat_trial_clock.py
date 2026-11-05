"""Monotonic observation accounting. Wall time never earns valid hours."""
import math
import uuid
from coincat_beta_store import BetaBlocked

NS=1_000_000_000
TARGET_NS=168*3600*NS
PHASES={'RECOVERING','RUNNING','PAUSED','DISCONNECTED','COMPLETE','REVIEW_REQUIRED'}
COUNTERS=('valid_ns','paused_ns','disconnected_ns','partial_ns','unobserved_ns','offline_ns',
    'coverage_observed_ns','coverage_weighted_units','restarts','interruptions','clock_changes')

def _wall(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<1e12:raise BetaBlocked('INVALID_TRIAL_WALL_TIME')
    return float(value)

def validate_clock(s):
    if s.get('schema')!=1 or s['phase'] not in PHASES or s['target_ns']!=TARGET_NS:raise BetaBlocked('TRIAL_CLOCK_SCHEMA_INVALID')
    if any(type(s[k]) is not int or s[k]<0 for k in COUNTERS):raise BetaBlocked('TRIAL_CLOCK_COUNTER_INVALID')
    if s['valid_ns']>TARGET_NS or s['coverage_weighted_units']>s['coverage_observed_ns']*7:raise BetaBlocked('TRIAL_CLOCK_COVERAGE_INVALID')
    if type(s['wanted']) is not bool or type(s['run_open']) is not bool:raise BetaBlocked('TRIAL_CLOCK_FLAG_INVALID')
    if type(s['previous_valid']) is not bool or type(s['previous_coverage']) is not int or not 0<=s['previous_coverage']<=7:
        raise BetaBlocked('TRIAL_CLOCK_QUALITY_INVALID')
    if s['phase']=='COMPLETE' and (s['valid_ns']!=TARGET_NS or s['wanted']):raise BetaBlocked('TRIAL_COMPLETION_INVALID')
    _wall(s['started_at']);_wall(s['last_wall'])
    if s['last_mono_ns'] is not None and (type(s['last_mono_ns']) is not int or s['last_mono_ns']<0):raise BetaBlocked('TRIAL_MONOTONIC_TIME_INVALID')

def new_clock(trial_id,at):
    s=dict(schema=1,trial_id=trial_id,started_at=_wall(at),last_wall=_wall(at),target_ns=TARGET_NS,
        phase='RECOVERING',wanted=True,run_open=False,run_id=None,last_mono_ns=None,previous_valid=False,previous_coverage=0,
        complete_at=None,calendar_uncertain=False,reason='WAIT_FOR_VALIDATED_SEVEN_MARKET_EVALUATION',
        **{k:0 for k in COUNTERS})
    validate_clock(s);return s

def begin_run(s,*,wall,mono_ns,run_id=None):
    validate_clock(s);wall=_wall(wall)
    if type(mono_ns) is not int or mono_ns<0:raise BetaBlocked('TRIAL_MONOTONIC_TIME_INVALID')
    if s['phase']=='COMPLETE':return
    first=s['run_id'] is None
    if not first:
        s['restarts']+=1;s['interruptions']+=int(s['run_open'])
        gap=wall-s['last_wall']
        if gap>=0 and not s['calendar_uncertain']:s['offline_ns']+=round(gap*NS)
        else:s['calendar_uncertain']=True;s['clock_changes']+=1
    s.update(run_id=run_id or uuid.uuid4().hex,run_open=True,last_mono_ns=mono_ns,last_wall=wall,
        previous_valid=False,previous_coverage=0,phase='RECOVERING' if s['wanted'] else 'PAUSED',
        reason='RESUME_REQUIRES_FRESH_INPUTS_NO_DOWNTIME_FILLS')

def advance(s,*,wall,mono_ns,valid,coverage,run_id):
    validate_clock(s);wall=_wall(wall)
    if type(mono_ns) is not int or mono_ns<0 or type(valid) is not bool or type(coverage) is not int or not 0<=coverage<=7:
        raise BetaBlocked('TRIAL_CHECKPOINT_INPUT_INVALID')
    if s['phase']=='COMPLETE':return 'COMPLETE'
    if not s['run_open'] or run_id!=s['run_id']:raise BetaBlocked('TRIAL_RUN_IDENTITY_CONFLICT')
    old=s['last_mono_ns']
    if mono_ns==old:return 'DUPLICATE_IGNORED'
    if mono_ns<old:
        s.update(phase='REVIEW_REQUIRED',previous_valid=False,reason='MONOTONIC_TIME_MOVED_BACKWARDS');return 'REJECTED'
    elapsed=mono_ns-old;wall_delta=wall-s['last_wall']
    if s['phase']=='REVIEW_REQUIRED':
        s['unobserved_ns']+=elapsed;s.update(last_mono_ns=mono_ns,last_wall=wall,previous_valid=False)
        return 'REVIEW_REQUIRED'
    if abs(wall_delta-elapsed/NS)>5:s['calendar_uncertain']=True;s['clock_changes']+=1
    s.update(last_mono_ns=mono_ns,last_wall=wall)
    if elapsed>45*NS:
        s['unobserved_ns']+=elapsed
        s.update(previous_valid=False,previous_coverage=0,phase='RECOVERING' if s['wanted'] else 'PAUSED',
            reason='IMPLAUSIBLE_CHECKPOINT_GAP_NOT_COUNTED')
        return 'GAP_NOT_COUNTED'
    if not s['wanted']:
        s['paused_ns']+=elapsed;s.update(phase='PAUSED',previous_valid=False,previous_coverage=0,reason='USER_PAUSED');return 'PAUSED'
    s['coverage_observed_ns']+=elapsed
    s['coverage_weighted_units']+=elapsed*min(coverage,s['previous_coverage'])
    if valid and coverage==7 and s['previous_valid'] and s['previous_coverage']==7:
        s['valid_ns']=min(TARGET_NS,s['valid_ns']+elapsed);s['phase']='RUNNING';s['reason']='VALIDATED_SEVEN_MARKET_OBSERVATION'
    else:
        if coverage==0:s['disconnected_ns']+=elapsed;s['phase']='DISCONNECTED';s['reason']='NO_TRUSTWORTHY_MARKET_COVERAGE'
        else:s['partial_ns']+=elapsed;s['phase']='RECOVERING';s['reason']='PARTIAL_OR_UNVALIDATED_OBSERVATION_NOT_FULL_HOURS'
    s['previous_valid']=bool(valid and coverage==7);s['previous_coverage']=coverage
    if s['valid_ns']==TARGET_NS:s.update(phase='COMPLETE',wanted=False,complete_at=wall,reason='168_VALID_HOURS_REACHED_NO_NEW_TRIAL_OR_PERMISSION')
    return s['phase']

def prime_quality(s,*,valid,coverage):
    """A new validation starts a lease; it never earns the preceding interval."""
    if s['phase'] in ('COMPLETE','REVIEW_REQUIRED'):return
    s['previous_valid']=bool(valid and coverage==7 and s['wanted']);s['previous_coverage']=coverage if s['wanted'] else 0
    if s['wanted']:s['phase']='RUNNING' if s['previous_valid'] else 'DISCONNECTED' if coverage==0 else 'RECOVERING'

def end_run(s,*,wall):
    s.update(last_wall=_wall(wall),run_open=False,previous_valid=False,previous_coverage=0)
    if s['phase']!='COMPLETE':s['phase']='PAUSED' if not s['wanted'] else 'RECOVERING'

def progress(s,wall):
    validate_clock(s);endpoint=s['complete_at'] or _wall(wall)
    return dict(state=s['phase'],valid_seconds=s['valid_ns']/NS,remaining_seconds=(TARGET_NS-s['valid_ns'])/NS,
        completion_percent=s['valid_ns']/TARGET_NS*100,
        calendar_elapsed_s=None if s['calendar_uncertain'] else max(0,endpoint-s['started_at']),
        downtime_s=None if s['calendar_uncertain'] else (s['offline_ns']+s['unobserved_ns'])/NS,
        paused_s=s['paused_ns']/NS,disconnected_s=s['disconnected_ns']/NS,partial_s=s['partial_ns']/NS,
        coverage_percent=0 if not s['coverage_observed_ns'] else s['coverage_weighted_units']/s['coverage_observed_ns']/7*100,
        restart_count=s['restarts'],interruptions=s['interruptions'],reason=s['reason'])
