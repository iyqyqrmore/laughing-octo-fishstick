"""Windows native tray, no dependency or shutdown veto. UI policy is testable."""
import sys

class TrayController:
    def __init__(self,root,*,status,toggle,open_trial,exit_safely,shutdown,backend=None):
        self.root=root;self.status=status;self.toggle=toggle;self.open_trial=open_trial;self.exit_safely=exit_safely
        self.available=False;self.backend=None
        try:
            if backend is None:
                if sys.platform!='win32':return
                backend=WindowsTray(root,self.menu,self.open,shutdown)
            self.backend=backend;self.available=True
        except (OSError,ValueError,AttributeError):pass
    def menu(self):
        state,progress,performance=self.status()
        return [('Open CoinCat',self.open),(state,None),(progress,None),(performance,None),
            ('Pause / resume shadow trial',self.toggle),('Trial progress / performance',self.open_trial),('Exit safely',self.exit_safely)]
    def hide(self):
        if self.available:self.root.withdraw();return True
        return False
    def open(self):self.root.deiconify();self.root.lift()
    def minimized(self,event=None):
        if self.available and self.root.state()=='iconic':self.hide()
    def close(self):
        if self.backend is not None:self.backend.close();self.backend=None
        self.available=False

class WindowsTray:
    """Own icon and WNDPROC on the Tk thread; retained callbacks until removal."""
    def __init__(self,root,menu,open_window,shutdown):
        import ctypes as c
        from ctypes import wintypes as w
        self.c=c;self.root=root;self.menu=menu;self.open_window=open_window;self.shutdown=shutdown
        self.user=c.WinDLL('user32',use_last_error=True);self.shell=c.WinDLL('shell32',use_last_error=True)
        LRESULT=c.c_ssize_t;self.WNDPROC=c.WINFUNCTYPE(LRESULT,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
        class GUID(c.Structure):_fields_=[('Data1',w.DWORD),('Data2',w.WORD),('Data3',w.WORD),('Data4',c.c_ubyte*8)]
        class DATA(c.Structure):
            _fields_=[('cbSize',w.DWORD),('hWnd',w.HWND),('uID',w.UINT),('uFlags',w.UINT),('uCallbackMessage',w.UINT),
                ('hIcon',w.HICON),('szTip',w.WCHAR*128),('dwState',w.DWORD),('dwStateMask',w.DWORD),('szInfo',w.WCHAR*256),
                ('uTimeoutOrVersion',w.UINT),('szInfoTitle',w.WCHAR*64),('dwInfoFlags',w.DWORD),('guidItem',GUID),('hBalloonIcon',w.HICON)]
        u=self.user;u.GetParent.argtypes=[w.HWND];u.GetParent.restype=w.HWND
        u.CallWindowProcW.argtypes=[c.c_void_p,w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.CallWindowProcW.restype=LRESULT
        self.setproc=getattr(u,'SetWindowLongPtrW' if c.sizeof(c.c_void_p)==8 else 'SetWindowLongW')
        self.setproc.argtypes=[w.HWND,c.c_int,c.c_void_p];self.setproc.restype=c.c_void_p
        u.LoadIconW.argtypes=[w.HINSTANCE,c.c_void_p];u.LoadIconW.restype=w.HICON
        u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.SendMessageW.restype=LRESULT
        u.RegisterWindowMessageW.argtypes=[w.LPCWSTR];u.RegisterWindowMessageW.restype=w.UINT
        u.CreatePopupMenu.restype=w.HMENU;u.AppendMenuW.argtypes=[w.HMENU,w.UINT,c.c_size_t,w.LPCWSTR]
        u.TrackPopupMenu.argtypes=[w.HMENU,w.UINT,c.c_int,c.c_int,c.c_int,w.HWND,c.c_void_p];u.TrackPopupMenu.restype=w.UINT
        u.DestroyMenu.argtypes=[w.HMENU];u.SetForegroundWindow.argtypes=[w.HWND]
        u.GetCursorPos.argtypes=[c.POINTER(w.POINT)]
        self.shell.Shell_NotifyIconW.argtypes=[w.DWORD,c.POINTER(DATA)];self.shell.Shell_NotifyIconW.restype=w.BOOL
        root.update_idletasks();native=root.winfo_id();self.hwnd=u.GetParent(native) or native
        self.callback_message=0x8000+104;self.taskbar_created=u.RegisterWindowMessageW('TaskbarCreated');self.old=None;self.closed=False
        self.callback=self.WNDPROC(self.dispatch)
        self.old=self.setproc(self.hwnd,-4,c.cast(self.callback,c.c_void_p))
        if not self.old:raise OSError('TRAY_WINDOW_HOOK_UNAVAILABLE')
        self.data=DATA();self.data.cbSize=c.sizeof(DATA);self.data.hWnd=self.hwnd;self.data.uID=104
        self.data.uFlags=7;self.data.uCallbackMessage=self.callback_message
        self.data.hIcon=u.SendMessageW(self.hwnd,0x7F,2,0) or u.LoadIconW(None,c.c_void_p(32512))
        self.data.szTip='CoinCat v1.04 - shadow research; manual live block defaults ON'
        if not self.shell.Shell_NotifyIconW(0,c.byref(self.data)):
            self.setproc(self.hwnd,-4,self.old);raise OSError('TRAY_ICON_UNAVAILABLE')
    def dispatch(self,hwnd,msg,wp,lp):
        if msg==0x11:return 1 # WM_QUERYENDSESSION: always allow Windows shutdown.
        if msg==0x16 and wp:
            self.root.after(0,self.shutdown);return 0
        if msg==getattr(self,'taskbar_created',None):
            if not self.shell.Shell_NotifyIconW(0,self.c.byref(self.data)):self.root.after(0,self.open_window)
            return 0
        if msg==self.callback_message:
            if lp==0x203:self.root.after(0,self.open_window)
            elif lp in (0x205,0x202):self.popup()
            return 0
        return self.user.CallWindowProcW(self.old,hwnd,msg,wp,lp)
    def popup(self):
        from ctypes import wintypes as w
        menu=self.user.CreatePopupMenu();actions={}
        try:
            for i,(label,action) in enumerate(self.menu(),1):
                self.user.AppendMenuW(menu,0 if action else 1,i,label[:160]);actions[i]=action
            point=w.POINT();self.user.GetCursorPos(self.c.byref(point));self.user.SetForegroundWindow(self.hwnd)
            choice=self.user.TrackPopupMenu(menu,0x100|0x2,point.x,point.y,0,self.hwnd,None)
            if actions.get(choice):self.root.after(0,actions[choice])
        finally:self.user.DestroyMenu(menu)
    def close(self):
        if self.closed:return
        self.closed=True;self.shell.Shell_NotifyIconW(2,self.c.byref(self.data));self.setproc(self.hwnd,-4,self.old)
