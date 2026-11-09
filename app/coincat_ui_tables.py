"""Shared presentation only. No strategy or financial calculations."""
from tkinter import ttk
def number(value):return 'UNKNOWN' if value is None else '0' if value==0 else format(value,'.12g')
def native(value):return 'UNKNOWN' if value is None else format(value,'f')
def table(parent,columns,height):
    frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=5);frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    tree=ttk.Treeview(frame,columns=tuple(k for k,_,_ in columns),show='headings',height=height)
    for key,title,width in columns:tree.heading(key,text=title);tree.column(key,width=width,minwidth=65)
    tree.grid(row=0,column=0,sticky='nsew')
    vertical=ttk.Scrollbar(frame,command=tree.yview);vertical.grid(row=0,column=1,sticky='ns')
    horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.grid(row=1,column=0,sticky='ew')
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set);return tree
