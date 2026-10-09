"""Citi Bike GBFS 2.3 collector; stdlib only, Python 3.10+."""
import argparse
import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DISCOVERY='https://gbfs.citibikenyc.com/gbfs/2.3/gbfs.json'


def stamp(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch,timezone.utc).isoformat()


def open_db(root):
    (root/'data').mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'data'/'operations.sqlite',timeout=30)
    db.row_factory=sqlite3.Row
    db.executescript('''
    CREATE TABLE IF NOT EXISTS live_batches (
      batch_id TEXT PRIMARY KEY, observed_at TEXT, info_feed_time INTEGER,
      status_feed_time INTEGER, version TEXT, raw_path TEXT);
    CREATE TABLE IF NOT EXISTS live_polls (
      poll_id TEXT PRIMARY KEY, observed_at TEXT, outcome TEXT, batch_id TEXT,
      error TEXT, raw_path TEXT, requested_interval INTEGER, effective_interval INTEGER);
    CREATE TABLE IF NOT EXISTS station_snapshots (
      batch_id TEXT, station_id TEXT, short_name TEXT, name TEXT, observed_at TEXT,
      source_feed_time INTEGER, source_reported_at INTEGER, information_feed_time INTEGER,
      bikes_available INTEGER, docks_available INTEGER, capacity INTEGER,
      bikes_disabled INTEGER, docks_disabled INTEGER, is_installed INTEGER,
      is_renting INTEGER, is_returning INTEGER, latitude REAL, longitude REAL,
      region_id TEXT, warnings TEXT, stale_after_seconds INTEGER,
      low_bike_threshold INTEGER, low_dock_threshold INTEGER,
      PRIMARY KEY(batch_id,station_id));
    CREATE TABLE IF NOT EXISTS live_quarantine (
      batch_id TEXT, station_id TEXT, reason TEXT, raw_json TEXT);
    CREATE INDEX IF NOT EXISTS snapshot_station_time
      ON station_snapshots(station_id,source_reported_at,source_feed_time);
    DROP VIEW IF EXISTS station_latest;
    CREATE VIEW station_latest AS
    WITH ranked AS (
      SELECT s.*,ROW_NUMBER() OVER(PARTITION BY station_id
        ORDER BY source_reported_at DESC,source_feed_time DESC,observed_at DESC,batch_id DESC) AS rn
      FROM station_snapshots s
    ), newest AS (
      SELECT batch_id,observed_at FROM live_polls WHERE outcome IN ('processed','repeated')
      ORDER BY observed_at DESC,poll_id DESC LIMIT 1
    )
    SELECT r.*,
      (SELECT observed_at FROM newest) AS latest_successful_poll_at,
      EXISTS(SELECT 1 FROM station_snapshots p,newest n
        WHERE p.batch_id=n.batch_id AND p.station_id=r.station_id) AS present_in_latest_poll,
      EXISTS(SELECT 1 FROM station_snapshots p,newest n
        WHERE p.batch_id=n.batch_id AND p.station_id=r.station_id
        AND (p.source_reported_at<r.source_reported_at OR p.source_feed_time<r.source_feed_time)) AS source_regressed,
      CAST(strftime('%s','now') AS INTEGER)-source_reported_at AS station_age_seconds,
      CAST(strftime('%s','now') AS INTEGER)-source_feed_time AS feed_age_seconds,
      CASE WHEN
        CAST(strftime('%s','now') AS INTEGER)-source_reported_at NOT BETWEEN -60 AND stale_after_seconds
        OR CAST(strftime('%s','now') AS INTEGER)-source_feed_time NOT BETWEEN -60 AND stale_after_seconds
        OR EXISTS(SELECT 1 FROM station_snapshots p,newest n
          WHERE p.batch_id=n.batch_id AND p.station_id=r.station_id
          AND (p.source_reported_at<r.source_reported_at OR p.source_feed_time<r.source_feed_time))
        OR NOT EXISTS(SELECT 1 FROM station_snapshots p,newest n
          WHERE p.batch_id=n.batch_id AND p.station_id=r.station_id)
        THEN 1 ELSE 0 END AS is_stale,
      (is_installed=1 AND is_renting=1 AND is_returning=1) AS is_operational,
      CASE WHEN is_installed=1 AND is_renting=1 THEN bikes_available<=low_bike_threshold ELSE 0 END AS low_bike,
      CASE WHEN is_installed=1 AND is_returning=1 THEN docks_available<=low_dock_threshold ELSE 0 END AS low_dock,
      CASE WHEN capacity>0 AND bikes_available+bikes_disabled<=capacity
        THEN (bikes_available+bikes_disabled)*1.0/capacity ELSE NULL END AS utilization
    FROM ranked r WHERE rn=1;
    DROP VIEW IF EXISTS station_inventory_changes;
    CREATE VIEW station_inventory_changes AS
    WITH lagged AS (
      SELECT s.*,
        LAG(bikes_available) OVER w AS previous_bikes,
        LAG(source_reported_at) OVER w AS previous_reported_at,
        LAG(source_feed_time) OVER w AS previous_feed_time,
        LAG(observed_at) OVER w AS previous_observed_at,
        LAG(is_installed*is_renting*is_returning) OVER w AS previous_operational
      FROM station_snapshots s
      WINDOW w AS (PARTITION BY station_id ORDER BY observed_at,batch_id)
    )
    SELECT *,CASE WHEN source_reported_at>previous_reported_at
      AND source_reported_at-previous_reported_at<=stale_after_seconds
      AND is_installed*is_renting*is_returning=1 AND previous_operational=1
      AND CAST(strftime('%s',observed_at) AS INTEGER)-source_reported_at BETWEEN -60 AND stale_after_seconds
      AND CAST(strftime('%s',observed_at) AS INTEGER)-source_feed_time BETWEEN -60 AND stale_after_seconds
      AND CAST(strftime('%s',previous_observed_at) AS INTEGER)-previous_reported_at BETWEEN -60 AND stale_after_seconds
      AND CAST(strftime('%s',previous_observed_at) AS INTEGER)-previous_feed_time BETWEEN -60 AND stale_after_seconds
      THEN bikes_available-previous_bikes ELSE NULL END AS net_bike_inventory_change
    FROM lagged;
    ''')
    db.commit()
    return db


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'CitiBikeStudentProject/1.0'}),timeout=30) as response:
                raw=response.read()
            return json.loads(raw),raw.decode('utf-8')
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as error:
            if attempt==2: raise
            delay=2**attempt
            if isinstance(error,urllib.error.HTTPError) and error.code==429:
                try: delay=max(delay,int(error.headers.get('Retry-After','60')))
                except ValueError: delay=60
            time.sleep(delay)


