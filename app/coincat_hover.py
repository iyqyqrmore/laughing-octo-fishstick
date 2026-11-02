"""Delayed mouse and keyboard help, with deterministic Tk callback cleanup."""
import tkinter as tk
from tkinter import ttk


class Hover:
    def __init__(self,widget,text):
        self.widget=widget;self.text=text;self.after=None;self.window=None
        widget.bind('<Enter>',self.schedule,add='+')
        widget.bind('<FocusIn>',self.schedule,add='+')
        for event in ('<Leave>','<FocusOut>','<ButtonPress>','<Escape>','<Destroy>'):
            widget.bind(event,self.hide,add='+')
        widget.hover_help=self

    def schedule(self,event=None):
        self.hide()
        self.after=self.widget.after(450,self.show)

    def show(self):
        self.after=None
        if not self.widget.winfo_exists():return
        text=self.text() if callable(self.text) else self.text
        if not text:return
        self.hide();self.window=tk.Toplevel(self.widget)
        self.window.withdraw()
        self.window.wm_overrideredirect(True)
        root=self.widget.winfo_toplevel()
        previous=getattr(root,'_active_hover',None)
        if previous is not None and previous is not self:previous.hide()
        root._active_hover=self
        label=ttk.Label(self.window,text=text,wraplength=480,padding=10,justify='left',relief='solid',borderwidth=1)
        label.pack();self.window.update_idletasks()
        x=min(self.widget.winfo_rootx()+12,self.widget.winfo_screenwidth()-self.window.winfo_reqwidth()-8)
        y=min(self.widget.winfo_rooty()+self.widget.winfo_height()+5,
              self.widget.winfo_screenheight()-self.window.winfo_reqheight()-8)
        self.window.wm_geometry(f'+{max(0,x)}+{max(0,y)}')
        self.window.deiconify()

    def hide(self,event=None):
        if self.after is not None:
            try:self.widget.after_cancel(self.after)
            except tk.TclError:pass
            self.after=None
        if self.window is not None:
            try:self.window.destroy()
            except tk.TclError:pass
            self.window=None


def help_tree(parent,default):
    """Ensure every user-facing control/readout, including editor internals, has help."""
    for child in parent.winfo_children():
        if child.winfo_class() not in ('TFrame','TLabelframe','Frame','Toplevel') and not hasattr(child,'hover_help'):
            Hover(child,default)
        help_tree(child,default)
