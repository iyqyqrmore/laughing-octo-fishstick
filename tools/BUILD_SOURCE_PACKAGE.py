"""Regenerate the v100 manifest and optional source-only ZIP; no private inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES=('.gitignore','00_READ_ME_FIRST.txt','01_START_COINCAT.bat','02_SETUP_COINCAT.bat',
    '03_VERIFY_COINCAT.bat','04_FIRST_TIME_SETUP.bat','AGENTS.md','DECISION_CHAIN_REVIEW.md',
    'PATCH_NOTES.md','README.md','START_HERE.md','THIRD_PARTY_ATTRIBUTION_AND_RISK.md',
    'VERIFICATION.txt','VERIFY_SOURCE.py','app_requirements.txt','app_requirements.lock')


def source_files():
    names=list(ROOT_FILES)
    for folder,suffixes in {'app':{'.py','.ico','.png'},'docs':{'.md'},
            'offline_tests':{'.py'},'tools':{'.py','.bat','.ps1'},'verification':{'.py'}}.items():
        for p in sorted((ROOT/folder).iterdir()):
            if p.is_file() and p.suffix in suffixes:names.append(p.relative_to(ROOT).as_posix())
    for name in names:
        p=ROOT/name
        if p.is_symlink() or not p.is_file():raise ValueError('Source file missing or symlink: '+name)
    return sorted(names)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',type=Path);args=parser.parse_args()
    names=source_files()
    data=dict(build='100.0-adaptive-eth-journal-candidate',
        description='Seven-market conditional adaptive ETH research; no execution or financial writes.',
        base_commit='1e0d88e0161c98f3f1328eeb9a40ebffe9826467',
        files={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names})
    (ROOT/'SHA256_MANIFEST.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print('Manifest source files:',len(names))
    if args.zip:
        path=args.zip.resolve();path.parent.mkdir(parents=True,exist_ok=True)
        if path==ROOT or ROOT in path.parents:raise ValueError('Keep package outside source checkout')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names+['SHA256_MANIFEST.json']:
                archive.write(ROOT/name,'CoinCat_v100/'+name)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(path.suffix+'.sha256').write_text(digest+'  '+path.name+'\n',encoding='utf-8')
        print('Source ZIP:',path.name,'SHA256',digest)


if __name__=='__main__':main()
