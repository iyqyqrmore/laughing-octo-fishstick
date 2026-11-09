"""Private construction aid. This window cannot submit, authorize or replay an order."""
from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from coincat_beta_store import BetaBlocked
from coincat_maker_shadow import free
from coincat_intelligent_policy import seed
from coincat_multi_policy import MultiConfig
from coincat_order_explanation import explain,minimum_budget,reported_manual_example
from coincat_ui_tables import table,native as native_text,number
from coincat_watchlist import WATCH_PAIRS
from coincat_theme import MUTED
from coincat_version import DISPLAY

def native(value):
    text=native_text(value)
    return text.rstrip('0').rstrip('.') if '.' in text else text

class ExplanationWindow:
    def __init__(self,app):
        self.app=app;self.root=tk.Toplevel(app.root);self.root.title(DISPLAY+' · Private order construction · No order actions');self.root.geometry('1220x820');self.root.minsize(1040,740)
        shell=ttk.Frame(self.root,padding=12);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=DISPLAY+' · Order construction and decision explanation',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='Preview only · no create/cancel/live authorization · source budget includes the modeled entry fee for BUY',foreground='#eab86b').pack(anchor='w',pady=5)
        fields=ttk.Frame(shell);fields.pack(fill='x',pady=7)
        self.pair=tk.StringVar(value=app.market.get());self.side=tk.StringVar(value='BUY');self.budget=tk.StringVar();self.price=tk.StringVar()
        for column,(label,var,values,width) in enumerate((('Native market',self.pair,WATCH_PAIRS,14),('Side',self.side,('BUY','SELL'),8))):
            ttk.Label(fields,text=label).grid(row=0,column=column*2,sticky='w',padx=4);ttk.Combobox(fields,textvariable=var,values=values,width=width,state='readonly').grid(row=0,column=column*2+1,sticky='w')
        self.units=tk.StringVar();ttk.Label(fields,textvariable=self.units).grid(row=0,column=4,sticky='w',padx=8)
        self.budget_entry=ttk.Entry(fields,textvariable=self.budget,width=18);self.budget_entry.grid(row=0,column=5,sticky='w')
        ttk.Label(fields,text='Optional native limit').grid(row=1,column=0,sticky='w',padx=4,pady=6)
        self.price_entry=ttk.Entry(fields,textvariable=self.price,width=18);self.price_entry.grid(row=1,column=1,sticky='w')
        controls=ttk.Frame(shell);controls.pack(fill='x',pady=5)
        ttk.Button(controls,text='Use native minimum',command=self.use_minimum).pack(side='left')
        ttk.Button(controls,text='Explain current candidate',command=self.preview).pack(side='left',padx=5)
        ttk.Button(controls,text='Reported November 9 example',command=self.historical).pack(side='left',padx=5)
        self.answers=tk.StringVar();ttk.Label(shell,textvariable=self.answers,wraplength=1160,justify='left').pack(anchor='w',pady=8)
        self.construction=tk.StringVar();ttk.Label(shell,textvariable=self.construction,wraplength=1160,justify='left').pack(anchor='w',pady=8)
        self.table=table(shell,(('h','Horizon',100),('state','Economics',100),('mark','Projected marked USD',180),('forecast','Expected incremental USD',190),('risk','After risk / uncertainty USD',210),('reason','Exact reason',350)),6)
        self.footer=ttk.Label(shell,text='Paper wallet available excludes local reservations. Native validity is not exchange acceptance, economic qualification, realistic fill evidence or real permission. Detailed values stay local.',wraplength=1160,style='Muted.TLabel');self.footer.pack(side='bottom',before=self.table.master,anchor='w',pady=5)
        self.pair.trace_add('write',lambda *args:self.update_units());self.side.trace_add('write',lambda *args:self.update_units());self.update_units()
        self.answers.set('A. Native validity UNKNOWN · B. Economics UNKNOWN · C. Maker fill probability UNKNOWN · D. SHADOW ONLY')
        self.root.bind('<Configure>',self.resize,add='+')
    def resize(self,event):
        if event.widget is self.root:
            for widget in self.root.winfo_children()[0].winfo_children():
                if isinstance(widget,ttk.Label) and int(widget.cget('wraplength') or 0):widget.configure(wraplength=max(500,event.width-40))
    def update_units(self):
        base,quote=self.pair.get().split('-');self.units.set(('All-in '+quote if self.side.get()=='BUY' else base)+' source budget');self.price.set('')
    def context(self):
        frame=self.app.latest_shadow_frame
        if frame is None or not 0<=self.app.clock()-frame['at']<=30:raise BetaBlocked('FRESH_NATIVE_OBSERVATION_REQUIRED')
        engine=self.app.current_shadow();s=engine.state()
        if s is None:
            config=MultiConfig();wallet=seed(frame,self.app.clock(),config)['wallet'];available=deepcopy(wallet);original=deepcopy(wallet)
        else:wallet=s['wallet'];available=free(s);original=s['original'];config=MultiConfig(**{k:v for k,v in s['config'].items() if k in MultiConfig.__dataclass_fields__})
        return frame,wallet,available,original,config
    def use_minimum(self):
        try:frame,*_=self.context();self.budget.set(native(minimum_budget(frame,self.pair.get(),self.side.get())));self.price.set('')
        except (ValueError,TypeError,KeyError,ArithmeticError):self.answers.set('Fresh native rules, maker fees and account/paper inventory are needed before computing a minimum.')
    def preview(self):
        try:
            frame,wallet,available,original,config=self.context()
            result=explain(frame,wallet,available,original,self.pair.get(),self.side.get(),self.budget.get(),price=self.price.get() or None,config=config)
        except (ValueError,TypeError,KeyError,ArithmeticError):self.answers.set('Preview unavailable: refresh native data and enter a positive source budget. No order action occurred.');return
        self.answers.set('A. '+result['validity']['state']+' · '+result['validity']['reason']+'\nB. '+result['economics']['state']+' · '+result['economics']['reason']+
            '\nC. '+result['execution']['state']+' · '+result['execution']['reason']+'\nD. SHADOW ONLY · automatic real authority NONE; manual trading is a separate explicit-click route.')
        c=result['construction']
        self.construction.set('' if c is None else 'Exchange '+native(c['source_debit'])+' '+c['source']+' for approximately '+native(c['estimated_destination'])+' '+c['target']+
            '\n'+c['ticket']['side']+' '+c['ticket']['pair']+' · base quantity '+native(c['base_quantity'])+' · native limit '+native(c['ticket']['price'])+' '+c['ticket']['pair'].split('-')[1]+'/'+c['ticket']['pair'].split('-')[0]+
            '\nOwn modeled commission '+native(c['estimated_commission'])+' '+c['fee_currency']+
            '\nAuthenticated maker rate; quote-currency simulation assumption, not exact settled fee evidence.'+
            '\nAvailable source '+native(c['available_source'])+' '+c['source']+' · unused requested budget '+native(c['unused_budget'])+
            '\nBase increment '+native(c['base_increment'])+' · price increment '+native(c['price_increment'])+
            '\nBase minimum '+native(c['base_minimum'])+' · quote minimum '+native(c['quote_minimum']))
        for key in self.table.get_children():self.table.delete(key)
        for name,row in result['horizons'].items():self.table.insert('','end',values=(name,row['state'],number(row.get('projected_marked_change_usd')),number(row.get('expected_incremental_usd')),number(row.get('projected_advantage_usd')),row['reason']))
    def historical(self):
        row=reported_manual_example();self.answers.set('A. '+row['validity']+'\nB. '+row['economics']+'\nC. '+row['execution']+'\nD. '+row['authorization'])
        self.construction.set('Reported BUY ETH-BTC · '+native(row['quantity'])+' ETH at '+native(row['limit_price'])+' BTC/ETH'+
            '\nComputed gross from reported numbers '+native(row['computed_gross_btc'])+' BTC · conditional 0.50% estimate '+native(row['modeled_fee_btc'])+' BTC'+
            '\nActual unrounded commission and exact settlement UNKNOWN. The displayed rounded fee is not an API receipt.'+
            '\nNo current or later quote is used to reconstruct the historical decision. Original screen timezone UNKNOWN; no original data is invented.')
        for key in self.table.get_children():self.table.delete(key)
