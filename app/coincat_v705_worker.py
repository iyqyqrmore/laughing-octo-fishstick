"""Read-only worker timing: a previous scan's timer is not a new job's age."""
SCAN_OPERATIONS=frozenset(('market scan','manual research scan'))


def worker_state(app,*,mono,wall):
    busy=bool(getattr(app,'worker_busy',False))
    operation=str(getattr(app,'_worker_operation','') or '')
    started=getattr(app,'_worker_started_at',0) or 0
    elapsed=max(0,mono-started) if busy and started else 0
    scan=bool(busy and getattr(app,'_scan_processing',False) and operation in SCAN_OPERATIONS)
    phase=getattr(app,'_scan_phase',{}) or {}
    phase_started=phase.get('started_at',0) or 0
    last_scan=getattr(app,'_last_scan_at',0) or 0
    urgent=getattr(app,'_fast_observed_at',0) or 0
    return {'busy':busy,'operation':operation,'elapsed_s':elapsed,'scan_active':scan,
            'slow_scan':bool(scan and elapsed>90),
            'phase':str(phase.get('name','STARTING')) if scan else None,
            'phase_elapsed_s':max(0,mono-phase_started) if scan and phase_started else 0,
            'last_scan_age_s':max(0,mono-last_scan) if last_scan else None,
            'last_urgent_age_s':max(0,wall-urgent) if urgent else None}
