"""Private native-unit L2 display. Display controls never change evidence."""
from decimal import Decimal as D
import time
import tkinter as tk
from tkinter import ttk

from coincat_order_book import display_levels
from coincat_fee_prices import ask_costs
from coincat_hover import Hover


class OrderBookPanel(ttk.Frame):
    def __init__(self,parent,app,pair):
        super().__init__(parent);self.app=app;self.pair=pair;self.trees={};self.bars={}
        self.group=tk.StringVar(value='1');self.units=tk.StringVar(value='Base')
        self.status=tk.StringVar(value='Public stream OFF · BBO sizes UNKNOWN')
        self.spread=tk.StringVar(value='Bid / ask unobserved');self.cost=tk.StringVar(value='Fee-adjusted ASK: UNKNOWN')
        base,quote=pair.split('-')
        style=ttk.Style(self);style.configure('Book.Treeview',rowheight=19,font=('Consolas',9))
        style.configure('Book.Treeview.Heading',font=('Segoe UI',9),padding=(2,2))
        controls=ttk.Frame(self);controls.pack(fill='x')
        ttk.Label(controls,text='Group × tick').pack(side='left')
        for variable,values,width in ((self.group,('1','2','5','10','25','50','100'),5),(self.units,('Base','Quote notional'),14)):
            box=ttk.Combobox(controls,textvariable=variable,values=values,state='readonly',width=width)
            box.pack(side='left',padx=3);box.bind('<<ComboboxSelected>>',lambda e:self.refresh())
        for side,color in (('Ask','#ed6b7a'),('Bid','#55c99c')):
            if side=='Bid':
                ttk.Label(self,textvariable=self.spread,wraplength=360).pack(fill='x',pady=2)
            line=ttk.Frame(self);line.pack(fill='x')
            tree=ttk.Treeview(line,columns=('price','size','total'),show='headings' if side=='Ask' else '',height=3,style='Book.Treeview')
            for key,label,width in (('price','Price '+quote,108),('size','Amount '+base,93),('total','Total '+base,93)):
                tree.heading(key,text=label);tree.column(key,width=width,minwidth=65,anchor='e')
            tree.tag_configure(side,foreground=color);tree.pack(side='left',fill='x',expand=True);self.trees[side]=tree
            bars=tk.Canvas(line,width=38,height=60,background='#0b0f12',highlightthickness=0)
            bars.pack(side='right',fill='y');self.bars[side]=bars
        for variable in (self.status,self.cost):ttk.Label(self,textvariable=variable,wraplength=350,style='Muted.TLabel').pack(anchor='w',pady=2)
        Hover(self,'Red ASK offers above the spread; green BID offers below. Total accumulates outward from best price. '
            'Native quote units per base coin. Visible liquidity is not queue position or fill evidence. '
            'Grouping affects display only. Fee-adjusted ASK is a cost benchmark, never a submitted post-only BUY price.')

    def refresh(self,bbo=None,tier=None,rules=None,*,at=None):
        now=time.time() if at is None else at
        self._bbo=bbo if bbo is not None else getattr(self,'_bbo',None)
        self._tier=tier if tier is not None else getattr(self,'_tier',{})
        self._rules=rules if rules is not None else getattr(self,'_rules',{})
        view=self.app.book_hub.view(self.pair,at=now);base,quote=self.pair.split('-')
        tick=self._rules.get('price_increment',self._rules.get('quote_increment'))
        quote_amount=self.units.get()=='Quote notional'
        unit=quote if quote_amount else base
        for tree in self.trees.values():
            tree.heading('size',text='Amount '+unit);tree.heading('total',text='Total '+unit)
        rows=None
        if view.state=='HEALTHY' and tick:
            try:rows=display_levels(view,tick=tick,multiple=int(self.group.get()),quote_amount=quote_amount,limit=3)
            except (ValueError,ArithmeticError):pass
        bid,ask=(view.bids[0][0],view.asks[0][0]) if rows else (self._bbo[:2] if self._bbo else (None,None))
        for label in ('Ask','Bid'):
            tree=self.trees[label]
            bars=self.bars[label];bars.delete('all')
            for item in tree.get_children():tree.delete(item)
            if rows:
                visible=rows['asks' if label=='Ask' else 'bids'];maximum=max((r[2] for r in visible),default=D(1))
                height=max(16,tree.winfo_height()//(4 if label=='Ask' else 3));top=height if label=='Ask' else 0
                for index,(price,size,total) in enumerate(visible):
                    tree.insert('','end',values=tuple(format(x,'.10g') for x in (price,size,total)),tags=(label,))
                    width=float(total/maximum)*36 if maximum else 0
                    bars.create_rectangle(38-width,top+index*height+2,38,top+(index+1)*height-2,
                        fill='#45272e' if label=='Ask' else '#193d33',outline='')
            else:tree.insert('','end',values=('UNOBSERVED' if (ask if label=='Ask' else bid) is None else str(ask if label=='Ask' else bid),'UNKNOWN','UNKNOWN'),tags=(label,))
        self.spread.set('Bid / ask unobserved' if bid is None or ask is None else
            f'Bid {bid} / Ask {ask} {quote}\nSpread {ask-bid} · {(ask-bid)/((ask+bid)/2)*10000:.3f} bps')
        age=None if view.observed_at is None else max(0,now-view.observed_at)
        self.status.set(view.state+' · '+('L2 '+str(round(age,1))+'s · not queue / fills' if rows else
            'REST BBO only · size UNKNOWN'))
        self.cost.set('Fee-adjusted ASK: UNKNOWN')
        # No historical CSV-derived fee or inferred quote currency is applied.
        units=getattr(self.app,'fee_units',{}).get((self.pair,'BUY'),{})
        tier=self._tier
        try:
            if not tier.get('fresh') or not 0<=now-tier['captured_at']<=7200 or not units.get('verified') or not 0<=now-units['observed_at']<=30: return
            result=ask_costs(self.pair,ask,tier['maker'],fee_currency=units['currency'],price_increment=tick)
            self.cost.set(f"Maker quote-fee estimate {tier['maker']*100}% · ASK cost/base {result['buy_cost_per_base']} {quote}\n"
                f"SELL limit retaining ASK net {result['sell_limit_retaining_market_ask']} · not submitted BUY price")
        except (KeyError,TypeError,ValueError,ArithmeticError):pass
