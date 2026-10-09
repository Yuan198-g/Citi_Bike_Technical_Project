"""Local Citi Bike operations dashboard. Python stdlib; no extra installs."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parent


def get_state(database, station=None):
    if not database.is_file():
        raise FileNotFoundError('Database not found. Put this script beside poll_stations.py and run collection first.')
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        rows=[dict(r) for r in db.execute('SELECT * FROM station_latest ORDER BY short_name,station_id')]
        for row in rows:
            row['warnings']=json.loads(row['warnings'] or '[]')
        options={r['station_id'] for r in rows}
        if station not in options:
            station=next((r['station_id'] for r in rows if r['short_name']=='JC009'),rows[0]['station_id'] if rows else None)
        history=[dict(r) for r in db.execute('''SELECT * FROM (
          SELECT observed_at,source_reported_at,source_feed_time,bikes_available,docks_available,
                 bikes_disabled,docks_disabled,capacity,net_bike_inventory_change,warnings
          FROM station_inventory_changes WHERE station_id=?
          ORDER BY observed_at DESC,batch_id DESC LIMIT 600) ORDER BY observed_at''',(station,))]
        for row in history: row['warnings']=json.loads(row['warnings'] or '[]')
        success=db.execute("SELECT observed_at,outcome FROM live_polls WHERE outcome IN ('processed','repeated') ORDER BY observed_at DESC LIMIT 1").fetchone()
        attempt=db.execute('SELECT observed_at,outcome,error FROM live_polls ORDER BY observed_at DESC LIMIT 1').fetchone()
        evidence=dict(db.execute('''SELECT COUNT(*) AS successful_polls,MIN(observed_at) AS first_success,
          MAX(observed_at) AS last_success FROM live_polls WHERE outcome IN ('processed','repeated')''').fetchone())
        evidence['snapshot_rows']=db.execute('SELECT COUNT(*) FROM station_snapshots').fetchone()[0]
        evidence['distinct_batches']=db.execute('SELECT COUNT(*) FROM live_batches').fetchone()[0]
        evidence['quarantined_records']=db.execute('SELECT COUNT(*) FROM live_quarantine').fetchone()[0]
        return dict(dashboard_refreshed_at=datetime.now(timezone.utc).isoformat(),
          latest_successful_poll=dict(success) if success else None,last_attempt=dict(attempt) if attempt else None,
          scope='Current GBFS stations whose short_name begins JC or HB',
          evidence=evidence,stations=rows,selected_station_id=station,history=history)


HTML=r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Citi Bike operations</title><style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#182536;background:#f4f6f9;font-size:14px}*{box-sizing:border-box}body{margin:0}.wrap{max-width:1320px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;gap:20px;align-items:center}h1{font-size:27px;letter-spacing:-.6px;margin:0 0 6px}h2{font-size:18px;margin:0 0 14px}.muted{color:#637084}.meta{font-size:12px;line-height:1.8;text-align:right}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:22px 0 14px}button,select,input{font:inherit;border:1px solid #d2dae4;border-radius:7px;padding:9px 12px;background:white;color:#182536}button{cursor:pointer}button.active{background:#214a82;color:white;border-color:#214a82}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #95b8ec}.notice{border:1px solid #e7ce99;background:#fff8e8;color:#70531c;padding:13px 16px;border-radius:9px;line-height:1.6}.notice.error{background:#fff0f0;border-color:#e9bcbc;color:#882828}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:17px 0}.card,.panel{background:white;border:1px solid #dee4ec;border-radius:11px;padding:18px}.number{font-size:30px;font-weight:650;margin:9px 0}.card small{color:#637084}.grid{display:grid;grid-template-columns:1.05fr 1fr;gap:16px;margin:16px 0}.details{display:grid;grid-template-columns:repeat(2,1fr);gap:13px;margin-top:16px}.label{font-size:12px;color:#637084;margin-bottom:5px}.value{font-size:15px;overflow-wrap:anywhere}.pill{display:inline-block;border-radius:5px;padding:3px 7px;font-size:11px;background:#eef1f5;color:#4d5c6d;margin:2px}.pill.warn{background:#fff2d6;color:#805609}.pill.bad{background:#ffe6e6;color:#932c2c}.pill.good{background:#e5f4ee;color:#246044}.tablebox{max-height:410px;overflow:auto;border:1px solid #e5e9ef;border-radius:7px}table{border-collapse:collapse;width:100%;font-size:12px}th{position:sticky;top:0;background:#f2f5f9;text-align:left;color:#5d6a7b}th,td{padding:10px;border-bottom:1px solid #e9edf3;white-space:nowrap}tbody tr{cursor:pointer}tbody tr:hover{background:#f2f6fc}tbody tr.selected{background:#e9f1fc}td.name{white-space:normal;min-width:170px}.tablebar{display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap}.tablebar input[type=search]{flex:1;min-width:200px}#chart{width:100%;height:230px;display:block}.legend{display:flex;gap:15px;font-size:12px}.legend span::before{content:'';display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:6px}.legend .bikes::before{background:#2864a7}.legend .docks::before{background:#de9545}.footer{font-size:12px;line-height:1.7;color:#637084;margin-top:18px}a{color:#214a82}#error{display:none;margin:12px 0}.empty{padding:24px;color:#637084}@media(max-width:850px){.grid{grid-template-columns:1fr}.cards{grid-template-columns:repeat(2,1fr)}header{align-items:flex-start;flex-direction:column}.meta{text-align:left}.wrap{padding:18px}}@media(max-width:450px){.cards{grid-template-columns:1fr}.details{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<header><div><h1>Citi Bike operations</h1><div class="muted">Jersey City / Hoboken · station inventory snapshots</div></div><div class="meta"><div id="sourceTime">Source poll: —</div><div id="refreshTime">Page data refresh: —</div><div>Display timezone: <span id="timezone"></span> · automatic refresh every 10 seconds</div></div></header>
<div id="error" class="notice error" role="alert"></div>
<div class="toolbar"><button id="recorded" class="active">Recorded snapshots</button><button id="current">Current operations</button><button id="refresh">Refresh now</button></div>
<div id="notice" class="notice">Loading stored observations…</div>
<div class="cards" id="cards"></div>
<div class="grid"><section class="panel"><h2>Station inventory history</h2><label for="stationSelect" class="label">Choose a station</label><select id="stationSelect" style="width:100%"></select><div class="legend" style="margin-top:16px"><span class="bikes">Available bikes</span><span class="docks">Available docks</span></div><svg id="chart" role="img" aria-label="Available bikes and docks over collection time"></svg><div id="chartNote" class="muted" style="font-size:12px"></div></section>
<section class="panel"><h2>Selected station</h2><div id="details"></div></section></div>
<section class="panel"><h2>Stations and attention flags</h2><div class="tablebar"><input id="search" type="search" placeholder="Search station ID or name" aria-label="Search stations"><label><input id="attention" type="checkbox"> Attention only</label><span id="rowCount" class="muted"></span></div><div class="tablebox"><table><thead><tr><th>Station</th><th>Name</th><th>Bikes</th><th>Docks</th><th>Capacity</th><th>Source age</th><th>Status / attention</th></tr></thead><tbody id="stations"></tbody></table></div></section>
<section class="panel" style="margin-top:16px"><h2>Selected station snapshots</h2><div class="tablebox" style="max-height:230px"><table><thead><tr><th>Collected</th><th>Bikes</th><th>Docks</th><th>Disabled bikes</th><th>Disabled docks</th><th>Capacity</th><th>Net bike change</th><th>Quality warnings</th></tr></thead><tbody id="history"></tbody></table></div></section>
<div id="evidence" class="footer"></div><div class="footer">Recorded mode displays retained observations; it does not make old data current. Current mode includes only fresh, fully operational stations in its totals. A page refresh is not a source update. Low bikes / docks: thresholds saved with each snapshot. Inventory changes are net changes in available bikes, not observed ride counts. Utilization = (available + disabled bikes) / reported capacity; unknown inputs produce N/A. Historical demand risk is not connected yet.</div>
</div><script>
let state=null,mode='recorded',selected=null,requestNumber=0;
const el=id=>document.getElementById(id),safe=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=n=>Number(n||0).toLocaleString();
const when=v=>v?new Date(typeof v==='number'?v*1000:v).toLocaleString(): '—';
const age=s=>s==null?'—':s<0?'future clock':s<60?Math.floor(s)+'s':s<3600?Math.floor(s/60)+'m':s<86400?Math.floor(s/3600)+'h':Math.floor(s/86400)+'d';
const pill=(s,c='')=>`<span class="pill ${c}">${safe(s)}</span>`;
el('timezone').textContent=Intl.DateTimeFormat().resolvedOptions().timeZone;
function cards(){const rows=state.stations,chosen=rows.filter(r=>r.is_operational && (mode==='recorded'||!r.is_stale));const sums=k=>chosen.reduce((n,r)=>n+Number(r[k]||0),0);const data=[[mode==='recorded'?'Recorded operating stations':'Fresh operating stations',chosen.length,'Installed, renting and returning'],[mode==='recorded'?'Recorded available bikes':'Current available bikes',sums('bikes_available'),mode==='recorded'?'Latest retained station records':'Fresh operating stations only'],[mode==='recorded'?'Recorded available docks':'Current available docks',sums('docks_available'),mode==='recorded'?'Latest retained station records':'Fresh operating stations only'],['Stale / unavailable source records',rows.filter(r=>r.is_stale).length,'Excluded from current totals']];el('cards').innerHTML=data.map(([l,n,d])=>`<div class="card"><div class="muted">${l}</div><div class="number">${num(n)}</div><small>${d}</small></div>`).join('')}
function badges(r){let b=[];if(r.is_stale)b.push(pill('Stale','bad'));if(!r.is_operational)b.push(pill('Restricted','bad'));if(r.low_bike)b.push(pill('Low bikes','warn'));if(r.low_dock)b.push(pill('Low docks','warn'));if(r.warnings.length)b.push(pill('Quality warning','warn'));if(!r.present_in_latest_poll)b.push(pill('Missing latest','bad'));if(r.source_regressed)b.push(pill('Source regressed','bad'));return b.join(' ')||pill('Normal','good')}
function table(){if(!state)return;let q=el('search').value.toLowerCase(),attention=el('attention').checked;let rows=state.stations.filter(r=>(`${r.short_name} ${r.station_id} ${r.name}`).toLowerCase().includes(q)).filter(r=>!attention||r.is_stale||!r.is_operational||r.low_bike||r.low_dock||r.warnings.length);el('rowCount').textContent=`${rows.length} / ${state.stations.length} stations`;el('stations').innerHTML=rows.map(r=>`<tr data-id="${safe(r.station_id)}" class="${r.station_id===selected?'selected':''}"><td>${safe(r.short_name)}</td><td class="name">${safe(r.name)}</td><td>${num(r.bikes_available)}</td><td>${num(r.docks_available)}</td><td>${safe(r.capacity)}</td><td>${age(r.station_age_seconds)}</td><td>${badges(r)}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">No matching stations.</td></tr>';el('stations').querySelectorAll('tr[data-id]').forEach(row=>row.onclick=()=>{selected=row.dataset.id;load()})}
function details(){let r=state.stations.find(r=>r.station_id===selected);if(!r){el('details').textContent='No stations available.';return}let d=[['Historical-style ID',r.short_name],['GBFS source ID',r.station_id],['Name',r.name],['Latest snapshot collected',when(r.observed_at)],['Station reported',when(r.source_reported_at)],['Feed updated',when(r.source_feed_time)],['Bikes / docks',`${r.bikes_available} / ${r.docks_available}`],['Capacity',r.capacity??'Unknown'],['Utilization',r.utilization==null?'N/A':(r.utilization*100).toFixed(1)+'%'],['Installed / renting / returning',`${r.is_installed} / ${r.is_renting} / ${r.is_returning}`],['Latitude / longitude',`${r.latitude} / ${r.longitude}`],['Low bikes / docks thresholds',`${r.low_bike_threshold} / ${r.low_dock_threshold}`]];el('details').innerHTML=badges(r)+`<div class="details">${d.map(([l,v])=>`<div><div class="label">${l}</div><div class="value">${safe(v)}</div></div>`).join('')}</div>`+(r.warnings.length?`<div class="notice" style="margin-top:14px">${r.warnings.map(safe).join(', ')}</div>`:'')}
function chart(){let rows=state.history,svg=el('chart');let W=600,H=230,L=44,R=18,T=18,B=40;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);if(!rows.length){svg.innerHTML='<text x="30" y="100" fill="#637084">No stored snapshots for this station.</text>';return}let times=rows.map(r=>Date.parse(r.observed_at)),lo=Math.min(...times),hi=Math.max(...times),max=Math.max(1,...rows.flatMap(r=>[r.bikes_available,r.docks_available]));let x=t=>L+(t-lo)/(hi-lo||1)*(W-L-R),y=v=>H-B-v/max*(H-T-B);let parts=[];for(let i=0;i<=4;i++){let v=max*i/4;parts.push(`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#e7ecf2"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="#637084">${Number(v.toFixed(1))}</text>`)}for(let [field,color] of [['bikes_available','#2864a7'],['docks_available','#de9545']]){let points=rows.map((r,i)=>`${x(times[i])},${y(r[field])}`).join(' ');parts.push(`<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.4"/>`);if(rows.length<=60)rows.forEach((r,i)=>parts.push(`<circle cx="${x(times[i])}" cy="${y(r[field])}" r="3" fill="${color}"><title>${safe(when(r.observed_at))}: ${safe(field)} ${r[field]}</title></circle>`))}let label=t=>new Date(t).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});parts.push(`<text x="${L}" y="${H-14}" font-size="11" fill="#637084">${label(lo)}</text><text x="${W-R}" y="${H-14}" text-anchor="end" font-size="11" fill="#637084">${label(hi)}</text>`);svg.innerHTML=parts.join('');el('chartNote').textContent=`${rows.length} retained snapshots shown (latest 600 maximum). X-axis uses actual collection times. Lines connect recorded points; gaps contain no observations.`}
function history(){el('history').innerHTML=state.history.map(r=>`<tr><td>${safe(when(r.observed_at))}</td><td>${r.bikes_available}</td><td>${r.docks_available}</td><td>${safe(r.bikes_disabled)}</td><td>${safe(r.docks_disabled)}</td><td>${safe(r.capacity)}</td><td>${r.net_bike_inventory_change==null?'N/A':r.net_bike_inventory_change>0?'+'+r.net_bike_inventory_change:r.net_bike_inventory_change}</td><td>${r.warnings.map(safe).join(', ')||'—'}</td></tr>`).join('')}
function render(){el('sourceTime').textContent='Latest successful poll: '+when(state.latest_successful_poll?.observed_at);el('refreshTime').textContent='Page data refresh: '+when(state.dashboard_refreshed_at);let stale=state.stations.filter(r=>r.is_stale).length;el('notice').textContent=mode==='recorded'?`RECORDED SNAPSHOTS — ${stale} of ${state.stations.length} retained station records are stale. The displayed inventory is historical, not current availability.`:`CURRENT OPERATIONS — ${stale} of ${state.stations.length} station records are stale and excluded from current totals. Keep the collector running to receive new snapshots.`;if(state.last_attempt?.outcome==='failed')el('notice').textContent+=' Latest collection attempt failed: '+state.last_attempt.error;el('stationSelect').innerHTML=state.stations.map(r=>`<option value="${safe(r.station_id)}">${safe(r.short_name)} · ${safe(r.name)}</option>`).join('');el('stationSelect').value=selected;cards();table();details();chart();history();let e=state.evidence;el('evidence').textContent=`Collection evidence: ${e.successful_polls} successful polls · ${e.distinct_batches} distinct payload batches · ${e.snapshot_rows} retained station snapshots · ${e.quarantined_records} quarantined records. First success: ${when(e.first_success)}. Last success: ${when(e.last_success)}.`}
async function load(){let id=++requestNumber;try{let response=await fetch('/api/state'+(selected?'?station='+encodeURIComponent(selected):''),{cache:'no-store'});let data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');if(id!==requestNumber)return;state=data;selected=data.selected_station_id;el('error').style.display='none';render()}catch(e){if(id!==requestNumber)return;el('error').style.display='block';el('error').textContent='Dashboard read failed. Any previously shown values are retained and may be outdated. '+e.message;if(mode==='current')el('cards').innerHTML='<div class="card">Current totals unavailable until the next successful read.</div>'}}
for(let m of ['recorded','current'])el(m).onclick=()=>{mode=m;el('recorded').classList.toggle('active',m==='recorded');el('current').classList.toggle('active',m==='current');if(state)render()};el('refresh').onclick=load;el('stationSelect').onchange=e=>{selected=e.target.value;load()};el('search').oninput=table;el('attention').onchange=table;load();setInterval(load,10000);
</script></body></html>'''


def handler_for(database):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route=urlparse(self.path)
            if route.path=='/':
                body=HTML.encode();code=200;kind='text/html; charset=utf-8'
            elif route.path=='/api/state':
                try:
                    station=parse_qs(route.query).get('station',[None])[0]
                    body=json.dumps(get_state(database,station)).encode();code=200
                except (sqlite3.Error,FileNotFoundError,ValueError) as error:
                    body=json.dumps({'error':str(error)}).encode();code=503
                kind='application/json'
            elif route.path=='/favicon.ico':
                body=b'';code=204;kind='image/x-icon'
            else:
                body=b'Not found';code=404;kind='text/plain'
            self.send_response(code);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    return Handler


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8501)
    parser.add_argument('--db',type=Path,default=ROOT/'data'/'operations.sqlite')
    args=parser.parse_args()
    get_state(args.db) # Fail early on wrong path/schema; never create an empty DB.
    server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(args.db))
    print(f'Open http://127.0.0.1:{args.port} in your browser. Refresh interval: 10 seconds.',flush=True)
    print('Keep this terminal open. Ctrl+C stops the dashboard; collection runs separately.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
