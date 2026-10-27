"""Hold an OS-released single-process lock while CoinCat v60 is running.

v40 data lives under its own verified directory. Previous versions have
independent storage and do not need to be installed.
"""
from pathlib import Path
import os

class AnotherCoinCatRunning(RuntimeError):
    pass

class SingleInstance:
    def __init__(self,data_dir):
        self.path=Path(data_dir)/'coincat_v70_instance.lock'
        self.file=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=open(self.path,'a+b',buffering=0)
        try:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                self.file.write(b'0')
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except (OSError,BlockingIOError) as exc:
            self.file.close();self.file=None
            raise AnotherCoinCatRunning('Another CoinCat process holds the current state lock. Close it before launching.') from exc
        return self

    def __exit__(self,*args):
        if self.file is not None:
            try:
                if os.name=='nt':
                    import msvcrt
                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            finally:
                self.file.close();self.file=None
