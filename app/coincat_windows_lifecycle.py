"""Windows shutdown checkpoints only. No tray, hidden window or minimize hook."""
import sys

def without_minimize(style):return style & ~0x00020000 # WS_MINIMIZEBOX only.

class WindowsLifecycle:
    def __init__(self,root,shutdown,backend=None):
        self.backend=backend
        if backend is None and sys.platform=='win32':
            try:self.backend=NativeSessionHook(root,shutdown)
            except (OSError,ValueError,AttributeError):self.backend=None
    def close(self):
        if self.backend is not None:self.backend.close();self.backend=None

class NativeSessionHook:
    def __init__(self,root,shutdown):
        import ctypes as c
        from ctypes import wintypes as w
        self.c=c;self.root=root;self.shutdown=shutdown;self.closed=False
        self.user=c.WinDLL('user32',use_last_error=True);u=self.user;result=c.c_ssize_t
        self.WNDPROC=c.WINFUNCTYPE(result,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
        u.GetParent.argtypes=[w.HWND];u.GetParent.restype=w.HWND
        self.getlong=getattr(u,'GetWindowLongPtrW' if c.sizeof(c.c_void_p)==8 else 'GetWindowLongW')
        self.getlong.argtypes=[w.HWND,c.c_int];self.getlong.restype=c.c_ssize_t
        self.setlong=getattr(u,'SetWindowLongPtrW' if c.sizeof(c.c_void_p)==8 else 'SetWindowLongW')
        self.setlong.argtypes=[w.HWND,c.c_int,c.c_ssize_t];self.setlong.restype=c.c_ssize_t
        u.CallWindowProcW.argtypes=[c.c_void_p,w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.CallWindowProcW.restype=result
        u.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
        root.update_idletasks();self.hwnd=u.GetParent(root.winfo_id()) or root.winfo_id()
        self.style=self.getlong(self.hwnd,-16);self.setlong(self.hwnd,-16,without_minimize(self.style))
        u.SetWindowPos(self.hwnd,None,0,0,0,0,0x0027) # frame changed, no move/size/z-order.
        self.callback=self.WNDPROC(self.dispatch)
        self.old=self.setlong(self.hwnd,-4,c.cast(self.callback,c.c_void_p).value)
        if not self.old:raise OSError('WINDOWS_SHUTDOWN_HOOK_UNAVAILABLE')
    def dispatch(self,hwnd,msg,wp,lp):
        if msg==0x11:return 1 # Never veto WM_QUERYENDSESSION.
        if msg==0x16 and wp:self.root.after(0,self.shutdown);return 0
        return self.user.CallWindowProcW(self.old,hwnd,msg,wp,lp)
    def close(self):
        if not self.closed:self.closed=True;self.setlong(self.hwnd,-4,self.old)
