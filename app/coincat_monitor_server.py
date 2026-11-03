"""Local-only GET server for already redacted monitor files; no app commands."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import stat
import webbrowser

from coincat_monitor import monitor_directory,status

HTML='''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoinCat v1.01 · Monitor</title><link rel="stylesheet" href="/monitor.css"></head>
<body><main><h1>CoinCat <small>v1.01 · Monitor</small></h1>
<p>Read-only app health · Trading blocked · Fills and profit unverified</p>
<h2 id="state">Connecting…</h2><p id="message"></p>
<div class="cards"><section><span>Last good scan</span><strong id="scan">—</strong></section>
<section><span>Account / fees now</span><strong id="fees">—</strong></section>
<section><span>Recovery</span><strong id="retry">—</strong></section></div>
<table><thead><tr><th>Market</th><th>Quote age</th><th>Setup</th><th>Observation gaps</th></tr></thead><tbody id="markets"></tbody></table>
<p id="counts"></p><h2>Adaptive ETH Research</h2><p id="adaptive"></p>
<h2>Prospective experiment journal</h2><p id="journal"></p><button id="download">Save redacted snapshot</button>
<h2>Auto maker PAPER session</h2><p id="paper"></p>
<details><summary>Technical detail</summary><pre id="detail"></pre></details>
<p class="note">The helper records while this chat is inactive. An assistant reads it only during an active session with private access configured.
App updates use a separate source build and restart.</p></main><script src="/monitor.js"></script></body></html>'''
CSS='''body{background:#121821;color:#eef1f5;font:16px system-ui;margin:0}main{max-width:1040px;margin:40px auto;padding:0 24px}
h1{color:#ffc76b}small{font-size:.6em;color:#bac3cf}p,.note,span{color:#bac3cf}h2{font-size:1.4em}.cards{display:flex;gap:12px;flex-wrap:wrap}
section{background:#1d2633;border-radius:8px;padding:18px;flex:1;min-width:200px}strong{display:block;margin-top:10px;font-size:1.2em}
table{width:100%;border-collapse:collapse;margin:24px 0}th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #354153}
button{background:#ffc76b;color:#121821;border:0;padding:12px 18px;border-radius:6px;cursor:pointer}details{margin-top:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.note{font-size:.85em;line-height:1.6}'''
JS='''"use strict";
let token=location.hash.slice(1), latest=null;
history.replaceState(null,"",location.pathname);
const put=(id,text)=>document.getElementById(id).textContent=text;
const reasonText={QUOTE_WIDE:"Spread exceeds 0.25%; no current pricing",QUOTE_STALE:"Quote older than 30 seconds",QUOTE_NOT_RETURNED:"No quote returned",QUOTE_FUTURE:"Future-dated quote rejected",ACCOUNT_FEE_TIER_UNAVAILABLE:"Fresh fee evidence unavailable"};
const age=x=>x===null||x===undefined?"Unobserved":x<0?"Future timestamp":x<60?Math.round(x)+" s":x<3600?Math.round(x/60)+" min":(x/3600).toFixed(1)+" h";
async function refresh(){
 try{
  const r=await fetch("/api/status",{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:AbortSignal.timeout(3000)});
  if(!r.ok)throw new Error("Read access unavailable. Reopen using the helper launcher.");
  latest=await r.json();put("state",latest.state.replaceAll("_"," "));
  const s=latest.snapshot,a=latest.ages;
  put("message",s?"Snapshot "+new Date(s.captured_at*1000).toLocaleString()+" · Heartbeat "+age(a.heartbeat_s)+" ago":"Enable Local monitor in CoinCat’s Research notes tab.");
  put("scan",s?age(a.last_good_scan_s)+" ago · #"+(s.health.scan_number??"—"):"—");
  put("fees",s?(a.authenticated_fresh?"Account recent":"Account stale / unobserved")+" · "+(a.fee_valid_now?"Fees within TTL":"Fees stale / unobserved"):"—");
  put("retry",s?s.health.connection_state+(s.health.retry_in_s===null?"":" · Captured countdown "+age(s.health.retry_in_s)):"—");
  const body=document.getElementById("markets");body.replaceChildren();
  if(s)for(const p of s.products){
   const current=a.products.find(x=>x.pair===p.pair),tr=document.createElement("tr");
   for(const text of [p.pair,age(current.quote_age_s)+(current.quote_within_age_limit?"":" · stale / unobserved"),(current.current_setup_state==="NO_SETUP_UNPRICED"?"No valid first setup":current.current_setup_state),p.reasons.map(x=>reasonText[x]||x).join(", ")||"None at capture"]){const td=document.createElement("td");td.textContent=text;tr.appendChild(td);}body.appendChild(tr);
  }
  put("counts",s?"Setups "+s.observations.setups+" · Gap episodes "+s.observations.unpriced_episodes+" · Resumptions "+s.observations.resumed_episodes+" · Uncertain entry touches "+s.observations.entry_touches_uncertain:"");
  put("adaptive",s?s.adaptive.decision+" · NO DEMONSTRATED EDGE · Recoverable research ETH: UNKNOWN · Independent cases; no verified exchange fills":"No current research snapshot");
  put("journal",s?s.prospective_journal.state+" · Registered "+s.prospective_journal.registered+" · Waiting "+s.prospective_journal.waiting+" · Conditional adverse "+s.prospective_journal.adverse+" · Unknown "+s.prospective_journal.unknown+" · Missed horizons "+s.prospective_journal.missed_horizons+" · Unpriced open "+s.prospective_journal.unpriced_open_cases+" · No paper trades":"No current journal snapshot");
  const p=s?.auto_paper;put("paper",p?p.state+" · "+p.model+" · Paper orders "+p.orders+" · Simulated fills "+p.fills+" · Non-fills "+p.non_fills+" · NO DEMONSTRATED EDGE":"No current auto-paper snapshot");
  put("detail",JSON.stringify(latest,null,2));
 }catch(e){latest=null;put("paper","Current paper status unavailable");put("journal","Current journal unavailable");put("adaptive","Current research unavailable");put("state","HELPER UNAVAILABLE");put("message",e.message);put("fees","Current validity unavailable");put("scan","Unverified now");put("retry","Unverified now");put("counts","");put("detail","No current response. Earlier observations do not establish current validity.");document.getElementById("markets").replaceChildren();}
}
document.getElementById("download").addEventListener("click",()=>{if(!latest)return;const u=URL.createObjectURL(new Blob([JSON.stringify(latest,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=u;a.download="CoinCat_v1.01_Monitor_Snapshot.json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);});
refresh();setInterval(refresh,5000);
'''


def tailscale_name(value):
    value=value.lower().rstrip('.')
    if len(value)>253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.ts\.net',value):
        raise argparse.ArgumentTypeError('Use the full Tailscale DNS name ending in .ts.net')
    if any(not p or len(p)>63 or p.startswith('-') or p.endswith('-') for p in value.split('.')):
        raise argparse.ArgumentTypeError('Invalid Tailscale DNS name')
    return value


def access_token(directory):
    """Stable read token, stored separately from shareable snapshot files."""
    root=Path(directory)
    if root.is_symlink():raise ValueError('MONITOR_SYMLINK_REJECTED')
    root.mkdir(parents=True,exist_ok=True);path=root/'monitor_read_token.key'
    try:
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w',encoding='ascii') as out:
            token=secrets.token_urlsafe(32);out.write(token+'\n')
        return token
    except FileExistsError:
        if path.is_symlink():raise ValueError('MONITOR_SYMLINK_REJECTED')
        with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)),'r',encoding='ascii') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):raise ValueError('INVALID_MONITOR_TOKEN_FILE')
            token=source.read(128).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('INVALID_MONITOR_TOKEN_FILE')
        return token


class MonitorServer(HTTPServer):
    allow_reuse_address=False

    def __init__(self,directory,*,port=8765,token=None,tailnet_name=None):
        self.directory=Path(directory);self.token=access_token(directory) if token is None else token
        self.tailnet_name=None if tailnet_name is None else tailscale_name(tailnet_name)
        super().__init__(('127.0.0.1',port),MonitorHandler)
        port=self.server_address[1]
        self.hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
        self.origins={f'http://{host}' for host in self.hosts}
        if self.tailnet_name:
            self.hosts.update({self.tailnet_name,self.tailnet_name+':443',self.tailnet_name+':8443'})
            self.origins.update({'https://'+self.tailnet_name,'https://'+self.tailnet_name+':443','https://'+self.tailnet_name+':8443'})

    def get_request(self):
        sock,address=super().get_request();sock.settimeout(3);return sock,address


class MonitorHandler(BaseHTTPRequestHandler):
    server_version='CoinCatMonitor';sys_version=''

    def log_message(self,*args):pass  # Never log URLs, token headers or private paths.

    def reply(self,code,body,kind='application/json; charset=utf-8'):
        raw=body.encode('utf-8') if isinstance(body,str) else body
        self.send_response(code)
        for name,value in {'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store',
                'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"}.items():
            self.send_header(name,value)
        self.end_headers()
        try:self.wfile.write(raw)
        except (OSError,TimeoutError):pass

    def do_GET(self):
        host=self.headers.get('Host','').lower();origin=self.headers.get('Origin')
        if host not in self.server.hosts or (origin is not None and origin not in self.server.origins):
            self.reply(403,'{"error":"ORIGIN_REJECTED"}');return
        static={'/':(HTML,'text/html; charset=utf-8'),'/monitor.js':(JS,'application/javascript; charset=utf-8'),
                '/monitor.css':(CSS,'text/css; charset=utf-8')}
        if self.path in static:
            body,kind=static[self.path];self.reply(200,body,kind);return
        if self.path!='/api/status':self.reply(404,'{"error":"NOT_FOUND"}');return
        auth=self.headers.get('Authorization','')
        expected='Bearer '+self.server.token
        if len(auth)>512 or not hmac.compare_digest(auth.encode('utf-8'),expected.encode('ascii')):
            self.reply(401,'{"error":"READ_TOKEN_REQUIRED"}');return
        self.reply(200,json.dumps(status(self.server.directory),separators=(',',':'),allow_nan=False))

    def reject(self):self.reply(405,'{"error":"READ_ONLY_GET_ONLY"}')
    do_POST=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=do_HEAD=reject


def main(argv=None):
    parser=argparse.ArgumentParser(description='CoinCat read-only monitor; binds localhost only.')
    parser.add_argument('--directory',type=Path,default=monitor_directory())
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--tailscale-name',type=tailscale_name)
    parser.add_argument('--open',action='store_true',help='Open the local browser dashboard')
    parser.add_argument('--once',action='store_true',help='Print redacted local status and exit; no listener')
    args=parser.parse_args(argv)
    if args.once:
        print(json.dumps(status(args.directory),indent=2,allow_nan=False));return 0
    if not 1024<=args.port<=65535:parser.error('Port must be between 1024 and 65535')
    try:
        server=MonitorServer(args.directory,port=args.port,tailnet_name=args.tailscale_name)
    except (OSError,ValueError):
        print('Monitor could not start. Check that its port is free and support_monitor is writable.');return 2
    print('CoinCat v1.01 read-only monitor: http://127.0.0.1:'+str(args.port)+'/')
    print('No app commands. Ctrl+C stops this helper; CoinCat research continues.')
    if args.tailscale_name:
        print('Private HTTPS hostname configured. Tailscale Serve and cloud VPN access must be set up separately.')
    if args.open:
        try:webbrowser.open('http://127.0.0.1:'+str(args.port)+'/#'+server.token)
        except webbrowser.Error:print('Browser could not open. Restart the helper with --open after checking your default browser.')
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=='__main__':raise SystemExit(main())
