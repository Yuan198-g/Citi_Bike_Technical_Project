"""Integrated Citi Bike dashboard; Python standard library only."""
import argparse
import calendar
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import operations_dashboard as operations
from compare_inventory import NY, mapping, profiles, read_db, signal

ROOT=Path(__file__).resolve().parent


def historical_data(root, month):
    start=datetime.strptime(month,'%Y%m').date()
    last=start.replace(day=calendar.monthrange(start.year,start.month)[1])
    params=(start.isoformat(),last.isoformat())
    with closing(read_db(root/'data'/'citibike.sqlite')) as db:
        def query(sql): return [dict(r) for r in db.execute(sql,params)]
        where=' WHERE local_date BETWEEN ? AND ? '
        stats=query('SELECT COUNT(*) AS trips, SUM(start_station_id IS NULL) AS missing_origin, SUM(end_station_id IS NULL) AS missing_destination, AVG(duration_seconds)/60 AS mean_minutes FROM fact_trip'+where)[0]
        daily=query('SELECT local_date AS label,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY local_date ORDER BY local_date')
        hourly=query('SELECT local_hour AS label,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY local_hour ORDER BY local_hour')
        mix={col:query(f'SELECT {col} AS label,COUNT(*) AS trips FROM fact_trip'+where+f'GROUP BY {col} ORDER BY trips DESC') for col in ('rider_type','bike_type')}
        origins=query('SELECT start_station_id AS label,COUNT(*) AS trips FROM fact_trip'+where+'AND start_station_id IS NOT NULL GROUP BY start_station_id ORDER BY trips DESC LIMIT 10')
        destinations=[dict(r) for r in db.execute('''SELECT t.end_station_id AS label,COUNT(*) AS trips FROM fact_trip t
          JOIN trip_arrival_time a USING(ride_id) WHERE a.local_date BETWEEN ? AND ? AND t.end_station_id IS NOT NULL
          GROUP BY t.end_station_id ORDER BY trips DESC LIMIT 10''',params)]
        duration=query('''SELECT CASE WHEN duration_seconds<300 THEN '1. Under 5 min'
          WHEN duration_seconds<900 THEN '2. 5–15 min' WHEN duration_seconds<1800 THEN '3. 15–30 min'
          WHEN duration_seconds<3600 THEN '4. 30–60 min' ELSE '5. 60+ min' END AS label,
          COUNT(*) AS trips FROM fact_trip'''+where+'GROUP BY label ORDER BY label')
        weekday=query('SELECT is_weekend AS label,local_hour,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY is_weekend,local_hour ORDER BY is_weekend,local_hour')
        counts=Counter(int(start.replace(day=d).weekday()>=5) for d in range(1,last.day+1))
        for r in weekday: r['average_per_day']=round(r['trips']/counts[r['label']],2)
        bases=[dict(r) for r in db.execute('SELECT * FROM station_hourly_baseline_'+month)]
    days={r['label']:r['trips'] for r in daily}; hours={r['label']:r['trips'] for r in hourly}
    return dict(month=month,start=str(start),end=str(last),stats=stats,
        daily=[dict(label=str(start.replace(day=d)),trips=days.get(str(start.replace(day=d)),0)) for d in range(1,last.day+1)],
        hourly=[dict(label=h,trips=hours.get(h,0)) for h in range(24)],origins=origins,destinations=destinations,
        duration=duration,weekday=weekday,calendar_days=dict(counts),**mix),bases


