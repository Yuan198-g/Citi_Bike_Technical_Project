"""Read-only historical/live comparison. Standard library, Python 3.10+."""
import argparse
import csv
import io
import json
import math
import re
import sqlite3
import statistics
import zipfile
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
NY = ZoneInfo('America/New_York')


def read_db(path):
    if not path.is_file():
        raise FileNotFoundError(f'Database not found: {path}')
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('BEGIN')
    return db


def distance(a, b, c, d):
    a,b,c,d = map(math.radians, (a,b,c,d))
    h = math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371000*2*math.asin(min(1, math.sqrt(h)))


def name_key(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def profiles(archive):
    points = defaultdict(list)
    names = defaultdict(Counter)
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            if not member.lower().endswith('.csv') or member.startswith('__MACOSX/'):
                continue
            with z.open(member) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig')):
                    for side in ('start','end'):
                        sid = (row.get(side+'_station_id') or '').strip()
                        if not sid: continue
                        name = (row.get(side+'_station_name') or '').strip()
                        if name: names[sid][name] += 1
                        try:
                            lat, lon = float(row[side+'_lat']), float(row[side+'_lng'])
                            if 40 <= lat <= 42 and -75 <= lon <= -72:
                                points[sid].append((lat,lon))
                        except (KeyError,ValueError,TypeError): pass
    out = {}
    for sid in names.keys() | points.keys():
        p = points[sid]
        out[sid] = dict(name=names[sid].most_common(1)[0][0] if names[sid] else '',
                        samples=len(p), latitude=statistics.median(x[0] for x in p) if p else None,
                        longitude=statistics.median(x[1] for x in p) if p else None)
    return out


def mapping(row, profile, duplicate=False):
    if duplicate: return 'ambiguous_live_short_name', None
    if not profile: return 'no_historical_profile', None
    if profile['samples'] < 5: return 'insufficient_location_evidence', None
    meters = distance(profile['latitude'],profile['longitude'],row['latitude'],row['longitude'])
    if meters > 150: return 'location_mismatch', round(meters,1)
    if name_key(profile['name']) != name_key(row['name']):
        return 'name_mismatch_review', round(meters,1)
    return 'supported_by_id_name_location', round(meters,1)


def signal(row, base, supported, as_of):
    if not supported: return 'mapping_not_supported', None
    if not base: return 'no_baseline', None
    stamp = as_of.timestamp()
    if (not row['present_in_latest_poll'] or row['source_regressed'] or
        any(not -60 <= stamp-row[k] <= row['stale_after_seconds']
            for k in ('source_reported_at','source_feed_time'))):
        return 'stale_or_unreliable_source', None
    if not row['is_operational']: return 'not_fully_operational', None
    if json.loads(row['warnings'] or '[]'): return 'quality_warning_review', None
    if base['sample_days'] < 4: return 'insufficient_baseline_days', None
    local = as_of.astimezone(NY)
    fraction = 1-(local.minute*60+local.second+local.microsecond/1e6)/3600
    flow = base['avg_net_outflow']*fraction
    if row['bikes_available'] <= row['low_bike_threshold']:
        return 'low_bikes_now', round(flow,2)
    if row['docks_available'] <= row['low_dock_threshold']:
        return 'low_docks_now', round(flow,2)
    if flow > 0 and flow >= row['bikes_available']:
        return 'historical_outflow_pressure', round(flow,2)
    if flow < 0 and -flow >= row['docks_available']:
        return 'historical_inflow_pressure', round(flow,2)
    return 'no_threshold_trigger', round(flow,2)


def write_csv(path, rows):
    with path.open('w',newline='',encoding='utf-8-sig') as file:
        if rows:
            writer=csv.DictWriter(file,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)


def run(root, month, recorded=False):
    if not re.fullmatch(r'\d{6}',month): raise ValueError('Month must be YYYYMM')
    datetime.strptime(month,'%Y%m')
    archive=root/'data'/'raw'/month/f'JC-{month}-citibike-tripdata.csv.zip'
    if not archive.is_file(): raise FileNotFoundError(f'Historical raw ZIP missing: {archive}')
    with closing(read_db(root/'data'/'citibike.sqlite')) as historical, closing(read_db(root/'data'/'operations.sqlite')) as live:
        view='station_hourly_baseline_'+month
        if not historical.execute('SELECT 1 FROM sqlite_master WHERE name=?',(view,)).fetchone():
            raise ValueError('Baseline missing. Run run_phase1.py for this analysis month first.')
        rows=[dict(r) for r in live.execute('SELECT * FROM station_latest ORDER BY short_name,station_id')]
        poll=live.execute("SELECT MAX(observed_at) FROM live_polls WHERE outcome IN ('processed','repeated')").fetchone()[0]
        if not rows or not poll: raise ValueError('Collect station data first')
        as_of=datetime.fromisoformat(poll) if recorded else datetime.now(timezone.utc)
        local=as_of.astimezone(NY)
        bases={r['station_id']:dict(r) for r in historical.execute(f'SELECT * FROM {view} WHERE weekday=? AND local_hour=?',(local.weekday(),local.hour))}
        ids={r[0] for r in historical.execute(f'SELECT DISTINCT station_id FROM {view}')}
    ps=profiles(archive)
    counts=Counter(r['short_name'] for r in rows)
    maps=[]; comparisons=[]
    for row in rows:
        p=ps.get(row['short_name'])
        status,meters=mapping(row,p,counts[row['short_name']]>1)
        if row['short_name'] not in ids: status='no_historical_baseline_station'
        supported=status=='supported_by_id_name_location'
        maps.append(dict(live_station_id=row['station_id'],historical_station_id=row['short_name'],
                         live_name=row['name'],historical_name=p['name'] if p else '',
                         location_samples=p['samples'] if p else 0,distance_meters=meters,mapping_status=status))
        base=bases.get(row['short_name'])
        attention,flow=signal(row,base,supported,as_of)
        comparisons.append(dict(station=row['short_name'],name=row['name'],mode='recorded_example' if recorded else 'current',
            as_of_utc=as_of.isoformat(),comparison_local_time=local.isoformat(),observed_at=row['observed_at'],
            bikes=row['bikes_available'],docks=row['docks_available'],mapping_status=status,baseline_month=month,
            sample_days=base['sample_days'] if base else None,avg_departures=base['avg_departures'] if supported and base else None,
            avg_arrivals=base['avg_arrivals'] if supported and base else None,
            avg_net_outflow=base['avg_net_outflow'] if supported and base else None,
            illustrative_remaining_hour_net_outflow=flow,attention=attention,warnings=row['warnings']))
    out=root/'data'/'reports'/'phase3'/month/('recorded' if recorded else 'current')
    out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'station_mapping.csv',maps)
    write_csv(out/'inventory_demand_comparison.csv',comparisons)
    supported_ids={m['historical_station_id'] for m in maps if m['mapping_status']=='supported_by_id_name_location'}
    write_csv(out/'historical_unmatched.csv',[dict(historical_station_id=sid,reason='no_supported_live_mapping') for sid in sorted(ids-supported_ids)])
    summary=dict(mode='recorded_example' if recorded else 'current',generated_at=datetime.now(timezone.utc).isoformat(),
        as_of_utc=as_of.isoformat(),latest_poll_utc=poll,baseline_month=month,live_stations=len(rows),
        supported_mappings=sum(m['mapping_status']=='supported_by_id_name_location' for m in maps),
        historical_stations_without_live_match=len(ids-{m['historical_station_id'] for m in maps if m['mapping_status']=='supported_by_id_name_location'}),
        mapping_counts=dict(Counter(m['mapping_status'] for m in maps)),attention_counts=dict(Counter(r['attention'] for r in comparisons)),
        output_directory=str(out),limitations=[
          'Heuristic comparison, not a calibrated probability or a stockout time prediction.',
          'Historical month may differ in year and season from inventory; representativeness is unvalidated.',
          '4 or 5 weekday samples are small; zero-day and month-long station availability assumptions remain.',
          'Net demand is assumed uniform within the remaining hour; variability and rebalancing are omitted.',
          'ID, dominant name and median location support a mapping, but do not prove unchanged station identity.',
          'Recorded mode evaluates freshness at the last successful poll, never at the current time.',
          'Two databases are read consistently individually, without a cross-database atomic snapshot.' ])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-month',default='202509')
    parser.add_argument('--recorded',action='store_true',help='Explicit historical snapshot example; not current availability')
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    try: run(args.root,args.baseline_month,args.recorded)
    except (OSError,ValueError,sqlite3.Error,zipfile.BadZipFile) as error:
        parser.exit(1,f'Comparison failed: {error}\n')
