"""Standalone SHA-256 verification for CoinCat v100.0 source release; no network."""
import hashlib, json, sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parent
    manifest=root/'SHA256_MANIFEST.json'
    try:data=json.loads(manifest.read_text(encoding='utf-8'))
    except (ValueError,OSError):return 2
    if data.get('build')!='100.0-adaptive-eth-journal-candidate':return 3
    files=data.get('files')
    if not isinstance(files,dict) or not files:return 4
    fails=[]
    for name,expected in files.items():
        path=root/name
        if '..' in Path(name).parts or path.is_symlink() or not path.is_file():fails.append(name);continue
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:fails.append(name)
    print('CoinCat v100.0 source hashes checked:',len(files),'Failures:',len(fails))
    if fails:
        print('BLOCKED: Source files missing or changed; first discrepancies:',fails[:4]);return 5
    print('PASS / SOURCE INTEGRITY ONLY; live trading still blocked')
    return 0
if __name__=='__main__':sys.exit(main())
