"""One full-balance scanner and passive AI Lab; no trading or shadow modes."""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from queue import Queue, Empty
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from coinbase_account import parse_key_json, save_encrypted, load_encrypted
from coincat_live import LiveLedger, client_from_credentials
from coincat_live_forward_store import ForwardStore, Retention
from coincat_state_v50 import data_root
from coincat_v502_fee_learning import FeeLearning
from coincat_scanner import Scanner
from coincat_version import DISPLAY
from coincat_simple_diagnostics import make_report
from coincat_eth_farmer import measure_eth, measure_working_eth, reserve_preview, ReservePolicy
from coincat_allocation_editor import WorkingAllocationEditor
from coincat_mixer import ResearchMixer
from coincat_settings_advisor import settings_advice


class CoinCatApp:
    def __init__(self, root):
        self.root=root
        root.title(DISPLAY+' | ETH Farmer design preview | LIVE blocked')
        root.geometry('1120x900');root.minsize(1040,780)
        self.data=data_root()
        self.ledger=LiveLedger(self.data/'CoinCat_Live_Orders.sqlite3')
        self.fees=FeeLearning(self.data/'research_data'/'CoinCat_Fee_Evidence_v502.sqlite3')
        self.market=ForwardStore(self.data/'research_data'/'CoinCat_Forward_Market.sqlite3',Retention())
        self.scanner=None;self.credentials=None;self.last_result=None
        self.running=False;self.closed=False;self.busy=False;self.generation=0
        self.cancel=threading.Event();self.jobs=Queue();self._after={}
        self.connected=False;self.last_error=None
        self.eth_measurement=None
        self.reserve_calculation=None
        self.working_allocation=None;self.working_eth_measurement=None
        self.eth_text=tk.StringVar(value='ETH: awaiting a fresh account/market snapshot. Settled / protected / earned ETH UNKNOWN.')
        self.reserve_text=tk.StringVar()
        self.eth_details=tk.StringVar(value='ETH measurement details await a fresh snapshot. No working/reserve allocation has been approved.')
        self.eth_details_open=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='Connect to read available balances and spot products.')
        self.policy=tk.StringVar(value='Full verified available balance | greatest positive immediate USD advantage | no portfolio budget or profit floor. No automatic profit reserve or extra 10% BUY holdback; fees and exchange rounding stay inside the available balance.')
        self.best_text=tk.StringVar(value='Best swap: awaiting fresh prices.')
        self.cost_text=tk.StringVar(value='Fees: unknown | spread: unknown | depth impact: unknown | execution slippage: not measured')
        self.coverage_text=tk.StringVar(value='Coverage: not observed')
        self.execution_text=tk.StringVar(value='REAL SWAPS UNAVAILABLE - durable order/fill accounting and recovery are not integrated. No orders are submitted.')
        self._ui()
        self.root.protocol('WM_DELETE_WINDOW',self._close)
        self._schedule('poll',100,self._poll)

    def _ui(self):
        shell=ttk.Frame(self.root,padding=14);shell.pack(fill='both',expand=True)
        ttk.Label(shell,text=DISPLAY+' base - ETH Farmer design preview',font=('Segoe UI',17,'bold')).pack(anchor='w')
        ttk.Label(shell,textvariable=self.policy,wraplength=1040).pack(anchor='w',pady=(3,8))
        controls=ttk.Frame(shell);controls.pack(fill='x')
        for text,command in (('Import key JSON',self._import_key),('Connect / refresh',self._connect),
                             ('Start scanning',self._start),('STOP',self._stop),('Export diagnostics',self._export)):
            ttk.Button(controls,text=text,command=command).pack(side='left',padx=(0,7))
        ttk.Label(shell,textvariable=self.status,wraplength=1040).pack(anchor='w',pady=(8,3))
        ttk.Label(shell,textvariable=self.execution_text,wraplength=1040,foreground='#a34d00').pack(anchor='w')
        self.mixer=ResearchMixer(shell,self._mixer_changed)
        self.mixer.pack(fill='x',pady=(6,0))
        ttk.Label(shell,textvariable=self.reserve_text,wraplength=1040).pack(anchor='w',pady=(3,0))
        ttk.Label(shell,textvariable=self.eth_text,wraplength=1040).pack(anchor='w',pady=(3,0))
        self._mixer_changed()
        summary=ttk.LabelFrame(shell,text='Best currently priced full-balance swap',padding=10)
        summary.pack(fill='x',pady=10)
        ttk.Label(summary,textvariable=self.best_text,wraplength=1010,font=('Segoe UI',11,'bold')).pack(anchor='w')
        ttk.Label(summary,textvariable=self.cost_text,wraplength=1010).pack(anchor='w',pady=4)
        ttk.Label(summary,textvariable=self.coverage_text,wraplength=1010).pack(anchor='w')
        tabs=ttk.Notebook(shell);tabs.pack(fill='both',expand=True)
        wallet=ttk.Frame(tabs,padding=5);routes=ttk.Frame(tabs,padding=5);lab=ttk.Frame(tabs,padding=5)
        tabs.add(wallet,text='Available portfolio');tabs.add(routes,text='Ranked swaps');tabs.add(lab,text='AI Lab - passive notes')
        self.eth_details_toggle=ttk.Checkbutton(wallet,text='ETH accounting details (read only)',
            variable=self.eth_details_open,command=self._toggle_eth_details)
        self.eth_details_toggle.pack(anchor='w')
        self.eth_details_label=ttk.Label(wallet,textvariable=self.eth_details,wraplength=990)
        self.wallet_tree=self._table(wallet,('Asset','Available units','Policy'))
        self.route_tree=self._table(routes,('Product / side','Source -> destination','Full source','Spent / residue','Estimated W USD','State'))
        self.lab_text=tk.Text(lab,wrap='word',font=('Segoe UI',10),state='disabled')
        scroll=ttk.Scrollbar(lab,orient='vertical',command=self.lab_text.yview)
        self.lab_text.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.lab_text.pack(fill='both',expand=True)
        allocation_tab=ttk.Frame(tabs);conversion_tab=ttk.Frame(tabs,padding=5)
        tabs.add(allocation_tab,text='Working allocation');tabs.add(conversion_tab,text='ETH conversion blockers')
        self.allocation_editor=WorkingAllocationEditor(allocation_tab,self._allocation_changed)
        self.allocation_editor.pack(fill='both',expand=True)
        ttk.Label(conversion_tab,text='Account AVAILABLE scope; public asset symbols and reasons only. '
            'Complete ETH totals remain UNKNOWN whenever a required holding, residue or quote is blocked.',
            wraplength=990).pack(anchor='w')
        self.conversion_tree=self._table(conversion_tab,('Asset','Conversion state','Verified blockers','Observed route'))
        self._note('AI Lab is a passive observer. It reports available findings about every three minutes. It never ranks trades, changes sizing or controls the scanner.')

    def _allocation_changed(self):
        self.working_allocation=self.allocation_editor.assessment()
        if self.last_result is not None:self._render_eth(self.last_result)

    def _toggle_eth_details(self):
        if self.eth_details_open.get():
            self.eth_details_label.pack(after=self.eth_details_toggle,anchor='w',pady=(2,6))
        else:
            self.eth_details_label.pack_forget()

    def _mixer_changed(self):
        settings=self.mixer.values()
        self.reserve_calculation=reserve_preview(ReservePolicy(settings['initial_usd'],
            settings['growth_step_usd'],settings['harvest_usd']),fixed_reference=settings['reference_usd'])
        preview=self.reserve_calculation
        if preview['fixed_reference'] is None:
            text='Reserve proposal PENDING: enter a fixed reference rate to see ETH quantities.'
        else:
            text=(f"Proposed starting reserve {preview['initial_target_eth']:.8f} ETH; "
                  f"growth step {preview['growth_step_eth']:.8f} ETH; "
                  f"harvest/step {preview['harvest_per_step_eth']:.8f} ETH at fixed ${preview['fixed_reference']}/ETH.")
        self.reserve_text.set(text+' Earned/settled allocation UNKNOWN; no funds earmarked. Preferences are RAM-only.')
        if self.last_result is not None:
            self._render_eth(self.last_result)

    def _render_eth(self,result):
        snapshot=result.get('eth_observation')
        if snapshot is None:
            return
        self.eth_measurement=measure_eth(result=result,**snapshot,
            slippage_bps=self.mixer.values()['slippage_bps'])
        value=self.eth_measurement
        self.working_allocation=self.allocation_editor.assessment()
        self.working_eth_measurement=measure_working_eth(allocation=self.working_allocation,
            observation=snapshot,slippage_bps=self.mixer.values()['slippage_bps'])
        for item in self.conversion_tree.get_children():self.conversion_tree.delete(item)
        for row in value['conversion_diagnostics']['holdings']:
            self.conversion_tree.insert('','end',values=(row['asset'],row['state'],
                ', '.join(row['blockers']) or 'NONE_OBSERVED',', '.join(row['route']) or 'NONE'))
        available=value['actual_available_eth']
        best=result.get('best')
        w=None if best is None else value['w_eth_by_frame'].get(best['frame']['id'])
        hold=value.get('hold') or {}
        recoverable=hold.get('estimated_recoverable_eth')
        self.eth_text.set(
            'Account AVAILABLE ETH: '+('UNKNOWN' if available is None else str(available))+
            ' | Complete modeled return to ETH: '+('UNKNOWN' if recoverable is None else f'{recoverable:.8f} ETH (unverified)')+
            ' | Best USD W expressed in ETH: '+('UNKNOWN' if w is None else f'{w:+.10f} ETH (same ranking)')+
            '\nCoinCat working ETH: UNKNOWN — '+self.working_eth_measurement['reason']+'. '+value['reason']+
            '. All return legs include costs; unconverted native dust is retained. No fill or profit claimed.')
        switch=value.get('switch') or {}
        def shown(raw):
            return 'UNKNOWN' if raw is None else str(raw)
        self.eth_details.set(
            'ETH Farmer read-only design | account AVAILABLE scope, not reconciled unreserved working capital.\n'
            'Settled / protected / actual earned ETH: UNKNOWN. Cashflow-adjusted improvement vs starting holdings: UNKNOWN; no baseline or manual-flow journal.\n'
            f"HOLD complete modeled ETH return: {shown(hold.get('estimated_recoverable_eth'))}; "
            f"SWITCH complete modeled ETH return: {shown(switch.get('estimated_recoverable_eth'))}; "
            f"immediate modeled difference: {shown(value['return_advantage_eth'])} ETH.\n"
            f"HOLD ETH proceeds subtotal: {shown(hold.get('modeled_eth_proceeds'))}; retained native quantities: {hold.get('unconverted_native',{})}. "
            'A subtotal excludes these quantities and is not complete recoverable ETH.\n'
            f"Secondary available-portfolio USD mark: {shown(value['portfolio_usd_mark'])}; "
            f"ETH reference: {shown(value['reference_eth_usd'])} USD/ETH; snapshot {value['balances_at']}; "
            f"quote span: {shown(value.get('quote_span_s'))} s. Depth / fee currency / exchange event timing unverified.")

    @staticmethod
    def _table(parent,columns):
        tree=ttk.Treeview(parent,columns=columns,show='headings')
        for column in columns:
            tree.heading(column,text=column);tree.column(column,width=155,stretch=True)
        scrollbar=ttk.Scrollbar(parent,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        return tree

    def _schedule(self,key,delay,callback):
        if not self.closed:self._after[key]=self.root.after(delay,callback)

    def _submit(self,kind,task):
        if self.closed or self.busy:return False
        self.busy=True;generation=self.generation
        def work():
            try:self.jobs.put((kind,generation,task(),None))
            except Exception as exc:self.jobs.put((kind,generation,None,type(exc).__name__))
        threading.Thread(target=work,daemon=True).start()
        return True

    def _import_key(self):
        if self.busy:
            self.status.set('Wait for the current read-only request before changing keys.');return
        path=filedialog.askopenfilename(title='Choose Coinbase CDP JSON',filetypes=[('JSON','*.json')])
        if not path:return
        self._stop()
        try:
            credentials=parse_key_json(Path(path).read_text(encoding='utf-8'))
            save_encrypted(credentials)
            self.credentials=credentials;self.scanner=None;self.connected=False
            self.status.set('Key saved locally with Windows DPAPI. Connect to refresh verified available balances.')
        except Exception as exc:
            messagebox.showerror('Key import',f'Import failed ({type(exc).__name__}). Your key is not printed or sent to diagnostics.')

    def _connect(self):
        if self.busy:
            self.status.set('A read-only request is finishing; retry refresh when it completes.');return
        if self.credentials is None and self.scanner is None:
            try:self.credentials=load_encrypted()
            except Exception:self.credentials=None
            if not self.credentials:
                self.status.set('Import a Coinbase CDP key JSON locally first.');return
        self.status.set('Refreshing available balances, spot products and account fee estimate…')
        def task():
            if self.scanner is None:
                self.scanner=Scanner(self.ledger,client_from_credentials(self.credentials),self.fees,self.market)
            return self.scanner.refresh()
        self._submit('connect',task)

    def _start(self):
        if self.scanner is None or not self.connected:
            self.status.set('Connect and finish a verified account refresh before starting.');return
        if self.running:return
        self.running=True;self.cancel.clear()
        self.status.set('Scanning full available balances. AI Lab observes only. Real swaps remain unavailable.')
        self._scan()

    def _stop(self):
        self.running=False;self.cancel.set();self.generation+=1
        after=self._after.pop('scan',None)
        if after is not None:
            try:self.root.after_cancel(after)
            except tk.TclError:pass
        self.status.set('STOPPED - findings and ranked proposals retained. No orders were submitted.')

    def _scan(self):
        if self.closed or not self.running:return
        if self.busy:
            self._schedule('scan',250,self._scan);return
        interval=self.mixer.values()['scan_interval_s']
        allocation=self.allocation_editor.parameters()
        self._submit('scan',lambda:self.scanner.scan(cancel=self.cancel,scan_interval_s=interval,**allocation))

    def _poll(self):
        if self.closed:return
        try:
            while True:
                kind,generation,payload,error=self.jobs.get_nowait()
                self.busy=False
                if generation!=self.generation:continue
                if error:
                    self.last_error=error
                    if kind=='connect':self.connected=False
                    self.status.set(f'Read-only {kind} failed ({error}); check connection/key permissions and refresh.')
                    if kind=='scan':self._schedule('scan',5000,self._scan)
                    continue
                self.last_error=None
                if kind=='connect':
                    self.connected=True;self._render_wallet()
                    self.status.set(f'Connected | {payload["catalog_count"]} spot products | full available sizing | trading unavailable')
                elif kind=='scan' and payload.get('state')!='CANCELLED':
                    self.last_result=payload;self._render(payload)
                    if payload.get('lab_note'):
                        self._note(payload['lab_note']+'\n'+settings_advice(payload,
                            scan_interval_s=self.mixer.values()['scan_interval_s']))
                    self._schedule('scan',int(self.mixer.values()['scan_interval_s']*1000),self._scan)
        except Empty:pass
        self._schedule('poll',100,self._poll)

    def _render_wallet(self):
        for item in self.wallet_tree.get_children():self.wallet_tree.delete(item)
        if self.scanner is None:return
        excluded={row['asset'] for row in self.ledger.assets() if not row.get('enabled',1)}
        self.allocation_editor.snapshot(self.scanner.balances,self.scanner.account_at,time.time(),excluded)
        self.working_allocation=self.allocation_editor.assessment()
        for asset,quantity in sorted(self.scanner.balances.items()):
            self.wallet_tree.insert('', 'end',values=(asset,str(quantity),'EXCLUDED' if asset in excluded else 'FULL AVAILABLE'))

    def _render(self,result):
        self._render_wallet()
        self._render_eth(result)
        for item in self.route_tree.get_children():self.route_tree.delete(item)
        for row in result['ranked']:
            self.route_tree.insert('', 'end',values=(row['pair']+' / '+row['side'],row['source']+' -> '+row['target'],
                str(row['available']),str(row['spent'])+' / '+str(row['residual']),f'{row["w"]:+.8f}',row['state']))
        best=result['best']
        if best:
            self.best_text.set(f'{best["source"]} -> {best["target"]} via {best["pair"]} {best["side"]}: modeled immediate advantage ${best["w"]:+.8f}')
            self.cost_text.set(f'Estimated fee ${best["estimated_fee_usd"]:.6f} | spread {best["spread_pct"]:.4f}% | modeled slippage reserve {best["slippage_reserve_pct"]}% | depth impact UNKNOWN | actual execution NOT MEASURED')
        else:
            self.best_text.set(
                f'HOLD - no positive estimate among {result["priced_directions"]}/{result["eligible_directions"]} currently priced directions. Unpriced directions remain UNKNOWN.'
                if result['ranked'] else 'Waiting - '+result['reason']+'; unpriced directions remain UNKNOWN.')
            self.cost_text.set('Depth impact UNKNOWN | actual execution NOT MEASURED | prices and account fee tier are estimates, not fill evidence')
        history=result.get('coverage_history',{})
        conditions='; '.join(f'{key.lower()} {value}' for key,value in sorted(result.get('book_conditions',{}).items()))
        self.coverage_text.set(f'Now priced {result["priced_directions"]}/{result["eligible_directions"]}, {result["positive_directions"]} positive | '
            f'5 min {history.get("last_5min_priced_directions","UNKNOWN")} | session {history.get("session_priced_directions","UNKNOWN")} '
            f'(historical, not fresh coverage). Books: {conditions or "UNKNOWN"}. Frame/product rejections are detailed in diagnostics.')
        self.status.set(f'Scan {result["scan"]} | full available sizing | no portfolio spending cap | AI Lab passive | no orders')

    def _note(self,text):
        stamp=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        self.lab_text.configure(state='normal');self.lab_text.insert('end',stamp+'\n'+text+'\n\n')
        if int(self.lab_text.index('end-1c').split('.')[0])>1500:self.lab_text.delete('1.0','400.0')
        self.lab_text.see('end');self.lab_text.configure(state='disabled')

    def _export(self):
        path=filedialog.asksaveasfilename(title='Save CoinCat diagnostics',defaultextension='.txt',
            initialfile='CoinCat_ETH_Design_Complete_Diagnostics.txt',filetypes=[('Text','*.txt')])
        if not path:return
        try:Path(path).write_text(make_report(self),encoding='utf-8')
        except OSError as exc:messagebox.showerror('Diagnostics',f'Export failed ({type(exc).__name__}).')

    def _close(self):
        if self.closed:return
        self._stop();self.closed=True
        for task in list(self._after.values()):
            try:self.root.after_cancel(task)
            except tk.TclError:pass
        self.root.destroy()


def main():
    from coincat_single_instance import SingleInstance,AnotherCoinCatRunning
    from coincat_state_v50 import state_status,StateError
    directory=data_root()
    try:
        state_status(directory)
        with SingleInstance(directory):
            root=tk.Tk();CoinCatApp(root);root.mainloop()
    except (AnotherCoinCatRunning,StateError) as exc:
        print('CoinCat launch blocked:',type(exc).__name__)
        raise SystemExit(2) from exc


if __name__=='__main__':main()
