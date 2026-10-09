"""Reproducible historical workflow; uses the existing pipeline.py."""
import argparse
import calendar
import csv
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from pipeline import ROOT, connect, download, ingest


def month_bounds(month):
    date = datetime.strptime(month, '%Y%m')
    if len(month) != 6 or not month.isdigit():
        raise ValueError('Month must be YYYYMM')
    first = date.strftime('%Y-%m-01')
    last = date.replace(day=calendar.monthrange(date.year,date.month)[1]).strftime('%Y-%m-%d')
    return first, last


def create_baseline(db, month):
    first, last = month_bounds(month)
    source_name = f'JC-{month}-citibike-tripdata.csv.zip'
    if not db.execute('SELECT 1 FROM processed_files WHERE file_name=?',(source_name,)).fetchone():
        raise ValueError('Baseline requires a successfully processed source month: '+month)
    view = 'station_hourly_baseline_'+month
    # Month is validated above. Store explicit calendar coverage in the view definition.
    sql = f'''CREATE VIEW {view} AS
    WITH RECURSIVE
    dates(day) AS (
      SELECT '{first}' UNION ALL
      SELECT date(day, '+1 day') FROM dates WHERE day < '{last}'
    ),
    hours(hour) AS (SELECT 0 UNION ALL SELECT hour+1 FROM hours WHERE hour<23),
    day_counts AS (
      SELECT (CAST(strftime('%w',day) AS INTEGER)+6)%7 AS weekday,
             COUNT(*) AS sample_days FROM dates GROUP BY weekday
    ),
    flows AS (
      SELECT station_id,local_date,local_hour,trips AS departures,0 AS arrivals
      FROM station_departures_hourly WHERE local_date BETWEEN '{first}' AND '{last}'
      UNION ALL
      SELECT station_id,local_date,local_hour,0 AS departures,trips AS arrivals
      FROM station_arrivals_hourly WHERE local_date BETWEEN '{first}' AND '{last}'
    ),
    stations AS (SELECT DISTINCT station_id FROM flows),
    totals AS (
      SELECT station_id,(CAST(strftime('%w',local_date) AS INTEGER)+6)%7 AS weekday,
             local_hour,SUM(departures) AS departures,SUM(arrivals) AS arrivals
      FROM flows GROUP BY station_id,weekday,local_hour
    )
    SELECT s.station_id,d.weekday,h.hour AS local_hour,d.sample_days,
      ROUND(COALESCE(t.departures,0)*1.0/d.sample_days,2) AS avg_departures,
      ROUND(COALESCE(t.arrivals,0)*1.0/d.sample_days,2) AS avg_arrivals,
      ROUND((COALESCE(t.departures,0)-COALESCE(t.arrivals,0))*1.0/d.sample_days,2)
        AS avg_net_outflow
    FROM stations s CROSS JOIN day_counts d CROSS JOIN hours h
    LEFT JOIN totals t ON t.station_id=s.station_id
      AND t.weekday=d.weekday AND t.local_hour=h.hour'''
    # Atomic replacement of this derived view only. Never delete trip records.
    with db:
        db.execute('DROP VIEW IF EXISTS '+view)
        db.execute(sql)
    return view


