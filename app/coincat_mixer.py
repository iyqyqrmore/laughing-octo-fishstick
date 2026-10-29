"""Accessible RAM-only research controls, separate from production settings."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import tkinter as tk
from tkinter import ttk
from coincat_v80_immediate import exact


@dataclass(frozen=True)
class Control:
    key: str
    label: str
    unit: str
    default: Decimal
    minimum: Decimal
    maximum: Decimal
    step: Decimal
    explanation: str


CONTROLS = (
    Control('initial_usd', 'Starting reserve', 'USD equivalent', Decimal(10), Decimal(0), Decimal(100), Decimal(1),
            'Proposed target only. No ETH is bought, reserved or removed from funding.'),
    Control('growth_step_usd', 'Earned growth step', 'USD at fixed reference', Decimal(20), Decimal(1), Decimal(200), Decimal(1),
            'Proposed milestone. Deposits, manual trades and price revaluation are never earned gain.'),
    Control('harvest_usd', 'ETH per milestone', 'USD at fixed reference', Decimal(10), Decimal(0), Decimal(100), Decimal(1),
            'Proposed harvest of already-settled eligible ETH; unknown or insufficient ETH stays pending.'),
    Control('reference_usd', 'Fixed ETH reference', 'USD / ETH; 0 = unset', Decimal(0), Decimal(0), Decimal(100000), Decimal(1),
            'Explicit what-if rate, never auto-filled from market prices. Not a recorded financial benchmark.'),
    Control('slippage_bps', 'Return-leg slippage', 'basis points; assumed', Decimal(15), Decimal(0), Decimal(50), Decimal(1),
            'ETH-return model only. The v91 ranking retains its 15 bps assumption and all hard safeguards.'),
    Control('scan_interval_s', 'Scan interval', 'seconds after each pass', Decimal(5), Decimal(5), Decimal(60), Decimal(1),
            'Manual request cadence only. AI Lab stays at 180 seconds. Does not loosen freshness or synchronization.'),
)


class Fader(ttk.Frame):
    def __init__(self, parent, spec, on_change):
        super().__init__(parent, padding=5)
        self.spec = spec
        self.on_change = on_change
        self.value = spec.default
        self._syncing = False
        self.text = tk.StringVar(value=str(self.value))
        self.marker = tk.StringVar()
        self.error = tk.StringVar()
        self.error_label = None
        ttk.Label(self, text=spec.label, font=('Segoe UI', 9, 'bold')).pack()
        units=ttk.Frame(self,height=36,width=155)
        units.pack();units.pack_propagate(False)
        ttk.Label(units,text=spec.unit,wraplength=150,anchor='center',justify='center').pack(expand=True,fill='x')
        self.scale = ttk.Scale(self, from_=float(spec.maximum), to=float(spec.minimum),
                               orient='vertical', length=76, command=self._slide, takefocus=True)
        self.scale.pack(pady=3)
        self.scale.set(float(self.value))
        self.entry = ttk.Entry(self, textvariable=self.text, width=13, justify='center')
        self.entry.pack()
        self.entry.bind('<Return>', self._entered)
        self.entry.bind('<FocusOut>', self._entered)
        for key, direction in (('<Up>', 1), ('<Right>', 1), ('<Down>', -1), ('<Left>', -1)):
            self.scale.bind(key, lambda event, d=direction: self._step(d))
        self.scale.bind('<Home>', lambda event: self._keyset(spec.minimum))
        self.scale.bind('<End>', lambda event: self._keyset(spec.maximum))
        ttk.Label(self, textvariable=self.marker, wraplength=150).pack(pady=(3, 0))
        ttk.Label(self, text=f'Range {spec.minimum} to {spec.maximum}', wraplength=150).pack()
        ttk.Button(self, text='Reset', command=lambda: self.set(spec.default), takefocus=True).pack(pady=3)
        self.error_label = ttk.Label(self, textvariable=self.error, foreground='#a34d00', wraplength=150)
        self._tip = None
        for widget in (self.scale, self.entry):
            widget.bind('<Enter>', self._show_tip)
            widget.bind('<FocusIn>', self._show_tip)
            widget.bind('<Leave>', self._hide_tip)
            widget.bind('<FocusOut>', self._hide_tip, add='+')
        self._mark()

    def _mark(self):
        self.marker.set(f'Now {self.value} | default {self.spec.default}')

    def set(self, value):
        value = exact(value)
        if not self.spec.minimum <= value <= self.spec.maximum:
            raise ValueError('OUT_OF_RANGE')
        self.value = value
        self._syncing = True
        self.scale.set(float(value))
        self.text.set(str(value))
        self._syncing = False
        self.error.set('')
        if self.error_label is not None:
            self.error_label.pack_forget()
        self._mark()
        self.on_change()

    def _slide(self, raw):
        if self._syncing:
            return
        n = Decimal(raw)
        n = (n/self.spec.step).to_integral_value(rounding=ROUND_HALF_UP)*self.spec.step
        self.set(max(self.spec.minimum, min(self.spec.maximum, n)))

    def _entered(self, event=None):
        try:
            self.set(self.text.get())
        except (ValueError, ArithmeticError):
            self.error.set('Invalid: enter a finite value in range. Previous value retained.')
            self.error_label.pack()
            return 'break'

    def _step(self, direction):
        self.set(max(self.spec.minimum, min(self.spec.maximum, self.value+self.spec.step*direction)))
        return 'break'

    def _keyset(self, value):
        self.set(value)
        return 'break'

    def _show_tip(self, event=None):
        if self._tip is not None:
            return
        self._tip = tk.Toplevel(self)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f'+{self.winfo_rootx()}+{self.winfo_rooty()+25}')
        ttk.Label(self._tip, text=self.spec.explanation, wraplength=280, padding=8).pack()

    def _hide_tip(self, event=None):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class ResearchMixer(ttk.LabelFrame):
    def __init__(self, parent, on_change):
        super().__init__(parent, text='ETH Farmer mixer | proposed / RAM-only | no funds reserved', padding=4)
        self.controls = {}
        self._ready = False
        for index, spec in enumerate(CONTROLS):
            fader = Fader(self, spec, lambda: on_change() if self._ready else None)
            fader.grid(row=0, column=index, sticky='nsew')
            self.columnconfigure(index, weight=1, uniform='faders')
            self.controls[spec.key] = fader
        self._ready = True

    def values(self):
        return {key: control.value for key, control in self.controls.items()}
