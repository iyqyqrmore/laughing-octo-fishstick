"""Pointer-adjacent, bounded mouse/keyboard help with scrollable long details."""
import sys
import tkinter as tk
from tkinter import ttk


def popup_geometry(anchor,bounds,width,height):
    """Place beside the pointer; flip above/left and keep all edges visible."""
    left,top,right,bottom=bounds
    width=min(width,max(1,right-left-16));height=min(height,max(1,bottom-top-16))
    x,y=anchor[0]+16,anchor[1]+20
    if x+width>right-8:x=anchor[0]-width-12
    if y+height>bottom-8:y=anchor[1]-height-12
    x=max(left+8,min(x,right-width-8));y=max(top+8,min(y,bottom-height-8))
    return int(x),int(y),int(width),int(height)


def visible_bounds(widget,anchor):
    """Intersect the app's visible area with the pointer monitor's work area."""
    left,top=widget.winfo_vrootx(),widget.winfo_vrooty()
    right,bottom=left+widget.winfo_screenwidth(),top+widget.winfo_screenheight()
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),
                      ('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]
        user32=ctypes.windll.user32
        user32.MonitorFromPoint.argtypes=[wintypes.POINT,wintypes.DWORD]
        user32.MonitorFromPoint.restype=wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype=wintypes.BOOL
        info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
        monitor=user32.MonitorFromPoint(wintypes.POINT(*anchor),2)
        if user32.GetMonitorInfoW(monitor,ctypes.byref(info)):
            r=info.rcWork;left,top,right,bottom=r.left,r.top,r.right,r.bottom
    root=widget.winfo_toplevel()
    app=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),
         root.winfo_rooty()+root.winfo_height())
    intersect=(max(left,app[0]),max(top,app[1]),min(right,app[2]),min(bottom,app[3]))
    return intersect if intersect[2]-intersect[0]>=200 and intersect[3]-intersect[1]>=100 else (left,top,right,bottom)


class Hover:
    def __init__(self,widget,text):
        self.widget=widget;self.text=text;self.after=None;self.window=None;self.dismiss=None
        self.anchor=None;self.body=None
        widget.bind('<Enter>',self.schedule,add='+')
        widget.bind('<Motion>',self.motion,add='+')
        widget.bind('<FocusIn>',self.schedule,add='+')
        for event in ('<Leave>','<FocusOut>'):widget.bind(event,self.schedule_hide,add='+')
        for event in ('<ButtonPress>','<Escape>','<Destroy>'):widget.bind(event,self.hide,add='+')
        widget.hover_help=self

    def motion(self,event):
        self.anchor=(event.x_root,event.y_root)

    def schedule(self,event=None):
        self.hide()
        self.anchor=((event.x_root,event.y_root) if event is not None and event.type in (tk.EventType.Enter,tk.EventType.Motion) else None)
        self.after=self.widget.after(450,self.show)

    def show(self):
        self.after=None
        if not self.widget.winfo_exists():return
        text=self.text() if callable(self.text) else self.text
        if not text:return
        anchor=self.anchor
        if anchor is None:
            if self.widget.focus_get() is self.widget:
                anchor=(self.widget.winfo_rootx()+12,self.widget.winfo_rooty()+12)
            else:anchor=self.widget.winfo_pointerxy()
        bounds=visible_bounds(self.widget,anchor)
        width=min(520,max(160,bounds[2]-bounds[0]-24))
        max_height=min(480,max(64,bounds[3]-bounds[1]-24))
        self.hide();self.window=tk.Toplevel(self.widget);self.window.withdraw()
        self.window.wm_overrideredirect(True)
        root=self.widget.winfo_toplevel();previous=getattr(root,'_active_hover',None)
        if previous is not None and previous is not self:previous.hide()
        root._active_hover=self
        # Measure the actual wrapped text, including font/DPI, before placing.
        label=ttk.Label(self.window,text=text,wraplength=width-26,padding=10)
        label.pack();self.window.update_idletasks()
        desired_height=label.winfo_reqheight()+2;desired_width=min(width,label.winfo_reqwidth()+2)
        if desired_height>max_height:
            label.destroy()
            frame=ttk.Frame(self.window,padding=7,relief='solid',borderwidth=1);frame.pack(fill='both',expand=True)
            body=tk.Text(frame,wrap='word',font='TkDefaultFont',borderwidth=0,highlightthickness=0,
                         takefocus=False,cursor='arrow')
            scroll=ttk.Scrollbar(frame,orient='vertical',command=body.yview)
            body.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');body.pack(fill='both',expand=True)
            body.insert('1.0',text);body.configure(state='disabled');self.body=body
            desired_width=width;desired_height=max_height
            for child in (frame,body,scroll):
                child.bind('<Enter>',self.cancel_hide,add='+');child.bind('<Leave>',self.schedule_hide,add='+')
        else:label.configure(relief='solid',borderwidth=1)
        x,y,w,h=popup_geometry(anchor,bounds,desired_width,desired_height)
        self.window.wm_geometry(f'{w}x{h}+{x}+{y}')
        self.window.bind('<Enter>',self.cancel_hide,add='+')
        self.window.bind('<Leave>',self.schedule_hide,add='+')
        self.window.bind('<Escape>',self.hide,add='+');self.window.deiconify()

    def cancel_hide(self,event=None):
        if self.dismiss is not None:
            try:self.widget.after_cancel(self.dismiss)
            except tk.TclError:pass
            self.dismiss=None

    def schedule_hide(self,event=None):
        self.cancel_hide()
        self.dismiss=self.widget.after(180,self._hide_if_outside)

    def _hide_if_outside(self):
        self.dismiss=None
        if self.window is not None:
            x,y=self.widget.winfo_pointerxy();w=self.window
            if w.winfo_rootx()<=x<=w.winfo_rootx()+w.winfo_width() and w.winfo_rooty()<=y<=w.winfo_rooty()+w.winfo_height():return
        self.hide()

    def hide(self,event=None):
        self.cancel_hide()
        if self.after is not None:
            try:self.widget.after_cancel(self.after)
            except tk.TclError:pass
            self.after=None
        if self.window is not None:
            try:self.window.destroy()
            except tk.TclError:pass
            self.window=None;self.body=None
            self.cancel_hide()


def help_tree(parent,default):
    """Ensure every user-facing control/readout, including editor internals, has help."""
    for child in parent.winfo_children():
        if child.winfo_class() not in ('TFrame','TLabelframe','Frame','Toplevel') and not hasattr(child,'hover_help'):
            Hover(child,default)
        help_tree(child,default)
