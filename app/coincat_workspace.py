"""Spot-style chart workspace. All actions remain the existing read-only ones."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from coincat_allocation_editor import WorkingAllocationEditor
from coincat_chart import QuoteChart
from coincat_hover import Hover,help_tree
from coincat_mixer import ResearchMixer
from coincat_theme import apply_theme,BG,TEXT
from coincat_version import DISPLAY
from coincat_watchlist import WATCH_PAIRS
from coincat_paper_panel import PaperPanel


def build_workspace(app):
    root=app.root;apply_theme(root)
    shell=ttk.Frame(root,padding=10);shell.pack(fill='both',expand=True)
    # The owner-selected upper-right header space holds the larger cutout banner.
    top=ttk.Frame(shell);top.pack(fill='x',pady=(0,7))
    top.columnconfigure(1,weight=1);top.rowconfigure(0,minsize=160)
    header=ttk.Frame(top);header.grid(row=0,column=0,sticky='nw',padx=(0,12))
    ttk.Label(header,text=DISPLAY+' / ETH workspace',style='Title.TLabel',wraplength=410).pack(anchor='w')
    badge=ttk.Label(header,text='RESEARCH / PAPER  ·  LIVE BLOCKED',foreground='#eab86b');badge.pack(anchor='w',pady=(2,6))
    Hover(badge,'Real order submission is unconditionally blocked. Quotes and hypothetical setups never create Coinbase orders or verified profit.')
    if sys.platform=='win32':root.iconbitmap(str(Path(__file__).with_name('CoinCat50.ico')))
    actions=ttk.Frame(header);actions.pack(fill='x',pady=(0,5))
    for label,command,tip in (
        ('Import key JSON',app._import_key,'Import locally on this PC. Never send Coinbase keys to chat. Existing DPAPI and permission checks remain.'),
        ('Connect / refresh',app._connect,'Read current account, authenticated product rules and fee evidence. Only the approved seven products can receive research quotes.'),
        ('Export diagnostics',app._export,'Export all eight redacted sections. No balances, native amounts, receipts, private paths, account IDs or keys.')):
        button=ttk.Button(actions,text=label,command=command);button.pack(side='left',padx=(0,6));Hover(button,tip)
    status=ttk.Label(header,textvariable=app.status,style='Muted.TLabel',wraplength=410);status.pack(anchor='w')
    Hover(status,lambda:app.status.get()+'. Source preview only. No orders, transfers or automatic funding changes.')
    observation=ttk.Label(header,textvariable=app.observation_text,wraplength=410);observation.pack(anchor='w',pady=(2,0))
    Hover(observation,'Current recovery state and last-good observation age. STOP cancels queued research/retries. Historical evidence is not current pricing.')
    banner=ttk.Frame(top);banner.grid(row=0,column=1,sticky='nsew')
    # Trim only transparent display padding; the packaged RGBA artwork is intact.
    source=tk.PhotoImage(file=str(Path(__file__).with_name('coincat_logo_transparent.png')),format='png')
    app._logo_source=tk.PhotoImage(width=source.width(),height=445)
    app._logo_source.tk.call(app._logo_source,'copy',source,'-from',0,145,source.width(),590)
    app.logo=app._logo_source.subsample(3)
    app.logo_label=ttk.Label(banner,image=app.logo,anchor='center')
    app.logo_label.place(relx=.5,rely=.5,anchor='center')
    Hover(app.logo_label,DISPLAY+' · Larger CoinCat artwork with true alpha transparency in the upper workspace header.')
    app._logo_scale=3
    def fit_logo(event):
        import math
        scale=max(3,math.ceil(app._logo_source.width()/max(1,event.width-8)))
        if scale!=app._logo_scale:
            app._logo_scale=scale;app.logo=app._logo_source.subsample(scale)
            app.logo_label.configure(image=app.logo)
    banner.bind('<Configure>',fit_logo)
    app.tabs=ttk.Notebook(shell);app.tabs.pack(fill='both',expand=True)
    paper_tab=ttk.Frame(app.tabs);trading=ttk.Frame(app.tabs,padding=8)
    allocation=ttk.Frame(app.tabs);archive=ttk.Frame(app.tabs)
    for frame,label in ((paper_tab,'Auto Trader'),(trading,'Trading Settings'),(allocation,'Allocation'),
            (archive,'Research Archive')):app.tabs.add(frame,text=label)
    app.archive_tabs=ttk.Notebook(archive);app.archive_tabs.pack(fill='both',expand=True)
    growth=ttk.Frame(app.archive_tabs,padding=6);mixer_tab=ttk.Frame(app.archive_tabs,padding=8)
    lab=ttk.Frame(app.archive_tabs,padding=8);legacy_paper=ttk.Frame(app.archive_tabs,padding=8)
    for frame,label in ((growth,'ETH Growth'),(mixer_tab,'Legacy scenario mixer'),(lab,'AI Lab / notes'),
            (legacy_paper,'Legacy paper settings')):app.archive_tabs.add(frame,text=label)
    app.research_page=growth;app.lab_page=lab
    growth.columnconfigure(0,weight=1);growth.columnconfigure(1,weight=0,minsize=286)
    growth.rowconfigure(0,weight=1)
    left=ttk.Frame(growth);left.grid(row=0,column=0,sticky='nsew',padx=(0,8))
    left.columnconfigure(0,weight=1);left.rowconfigure(0,weight=1)
    app.chart=QuoteChart(left,app.market.path,allowed_products=WATCH_PAIRS)
    app.chart.grid(row=0,column=0,sticky='nsew')
    app.activity_tabs=ttk.Notebook(left);app.activity_tabs.grid(row=1,column=0,sticky='nsew',pady=(7,0))
    research=ttk.Frame(app.activity_tabs,padding=4);watch=ttk.Frame(app.activity_tabs,padding=4)
    orders=ttk.Frame(app.activity_tabs,padding=8);portfolio=ttk.Frame(app.activity_tabs,padding=8)
    for frame,label in ((research,'Research'),(watch,'Watchlist'),(orders,'Open orders'),(portfolio,'Portfolio')):app.activity_tabs.add(frame,text=label)
    columns=('Market','ETH / coin','Spread / age','Taker ΔETH','Maker ΔETH / move','Fill evidence')
    app.growth_tree=ttk.Treeview(research,columns=columns,show='headings',height=4,selectmode='browse')
    for name,width in zip(columns,(90,100,105,110,155,145)):
        app.growth_tree.heading(name,text=name);app.growth_tree.column(name,width=width,minwidth=65,stretch=True)
    app.growth_tree.pack(fill='both',expand=True)
    app.growth_tree.bind('<<TreeviewSelect>>',lambda event:app._select_row())
    Hover(app.growth_tree,lambda:app._row_help())
    def row_motion(event):
        pair=app.growth_tree.identify_row(event.y)
        if pair and pair!=getattr(app,'_hover_row',None):
            app._hover_row=pair;app.growth_tree.hover_help.schedule(event)
    app.growth_tree.bind('<Motion>',row_motion,add='+')
    detail=ttk.Label(research,textvariable=app.detail_text,wraplength=690,style='Muted.TLabel')
    detail.pack(anchor='w',pady=(4,0));Hover(detail,lambda:app._row_help())
    app.watch_tree=ttk.Treeview(watch,columns=('market','price','status','role'),show='headings',height=7,selectmode='browse')
    for name,width in (('market',100),('price',140),('status',140),('role',130)):
        app.watch_tree.heading(name,text=name.title());app.watch_tree.column(name,width=width,minwidth=80)
    app.watch_tree.pack(fill='both',expand=True)
    for pair in WATCH_PAIRS:app.watch_tree.insert('','end',iid=pair,values=(pair,'—','Unobserved','ETH companion' if 'ETH' in pair.split('-') else 'BTC cross-pair'))
    app.watch_tree.bind('<<TreeviewSelect>>',app._select_watch)
    Hover(app.watch_tree,'Only ADA-ETH, ETH-BTC, LINK-ETH, SOL-ETH, LINK-BTC, SOL-BTC and ADA-BTC. '
        'Prices use each actual product’s quote currency. BTC is an ETH companion through ETH-BTC. '
        'Four direct ETH products stay in each full pass; three BTC cross-pairs rotate through remaining slots, at most six books per pass. '
        'Deferred books retain their timestamp and cannot masquerade as a newly synchronized observation. Selecting a row only changes the chart.')
    ttk.Label(orders,text='CoinCat live orders: 0 · Submission blocked',style='Metric.TLabel').pack(anchor='w')
    ttk.Label(orders,text='Coinbase account order feed: not loaded',style='Muted.TLabel').pack(anchor='w',pady=6)
    app.orders_tree=ttk.Treeview(orders,columns=('market','side','price','amount','state'),show='headings',height=4)
    for name in app.orders_tree['columns']:app.orders_tree.heading(name,text=name.title());app.orders_tree.column(name,width=100,minwidth=70)
    app.orders_tree.pack(fill='both',expand=True)
    Hover(app.orders_tree,'This is an explicit empty CoinCat order view because submission is blocked. It does not assert that your Coinbase account has no manual orders. '
        'An actual accepted resting order normally appears on Coinbase for the same portfolio and matching filters. Filled orders appear in order/trade history. '
        'Quotes, entry touches and hypothetical paper setups never appear on the exchange as orders.')
    app.portfolio_text=tk.Text(portfolio,wrap='word',height=7,background=BG,foreground=TEXT,
        insertbackground=TEXT,relief='flat',state='disabled')
    app.portfolio_text.pack(fill='both',expand=True)
    Hover(app.portfolio_text,'Watched-basket midpoint reference in ETH, before exit fees, from fresh direct ETH quotes. '
        'Other holdings remain unvalued; no additional market is fetched. Value change is unadjusted for deposits, withdrawals and manual trades, and is not verified trading profit. '
        'Baseline stays in RAM and can be reset explicitly. No ledger or allocation is changed.')
    side=ttk.Frame(growth,width=286);side.grid(row=0,column=1,sticky='nsew');side.grid_propagate(False)
    side.rowconfigure(0,weight=1);side.columnconfigure(0,weight=1)
    canvas=tk.Canvas(side,background=BG,highlightthickness=0,width=270)
    canvas.grid(row=0,column=0,sticky='nsew')
    scroll=ttk.Scrollbar(side,orient='vertical',command=canvas.yview);scroll.grid(row=0,column=1,sticky='ns')
    canvas.configure(yscrollcommand=scroll.set)
    panel=ttk.Frame(canvas,padding=8);window=canvas.create_window((0,0),window=panel,anchor='nw')
    panel.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
    ttk.Label(panel,text='ETH engine',style='Title.TLabel').pack(anchor='w')
    ttk.Label(panel,text='Read-only research',foreground='#eab86b').pack(anchor='w',pady=(2,8))
    row=ttk.Frame(panel);row.pack(fill='x',pady=(0,8))
    for text,command,style in (('Start research',app._start,'Accent.TButton'),('STOP',app._stop,'Stop.TButton')):
        button=ttk.Button(row,text=text,command=command,style=style);button.pack(side='left',padx=(0,6))
        Hover(button,'Start observes only the approved markets after Apply; STOP cancels research/retries and retains findings. No exchange order is submitted or cancelled.')
    apply=ttk.Button(panel,text='Apply research plan',command=app._apply_plan);apply.pack(fill='x',pady=(0,5))
    Hover(apply,'Apply the exact manual research proposal in RAM. This is not allocation reconciliation, order permission or an automatic BTC purchase.')
    app.mixer=ResearchMixer(mixer_tab,app._invalidate);app.mixer.pack(fill='x')
    for key,label in (('amount_eth','Model ETH'),('target_pct','ETH target %'),('entry_offset_bps','Entry offset · bps')):
        ttk.Label(panel,text=label,style='Muted.TLabel').pack(anchor='w',pady=(5,0))
        control=app.mixer.controls[key]
        entry=ttk.Entry(panel,textvariable=control.text);entry.pack(fill='x',pady=(2,0))
        entry.bind('<Return>',control._entered);entry.bind('<FocusOut>',control._entered)
        Hover(entry,control.spec.explanation+' Same exact value as the audio mixer; Apply is required after editing.')
    ttk.Label(panel,text='Model companions',style='Muted.TLabel').pack(anchor='w',pady=(12,3))
    choices=ttk.Frame(panel);choices.pack(fill='x');app.companion_boxes=[]
    for i,variable in enumerate(app.companions):
        box=ttk.Combobox(choices,textvariable=variable,values=('',),state='readonly',width=9)
        box.grid(row=i//2,column=i%2,sticky='ew',padx=(0,5),pady=3);choices.columnconfigure(i%2,weight=1)
        app.companion_boxes.append(box)
        Hover(box,'Select up to four authenticated ETH companions from BTC, ADA, LINK and SOL. '
            'Each is an independent hypothetical comparison using the same ETH amount, never four simultaneous funded allocations. '
            'BTC cross-pairs stay observation-only until an explicit BTC budget/strategy is implemented. No automatic replacements.')
    app.funding_label=ttk.Label(panel,textvariable=app.funding_text,wraplength=246);app.funding_label.pack(anchor='w',pady=3)
    Hover(app.funding_label,lambda:app.funding_text.get()+'. Other assets cannot fund ETH scenarios. Protected/manual/excluded carve-outs remain exact. Unreconciled research only.')
    evidence=ttk.Label(panel,textvariable=app.evidence_text,wraplength=246,style='Muted.TLabel');evidence.pack(anchor='w',pady=4)
    Hover(evidence,app._fee_details)
    summary=ttk.Frame(side,padding=8);summary.grid(row=1,column=0,columnspan=2,sticky='ew')
    ttk.Separator(summary).pack(fill='x',pady=(0,6))
    for label,variable in (('ETH held',app.eth_held_text),('Watched basket · ETH',app.basket_text),('Value change · unadjusted',app.basket_change_text)):
        ttk.Label(summary,text=label,style='Muted.TLabel').pack(anchor='w',pady=(4,0))
        metric=ttk.Label(summary,textvariable=variable,style='Metric.TLabel');metric.pack(anchor='w')
        Hover(metric,'Reference values from fresh account balances and the watched direct ETH quotes, before exit fees. '
            'Change since the RAM baseline includes price moves, deposits, withdrawals and manual trading. It is not assumed bot earnings. '
            'Missing quotes remain unpriced and holdings outside the watch network are never silently included.')
    counters=ttk.Label(summary,textvariable=app.counter_text,wraplength=246);counters.pack(anchor='w',pady=(10,4))
    app.counter_label=counters
    Hover(counters,'Scans and hypothetical setups count research. Verified bot fills stay zero because live submission is blocked. A touch is not a fill or completed swap.')
    baseline=ttk.Button(summary,text='Reset view baseline',command=app._reset_view_baseline);baseline.pack(fill='x',pady=4)
    Hover(baseline,'Reset only the display baseline in RAM using a fresh fully priced watched basket. Does not edit the ledger, settings, funds or applied plan.')
    def wheel(event):
        steps=-1 if event.num==4 else 1 if event.num==5 else -int(event.delta/120)
        if steps:canvas.yview_scroll(steps,'units')
        return 'break'
    def wheel_bind(widget):
        for event in ('<MouseWheel>','<Button-4>','<Button-5>'):widget.bind(event,wheel,add='+')
        for child in widget.winfo_children():wheel_bind(child)
    wheel_bind(canvas)
    app.allocation_editor=WorkingAllocationEditor(allocation,app._allocation_changed)
    app.allocation_editor.canvas.configure(background=BG);app.allocation_editor.pack(fill='both',expand=True)
    app.paper_panel=PaperPanel(paper_tab,app,settings_parent=trading,legacy_parent=legacy_paper)
    app.paper_panel.pack(fill='both',expand=True)
    monitor_bar=ttk.Frame(lab);monitor_bar.pack(fill='x',pady=(0,6))
    ttk.Checkbutton(monitor_bar,text='Local monitor',variable=app.monitor_enabled,command=app._monitor_changed).pack(side='left')
    monitor_label=ttk.Label(monitor_bar,textvariable=app.monitor_text);monitor_label.pack(side='left',padx=12)
    Hover(monitor_label,'Local redacted snapshot writing, not an automatic assistant connection. The separately configured helper has no control or update channel.')
    adaptive=ttk.LabelFrame(lab,text='Adaptive ETH Research',padding=10);adaptive.pack(fill='x',pady=(0,10))
    app.adaptive_label=ttk.Label(adaptive,textvariable=app.adaptive_text,wraplength=850)
    app.adaptive_label.pack(anchor='w')
    Hover(app.adaptive_label,'Conditional research only. HOLD is the default; no predictive improvement has been demonstrated. '
        'The separate offline harness supports explicit simulated fills, a shared paper budget and fixed-horizon outcomes. '
        'Normal scanning creates no inventory or reservations. Missing sized depth, fee currency or native-residue valuation means UNKNOWN. '
        'A 15% alert is a review proposal only, never an automatic liquidation policy.')
    journal_label=ttk.Label(adaptive,textvariable=app.journal_text,wraplength=850)
    journal_label.pack(anchor='w',pady=(8,4))
    journal_button=ttk.Button(adaptive,text='Register hypothetical experiment…',command=app._open_experiment_dialog)
    journal_button.pack(anchor='w')
    Hover(journal_button,'Manually freeze a signal ID, exact ETH what-if slice and future horizon. '
        'Optional companion funding is an explicit independent simulated assumption, never a real seed. '
        'Existing scans update the local persistent journal; no automatic predictor or paper trade is started.')
    view_button=ttk.Button(adaptive,text='View registered experiments…',command=app._view_experiments)
    view_button.pack(anchor='w',pady=(4,0))
    Hover(view_button,'Read the bounded local experiment journal while running or stopped. '
        'View signal IDs, frozen horizons, gaps and conditional outcomes. This creates no network request or trade.')
    app.lab_text=tk.Text(lab,wrap='word',font=('Segoe UI',10),state='disabled',height=7,
        background=BG,foreground=TEXT,insertbackground=TEXT,relief='flat')
    app.lab_text.pack(fill='both',expand=True)
    app._note('Approved seven-market watch network. Independent ETH scenarios; BTC cross-pairs are observations. Fills and profit remain unverified.')
    app.tabs.select(paper_tab)
    help_tree(shell,DISPLAY+' read-only research. Exact manual controls and native amounts stay local. '
        'Seven approved markets only; no automatic settings, funding, orders or code updates. Mouse and keyboard help remain available.')