def discover(root):
    data,raw=fetch(DISCOVERY)
    if data.get('version')!='2.3': raise ValueError('Expected GBFS 2.3; inspect schema before changing versions')
    feeds={f['name']:f['url'] for f in data['data']['en']['feeds']}
    for name in ['station_information','station_status']:
        if name not in feeds: raise ValueError('Missing feed '+name)
    folder=root/'data'/'raw_live';folder.mkdir(parents=True,exist_ok=True)
    (folder/'discovery.json').write_text(raw,encoding='utf-8')
    (folder/'feed_manifest.json').write_text(json.dumps(dict(discovery_url=DISCOVERY,
        discovered_at=stamp(),version='2.3',feeds=feeds),indent=2),encoding='utf-8')
    return feeds


def count(value,label,optional=False):
    if value is None and optional: return None
    if type(value) is not int or value<0: raise ValueError('invalid_'+label)
    return value


def normalize(info,status,observed,info_time,status_time,batch_id,stale_after,low_bikes,low_docks):
    station_id=str(status.get('station_id','')).strip()
    if not station_id or station_id!=str(info.get('station_id','')): raise ValueError('missing_or_unmatched_station_id')
    bikes=count(status.get('num_bikes_available'),'bikes_available')
    docks=count(status.get('num_docks_available'),'docks_available')
    capacity=count(info.get('capacity'),'capacity',True)
    disabled_bikes=count(status.get('num_bikes_disabled'),'bikes_disabled',True)
    disabled_docks=count(status.get('num_docks_disabled'),'docks_disabled',True)
    flags=[]
    for name in ['is_installed','is_renting','is_returning']:
        v=status.get(name)
        if v not in (0,1) or not isinstance(v,(int,bool)): raise ValueError('invalid_'+name)
        flags.append(int(v))
    reported=count(status.get('last_reported'),'last_reported')
    if reported<=0: raise ValueError('missing_last_reported')
    lat=float(info['lat']);lon=float(info['lon'])
    if not (40<=lat<=42 and -75<=lon<=-72): raise ValueError('coordinates_outside_regional_bounds')
    warnings=[]
    if capacity is None or capacity==0: warnings.append('capacity_unknown_or_zero')
    if capacity is not None and disabled_bikes is not None and disabled_docks is not None:
        if bikes+docks+disabled_bikes+disabled_docks!=capacity: warnings.append('inventory_capacity_mismatch')
    observed_epoch=datetime.fromisoformat(observed).timestamp()
    if reported>observed_epoch+60: raise ValueError('future_station_report')
    # Missing disabled counts stay NULL; utilization is unknown, not fabricated.
    return (batch_id,station_id,info.get('short_name'),info.get('name'),observed,status_time,
      reported,info_time,bikes,docks,capacity,disabled_bikes,disabled_docks,*flags,lat,lon,
      str(info.get('region_id','')),json.dumps(warnings),stale_after,low_bikes,low_docks)


