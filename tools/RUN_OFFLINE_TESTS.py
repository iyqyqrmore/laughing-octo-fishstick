"""Complete synthetic suite with disposable state and HTTP forbidden."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os,sys,unittest,sqlite3


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root/'app'),str(root)]
    import tkinter
    print('RUNTIME',sys.platform,'Python',sys.version.split()[0],
          'SQLite',sqlite3.sqlite_version,'Tk',tkinter.TkVersion,'Tcl',tkinter.TclVersion,flush=True)
    with TemporaryDirectory(prefix='CoinCat_Offline_Disposable_') as data:
        with patch.dict(os.environ,{'COINCAT_DATA_DIR':data,'PYTHONDONTWRITEBYTECODE':'1'}):
            with patch('requests.sessions.Session.request',side_effect=AssertionError('OFFLINE_HTTP_FORBIDDEN')):
                suite=unittest.defaultTestLoader.discover(str(root/'offline_tests'))
                def cases(node):
                    for item in node:
                        if isinstance(item,unittest.TestSuite):yield from cases(item)
                        else:yield item
                ids=[t.id() for t in cases(suite)]
                print('DISCOVERED',len(ids),'DISTINCT',len(set(ids)),'HTTP FORBIDDEN',flush=True)
                result=unittest.TextTestRunner(verbosity=1).run(suite)
                print('COUNTS',result.testsRun,'failures',len(result.failures),'errors',len(result.errors),
                      'skips',len(result.skipped),'expected_failures',len(result.expectedFailures),flush=True)
                for case,reason in result.skipped:
                    print('SKIPPED',case.id(),reason,flush=True)
                return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
