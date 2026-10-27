"""Reusable, local-only ttk.Treeview cell tooltips for all CoinCat tables.

UI-only. No background polling, financial state changes, file/network access or
trade permissions. Column widths remain user-draggable via standard ttk headings.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import font as tkfont


def needs_tooltip(value, column_width, measure=lambda s: len(s)*8):
    """Pure testable approximation; long/hidden line breaks count as clipping."""
    text = str(value or '')
    return ('\n' in text or measure(text) > max(0, int(column_width)-16))


class TreeCellTips:
    def __init__(self, tree, *, delay_ms=390, wrap_px=305):
        self.tree=tree
        self.delay_ms=delay_ms
        self.wrap_px=wrap_px
        self._pending=None
        self._popup=None
        self._point=None
        self._font=None
        tree.bind('<Motion>',self._motion,add='+')
        for seq in ('<Leave>', '<ButtonPress>', '<MouseWheel>', '<Button-4>', '<Button-5>',
                    '<Configure>', '<Destroy>', '<KeyPress>'):
            tree.bind(seq,self.hide,add='+')

    def hide(self, event=None):
        if self._pending is not None:
            try:self.tree.after_cancel(self._pending)
            except tk.TclError:pass
            self._pending=None
        if self._popup is not None:
            try:self._popup.destroy()
            except tk.TclError:pass
            self._popup=None
        self._point=None

    def _full_text(self, iid, col_index):
        values=self.tree.item(iid,'values')
        if col_index < 0 or col_index >= len(values):return '', ''
        shown=str(values[col_index])
        resolver=getattr(self.tree,'_coincat_full_cell_text',None)
        if resolver:
            try:
                complete=resolver(iid,col_index)
                if complete is not None:return shown,str(complete)
            except (IndexError,KeyError,ValueError,tk.TclError):pass
        return shown,shown

    def _motion(self,event):
        try:
            if self.tree.identify_region(event.x,event.y)!='cell':
                self.hide();return
            iid=self.tree.identify_row(event.y)
            col=self.tree.identify_column(event.x)
            col_index=int(col[1:])-1
            if not iid or col_index<0:self.hide();return
            shown,full=self._full_text(iid,col_index)
            if not full or full=='—':self.hide();return
            columns=self.tree['columns']
            width=int(self.tree.column(columns[col_index],option='width'))
            if self._font is None:self._font=tkfont.nametofont('TkDefaultFont')
            clipped=(full!=shown or needs_tooltip(shown,width,self._font.measure))
            if not clipped:self.hide();return
            point=(iid,col_index,full)
            if point==self._point:return
            self.hide()
            self._point=point
            self._pending=self.tree.after(self.delay_ms,lambda p=point:self._show(p))
        except (tk.TclError,ValueError,IndexError,KeyError):self.hide()

    def _show(self,point):
        self._pending=None
        if point!=self._point:return
        try:
            if not self.tree.winfo_exists():return
            top=tk.Toplevel(self.tree)
            top.withdraw();top.overrideredirect(True)
            text=point[2][:2400]  # bound UI rendering; do not alter data or diagnostics
            label=tk.Label(top,text=text,justify='left',anchor='w',wraplength=self.wrap_px,
                           bg='#f2f9ff',fg='#071425',relief='solid',borderwidth=2,
                           font=('Segoe UI',9),padx=6,pady=4)
            label.pack()
            top.update_idletasks()
            pointer_x,pointer_y=self.tree.winfo_pointerxy()
            sw,sh=top.winfo_screenwidth(),top.winfo_screenheight()
            x=max(0,min(pointer_x+16,sw-top.winfo_reqwidth()-8))
            y=max(0,min(pointer_y+20,sh-top.winfo_reqheight()-8))
            top.geometry(f'+{x}+{y}')
            top.deiconify()
            self._popup=top
        except tk.TclError:self.hide()


def add_tree_tips(tree):
    """Attach once per table; underlying ttk column separators stay draggable."""
    existing=getattr(tree,'_coincat_cell_tips',None)
    if existing is None:
        existing=TreeCellTips(tree)
        tree._coincat_cell_tips=existing
    return existing