def process(db,root,info,status,raw_info,raw_status,observed,args):
    for payload in (info,status):
        if payload.get('version')!='2.3': raise ValueError('unexpected_gbfs_version')
        count(payload.get('last_updated'),'feed_time');count(payload.get('ttl'),'ttl')
        if not isinstance(payload.get('data',{}).get('stations'),list): raise ValueError('missing_station_array')
    batch_id=hashlib.sha256((raw_info+'\n'+raw_status).encode()).hexdigest()
    raw_dir=root/'data'/'raw_live'/observed[:10];raw_dir.mkdir(parents=True,exist_ok=True)
    raw_path=raw_dir/(batch_id+'.json')
    if not raw_path.exists():
        raw_path.write_text(json.dumps(dict(observed_at=observed,mode='live',
            station_information_raw=raw_info,station_status_raw=raw_status),ensure_ascii=False),encoding='utf-8')
    interval=max(args.interval,info['ttl'],status['ttl'],30)
    poll_id=str(uuid.uuid4())
    with db:
        repeated=db.execute('SELECT 1 FROM live_batches WHERE batch_id=?',(batch_id,)).fetchone() is not None
        inserted=rejected=missing=0
        if not repeated:
            all_info={}
            for row in info['data']['stations']:
                sid=str(row.get('station_id',''))
                if not sid or sid in all_info: raise ValueError('invalid_or_duplicate_information_station_id')
                all_info[sid]=row
            selected={sid:row for sid,row in all_info.items() if str(row.get('short_name','')).startswith(('JC','HB'))}
            if not selected: raise ValueError('No JC/HB stations; inspect selection rule')
            seen=set()
            for row in status['data']['stations']:
                sid=str(row.get('station_id',''))
                if not sid or sid in seen: raise ValueError('invalid_or_duplicate_status_station_id')
                seen.add(sid)
                if sid not in all_info:
                    db.execute('INSERT INTO live_quarantine VALUES(?,?,?,?)',
                        (batch_id,sid,'status_without_information_scope_unknown',json.dumps(row)))
                    rejected+=1
                    continue
                if sid not in selected: continue
                try:
                    record=normalize(selected[sid],row,observed,info['last_updated'],status['last_updated'],
                      batch_id,args.stale_after,args.low_bikes,args.low_docks)
                    db.execute('INSERT INTO station_snapshots VALUES('+','.join(['?']*len(record))+')',record)
                    inserted+=1
                except (ValueError,KeyError,TypeError) as e:
                    db.execute('INSERT INTO live_quarantine VALUES(?,?,?,?)',
                        (batch_id,sid,str(e),json.dumps(dict(information=selected[sid],status=row))))
                    rejected+=1
            for sid in selected.keys()-seen:
                db.execute('INSERT INTO live_quarantine VALUES(?,?,?,?)',
                    (batch_id,sid,'information_without_status',json.dumps(selected[sid])))
                missing+=1
            if not inserted: raise ValueError('No valid regional station rows; refuse latest update')
            db.execute('INSERT INTO live_batches VALUES(?,?,?,?,?,?)',
              (batch_id,observed,info['last_updated'],status['last_updated'],'2.3',str(raw_path)))
        db.execute('INSERT INTO live_polls VALUES(?,?,?,?,?,?,?,?)',
          (poll_id,observed,'repeated' if repeated else 'processed',batch_id,None,str(raw_path),args.interval,interval))
    latest=db.execute('''SELECT COUNT(*) AS known_stations,
      SUM(present_in_latest_poll) AS present_stations,SUM(is_stale) AS stale_stations,
      SUM(CASE WHEN is_stale=0 AND is_operational=1 THEN bikes_available ELSE 0 END) AS fresh_available_bikes,
      SUM(CASE WHEN is_stale=0 AND is_operational=1 THEN docks_available ELSE 0 END) AS fresh_available_docks,
      SUM(CASE WHEN is_stale=0 THEN low_bike ELSE 0 END) AS fresh_low_bike_stations,
      SUM(CASE WHEN is_stale=0 THEN low_dock ELSE 0 END) AS fresh_low_dock_stations
      FROM station_latest''').fetchone()
    report=dict(observed_at=observed,mode='live',gbfs_version='2.3',outcome='repeated' if repeated else 'processed',
      snapshots_inserted=inserted,quarantined=rejected,information_without_status=missing,
      effective_interval_seconds=interval,**dict(latest),
      retained_snapshot_rows=db.execute('SELECT COUNT(*) FROM station_snapshots').fetchone()[0],
      successful_poll_count=db.execute("SELECT COUNT(*) FROM live_polls WHERE outcome IN ('processed','repeated')").fetchone()[0])
    reports=root/'data'/'reports'/'live';reports.mkdir(parents=True,exist_ok=True)
    temp=reports/'collection_summary.tmp';temp.write_text(json.dumps(report,indent=2),encoding='utf-8')
    temp.replace(reports/'collection_summary.json')
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cycles',type=int,default=3,help='0 means keep polling until Ctrl+C')
    parser.add_argument('--interval',type=int,default=60)
    parser.add_argument('--stale-after',type=int,default=300)
    parser.add_argument('--low-bikes',type=int,default=3)
    parser.add_argument('--low-docks',type=int,default=3)
    args=parser.parse_args()
    if args.cycles<0 or args.interval<30 or args.stale_after<30 or min(args.low_bikes,args.low_docks)<0:
        parser.error('cycles>=0, interval/stale-after>=30, thresholds>=0 required')
    feeds=discover(ROOT)
    print('GBFS 2.3; scope=JC/HB short_name; collecting live station snapshots',flush=True)
    failed=0
    with closing(open_db(ROOT)) as db:
        last=db.execute("SELECT observed_at,effective_interval FROM live_polls WHERE outcome IN ('processed','repeated') ORDER BY observed_at DESC LIMIT 1").fetchone()
        if last:
            remaining=max(args.interval,last['effective_interval'])-(time.time()-datetime.fromisoformat(last['observed_at']).timestamp())
            if remaining>0:
                print(f'Restart: waiting {remaining:.1f}s to respect the previous polling interval',flush=True)
                time.sleep(remaining)
        cycle=0
        while args.cycles==0 or cycle<args.cycles:
            cycle+=1;interval=args.interval
            try:
                info,raw_info=fetch(feeds['station_information'])
                status,raw_status=fetch(feeds['station_status'])
                observed=stamp()
                report=process(db,ROOT,info,status,raw_info,raw_status,observed,args)
                interval=report['effective_interval_seconds']
                print(json.dumps(report,indent=2),flush=True)
            except (KeyboardInterrupt,SystemExit): raise
            except Exception as e:
                failed+=1
                with db: db.execute('INSERT INTO live_polls VALUES(?,?,?,?,?,?,?,?)',
                    (str(uuid.uuid4()),stamp(),'failed',None,str(e),None,args.interval,interval))
                print(json.dumps(dict(outcome='failed',error=str(e))),flush=True)
            if args.cycles==0 or cycle<args.cycles: time.sleep(interval)
    if failed: raise SystemExit('Collection ended with failed polls; inspect live_polls before claiming complete evidence')

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('Stopped; committed snapshots are retained.')
