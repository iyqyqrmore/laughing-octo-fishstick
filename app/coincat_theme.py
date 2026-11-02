"""Dark spot-workspace palette, using the existing standard Tk controls."""
from tkinter import ttk

BG='#0b0e12';PANEL='#141820';EDGE='#29303a';TEXT='#edf0f4';MUTED='#9aa5b5'
BLUE='#4b83ff';GREEN='#28b88a';RED='#f06475'


def apply_theme(root):
    style=ttk.Style(root);style.theme_use('clam');root.configure(background=BG)
    style.configure('.',background=PANEL,foreground=TEXT,font=('Segoe UI',10),bordercolor=EDGE,
        lightcolor=EDGE,darkcolor=EDGE,troughcolor=BG,selectbackground='#263b60',selectforeground=TEXT)
    style.configure('TFrame',background=BG)
    style.configure('Panel.TFrame',background=PANEL)
    style.configure('TLabel',background=BG)
    style.configure('Muted.TLabel',foreground=MUTED)
    style.configure('Title.TLabel',font=('Segoe UI',16,'bold'))
    style.configure('Metric.TLabel',font=('Segoe UI',13,'bold'))
    style.configure('TButton',padding=(10,6),background='#242a34',foreground=TEXT)
    style.map('TButton',background=[('active','#343e4d'),('disabled','#1a2028')],foreground=[('disabled',MUTED)])
    style.configure('Accent.TButton',background=BLUE)
    style.map('Accent.TButton',background=[('active','#6595ff')])
    style.configure('Stop.TButton',foreground=RED)
    style.configure('TEntry',fieldbackground='#1a2029',foreground=TEXT,insertcolor=TEXT)
    style.configure('TCombobox',fieldbackground='#1a2029',foreground=TEXT,arrowcolor=MUTED,padding=3)
    style.map('TCombobox',fieldbackground=[('readonly','#1a2029')],foreground=[('readonly',TEXT)],selectbackground=[('readonly','#1a2029')])
    style.configure('TCheckbutton',background=BG,padding=3)
    style.map('TCheckbutton',background=[('active',BG)])
    style.configure('TLabelframe',background=BG,bordercolor=EDGE)
    style.configure('TLabelframe.Label',background=BG,foreground=TEXT)
    style.configure('TNotebook',background=BG,borderwidth=0)
    style.configure('TNotebook.Tab',background=PANEL,foreground=MUTED,padding=(12,7))
    style.map('TNotebook.Tab',background=[('selected','#24314a')],foreground=[('selected',TEXT)])
    style.configure('Treeview',background=BG,fieldbackground=BG,foreground=TEXT,rowheight=27,bordercolor=EDGE)
    style.configure('Treeview.Heading',background=PANEL,foreground=MUTED,padding=(4,6))
    style.map('Treeview',background=[('selected','#253b5e')],foreground=[('selected',TEXT)])
    root.option_add('*TCombobox*Listbox.background','#1a2029')
    root.option_add('*TCombobox*Listbox.foreground',TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground','#253b5e')
