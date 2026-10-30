"""Local RAM-only allocation worksheet. Never writes a setting or ledger."""
import time
import tkinter as tk
from tkinter import ttk

from coincat_working_allocation import (AllocationRow, OwnerAuthorization,
    allocation_keys, assess_allocation, quantity)


class WorkingAllocationEditor(ttk.Frame):
    def __init__(self,parent,on_change=lambda:None,clock=None):
        super().__init__(parent)
        self.on_change=on_change;self.draft={};self.authorization=None
        self.clock=time.time if clock is None else clock
        self.balances={};self.excluded=();self.balances_at=None;self.now=0
        self.message=tk.StringVar(value='Unassigned funds are ineligible. No automatic trading is available.')
        self.canvas=tk.Canvas(self,highlightthickness=0,borderwidth=0,takefocus=True)
        scrollbar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        body=ttk.Frame(self.canvas,padding=6)
        window=self.canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda event:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda event:self.canvas.itemconfigure(window,width=event.width))
        self.canvas.bind('<Next>',lambda event:self.canvas.yview_scroll(1,'pages'))
        self.canvas.bind('<Prior>',lambda event:self.canvas.yview_scroll(-1,'pages'))
        ttk.Label(body,text='Local allocation draft — lost on restart. Protected amounts are ETH only. '
            'Existing exclusions take precedence. Draft authorization does not establish settlement or enable trading.',
            wraplength=990).pack(anchor='w')
        tree_frame=ttk.Frame(body);tree_frame.pack(fill='both',expand=True,pady=5)
        self.tree=ttk.Treeview(tree_frame,columns=('asset','available','working','manual','protected','excluded','unassigned'),
            show='headings',height=5,selectmode='browse')
        for name in self.tree['columns']:
            self.tree.heading(name,text=name.title());self.tree.column(name,width=125,stretch=True)
        tree_scroll=ttk.Scrollbar(tree_frame,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side='right',fill='y');self.tree.pack(side='left',fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self._select)
        entries=ttk.Frame(body);entries.pack(fill='x')
        self.fields={}
        for name in ('working','manual','protected'):
            ttk.Label(entries,text=name.title()+' native units').pack(side='left')
            value=tk.StringVar(value='0');self.fields[name]=value
            ttk.Entry(entries,textvariable=value,width=16).pack(side='left',padx=(3,8))
        ttk.Button(entries,text='Apply selected draft',command=self.apply_selected).pack(side='left')
        actions=ttk.Frame(body);actions.pack(fill='x',pady=(5,0))
        self.confirmed=tk.BooleanVar(value=False)
        ttk.Checkbutton(actions,text='I authorize the exact working amounts in this draft',
            variable=self.confirmed,command=self._confirmation_changed).pack(side='left')
        ttk.Button(actions,text='Record draft authorization',command=self.authorize).pack(side='left',padx=6)
        ttk.Button(actions,text='Clear draft',command=self.clear).pack(side='left')
        ttk.Label(body,textvariable=self.message,wraplength=970).pack(anchor='w',pady=(4,0))
        def wheel(event):
            steps=(-1 if event.num==4 else 1 if event.num==5 else -int(event.delta/120))
            if steps:
                (self.tree if event.widget is self.tree else self.canvas).yview_scroll(steps,'units')
            return 'break'
        def bind_wheel(widget):
            for name in ('<MouseWheel>','<Button-4>','<Button-5>'):widget.bind(name,wheel,add='+')
            for child in widget.winfo_children():bind_wheel(child)
        bind_wheel(self)

    def parameters(self):
        return {'allocation_draft':tuple(self.draft[a] for a in sorted(self.draft)),
                'allocation_authorization':self.authorization}

    def assessment(self):
        return assess_allocation(balances=self.balances,balances_at=self.balances_at,now=self.clock(),
            excluded=self.excluded,draft=tuple(self.draft.values()),authorization=self.authorization)

    def snapshot(self,balances,balances_at,now,excluded=()):
        old=allocation_keys(self.balances,(),self.excluded)[0]
        new=allocation_keys(balances,(),excluded)[0]
        self.balances=dict(balances);self.balances_at=balances_at;self.now=now;self.excluded=tuple(excluded)
        if old!=new:
            self.authorization=None;self.confirmed.set(False)
        self.render()

    def render(self):
        selected=self.tree.selection()
        for item in self.tree.get_children():self.tree.delete(item)
        value=self.assessment()
        for row in value['rows']:
            self.tree.insert('','end',iid=row['asset'],values=tuple(str(row[k]) for k in self.tree['columns']))
        if selected and self.tree.exists(selected[0]):self.tree.selection_set(selected[0])
        self.message.set(('Exact draft authorization recorded. ' if value['owner_authorized'] else 'Draft is not authorized. ')+
            'Working funds remain ineligible: verified settlement and external-flow reconciliation are unavailable. '+
            ('Draft invalid; edit or clear it. ' if value['state']=='INVALID_DRAFT' else '')+
            'Real execution and ETH-profit selection remain blocked.')

    def _select(self,event=None):
        selected=self.tree.selection()
        if selected:
            row=self.draft.get(selected[0],AllocationRow(selected[0]))
            for name,value in self.fields.items():value.set(str(getattr(row,name)))

    def apply_selected(self):
        selected=self.tree.selection()
        if not selected:
            self.message.set('Select an asset before editing its allocation.');return
        try:
            row=AllocationRow(selected[0],*(quantity(self.fields[n].get()) for n in self.fields))
            trial=dict(self.draft);trial[row.asset]=row
            value=assess_allocation(balances=self.balances,balances_at=self.balances_at,now=self.clock(),
                excluded=self.excluded,draft=tuple(trial.values()))
            if value['state']=='INVALID_DRAFT':raise ValueError()
        except (ValueError,ArithmeticError):
            self.message.set('Invalid allocation. Use exact nonnegative native amounts within AVAILABLE; '
                'only ETH can be protected, and excluded assets cannot be reassigned. Previous draft retained.');return
        self.draft=trial;self.authorization=None;self.confirmed.set(False)
        self.render();self.on_change()

    def _confirmation_changed(self):
        # Unchecking revokes authorization; checking alone never grants it.
        if not self.confirmed.get():
            self.authorization=None;self.render();self.on_change()

    def authorize(self):
        value=self.assessment()
        if (not self.confirmed.get() or value['state']=='INVALID_DRAFT' or
                'AVAILABLE_SNAPSHOT_STALE_OR_UNOBSERVED' in value['blockers'] or
                not any(r['working'] for r in value['rows'])):
            self.message.set('A valid working draft, fresh available snapshot and explicit owner checkbox are required.');return
        self.authorization=OwnerAuthorization(value['snapshot_key'],value['draft_key'],True)
        self.render();self.on_change()

    def clear(self):
        self.draft={};self.authorization=None;self.confirmed.set(False)
        self.render();self.on_change()
