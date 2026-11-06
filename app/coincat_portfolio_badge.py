"""Compact private header value and a live-updating, bounded holdings popup."""
from tkinter import ttk
from coincat_hover import Hover
from coincat_portfolio_display import presentation
from coincat_theme import TEXT,MUTED

class HoldingsHover(Hover):
    shown_text=None
    def show(self):
        super().show();self.shown_text=self.text() if callable(self.text) else self.text
    def refresh_if_open(self):
        text=self.text() if callable(self.text) else self.text
        if self.window is None or text==self.shown_text:return
        if self.body is not None:
            position=self.body.yview()[0];self.body.configure(state='normal');self.body.delete('1.0','end')
            self.body.insert('1.0',text);self.body.configure(state='disabled');self.body.yview_moveto(position);self.shown_text=text
        else:self.show()

class PortfolioBadge(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent);self.hover_text='Connect to refresh your portfolio.';self.last_view=None
        self.title=ttk.Label(self,text='Total portfolio · USD',style='Muted.TLabel');self.title.pack(anchor='w')
        self.amount=ttk.Label(self,text='—',font=('Segoe UI',18,'bold'),takefocus=True,cursor='hand2');self.amount.pack(anchor='w',pady=(2,0))
        self.caption=ttk.Label(self,text='Connect to refresh',font=('Segoe UI',9),foreground=MUTED);self.caption.pack(anchor='w')
        self.hovers=[HoldingsHover(w,lambda:self.hover_text) for w in (self.title,self.amount,self.caption)]
    def render(self,snapshot,now,connected):
        view=presentation(snapshot,now,connected)
        if view==self.last_view:return
        self.last_view=view;self.hover_text=view['hover'];self.title.configure(text=view['title'])
        self.amount.configure(text=view['amount'],foreground=MUTED if view['stale'] else TEXT)
        self.caption.configure(text=view['caption'],foreground='#eab86b' if view['stale'] and snapshot else MUTED)
        for hover in self.hovers:hover.refresh_if_open()
    def close(self):
        for hover in self.hovers:hover.hide()
