"""Source-only submission guard check; full validation uses RUN_OFFLINE_TESTS."""
from pathlib import Path
import ast,sys


def main():
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'app/coincat_live.py').read_text(encoding='utf-8'))
    broker=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
    submit=next(n for n in broker.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
    first=submit.body[0]
    if not isinstance(first,ast.Raise) or 'LiveBlocked' not in ast.unparse(first):
        print('FAIL: unconditional order submission guard missing');return 2
    print('PASS: unconditional first-statement POST block')
    print('LIVE NOT APPROVED; no exchange requests or account mutations')
    return 0


if __name__=='__main__':sys.exit(main())
