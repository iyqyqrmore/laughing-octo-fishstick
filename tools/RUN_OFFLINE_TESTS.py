"""Full or focused synthetic checks with disposable state and HTTP forbidden."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import argparse,os,sys,unittest,sqlite3,threading,time


class Progress:
    """Console-only liveness, including discovery and temporary-data cleanup."""
    def __init__(self,stream,*,interval=30):
        self.stream=stream;self.interval=interval;self.clock=time.perf_counter
        self.started=self.clock();self.step_started=self.started;self.label='test discovery'
        self.lock=threading.Lock();self.stop=threading.Event()
        self.thread=threading.Thread(target=self._heartbeat,name='CoinCatVerifyProgress')

    def __enter__(self):self.thread.start();return self

    def update(self,label):
        with self.lock:self.label=label;self.step_started=self.clock()

    def _heartbeat(self):
        while not self.stop.wait(self.interval):
            with self.lock:
                self.stream.write('\nSTILL RUNNING '+self.label+
                    f' | step {self.clock()-self.step_started:.0f}s | suite {self.clock()-self.started:.0f}s\n')
                self.stream.flush()

    def __exit__(self,*exc):self.stop.set();self.thread.join()


class ProgressResult(unittest.TextTestResult):
    def __init__(self,*args,total,progress,**kwargs):
        super().__init__(*args,**kwargs);self.total=total;self.progress=progress;self.timings=[]

    def startTest(self,test):
        self.test_started=self.progress.clock()
        self.progress.update(f'test {self.testsRun+1}/{self.total}: '+test.id())
        self.stream.write(f'[{self.testsRun+1}/{self.total}] ');self.stream.flush()
        super().startTest(test)

    def stopTest(self,test):
        elapsed=self.progress.clock()-self.test_started
        self.timings.append((elapsed,test.id()))
        self.stream.writeln(f'    Test {elapsed:.3f}s | suite {self.progress.clock()-self.progress.started:.1f}s')
        self.stream.flush();super().stopTest(test)
        self.progress.update(f'between tests ({self.testsRun}/{self.total} finished)')


def main(*,manual_window=False,trial=False,assumed=False,opportunity=False,intelligent=False):
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root/'app'),str(root)]
    import tkinter
    print('RUNTIME',sys.platform,'Python',sys.version.split()[0],
          'SQLite',sqlite3.sqlite_version,'Tk',tkinter.TkVersion,'Tcl',tkinter.TclVersion,flush=True)
    if trial:print('FOCUSED RESUMABLE TRIAL CHECKS ONLY; no connected or native Windows acceptance.',flush=True)
    if manual_window:print('FOCUSED MANUAL WINDOW CHECKS ONLY; full source verification is still required.',flush=True)
    if assumed:print('FOCUSED ASSUMED-FILL CHECKS ONLY; fictional orders, no connected or execution evidence.',flush=True)
    if intelligent:print('FOCUSED V1.05 INTELLIGENT SHADOW CHECKS; synthetic evidence, no connected/native Windows acceptance.',flush=True)
    if opportunity:print('FOCUSED OPPORTUNITY SHADOW CHECKS ONLY; synthetic evidence, no connected or native Windows acceptance.',flush=True)
    with Progress(sys.stderr) as progress,TemporaryDirectory(prefix='CoinCat_Offline_Disposable_') as data:
        with patch.dict(os.environ,{'COINCAT_DATA_DIR':data,'PYTHONDONTWRITEBYTECODE':'1'}):
            with patch('requests.sessions.Session.request',side_effect=AssertionError('OFFLINE_HTTP_FORBIDDEN')), \
                    patch('websockets.sync.client.connect',side_effect=AssertionError('OFFLINE_WS_FORBIDDEN')), \
                    patch('websockets.connect',side_effect=AssertionError('OFFLINE_WS_FORBIDDEN')):
                suite=unittest.defaultTestLoader.discover(str(root/'offline_tests'),
                    pattern='test_intelligent*.py' if intelligent else 'test_opportunity*.py' if opportunity else 'test_assumed*.py' if assumed else 'test_spot_workspace.py' if manual_window else 'test_*trial*.py' if trial else 'test*.py')
                def cases(node):
                    for item in node:
                        if isinstance(item,unittest.TestSuite):yield from cases(item)
                        else:yield item
                ids=[t.id() for t in cases(suite)]
                print('DISCOVERED',len(ids),'DISTINCT',len(set(ids)),'HTTP / WEBSOCKET FORBIDDEN',flush=True)
                result=unittest.TextTestRunner(verbosity=2,resultclass=lambda *args,**kwargs:
                    ProgressResult(*args,total=len(ids),progress=progress,**kwargs)).run(suite)
                print('COUNTS',result.testsRun,'failures',len(result.failures),'errors',len(result.errors),
                      'skips',len(result.skipped),'expected_failures',len(result.expectedFailures),flush=True)
                for case,reason in result.skipped:
                    print('SKIPPED',case.id(),reason,flush=True)
                print('SLOWEST TESTS (elapsed wall seconds)',flush=True)
                for elapsed,name in sorted(result.timings,reverse=True)[:5]:
                    print(f'{elapsed:.3f}s {name}',flush=True)
                progress.update('disposable test-data cleanup')
                return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manual-window',action='store_true',help='Run only the isolated manual-window checks; not a full verification pass.')
    parser.add_argument('--trial',action='store_true',help='Focused resumable trial checks only; not full acceptance.')
    parser.add_argument('--assumed',action='store_true',help='Focused assumed-fill simulator checks only; not full acceptance.')
    parser.add_argument('--opportunity',action='store_true',help='Focused opportunity shadow policy/lifecycle/forward scenarios only; not full acceptance.')
    parser.add_argument('--intelligent',action='store_true',help='Focused v1.05 forecast, policy, source, lifecycle, privacy and workspace checks.')
    args=parser.parse_args();raise SystemExit(main(manual_window=args.manual_window,trial=args.trial,assumed=args.assumed,opportunity=args.opportunity,intelligent=args.intelligent))
