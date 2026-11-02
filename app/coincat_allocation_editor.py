"""Local RAM-only allocation worksheet. Never writes a setting or ledger."""
import time
from decimal import localcontext, Inexact
import tkinter as tk
from tkinter import ttk

from coincat_working_allocation import (AllocationRow, OwnerAuthorization,
    allocation_keys, assess_allocation, quantity)


class WorkingAllocationEditor(ttk.Frame):
    def __init__(self,parent,on_change=lambda:None,clock=None):
        super().__init__(parent)
        self.on_change=on_change;self.draft={};self.authorization=None
        self.defaults_enabled=True;self.customized=set();self.explicit_working=set();self.selected_asset=None
        self.dirty_fields=set();self.loading_fields=False
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
            'Working starts at full AVAILABLE; manual/protected carve-outs reduce it. '
            'Existing exclusions take precedence. Draft authorization does not enable trading.',
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
        for column,name in enumerate(('working','manual','protected')):
            ttk.Label(entries,text=name.title()+' native units').grid(row=0,column=column,sticky='w')
            value=tk.StringVar(value='0');self.fields[name]=value
            ttk.Entry(entries,textvariable=value,width=24).grid(row=1,column=column,sticky='ew',padx=(0,8))
            entries.columnconfigure(column,weight=1)
            value.trace_add('write',lambda *args,field=name:self._edited(field))
        ttk.Button(entries,text='Apply selected draft',command=self.apply_selected).grid(row=1,column=3,sticky='w')
        actions=ttk.Frame(body);actions.pack(fill='x',pady=(5,0))
        self.confirmed=tk.BooleanVar(value=False)
        ttk.Checkbutton(actions,text='I authorize the exact working amounts in this draft',
            variable=self.confirmed,command=self._confirmation_changed).pack(side='left')
        ttk.Button(actions,text='Record draft authorization',command=self.authorize).pack(side='left',padx=6)
        ttk.Button(actions,text='Clear draft',command=self.clear).pack(side='left')
        ttk.Button(actions,text='Full AVAILABLE draft',command=self.reset_full).pack(side='left',padx=6)
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
        self._seed_defaults()
        if (self.dirty_fields and 'working' not in self.dirty_fields and
                self.selected_asset not in self.explicit_working):self._remaining_working()
        self.render()

    def _seed_defaults(self):
        for asset,available in self.balances.items():
            if asset in self.excluded:
                self.draft.pop(asset,None);self.customized.discard(asset);self.explicit_working.discard(asset)
            elif self.defaults_enabled and asset not in self.customized:
                self.draft[asset]=AllocationRow(asset,working=quantity(available))

    def render(self,reload_fields=False):
        value=self.assessment()
        # Update rows in place. Deleting/reselecting every scan queues a
        # TreeviewSelect event that used to overwrite in-progress entry text.
        rows=value['rows']
        if not rows:
            rows=[]
            for asset,raw in sorted(self.balances.items()):
                available=quantity(raw);proposal=self.draft.get(asset,AllocationRow(asset))
                excluded=available if asset in self.excluded else 0
                remainder=available-proposal.working-proposal.manual-proposal.protected-excluded
                rows.append(dict(asset=asset,available=available,working=proposal.working,
                    manual=proposal.manual,protected=proposal.protected,excluded=excluded,
                    unassigned=remainder if remainder>=0 else 'OVERALLOCATED'))
        assets={row['asset'] for row in rows}
        for item in self.tree.get_children():
            if item not in assets:self.tree.delete(item)
        for row in rows:
            fields=tuple(str(row[k]) for k in self.tree['columns'])
            if self.tree.exists(row['asset']):self.tree.item(row['asset'],values=fields)
            else:self.tree.insert('','end',iid=row['asset'],values=fields)
        if not self.tree.selection() and rows:self.tree.selection_set(rows[0]['asset'])
        self._select(force=reload_fields)
        if self.dirty_fields:
            self.message.set('Unapplied edits retained. Apply selected draft before recording authorization.');return
        self.message.set(('Exact draft authorization recorded. ' if value['owner_authorized'] else 'Draft is not authorized. ')+
            'Working funds remain ineligible; reconciliation is missing. '+
            ('Draft invalid; edit or clear it. ' if value['state']=='INVALID_DRAFT' else '')+
            'Execution and ETH selection remain blocked.')

    def _select(self,event=None,force=False):
        selected=self.tree.selection()
        if selected and (force or selected[0]!=self.selected_asset):
            self.selected_asset=selected[0]
            row=self.draft.get(selected[0],AllocationRow(selected[0]))
            self.loading_fields=True
            try:
                for name,value in self.fields.items():value.set(str(getattr(row,name)))
            finally:self.loading_fields=False
            self.dirty_fields.clear()

    def _remaining_working(self):
        if self.selected_asset not in self.balances:return
        try:
            with localcontext() as ctx:
                ctx.prec=60;ctx.traps[Inexact]=True
                remaining=(quantity(self.balances[self.selected_asset])-quantity(self.fields['manual'].get())
                           -quantity(self.fields['protected'].get()))
            if remaining<0:return
        except (ValueError,ArithmeticError):return
        self.loading_fields=True
        try:self.fields['working'].set(str(remaining))
        finally:self.loading_fields=False

    def _edited(self,field):
        if self.loading_fields:return
        self.dirty_fields.add(field)
        if (field in ('manual','protected') and 'working' not in self.dirty_fields and
                self.selected_asset not in self.explicit_working):self._remaining_working()
        self.authorization=None;self.confirmed.set(False)
        self.message.set('Unapplied edits retained. Apply selected draft before recording authorization.')
        self.on_change()  # Invalidate queued research even before an edit is applied.

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
        if 'working' in self.dirty_fields:self.explicit_working.add(row.asset)
        self.customized.add(row.asset);self.dirty_fields.clear()
        self.render(reload_fields=True);self.on_change()

    def _confirmation_changed(self):
        # Unchecking revokes authorization; checking alone never grants it.
        if not self.confirmed.get():
            self.authorization=None;self.render();self.on_change()

    def authorize(self):
        if self.dirty_fields:
            self.message.set('Apply selected edits before recording authorization.');return
        value=self.assessment()
        if (not self.confirmed.get() or value['state']=='INVALID_DRAFT' or
                'AVAILABLE_SNAPSHOT_STALE_OR_UNOBSERVED' in value['blockers'] or
                not any(r['working'] for r in value['rows'])):
            self.message.set('A valid working draft, fresh available snapshot and explicit owner checkbox are required.');return
        self.authorization=OwnerAuthorization(value['snapshot_key'],value['draft_key'],True)
        self.render();self.on_change()

    def clear(self):
        self.defaults_enabled=False;self.customized.clear();self.explicit_working.clear();self.dirty_fields.clear()
        self.draft={};self.authorization=None;self.confirmed.set(False)
        self.render(reload_fields=True);self.on_change()

    def reset_full(self):
        self.defaults_enabled=True;self.customized.clear();self.explicit_working.clear();self.dirty_fields.clear()
        self.draft={};self.authorization=None;self.confirmed.set(False)
        self._seed_defaults();self.render(reload_fields=True);self.on_change()