class Platform:
    def __init__(self,root,month):
        datetime.strptime(month,'%Y%m')
        if len(month)!=6 or not month.isdigit(): raise ValueError('Month must be YYYYMM')
        self.root=root.resolve(); self.month=month
        self.historical,bases=historical_data(self.root,month)
        self.bases={(b['station_id'],b['weekday'],b['local_hour']):b for b in bases}
        self.historical_ids={b['station_id'] for b in bases}
        self.profiles=profiles(self.root/'data'/'raw'/month/f'JC-{month}-citibike-tripdata.csv.zip')
        operations.get_state(self.root/'data'/'operations.sqlite')

    def state(self,station=None):
        data=operations.get_state(self.root/'data'/'operations.sqlite',station)
        data['historical']=self.historical
        counts=Counter(r['short_name'] for r in data['stations'])
        poll=data['latest_successful_poll']
        data['comparison']={}
        for mode in ('recorded','current'):
            as_of=datetime.fromisoformat(poll['observed_at']) if mode=='recorded' and poll else datetime.now(timezone.utc)
            local=as_of.astimezone(NY)
            comparisons=[]
            for r in data['stations']:
                status,meters=mapping(r,self.profiles.get(r['short_name']),counts[r['short_name']]>1)
                if r['short_name'] not in self.historical_ids: status='no_historical_baseline_station'
                supported=status=='supported_by_id_name_location'
                base=self.bases.get((r['short_name'],local.weekday(),local.hour))
                row={**r,'warnings':json.dumps(r['warnings'])}
                attention,flow=signal(row,base,supported,as_of)
                comparisons.append(dict(station_id=r['station_id'],station=r['short_name'],name=r['name'],
                    bikes=r['bikes_available'],docks=r['docks_available'],mapping_status=status,distance_meters=meters,
                    sample_days=base['sample_days'] if base else None,
                    net_outflow=base['avg_net_outflow'] if supported and base else None,
                    remaining_hour_flow=flow,attention=attention))
            data['comparison'][mode]=dict(as_of_utc=as_of.isoformat(),local_time=local.isoformat(),
                mapping_counts=dict(Counter(r['mapping_status'] for r in comparisons)),rows=comparisons)
        data['paths']=dict(root=str(self.root),historical_database=str(self.root/'data/citibike.sqlite'),
            operations_database=str(self.root/'data/operations.sqlite'))
        return data


