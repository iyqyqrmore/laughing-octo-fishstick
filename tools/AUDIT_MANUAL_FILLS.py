"""Local GET-only saved-key audit. Never creates, previews or cancels orders."""
import argparse
from pathlib import Path
import json
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT)]
os.environ.setdefault('COINCAT_DATA_DIR',str(ROOT/'private_data'))

def main():
    from coincat_fee_audit import statement_day,audit_day,collect_day
    from coincat_beta_store import pack
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',type=Path);parser.add_argument('--day',default='2026-11-04')
    parser.add_argument('--offline-receipts',type=Path,help='Strict local JSON records; skips all connected reads.')
    args=parser.parse_args()
    path=args.csv
    if path is None:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw();selected=filedialog.askopenfilename(title='Select private Coinbase statement CSV',filetypes=[('CSV','*.csv')]);root.destroy()
        if not selected:return 2
        path=Path(selected)
    statement=statement_day(path,args.day)
    coverage='PROVIDED_RECORDS_ONLY';client=None
    if args.offline_receipts:
        p=args.offline_receipts
        if p.is_symlink() or p.stat().st_size>1048576:raise ValueError('RECEIPT_INPUT_REJECTED')
        records=json.loads(p.read_text(encoding='utf-8'))
    else:
        from coinbase_account import load_encrypted
        from coincat_live import client_from_credentials
        from coincat_sdk_logging import protect_sdk_logs
        from coincat_v701_transport import BUDGET
        credentials=load_encrypted()
        if not credentials:print('No local saved key. Import it in CoinCat first; do not share it.');return 2
        protect_sdk_logs();client=client_from_credentials(credentials)
        try:
            collected=collect_day(client,args.day,budget=BUDGET);records=collected['records'];coverage=collected['coverage']
            from coincat_manual_trade import ManualTradeStore
            from coincat_state_v50 import data_root
            ManualTradeStore(data_root()/'research_data'/'manual_trade_lab'/'observations.sqlite3').append(dict(collected,reason=coverage))
        finally:
            if hasattr(client,'session'):client.session.close()
    report=audit_day(records,statement,api_coverage=coverage)
    from coincat_state_v50 import data_root
    out=data_root()/'research_data'/'manual_trade_lab'/('fee-audit-'+args.day+'.json');out.parent.mkdir(parents=True,exist_ok=True)
    if out.is_symlink():raise ValueError('AUDIT_PATH_REJECTED')
    out.write_text(pack(report),encoding='utf-8')
    print('Private local audit saved. CSV trades:',report['csv_trade_rows'],'API matches:',report['matched'])
    print('API fee currencies confirmed:',report['api_fee_currency_confirmed'],'liquidity confirmed:',report['liquidity_confirmed'])
    print(report['coverage'],'Account reconciliation UNKNOWN. Historical rates never become future fee settings.')
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:print('Audit incomplete. Private inputs preserved; no order action was attempted.');raise SystemExit(3)
