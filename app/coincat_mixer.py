"""Compact manual research faders. Exact text values, RAM only."""
from dataclasses import dataclass
from decimal import Decimal as D, ROUND_HALF_UP
import tkinter as tk
from tkinter import ttk
from coincat_v80_immediate import exact
from coincat_hover import Hover


@dataclass(frozen=True)
class Control:
    key: str
    label: str
    unit: str
    default: D
    minimum: D
    maximum: D
    step: D
    explanation: str


CONTROLS=(
    Control('amount_eth','Model ETH','ETH',D(0),D(0),D(10),D('.001'),
        'Defaults to the full available ETH working proposal after connection, excluding manual/protected/excluded funds. '
        'Must fit the ETH working draft after manual/protected carve-outs and exclusions. Each scenario uses the same allocation independently; '
        'results are never summed as simultaneous allocations. Unreconciled research only, never executable funding.'),
    Control('entry_offset_bps','Entry offset','bps from best resting price',D(0),D(0),D(50),D(1),
        'Hypothetical post-only entry away from the market: BUY below bid, or SELL above ask for an inverse ETH-base market. '
        '0 bps uses best bid for BUY or best ask for SELL; 10 bps is 0.10% farther away. A larger offset may reduce fill likelihood. '
        'A price at or through the opposite quote is rejected. Research only; no order is placed or repriced.'),
    Control('target_pct','ETH target','net ETH % scenario',D('.25'),D(0),D(5),D('.05'),
        'Requested hypothetical ETH improvement versus HOLD of exactly the same starting ETH, after both estimated maker fees and rounding. '
        'The calculator solves an exit limit target; it does not forecast that price, promise a fill, or optimize this control.'),
    Control('expiry_hours','Wait limit','hours',D(24),D(1),D(72),D(1),
        'Observation horizon for each frozen hypothetical setup. Expiry means cancelled/expired research, not a real cancellation. '
        'A real holding could remain exposed for longer or lose its entire value; unfilled and uncertain outcomes are retained as such.'),
    Control('scan_interval_s','Scan interval','seconds after each pass',D(5),D(5),D(60),D(1),
        'Manual observation cadence. At most three selected direct books use the existing collector, six-research/16-total ceilings, '
        '0.2-second spacing and server backoff. Quote age 30s, spread 0.25% and single-decision span 12s cannot be relaxed here.'),
    Control('taker_slippage_bps','Taker stress','bps per benchmark leg',D(15),D(0),D(50),D(1),
        'Explicit assumed slippage for the immediate taker benchmark only, in addition to actual bid/ask and estimated taker fee. '
        'Resting maker hypotheses use exact limit prices and maker fees; this stress is not charged to maker orders. Depth remains unverified.'),
)


class Fader(ttk.Frame):
    def __init__(self,parent,spec,on_change):
        super().__init__(parent,padding=5)
        self.spec=spec;self.on_change=on_change;self.value=spec.default;self._syncing=True
        self.default=spec.default;self.maximum=spec.maximum;self.customized=False
        self.text=tk.StringVar(value=str(self.value));self.error=tk.StringVar();self.marker=tk.StringVar()
        title=ttk.Label(self,text=spec.label,font=('Segoe UI',9,'bold'));title.pack()
        self.scale=ttk.Scale(self,from_=float(spec.maximum),to=float(spec.minimum),orient='vertical',
            length=72,command=self._slide,takefocus=True);self.scale.pack(pady=4)
        self.entry=ttk.Entry(self,textvariable=self.text,width=12,justify='center');self.entry.pack()
        units=ttk.Frame(self,width=140,height=40);units.pack();units.pack_propagate(False)
        unit=ttk.Label(units,text=spec.unit,wraplength=135,anchor='center',justify='center');unit.pack(expand=True,fill='x')
        self.entry.bind('<Return>',self._entered);self.entry.bind('<FocusOut>',self._entered)
        for key,direction in (('<Up>',1),('<Right>',1),('<Down>',-1),('<Left>',-1)):
            self.scale.bind(key,lambda event,d=direction:self._step(d))
        self.scale.bind('<Home>',lambda event:self._keyset(spec.minimum))
        self.scale.bind('<End>',lambda event:self._keyset(self.maximum))
        reset=ttk.Button(self,text='Reset',command=self.reset);reset.pack(pady=3)
        self.error_label=ttk.Label(self,textvariable=self.error,foreground='#a34d00',wraplength=135)
        for widget in (title,self.scale,self.entry,unit,reset):
            Hover(widget,lambda:spec.explanation+f' Range {spec.minimum}–{self.maximum}; current default {self.default}. Exact text entries are accepted.')
        self.scale.set(float(self.value));self._syncing=False
        self.text.trace_add('write',self._text_edited)

    def _text_edited(self,*args):
        if not self._syncing:
            self.customized=True;self.on_change()

    def set(self,value,*,user=True):
        value=exact(value)
        if not self.spec.minimum<=value<=self.maximum:raise ValueError('OUT_OF_RANGE')
        if user:self.customized=True
        changed=value!=self.value;self.value=value;self._syncing=True
        try:self.scale.set(float(value));self.text.set(str(value))
        finally:self._syncing=False
        self.error.set('');self.error_label.pack_forget()
        if changed:self.on_change()

    def update_default(self,value):
        value=exact(value)
        self.default=value;self.maximum=max(self.spec.maximum,value,self.value)
        self._syncing=True
        try:self.scale.configure(from_=float(self.maximum))
        finally:self._syncing=False
        if not self.customized:self.set(value,user=False)

    def reset(self):
        self.customized=False;self.set(self.default,user=False)

    def _slide(self,raw):
        if self._syncing:return
        n=(D(raw)/self.spec.step).to_integral_value(rounding=ROUND_HALF_UP)*self.spec.step
        self.set(max(self.spec.minimum,min(self.maximum,n)))

    def _entered(self,event=None):
        try:self.set(self.text.get(),user=self.customized or exact(self.text.get())!=self.value)
        except (ValueError,ArithmeticError):
            self.error.set('Invalid value; previous kept.');self.error_label.pack()
        return 'break' if event and event.type==tk.EventType.KeyPress else None

    def _step(self,direction):
        self.set(max(self.spec.minimum,min(self.maximum,self.value+self.spec.step*direction)));return 'break'

    def _keyset(self,value):
        self.set(value);return 'break'


class ResearchMixer(ttk.LabelFrame):
    def __init__(self,parent,on_change):
        super().__init__(parent,text='Manual research mixer',padding=4)
        self.controls={};self._ready=False
        for index,spec in enumerate(CONTROLS):
            control=Fader(self,spec,lambda:on_change() if self._ready else None)
            control.grid(row=0,column=index,sticky='nsew');self.columnconfigure(index,weight=1,uniform='faders')
            self.controls[spec.key]=control
        self._ready=True

    def values(self):return {key:control.value for key,control in self.controls.items()}

    def commit_entries(self):
        for control in self.controls.values():
            control.set(control.text.get(),user=False)
