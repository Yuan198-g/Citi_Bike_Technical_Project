"""Historical Citi Bike pipeline. Python 3.10+, standard library only."""
import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sqlite3
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
NY = ZoneInfo('America/New_York')
FIELDS = ['ride_id','rideable_type','started_at','ended_at','start_station_id',
          'end_station_id','member_casual']


def utc_time(value):
    """Reject ambiguous/nonexistent local times instead of inventing a DST fold."""
    local = datetime.fromisoformat(value)
    if local.tzinfo is not None:
        raise ValueError('unexpected_timezone')
    options = set()
    for fold in (0, 1):
        aware = local.replace(tzinfo=NY, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(NY).replace(tzinfo=None) == local:
            options.add(utc)
    if len(options) != 1:
        raise ValueError('ambiguous_or_nonexistent_local_time')
    return local, options.pop()


def normalize(row):
    if not row['ride_id'].strip():
        raise ValueError('missing_ride_id')
    start, start_utc = utc_time(row['started_at'])
    _, end_utc = utc_time(row['ended_at'])
    duration = (end_utc - start_utc).total_seconds()
    if not 0 < duration <= 86400:
        raise ValueError('duration_outside_0_to_24_hours')
    for prefix in ('start', 'end'):
        lat, lon = row.get(prefix+'_lat',''), row.get(prefix+'_lng','')
        if lat and not 40 <= float(lat) <= 42:
            raise ValueError('latitude_outside_regional_bounds')
        if lon and not -75 <= float(lon) <= -72:
            raise ValueError('longitude_outside_regional_bounds')
    return (row['ride_id'].strip(), row['rideable_type'], start_utc.isoformat(),
            end_utc.isoformat(), start.date().isoformat(), start.hour,
            start.weekday(), int(start.weekday() >= 5), duration,
            row['start_station_id'].strip() or None,
            row['end_station_id'].strip() or None, row['member_casual'])


def connect(root):
    db = sqlite3.connect(root/'data'/'citibike.sqlite')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS fact_trip (
      ride_id TEXT PRIMARY KEY, bike_type TEXT, started_at_utc TEXT, ended_at_utc TEXT,
      local_date TEXT, local_hour INTEGER, weekday INTEGER, is_weekend INTEGER,
      duration_seconds REAL, start_station_id TEXT, end_station_id TEXT, rider_type TEXT);
    CREATE TABLE IF NOT EXISTS processed_files (
      sha256 TEXT PRIMARY KEY, file_name TEXT, source_url TEXT, processed_at TEXT,
      raw_count INTEGER, inserted_count INTEGER, rejected_count INTEGER,
      duplicate_count INTEGER, conflict_count INTEGER);
    CREATE TABLE IF NOT EXISTS rejected_records (
      file_sha256 TEXT, csv_name TEXT, row_number INTEGER, reason TEXT, raw_json TEXT);
    CREATE VIEW IF NOT EXISTS trips_daily AS
      SELECT local_date, count(*) AS trips FROM fact_trip GROUP BY local_date;
    CREATE VIEW IF NOT EXISTS station_departures_hourly AS
      SELECT start_station_id AS station_id, local_date, local_hour, count(*) AS trips
      FROM fact_trip WHERE start_station_id IS NOT NULL
      GROUP BY start_station_id, local_date, local_hour;
    ''')
    # Arrival attributes are calculated in Python with the same timezone rules.
    db.execute('''CREATE TABLE IF NOT EXISTS trip_arrival_time (
      ride_id TEXT PRIMARY KEY REFERENCES fact_trip(ride_id), local_date TEXT,
      local_hour INTEGER)''')
    db.execute('''CREATE VIEW IF NOT EXISTS station_arrivals_hourly AS
      SELECT t.end_station_id AS station_id, a.local_date, a.local_hour, count(*) AS trips
      FROM fact_trip t JOIN trip_arrival_time a USING(ride_id)
      WHERE t.end_station_id IS NOT NULL GROUP BY t.end_station_id,a.local_date,a.local_hour''')
    db.commit()
    return db


def download(month, root):
    url = f'https://s3.amazonaws.com/tripdata/JC-{month}-citibike-tripdata.csv.zip'
    target = root/'data'/'raw'/month/url.rsplit('/',1)[-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target, url
    temporary = target.with_suffix('.part')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as out:
                shutil.copyfileobj(response, out)
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError('corrupt_zip')
            temporary.replace(target)
            return target, url
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def ingest(path, root, url='local-test-fixture'):
    (root/'data').mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    db = connect(root)
    try:
        if db.execute('SELECT 1 FROM processed_files WHERE sha256=?',(digest,)).fetchone():
            return {'status':'already_processed','file':path.name,
                    'total_trips':db.execute('SELECT count(*) FROM fact_trip').fetchone()[0]}
        counts = dict(raw=0, inserted=0, rejected=0, duplicates=0, conflicts=0)
        with db, zipfile.ZipFile(path) as archive:
            names = sorted(n for n in archive.namelist() if n.endswith('.csv') and not n.startswith('__MACOSX/'))
            if not names:
                raise ValueError('no_csv_files')
            for name in names:
                with archive.open(name) as stream:
                    reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig',newline=''))
                    if not set(FIELDS).issubset(reader.fieldnames or []):
                        raise ValueError('unexpected_schema: '+name)
                    for number, row in enumerate(reader, 2):
                        counts['raw'] += 1
                        try:
                            record = normalize(row)
                        except (ValueError, TypeError, KeyError, AttributeError) as error:
                            counts['rejected'] += 1
                            db.execute('INSERT INTO rejected_records VALUES(?,?,?,?,?)',
                                       (digest,name,number,str(error),json.dumps(row)))
                            continue
                        existing = db.execute('SELECT * FROM fact_trip WHERE ride_id=?',(record[0],)).fetchone()
                        if existing:
                            if existing == record:
                                counts['duplicates'] += 1
                            else:
                                counts['conflicts'] += 1
                                db.execute('INSERT INTO rejected_records VALUES(?,?,?,?,?)',
                                           (digest,name,number,'conflicting_ride_id_first_record_kept',json.dumps(row)))
                            continue
                        db.execute('INSERT INTO fact_trip VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',record)
                        arrival, _ = utc_time(row['ended_at'])
                        db.execute('INSERT INTO trip_arrival_time VALUES(?,?,?)',
                                   (record[0],arrival.date().isoformat(),arrival.hour))
                        counts['inserted'] += 1
            assert counts['raw'] == sum(counts[k] for k in ('inserted','rejected','duplicates','conflicts'))
            db.execute('INSERT INTO processed_files VALUES(?,?,?,?,?,?,?,?,?)',
                       (digest,path.name,url,datetime.now(timezone.utc).isoformat(),
                        counts['raw'],counts['inserted'],counts['rejected'],counts['duplicates'],counts['conflicts']))
        result = {'status':'processed','file':path.name,**counts,
                  'total_trips':db.execute('SELECT count(*) FROM fact_trip').fetchone()[0],
                  'missing_origin_station':db.execute('SELECT count(*) FROM fact_trip WHERE start_station_id IS NULL').fetchone()[0],
                  'missing_destination_station':db.execute('SELECT count(*) FROM fact_trip WHERE end_station_id IS NULL').fetchone()[0]}
        reports = root/'data'/'reports'; reports.mkdir(exist_ok=True)
        (reports/(digest+'.json')).write_text(json.dumps(result,indent=2))
        with (reports/'trips_daily.csv').open('w',newline='') as f:
            writer = csv.writer(f); writer.writerow(['local_date','trips'])
            writer.writerows(db.execute('SELECT * FROM trips_daily ORDER BY local_date'))
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--month', default='202509')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{6}',args.month):
        parser.error('--month must be YYYYMM')
    datetime.strptime(args.month,'%Y%m')
    path, url = download(args.month,ROOT)
    print(json.dumps(ingest(path,ROOT,url),indent=2))

if __name__ == '__main__':
    main()
