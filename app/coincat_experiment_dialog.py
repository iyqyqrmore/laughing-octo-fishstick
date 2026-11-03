"""Manual preregistration controls. Never an order, signal fitter or seed policy."""
from decimal import Decimal as D
from datetime import datetime,timezone
import tkinter as tk
from tkinter import ttk

from coincat_hover import Hover,help_tree
from coincat_watchlist import WATCH_ASSETS


class ExperimentDialog:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root)
        self.window.title('Register hypothetical experiment · No trading')
        self.window.transient(app.root);self.window.geometry('650x680');self.window.minsize(620,640)
        body=ttk.Frame(self.window,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Prospective ETH research',style='Title.TLabel').pack(anchor='w')
        ttk.Label(body,text='Registers an independent conditional comparison before the outcome is known. '
            'No account funds move and no paper order is executed.',wraplength=600).pack(anchor='w',pady=8)
        self.values={name:tk.StringVar(value=value) for name,value in (
            ('source','ETH'),('target',''),('initial_eth',''),('horizon_hours',''),
            ('signal_id',''),('fill_state','UNVERIFIED'))}
        self.ack=tk.BooleanVar(value=False)
        form=ttk.Frame(body);form.pack(fill='x');form.columnconfigure(1,weight=1)
        for index,(name,label,choices) in enumerate((
            ('source','Hypothetical source',WATCH_ASSETS),('target','Proposed next asset',WATCH_ASSETS),
            ('initial_eth','Initial ETH what-if slice',None),('horizon_hours','Fixed comparison horizon · hours',None),
            ('signal_id','Your signal ID · A–Z / 0–9 / underscore',None),
            ('fill_state','Entry assumption',('UNVERIFIED','SIMULATED_ASSUMPTION','NO_FILL','PARTIAL_OR_UNCERTAIN_FILL')))):
            ttk.Label(form,text=label).grid(row=index,column=0,sticky='w',padx=(0,10),pady=6)
            widget=(ttk.Entry(form,textvariable=self.values[name]) if choices is None else
                    ttk.Combobox(form,textvariable=self.values[name],values=choices,state='readonly'))
            widget.grid(row=index,column=1,sticky='ew',pady=6)
        ttk.Label(body,text='Hypothesis: the next asset will outperform HOLD of the source at this horizon. '
            'Confidence is unvalidated. A non-ETH source assumes an explicit hypothetical conversion '
            'from the ETH slice above; it does not claim you hold that coin. '
            'Costs use the applied taker-stress setting. Cases are independent comparisons '
            'and cannot be added as concurrent allocations.',wraplength=600).pack(anchor='w',pady=10)
        check=ttk.Checkbutton(body,variable=self.ack,text='I explicitly confirm these conditional assumptions.')
        check.pack(anchor='w')
        self.error=tk.StringVar()
        ttk.Label(body,textvariable=self.error,wraplength=600,foreground='#f06475').pack(anchor='w',pady=6)
        button=ttk.Button(body,text='Register experiment',command=self.register)
        button.pack(anchor='e')
        Hover(button,'Save the frozen signal, native rules, quotes, costs and horizon to the local private research journal. '
            'Existing scans observe it; STOP pauses observation. Unknown costs or missing depth remain UNKNOWN. '
            'The first observation at the horizon is final; no best-price exit is selected. No predictor or trade is started.')
        help_tree(body,'Manual conditional research only. Enter your own hypothetical size, horizon and signal ID; '
            'there are no recommended trading allocations or forecast settings. Data stays in the local research journal.')

    def register(self):
        try:
            hours=D(self.values['horizon_hours'].get())
            seconds=hours*3600
            if not hours.is_finite() or seconds!=seconds.to_integral_value() or not 1<=seconds<=259200:
                raise ValueError('INVALID_HORIZON')
            self.app._register_experiment(source=self.values['source'].get(),target=self.values['target'].get(),
                initial_eth=D(self.values['initial_eth'].get()),horizon_s=int(seconds),
                signal_id=self.values['signal_id'].get(),fill_state=self.values['fill_state'].get(),
                explicit_assumption=self.ack.get())
        except Exception:
            # No raw database/API errors, account identifiers or private paths.
            self.error.set('Not registered. Check the explicit assumptions, size, horizon, signal ID and fresh eligible quotes; wait for a completed scan.')
            return
        self.window.destroy()


def show_journal(app):
    """Bounded manual read; works while STOPPED, no polling or network."""
    window=tk.Toplevel(app.root);window.title('Prospective experiments · Local research only')
    window.transient(app.root);window.geometry('1040x460')
    body=ttk.Frame(window,padding=12);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Independent conditional comparisons · No paper trades · NO DEMONSTRATED EDGE',wraplength=980).pack(anchor='w')
    columns=('Signal','Direction','Horizon UTC','State','Conditional ΔETH vs source HOLD')
    tree=ttk.Treeview(body,columns=columns,show='headings',height=9)
    for name,width in zip(columns,(180,130,175,210,265)):
        tree.heading(name,text=name);tree.column(name,width=width,minwidth=90)
    tree.pack(fill='both',expand=True,pady=8)
    detail=tk.StringVar(value='Select a case for holding time and uncertainty. These values remain local.')
    ttk.Label(body,textvariable=detail,wraplength=980).pack(anchor='w')
    rows={}
    def selected(event=None):
        choice=tree.selection()
        if choice and choice[0] in rows:
            row=rows[choice[0]]
            detail.set('Observed holding time '+str(round(row['observed_holding_s']))+' s · '+
                (', '.join(row['reasons']) or 'No recorded pricing blocker; fill assumptions remain conditional.')+
                ' · The horizon closes the comparison, not a position.')
    tree.bind('<<TreeviewSelect>>',selected)
    def refresh():
        try:
            if app.journal is None:raise ValueError()
            current=app.journal.list_cases()
        except Exception:
            detail.set('Journal unavailable. No current result is established; retained records are unchanged.');return
        rows.clear();rows.update({r['reference']:r for r in current})
        for item in tree.get_children():tree.delete(item)
        for row in current:
            stamp=datetime.fromtimestamp(row['horizon_at'],timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            tree.insert('','end',iid=row['reference'],values=(row['signal'],row['source']+' → '+row['target'],
                stamp,row['state'],'UNKNOWN' if row['relative_eth'] is None else str(row['relative_eth'])))
    ttk.Button(body,text='Refresh local view',command=refresh).pack(anchor='e',pady=6)
    help_tree(body,'Local prospective journal only. Signal names and hypothetical native results are omitted from public diagnostics and monitoring. '
        'The first horizon observation is final. Missing or unsupported costs stay UNKNOWN; no paper order or forced sale occurs.')
    refresh()
    return window
