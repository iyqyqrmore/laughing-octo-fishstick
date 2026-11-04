"""Deliberate private read-only imports, isolated from trading and funding."""
import json
import tkinter as tk
from tkinter import ttk,filedialog

from coincat_hover import Hover


class ManualTradePanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=8);self.app=app
        self.order_id=tk.StringVar();self.window_hours=tk.StringVar(value='24')
        self.status=tk.StringVar(value='No import running. Records stay local; no paper funding or tax-ledger writes.')
        ttk.Label(self,text='Manual Trade Lab · read-only Coinbase history',style='Metric.TLabel').pack(anchor='w')
        ttk.Label(self,text='Exact native fill arithmetic requires reported fee currencies and complete fills. Screenshots alone cannot prove settlement.\n'
            'Imports are observations, not CoinCat bot fills. A view-only key is sufficient for accessible history.',wraplength=1000).pack(anchor='w',pady=4)
        controls=ttk.Frame(self);controls.pack(fill='x',pady=4)
        ttk.Label(controls,text='Order ID').pack(side='left');entry=ttk.Entry(controls,textvariable=self.order_id,width=39);entry.pack(side='left',padx=4)
        ttk.Button(controls,text='Read this order',command=lambda:app._manual_import(order_id=self.order_id.get())).pack(side='left')
        controls2=ttk.Frame(self);controls2.pack(fill='x',pady=4)
        ttk.Label(controls2,text='Recent UTC hours (1–168)').pack(side='left')
        ttk.Entry(controls2,textvariable=self.window_hours,width=6).pack(side='left',padx=4)
        ttk.Button(controls2,text='Import approved-market history',command=lambda:app._manual_import(hours=self.window_hours.get())).pack(side='left')
        ttk.Button(controls2,text='Cancel import',command=app._cancel_manual_import).pack(side='left',padx=4)
        ttk.Button(controls2,text='Statement math…',command=self.statement).pack(side='left',padx=4)
        ttk.Label(self,textvariable=self.status,wraplength=1000,style='Muted.TLabel').pack(anchor='w',pady=4)
        self.tree=ttk.Treeview(self,columns=('pair','side','status','coverage','native','liquidity'),show='headings',height=5)
        for key,label,width in (('pair','Market',90),('side','Side',55),('status','State',160),('coverage','Coverage',150),('native','Native flow',220),('liquidity','Liquidity',130)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=55)
        self.tree.pack(fill='x',pady=4);self.tree.bind('<<TreeviewSelect>>',self._select)
        body=ttk.Frame(self);body.pack(fill='both',expand=True)
        self.text=tk.Text(body,height=10,wrap='word',state='disabled',background='#0b0f12',foreground='#dce4ef',relief='flat')
        self.text.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(body,command=self.text.yview);scroll.pack(side='right',fill='y');self.text.configure(yscrollcommand=scroll.set)
        Hover(entry,'Paste the complete order identifier locally. Only permission-scoped GET order/fill calls are available to this importer. '
            'Do not send keys or full account records to chat. A UI creation-to-fill duration is not measured exchange acceptance or queue time.')
        self.refresh()

    def statement(self):
        path=filedialog.askopenfilename(title='Read local Coinbase statement; no record import',filetypes=[('CSV','*.csv')])
        if not path:return
        from coincat_statement_math import read_statement
        try:report=read_statement(path)
        except (OSError,ValueError,TypeError,ArithmeticError):
            self.status.set('Statement layout/native notes not recognized. No fee settings or records changed.');return
        self.text.configure(state='normal');self.text.delete('1.0','end')
        self.text.insert('1.0','Owner statement reconstruction only. Implied historical fees never set future maker/taker fees.\n'
            'No account balance reconciliation or authenticated order ID join is established.\n\n'+json.dumps(report,default=str,indent=2))
        self.text.configure(state='disabled')

    def refresh(self):
        self.records=self.app.manual_store.records()
        for item in self.tree.get_children():self.tree.delete(item)
        for index,record in enumerate(self.records):
            r=record['report'];self.tree.insert('','end',iid=str(index),values=tuple(r[k] for k in ('pair','side','state','coverage','native_settlement','liquidity')))

    def _select(self,event=None):
        choice=self.tree.selection()
        if not choice:return
        record=self.records[int(choice[0])];r=record['report'];quote=r['pair'].split('-')[1]
        lines=[r['pair']+' '+r['side']+' · '+r['state'],
            'Source: '+r['source']+'; manual origin requires your attestation.',
            'Base filled: '+str(r['base_qty'])+'; gross '+str(r['gross_quote'])+' '+quote,
            'Reported commission: '+str(r['fee_amount'])+'; reported currencies: '+str(r['fee_currencies']),
            'Native changes: base '+str(r['base_change'])+'; quote '+str(r['quote_change']),
            'Native flow: '+r['native_settlement']+'; account reconciliation: '+r['balance_reconciliation'],
            'Liquidity: '+r['liquidity']+'; post only explicitly reported: '+str(r['post_only']),
            'Creation to first fill: '+str(r['creation_to_first_fill_s'])+'s; accepted resting duration: UNKNOWN',
            'Conclusion: '+r['reason'],
            'Historical observations do not authorize automatic orders or prove profitable predictions.',
            '\nPrivate native evidence (never added to diagnostics):',json.dumps(record,default=str,indent=2)]
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0','\n'.join(lines));self.text.configure(state='disabled')