def validate(db, view):
    checks=[]
    def check(name, actual, expected):
        checks.append(dict(name=name,actual=actual,expected=expected,passed=actual==expected))
    def scalar(sql): return db.execute(sql).fetchone()[0]
    check('sqlite_integrity',scalar('PRAGMA integrity_check'),'ok')
    check('file_count_reconciliation',scalar('''SELECT COUNT(*) FROM processed_files
      WHERE raw_count != inserted_count+rejected_count+duplicate_count+conflict_count'''),0)
    check('trip_total_equals_inserted_total',scalar('SELECT COUNT(*) FROM fact_trip'),
          scalar('SELECT COALESCE(SUM(inserted_count),0) FROM processed_files'))
    check('quarantine_total',scalar('SELECT COUNT(*) FROM rejected_records'),
          scalar('SELECT COALESCE(SUM(rejected_count+conflict_count),0) FROM processed_files'))
    check('missing_or_duplicate_ride_id',scalar('''SELECT COUNT(*) FROM (
      SELECT ride_id FROM fact_trip GROUP BY ride_id
      HAVING ride_id IS NULL OR TRIM(ride_id)='' OR COUNT(*)>1)'''),0)
    check('invalid_duration',scalar('''SELECT COUNT(*) FROM fact_trip
      WHERE duration_seconds IS NULL OR duration_seconds<=0 OR duration_seconds>86400'''),0)
    check('end_before_or_equal_start',scalar('''SELECT COUNT(*) FROM fact_trip
      WHERE julianday(ended_at_utc)<=julianday(started_at_utc)
      OR julianday(ended_at_utc) IS NULL OR julianday(started_at_utc) IS NULL'''),0)
    check('invalid_time_attributes',scalar('''SELECT COUNT(*) FROM fact_trip
      WHERE local_hour IS NULL OR local_hour NOT BETWEEN 0 AND 23
      OR weekday IS NULL OR weekday NOT BETWEEN 0 AND 6
      OR is_weekend IS NULL OR is_weekend!=(weekday>=5)'''),0)
    total=scalar('SELECT COUNT(*) FROM fact_trip')
    check('daily_aggregate_total',scalar('SELECT COALESCE(SUM(trips),0) FROM trips_daily'),total)
    check('departure_aggregate_total',scalar('SELECT COALESCE(SUM(trips),0) FROM station_departures_hourly'),
          scalar('SELECT COUNT(*) FROM fact_trip WHERE start_station_id IS NOT NULL'))
    check('arrival_time_rows',scalar('SELECT COUNT(*) FROM trip_arrival_time'),total)
    check('orphan_arrival_rows',scalar('''SELECT COUNT(*) FROM trip_arrival_time a
      LEFT JOIN fact_trip t USING(ride_id) WHERE t.ride_id IS NULL'''),0)
    check('arrival_aggregate_total',scalar('SELECT COALESCE(SUM(trips),0) FROM station_arrivals_hourly'),
          scalar('SELECT COUNT(*) FROM fact_trip WHERE end_station_id IS NOT NULL'))
    first,last=month_bounds(view.rsplit('_',1)[-1])
    stations=db.execute('''SELECT COUNT(*) FROM (
      SELECT station_id FROM station_departures_hourly WHERE local_date BETWEEN ? AND ?
      UNION SELECT station_id FROM station_arrivals_hourly WHERE local_date BETWEEN ? AND ?)''',
      (first,last,first,last)).fetchone()[0]
    actual=scalar(f'SELECT COUNT(*) FROM {view}')
    check('baseline_grid_rows',actual,stations*7*24)
    check('baseline_unique_keys',scalar(f'''SELECT COUNT(*) FROM (
      SELECT station_id,weekday,local_hour FROM {view}
      GROUP BY station_id,weekday,local_hour HAVING COUNT(*)!=1)'''),0)
    check('baseline_calendar_sample_days',scalar(f'''SELECT COUNT(*) FROM {view}
      WHERE sample_days NOT BETWEEN 4 AND 5'''),0)
    if total==0 or stations==0:
        check('nonempty_data',0,1)
    return checks


def export_csv(db, path, sql, parameters=()):
    cursor=db.execute(sql,parameters)
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f); writer.writerow([c[0] for c in cursor.description])
        writer.writerows(cursor)
    temporary.replace(path)


