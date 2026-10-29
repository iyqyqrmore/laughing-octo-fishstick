"""Manual Xvfb smoke: off-line GUI export, no credentials, no broker connection."""
import os,tempfile
from pathlib import Path
from unittest.mock import patch

with tempfile.TemporaryDirectory(prefix='CoinCatV60_GUI_FAKE_') as d:
    os.environ['COINCAT_DATA_DIR']=d
    from coincat_live import LiveLedger
    import tkinter as tk
    from coincat_app import CoinCatApp
    LiveLedger(Path(d)/'CoinCat_Live_Orders.sqlite3')
    top=tk.Tk()
    try:
        app=CoinCatApp(top)
        assert 'v90.1' in top.title(), top.title()
        seen=[]
        def walk(w):
            try:
                if w.winfo_class()=='TButton':seen.append(w.cget('text'))
            except tk.TclError:pass
            for ch in w.winfo_children():walk(ch)
        walk(top)
        assert len([x for x in seen if 'Diagnostics' in x])==1,seen
        assert not any('Review evidence' in x or 'APPROVE CAPACITY' in x for x in seen),seen
        assert len([x for x in seen if 'ARM SHADOW' in x])==1,seen
        assert not app.shadow_pilot.armed
        assert len(app.lab_evidence_bars)==6
        assert not app._lab_technical_open.get() and not app._lab_outcomes_open.get()
        assert 'Advanced • research details' in ' '.join(seen) or app.ticker_tree.winfo_exists()
        assert 'PREFERRED' in app.ai_budget_preview.get() or 'Gathering' in app.ai_budget_preview.get()
        from coincat_v90_telemetry import DirectionCoverage
        app._direction_coverage=DirectionCoverage()
        app._direction_coverage.select([('AAA-USD','SELL','AAA','USD')],[],now=100,cycle_id='GUI_OFFLINE')
        details=app._show_immediate_opportunities()
        displayed=' '.join(w.get('1.0','end') for w in details.winfo_children() if isinstance(w,tk.Text))
        assert 'AAA-USD / SELL | never | never | never' in displayed
        details.destroy()
        report=Path(d)/'fake_report.txt'
        with patch('coincat_app.filedialog.asksaveasfilename',return_value=str(report)),patch('coincat_app.messagebox.showinfo'),patch('coincat_app.messagebox.showwarning'):
            app._export_complete_diagnostics()
            import time
            deadline=time.monotonic()+120
            while not report.exists() and time.monotonic()<deadline:
                top.update()
                time.sleep(.005)
            if not report.exists():
                session=getattr(app,'_diagnostics_session',None)
                completed=getattr(session,'index','unknown') if session is not None else 'session closed'
                failed=getattr(session,'failed',None) if session is not None else None
                raise AssertionError('Incremental GUI export did not finish within 120s; '
                    'session_active=%s completed_sections=%s failed_sections=%s' %
                    (session is not None,completed,failed))
        body=report.read_text()
        assert 'SETTLEMENT & RECOVERY' in body,body[:800]
        assert 'GO-LIVE VERDICT: NOT APPROVED' in body
        assert 'CROSS-CRYPTO POST' in body
        assert 'SECTION COMPLETENESS: COMPLETE (18/18)' in body
        assert 'Session candidate reconciliation (repeated sizes):' in body
        assert 'Direction coverage (app urgent research, not the armed-session counter):' in body
        assert 'Consumer cycle relation:' in body
        assert 'Freshness observation:' in body
        assert 'PRIMARY V80' not in body
        assert 'V50.7 ARM SHADOW + SEGREGATED FIFO ACCOUNTING' in body
        assert 'AI LAB RESEARCH DATABASE AND SINGLE-PLANNER AUDIT' in body
        assert 'DAILY REALIZED-LOSS PAUSE / AUTO-RESUME' in body
        assert 'Synthetic pause -> later SELL -> eligible BUY: PASS' in body
        print('PASS V90 GUI 1-button report',len(body),'bytes',top.title())
    finally:
        app._close()
