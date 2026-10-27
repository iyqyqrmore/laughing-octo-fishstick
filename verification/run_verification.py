"""CoinCat v60 source-mode verification pack (strictly no order submission).

The ALL mode is offline plus local read-only checks only. The optional authenticated
Coinbase order-history GET requires a separate user-typed opt-in. A successful
synthetic test is never a PASS on a production trading authorization gate.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app'
REPORTS=ROOT/'verification_reports'
GATES=('offline','gpu','coinbase','fifo','recovery','floor','edge','shadow','pilot')
GROUPS={
 'fifo':['test_v501_unified_fifo','test_v506_capital_integrated','test_v506r_full_route_and_gates'],
 'recovery':['test_v506_capital_integrated','test_v501_12_trade_pilot_and_routing','test_v506r_full_route_and_gates'],
 'floor':['test_v504_daily_loss_resume','test_v506_capital_integrated'],
 'edge':['test_v503_heldout_budget','test_v506_profit_floor','test_v506r_full_route_and_gates','test_v502_fee_consistency'],
 'shadow':['test_v507_shadow_fifo','test_v508_gpu_table_diagnostics']
}

class Audit:
    def __init__(self):self.lines=[];self.fail=False
    def add(self,status,description):
        row=f'[{status}] {description}'
        self.lines.append(row);print(row,flush=True)
        if status in ('FAIL','ERROR'):self.fail=True
    def section(self,heading):
        line='\n--- '+heading+' ---'
        self.lines.append(line);print(line,flush=True)
    def save(self,gate):
        REPORTS.mkdir(parents=True,exist_ok=True)
        dest=REPORTS/f'CoinCat_v601_{gate}_verification.txt'
        body=['CoinCat v60.3 VERIFICATION — '+gate.upper(),
              'Captured UTC: '+datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'No order POST, no ARM, no transfer, no canonical ledger mutations.',
              'PASS on synthetic/local checks does NOT authorize production trading.',
              'LIVE STATUS: NOT APPROVED — Coinbase order submission remains BLOCKED.',
              '']+self.lines+['','END. Only explicitly independently verified live production evidence can change a gate.']
        dest.write_text('\n'.join(body)+'\n',encoding='utf-8')
        print('\nSaved redacted report to verification_reports\\'+dest.name,flush=True)


def tests(a,names):
    if sys.version_info[:2] != (3,11) and os.environ.get('COINCAT_VERIFY_ALLOW_OTHER_PYTHON')!='1':
        a.add('NOT VERIFIED','Windows test battery requires Python 3.11; no tests launched.')
        return False
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join(filter(None,[str(APP),str(ROOT),env.get('PYTHONPATH','')]))
    env['PYTHONDONTWRITEBYTECODE']='1'
    with tempfile.TemporaryDirectory(prefix='CoinCat_VERIFY_DISPOSABLE_') as d:
        env['COINCAT_DATA_DIR']=d
        cmd=[sys.executable,'-B','-m','unittest']+['offline_tests.'+n for n in names]+['-q']
        rc=subprocess.run(cmd,cwd=str(ROOT),env=env).returncode
    a.add('PASS / SYNTHETIC' if rc==0 else 'FAIL',
          str(len(names))+' isolated offline unittest modules '+('passed' if rc==0 else 'failed')+'; no production account certification')
    return rc==0


def offline(a):
    a.section('RELEASE INTEGRITY AND COMPLETE OFFLINE SUITE')
    # Pack-level hashes; Python subprocess cannot arm or contact Coinbase.
    p=subprocess.run([sys.executable,'-B',str(ROOT/'VERIFY_SOURCE_V60.py')],cwd=str(ROOT))
    a.add('PASS / LOCAL' if p.returncode==0 else 'FAIL','SHA256 release guard')
    if p.returncode:return
    if sys.version_info[:2]!=(3,11) and os.environ.get('COINCAT_VERIFY_ALLOW_OTHER_PYTHON')!='1':
        a.add('NOT VERIFIED','Full Windows offline test suite needs Python 3.11; run from Windows CMD')
        return
    # Reuses the existing installed-dependency-safe runner; temporary fake data.
    if sys.version_info[:2]==(3,11):
        with tempfile.TemporaryDirectory(prefix='CoinCatV70_COMPLETE_TEST_') as disposable:
            env=os.environ.copy()
            env['COINCAT_DATA_DIR']=disposable
            env['PYTHONPATH']=os.pathsep.join([str(APP),str(ROOT)])
            rc=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','offline_tests','-q'],cwd=str(ROOT),env=env).returncode
        a.add('PASS / SYNTHETIC' if rc==0 else 'FAIL','Complete isolated regression suite, including new v60 safety tests')
    else:
        a.add('NOT VERIFIED','Complete Windows runner requires Python 3.11')


def gpu(a):
    a.section('WINDOWS CUDA / PACKAGED EXE')
    exe=APP/'coincat_v60_launcher.py'
    if os.name!='nt':
        a.add('NOT VERIFIED','GPU runtime must be verified on the user Windows RTX 4060 machine')
        return
    py=Path(sys.executable)
    expr="import sys;assert sys.version_info[:2]==(3,11);import torch;assert torch.cuda.is_available();print('CUDA GPU:',torch.cuda.get_device_name(0));print('allocated',float(torch.ones(1,device='cuda').cpu()[0]))"
    rc=subprocess.run([str(py),'-c',expr],cwd=str(ROOT)).returncode
    a.add('PASS / WINDOWS SOURCE RUNTIME' if rc==0 else 'FAIL','Local v60 isolated Python CUDA allocated tensor; NO PyInstaller EXE')
    a.add('NOT VERIFIED','GPU readiness does not prove predictive advantage or authorize orders')


def db_readonly(a):
    a.section('PRODUCTION LEDGER READ ONLY — NEVER CREATE OR REPAIR')
    if not os.environ.get('APPDATA'):
        a.add('NOT VERIFIED','Windows APPDATA not available; no production ledger opened')
        return
    path=Path(os.environ['APPDATA'])/'CoinCatV70'/'CoinCat_Live_Orders.sqlite3'
    if not path.is_file() or path.is_symlink():
        a.add('NOT VERIFIED','Canonical ledger unavailable; no zero balances/orders inferred')
        return
    try:
        sys.path.insert(0,str(APP))
        from coincat_go_live_readiness import _check_database
        from coincat_v506_readiness import _live_db_status
        out=_check_database(path)
        status=out.get('state')
        a.add('PASS / LOCAL READ ONLY' if status=='PASS' else 'BLOCKED',
              'SQLite/Decimal parity: '+str(status)+'; checked noncash assets='+str(out.get('audited_assets'))+
              '; mismatches='+str(out.get('lot_mismatch'))+'; unresolved local orders='+str(out.get('pending')))
        a.add('BLOCKED',_live_db_status(path))
        a.add('NOT VERIFIED','Unknown original tax basis, fill-time fee currency/FX and Coinbase-side parity require independent records')
    except (ImportError,sqlite3.Error,OSError,ValueError,TypeError) as ex:
        a.add('NOT VERIFIED','Read-only canonical inspection failed: '+type(ex).__name__)


def coinbase(a,allow_network=False):
    a.section('EXCHANGE GET HISTORY / PRODUCT EVIDENCE')
    tests(a,['test_v506_capital_integrated'])
    if not allow_network:
        a.add('NOT VERIFIED','Authenticated Coinbase GET not run; use VERIFY_03_COINBASE_READONLY.bat for explicit opt-in')
        return
    if os.name!='nt':
        a.add('NOT VERIFIED','DPAPI credential access works only on user Windows system')
        return
    if sys.version_info[:2]!=(3,11):
        a.add('NOT VERIFIED','Authenticated SDK GET requires Python 3.11')
        return
    # Verify existence of existing official app vault before calling load_encrypted.
    directory=Path(os.environ.get('APPDATA',''))/'CoinCatV70'
    if not (directory/'coinbase_key.dpapi').is_file():
        a.add('NOT VERIFIED','Existing DPAPI vault missing; no secrets requested or created')
        return
    ledger=directory/'CoinCat_Live_Orders.sqlite3'
    if not ledger.is_file():
        a.add('NOT VERIFIED','Existing canonical financial ledger missing; cannot scope GET to an existing CoinCat order')
        return
    try:
        with closing(sqlite3.connect(ledger.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            row=db.execute("SELECT order_id FROM orders WHERE order_id IS NOT NULL AND length(order_id)>0 ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            a.add('NOT VERIFIED','No existing CoinCat Coinbase order ID; do not create one just for verification')
            return
        sys.path.insert(0,str(APP))
        from coinbase_account import load_encrypted
        from coincat_v506_coinbase_evidence import fetch_authenticated_order_and_fills, mapping
        from coinbase.rest import RESTClient
        creds=load_encrypted()
        if not creds:raise ValueError('missing vault')
        # Official SDK client; never invoke preview, create_order, cancel or transfer.
        client=RESTClient(api_key=creds['name'],api_secret=creds['privateKey'],timeout=16,verbose=False)
        del creds
        output=fetch_authenticated_order_and_fills(client,row[0],page_limit=100,max_pages=10)
        a.add('PASS / AUTHENTICATED GET',
             'Existing order identity and bounded complete GET fill pagination; pages='+str(output['pages'])+
             '; fill count='+str(len(output['fills']))+'; no identifier/quantity exported')
        product_id=output['order'].get('product_id')
        if isinstance(product_id,str) and product_id and callable(getattr(client,'get_product',None)):
            response=mapping(client.get_product(product_id))
            product=mapping(response.get('product',response))
            a.add('PASS / AUTHENTICATED GET' if product.get('product_id')==product_id else 'BLOCKED',
                  'Coinbase read-only product identity response '+('matches' if product.get('product_id')==product_id else 'mismatches')+' existing order')
        else:
            a.add('NOT VERIFIED','Product identity GET unavailable; cannot verify increments/minima')
        a.add('NOT VERIFIED','Response shape alone does NOT certify fee currencies, full fill amounts, fill-time USD marks or live order previews')
    except (ImportError,sqlite3.Error,ValueError,TypeError,OSError,KeyError,AttributeError,RuntimeError) as ex:
        a.add('NOT VERIFIED','Authenticated GET evidence incomplete: '+type(ex).__name__)
    except Exception as ex:
        # SDK may raise many exception classes; never print details/tokens.
        a.add('NOT VERIFIED','Authenticated GET rejected/failed: '+type(ex).__name__)


def fifo(a):
    a.section('CURRENCY-AWARE FIFO, FEES AND CANONICAL MIGRATION')
    tests(a,GROUPS['fifo']);db_readonly(a)
    a.add('BLOCKED','Actual multi-quote Coinbase fill -> atomic canonical FIFO settlement not integrated/certified')


def recovery(a):
    a.section('DURABLE INTENT, PARTIAL FILL, RESTART / UNKNOWN POST')
    ok=tests(a,GROUPS['recovery'])
    if ok:
        a.add('PASS / SYNTHETIC','Existing fixture rehearses 12 order intents, split fills, replay/refusal, rollback')
    a.add('BLOCKED','Disposable fake journal is not wired to the real Coinbase POST or canonical production ledger')


def floor(a):
    a.section('INDEPENDENT USD PORTFOLIO LOSS FLOOR / PROTECTED CAPITAL')
    tests(a,GROUPS['floor'])
    a.add('BLOCKED','No certified independent production-wide portfolio USD loss-floor enforcement')
    a.add('BLOCKED','Protected reserve remains advisory until excluded from actual enrolled spendable balances')


def edge(a):
    a.section('PROSPECTIVE USD ADVANTAGE / DYNAMIC SIZING / API BACKPRESSURE')
    tests(a,GROUPS['edge'])
    a.add('NOT VERIFIED','No current independent positive after-cost forward results versus frozen HOLD')
    a.add('PASS / STATIC RESEARCH ONLY','V60 contains dynamic multi-size portfolio research; synthetic checks are NOT real fills or executable sizes')
    a.add('BLOCKED','Adaptive LIVE execution throughput / API backpressure not production-certified in v60')
    a.add('NOT VERIFIED','$0.55 is a screening target, not guaranteed profit')


def shadow(a):
    a.section('SHADOW / COMPLETE DIAGNOSTIC / GPU STATE')
    tests(a,GROUPS['shadow'])
    a.add('NOT VERIFIED','Live Windows GUI shadow/export requires installed-app combined diagnostics, not synthetic fixtures')
    a.add('NOT VERIFIED','Quote touches and isolated FIFO models are not Coinbase executable fills')


def pilot(a):
    a.section('FINAL GO-LIVE RELEASE AUTHORIZATION GATES')
    import ast
    p=APP/'coincat_live.py'
    try:
        tree=ast.parse(p.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
        method=next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='submit')
        # Ensure fail-closed top-level statement in LiveBroker.submit, no SDK called.
        first=method.body[0]
        gated=isinstance(first,ast.Raise) and isinstance(first.exc,ast.Call) and isinstance(first.exc.func,ast.Name) and first.exc.func.id=='LiveBlocked'
        a.add('PASS / STATIC CODE CHECK' if gated else 'FAIL',
              'Existing LiveBroker.submit has unconditional first-statement POST block' if gated else 'LiveBroker.submit safety block missing or changed')
    except (OSError,SyntaxError,ValueError,StopIteration,AttributeError) as ex:
        a.add('FAIL','Unable to verify broker submission block: '+type(ex).__name__)
    a.add('BLOCKED','Production FIFO/fee/FX reconciliation, Coinbase-side proof, durable recovery, portfolio floor and positive held-out advantage not certified')
    a.add('BLOCKED','Maximum 12 submitted order-leg pilot remains NOT APPROVED; no synthetic result or .bat file can authorize it')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('gate',choices=('all',)+GATES)
    p.add_argument('--authorize-readonly-network',action='store_true',help='only from user-confirmed exchange .bat; never with all')
    ns=p.parse_args(argv)
    if ns.authorize_readonly_network and ns.gate!='coinbase':
        p.error('Network opt-in is allowed ONLY for the dedicated Coinbase read-only gate')
    if ROOT.name.lower()!='coincat_v70' or not (ROOT/'SHA256_MANIFEST_V60.json').is_file():
        print('BLOCKED: invalid source root',flush=True);return 2
    a=Audit()
    a.add('INFO','v70 Codex baseline source verification; ALL trading order POST remains blocked')
    if ns.gate=='all':
        offline(a)
        gpu(a)
        coinbase(a,False)
        db_readonly(a)
        # In ALL, the complete isolated regression suite covers individual groups.
        for name,phrase in [('fifo','Production multi-currency FIFO and tax settlement'),
                            ('recovery','Canonical crash-safe ambiguous POST recovery'),
                            ('floor','Independent enrolled USD loss floor and protected capital'),
                            ('edge','Positive held-out portfolio advantage and dynamic throughput'),
                            ('shadow','Windows SHADOW runtime and 18-section diagnostic completion')]:
            a.section(name.upper());a.add('BLOCKED' if name!='shadow' else 'NOT VERIFIED',phrase+' requires additional real-world evidence; see individual verification BAT')
        pilot(a)
    else:
        {'offline':offline,'gpu':gpu,'coinbase':lambda x:coinbase(x,ns.authorize_readonly_network),
         'fifo':fifo,'recovery':recovery,'floor':floor,'edge':edge,'shadow':shadow,'pilot':pilot}[ns.gate](a)
    a.save(ns.gate)
    print('\nFINAL GO-LIVE VERDICT: NOT APPROVED. LIVE ORDER POST BLOCKED.',flush=True)
    # nonzero for failures only; remains NOT APPROVED regardless of shell RC.
    return 3 if a.fail else 0

if __name__=='__main__':raise SystemExit(main())