EXTRA=r'''
<section class="panel" style="margin-top:16px"><h2>Historical demand + inventory</h2>
<div class="notice" id="comparisonNote"></div>
<div class="tablebar" style="margin-top:12px"><input id="riskSearch" type="search" placeholder="Search station or name"><label><input id="riskAttention" type="checkbox" checked> Attention / unavailable only</label><span id="mappingCounts" class="muted"></span></div>
<div class="tablebox"><table><thead><tr><th>Station</th><th>Name</th><th>Bikes</th><th>Docks</th><th>Historical net / h</th><th>Illustrative remaining hour</th><th>Sample days</th><th>Indicator</th><th>Mapping</th></tr></thead><tbody id="riskRows"></tbody></table></div>
<div class="footer">Positive net = departures exceed arrivals; negative net = arrivals exceed departures. Pressure is a rule, not a forecast. Low bikes/docks are inventory thresholds. Unavailable indicators are not safe stations. Historical year/season, small samples, within-hour uniformity and rebalancing limit interpretation.</div></section>
<section class="panel" style="margin-top:16px"><h2>Historical analytics</h2><div id="coverage" class="notice"></div><div id="historicalCards" class="cards"></div>
<div class="grid"><section><h2>Trips by day</h2><div id="dailyChart"></div></section><section><h2>Trips by hour</h2><div id="hourlyChart"></div></section></div>
<div class="grid"><section><h2>Weekday hourly average</h2><div id="weekdayChart"></div></section><section><h2>Weekend hourly average</h2><div id="weekendChart"></div></section></div>
<div class="grid"><section><h2>Top origins</h2><div id="originChart"></div></section><section><h2>Top destinations</h2><div id="destinationChart"></div></section></div>
<div class="grid"><section><h2>Membership</h2><div id="memberChart"></div></section><section><h2>Bike type</h2><div id="bikeChart"></div></section></div>
<h2>Trip duration</h2><div id="durationChart"></div>
<div class="footer">Trip counts use local start date/hour in America/New_York (documented source-time assumption). Top destinations use local arrival date. Weekday/weekend charts divide hourly totals by all calendar days of that type, including zero-trip days. Duration uses accepted trips only. Missing stations remain in overall counts. Monthly historical data is cached at startup: restart this server after batch updates.</div></section>
<div id="databasePaths" class="footer"></div>
'''
JS=r'''
function barChart(target,rows,value='trips'){
 const max=Math.max(1,...rows.map(r=>Number(r[value])));
 el(target).innerHTML=rows.map(r=>`<div style="display:grid;grid-template-columns:110px 1fr 75px;gap:8px;align-items:center;margin:5px 0;font-size:12px"><span>${safe(r.label)}</span><div style="background:#edf1f6;height:12px"><div style="background:#2864a7;height:12px;width:${100*Number(r[value])/max}%"></div></div><span style="text-align:right">${safe(r[value])}</span></div>`).join('')||'<p>No data for this month.</p>';
}
function riskTable(){if(!state?.comparison)return;const c=state.comparison[mode];const q=el('riskSearch').value.toLowerCase();let rows=c.rows.filter(r=>(r.station+' '+r.name).toLowerCase().includes(q)&&(!el('riskAttention').checked||r.attention!=='no_threshold_trigger'));
 el('riskRows').innerHTML=rows.map(r=>`<tr data-id="${safe(r.station_id)}"><td>${safe(r.station)}</td><td class="name">${safe(r.name)}</td><td>${r.bikes}</td><td>${r.docks}</td><td>${safe(r.net_outflow)}</td><td>${safe(r.remaining_hour_flow)}</td><td>${safe(r.sample_days)}</td><td>${safe(r.attention)}</td><td>${safe(r.mapping_status)}</td></tr>`).join('');
 el('riskRows').querySelectorAll('tr').forEach(r=>r.onclick=()=>{selected=r.dataset.id;load()});
 el('mappingCounts').textContent=(c.mapping_counts.supported_by_id_name_location||0)+' supported mappings / '+c.rows.length+' stations';
 el('comparisonNote').textContent=(mode==='recorded'?'RECORDED EXAMPLE — evaluated at saved poll, not current availability. ':'CURRENT — stale/restricted/uncertain records have unavailable indicators. ')+ 'Historical month '+state.historical.month+'; matching New York weekday/hour: '+c.local_time+'. Remaining-hour net flow scales the historical hourly average by the remaining hour fraction. No validated shortage probability.';
}
function historical(){let h=state.historical,s=h.stats;el('coverage').textContent=`Coverage: ${h.start} to ${h.end}, Jersey City / Hoboken historical file; all accepted local-start trips. Historical period differs from live inventory period.`;
 el('historicalCards').innerHTML=[['Trips',s.trips],['Mean minutes',s.mean_minutes==null?'N/A':s.mean_minutes.toFixed(2)],['Missing origin',s.missing_origin||0],['Missing destination',s.missing_destination||0]].map(([label,v])=>`<div class="card">${label}<div class="number">${safe(v)}</div></div>`).join('');
 for(let [id,data] of [['dailyChart',h.daily],['hourlyChart',h.hourly],['originChart',h.origins],['destinationChart',h.destinations],['memberChart',h.rider_type],['bikeChart',h.bike_type],['durationChart',h.duration]])barChart(id,data);
 for(let [id,type] of [['weekdayChart',0],['weekendChart',1]]){let found=h.weekday.filter(r=>r.label===type);let rows=Array.from({length:24},(_,hour)=>({label:hour,average_per_day:found.find(r=>r.local_hour===hour)?.average_per_day||0}));barChart(id,rows,'average_per_day')}
 el('databasePaths').textContent='Historical database: '+state.paths.historical_database+' | Operations database: '+state.paths.operations_database;
}
const originalRender=render;
render=function(){originalRender();riskTable();historical()};
el('riskSearch').oninput=riskTable;el('riskAttention').onchange=riskTable;
'''
HTML=operations.HTML.replace('<title>Citi Bike operations</title>','<title>Citi Bike platform</title>').replace(
    '<div id="evidence"',EXTRA+'<div id="evidence"').replace('Historical demand risk is not connected yet.','Combined indicators are shown below.').replace(
    'load();setInterval(load,10000);',JS+'\nload();setInterval(load,10000);').replace("if(mode==='current')el('cards').innerHTML=","if(mode==='current'){el('riskRows').innerHTML='<tr><td colspan=9>Current comparison unavailable after read failure.</td></tr>';el('cards').innerHTML=").replace("next successful read.</div>'}}","next successful read.</div>'}}}")


def handler_for(platform):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route=urlparse(self.path)
            if route.path=='/': body=HTML.encode(); code=200; kind='text/html; charset=utf-8'
            elif route.path=='/api/state':
                try: body=json.dumps(platform.state(parse_qs(route.query).get('station',[None])[0])).encode(); code=200
                except (OSError,ValueError,sqlite3.Error) as error: body=json.dumps(dict(error=str(error))).encode(); code=503
                kind='application/json'
            else: body=b'Not found';code=404;kind='text/plain'
            self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--baseline-month',default='202509')
    parser.add_argument('--port',type=int,default=8502)
    args=parser.parse_args()
    try:
        platform=Platform(args.root,args.baseline_month)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(platform))
    except (OSError,ValueError,sqlite3.Error) as error: parser.exit(1,f'Startup failed: {error}\n')
    print('Historical DB:',platform.root/'data/citibike.sqlite',flush=True)
    print('Operations DB:',platform.root/'data/operations.sqlite',flush=True)
    print(f'Open http://127.0.0.1:{args.port}. Read refresh: 10 seconds. Keep this terminal open.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