def finish(root, month):
    first,last=month_bounds(month)
    reports=root/'data'/'reports'/month
    reports.mkdir(parents=True,exist_ok=True)
    with closing(connect(root)) as db:
        view=create_baseline(db,month)
        checks=validate(db,view)
        validation=dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),
                        analysis_month=month,all_passed=all(c['passed'] for c in checks),checks=checks)
        (reports/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
        if not validation['all_passed']:
            raise RuntimeError('Validation failed; see '+str(reports/'validation.json'))
        where=' WHERE local_date BETWEEN ? AND ? '
        queries={
          'trips_daily.csv': 'SELECT local_date,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY local_date ORDER BY local_date',
          'trips_hourly.csv': 'SELECT local_hour,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY local_hour ORDER BY local_hour',
          'hourly_weekday_weekend.csv': 'SELECT is_weekend,local_hour,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY is_weekend,local_hour ORDER BY is_weekend,local_hour',
          'rider_type.csv': 'SELECT rider_type,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY rider_type ORDER BY trips DESC',
          'bike_type.csv': 'SELECT bike_type,COUNT(*) AS trips FROM fact_trip'+where+'GROUP BY bike_type ORDER BY trips DESC',
          'duration_distribution.csv': '''SELECT CASE
            WHEN duration_seconds<300 THEN '1. Under 5 min'
            WHEN duration_seconds<900 THEN '2. 5-15 min'
            WHEN duration_seconds<1800 THEN '3. 15-30 min'
            WHEN duration_seconds<3600 THEN '4. 30-60 min'
            ELSE '5. 60+ min' END AS duration_group,COUNT(*) AS trips FROM fact_trip'''+where+'GROUP BY duration_group ORDER BY duration_group',
          'origin_stations.csv': 'SELECT start_station_id AS station_id,COUNT(*) AS departures FROM fact_trip'+where+'AND start_station_id IS NOT NULL GROUP BY start_station_id ORDER BY departures DESC',
          'station_departures_hourly.csv': 'SELECT * FROM station_departures_hourly'+where+'ORDER BY station_id,local_date,local_hour',
          'station_arrivals_hourly.csv': 'SELECT * FROM station_arrivals_hourly'+where+'ORDER BY station_id,local_date,local_hour',
        }
        for name,sql in queries.items(): export_csv(db,reports/name,sql,(first,last))
        export_csv(db,reports/'destination_stations.csv','''SELECT end_station_id AS station_id,COUNT(*) AS arrivals
          FROM fact_trip t JOIN trip_arrival_time a USING(ride_id)
          WHERE a.local_date BETWEEN ? AND ? AND end_station_id IS NOT NULL
          GROUP BY end_station_id ORDER BY arrivals DESC''',(first,last))
        export_csv(db,reports/'station_hourly_baseline.csv',f'SELECT * FROM {view} ORDER BY station_id,weekday,local_hour')
        export_csv(db,reports/'processed_files.csv','SELECT * FROM processed_files ORDER BY file_name')
        export_csv(db,reports/'rejection_reasons.csv','SELECT reason,COUNT(*) AS records FROM rejected_records GROUP BY reason')
        summary=dict(analysis_month=month,local_timezone='America/New_York (documented assumption)',
          total_database_trips=db.execute('SELECT COUNT(*) FROM fact_trip').fetchone()[0],
          analysis_trips=db.execute('SELECT COUNT(*) FROM fact_trip'+where,(first,last)).fetchone()[0],
          missing_origin_station=db.execute('SELECT COUNT(*) FROM fact_trip'+where+'AND start_station_id IS NULL',(first,last)).fetchone()[0],
          missing_destination_station=db.execute('SELECT COUNT(*) FROM fact_trip'+where+'AND end_station_id IS NULL',(first,last)).fetchone()[0],
          baseline_rows=db.execute(f'SELECT COUNT(*) FROM {view}').fetchone()[0],
          validation_checks=len(checks),output_directory=str(reports))
        (reports/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        (reports/'baseline_definition.sql').write_text(db.execute('SELECT sql FROM sqlite_master WHERE name=?',(view,)).fetchone()[0]+';\n',encoding='utf-8')
        return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--months',nargs='+',default=['202508','202509'])
    parser.add_argument('--analysis-month',default='202509')
    args=parser.parse_args()
    for month in [*args.months,args.analysis_month]: month_bounds(month)
    # Validate analysis source is among requested inputs or already processed.
    for month in dict.fromkeys([*args.months,args.analysis_month]):
        path,url=download(month,ROOT)
        print(json.dumps(ingest(path,ROOT,url),indent=2))
    print(json.dumps(finish(ROOT,args.analysis_month),indent=2))
    print('PHASE 1 CHECKS PASSED')

if __name__=='__main__': main()
