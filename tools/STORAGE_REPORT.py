"""Report local storage; --clean-source-cache removes only source __pycache__.

Financial/research SQLite, sessions, keys, locks, imports and backups are never
deleted. Old session names identify financial history and are not redundancy.
"""
import argparse
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clean-source-cache',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];removed=0;cache_bytes=0;files=0
    for folder in ('app','tools','offline_tests','verification'):
        for path in (root/folder).rglob('*.pyc'):
            if path.parent.name!='__pycache__' or path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=root):continue
            files+=1;cache_bytes+=path.stat().st_size
            if args.clean_source_cache:path.unlink();removed+=1
    print('CoinCat v1.04 source cache files:',files,'bytes:',cache_bytes,'removed:',removed)
    print('Financial, research, manual/live/paper history, backups, credentials and locks: preserved; no deletion candidates.')
    return 0


if __name__=='__main__':sys.exit(main())
