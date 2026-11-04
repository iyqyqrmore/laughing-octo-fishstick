"""Source-only default-ON/maker boundary check; no exchange or account access."""
from pathlib import Path
import ast,sys


def main():
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'app/coincat_live.py').read_text(encoding='utf-8'))
    broker=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiveBroker')
    submit=next(n for n in broker.body if isinstance(n,ast.FunctionDef) and n.name=='submit')
    guard=submit.body[1]
    if (not isinstance(guard,ast.If) or 'runtime is None or live_dispatch is None'!=ast.unparse(guard.test) or
            not isinstance(guard.body[0],ast.Raise) or 'LiveBlocked' not in ast.unparse(guard.body[0])):
        print('FAIL: default-ON bounded dispatch guard missing');return 2
    names={n.attr for n in ast.walk(submit) if isinstance(n,ast.Attribute)}
    if names & {'market_order_buy','market_order_sell','create_order','preview_market_order_buy','preview_market_order_sell'}:
        print('FAIL: non-maker submission fallback');return 3
    if not {'limit_order_gtc_buy','limit_order_gtc_sell','claim'}<=names:
        print('FAIL: bounded maker adapter missing');return 4
    if not any(isinstance(n,ast.keyword) and n.arg=='post_only' and isinstance(n.value,ast.Constant) and n.value.value is True for n in ast.walk(submit)):
        print('FAIL: explicit post_only=True missing');return 5
    print('PASS: default-ON bounded beta guard / maker-only adapter')
    print('CONNECTED BETA ACCEPTANCE NOT VERIFIED; no exchange requests or account mutations')
    return 0


if __name__=='__main__':sys.exit(main())
