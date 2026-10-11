"""Local batch orchestration, persistent daily UTC schedule and acceptance."""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from compare_inventory import read_db
from run_phase1 import month_bounds, validate

ROOT=Path(__file__).resolve().parent
TESTS=['test_pipeline','test_stations','test_operations_dashboard','test_compare_inventory','test_platform_dashboard','test_workflow']


def config(path):
    c=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(c.get('months'),list) or not c['months']: raise ValueError('Nonempty months list required')
    for m in [*c['months'],c['analysis_month']]: month_bounds(m)
    if c['analysis_month'] not in c['months']: raise ValueError('analysis_month must be listed in months')
    datetime.strptime(c['daily_at_utc'],'%H:%M')
    if not 1<=c['batch_attempts']<=5 or not 0<=c['retry_seconds']<=60: raise ValueError('Invalid retry configuration')
    return c


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    f=path.open('a+b')
    try:
        f.seek(0,2)
        if f.tell()==0: f.write(b'0');f.flush()
        f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error: raise RuntimeError('Another workflow holds '+str(path)) from error
        yield
    finally: f.close() # OS releases the advisory lock, including after process termination.


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2),encoding='utf-8');temp.replace(path)


def due(c,now,state):
    hour,minute=map(int,c['daily_at_utc'].split(':'))
    return (now.hour,now.minute)>=(hour,minute) and state.get('last_attempt_date')!=str(now.date())


def batch(c):
    logdir=ROOT/'data/logs';logdir.mkdir(parents=True,exist_ok=True)
    path=logdir/('batch_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.log')
    command=[sys.executable,'-u',str(ROOT/'run_phase1.py'),'--months',*c['months'],'--analysis-month',c['analysis_month']]
    with lock(ROOT/'data/workflow_batch.lock'),path.open('w',encoding='utf-8') as log:
        for attempt in range(1,c['batch_attempts']+1):
            log.write(f'Attempt {attempt}; UTC {datetime.now(timezone.utc).isoformat()}\n');log.flush()
            result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode==0:
                print('Batch passed. Log:',path,flush=True);return
            if attempt<c['batch_attempts']: time.sleep(c['retry_seconds'])
    raise RuntimeError('Batch failed after retries. Inspect '+str(path))


def acceptance(c):
    atomic_json(ROOT/'data/reports/final_acceptance.json',dict(status='running',checked_at=datetime.now(timezone.utc).isoformat(),root=str(ROOT)))
    subprocess.run([sys.executable,'-m','unittest',*TESTS,'-v'],cwd=ROOT,check=True)
    with closing(read_db(ROOT/'data/citibike.sqlite')) as db:
        checks=validate(db,'station_hourly_baseline_'+c['analysis_month'])
        if any(not row['passed'] for row in checks): raise ValueError('Historical validation failed: '+json.dumps(checks))
        total=db.execute('SELECT COUNT(*) FROM fact_trip').fetchone()[0]
    with closing(read_db(ROOT/'data/operations.sqlite')) as db:
        required={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'station_snapshots','live_polls','live_batches','live_quarantine'}<=required: raise ValueError('Operational schema incomplete')
        checks_live={
          'invalid_identifiers':"SELECT COUNT(*) FROM station_snapshots WHERE station_id IS NULL OR TRIM(station_id)='' OR batch_id IS NULL OR TRIM(batch_id)=''",
          'invalid_counts':"SELECT COUNT(*) FROM station_snapshots WHERE bikes_available IS NULL OR docks_available IS NULL OR bikes_available<0 OR docks_available<0 OR capacity<0 OR bikes_disabled<0 OR docks_disabled<0",
          'invalid_coordinates':"SELECT COUNT(*) FROM station_snapshots WHERE latitude IS NULL OR longitude IS NULL OR latitude NOT BETWEEN 40 AND 42 OR longitude NOT BETWEEN -75 AND -72",
          'duplicate_snapshot_keys':"SELECT COUNT(*) FROM (SELECT batch_id,station_id FROM station_snapshots GROUP BY batch_id,station_id HAVING COUNT(*)>1)",
          'orphan_batches':"SELECT COUNT(*) FROM station_snapshots s LEFT JOIN live_batches b USING(batch_id) WHERE b.batch_id IS NULL",
          'incorrect_fresh_classification':"SELECT COUNT(*) FROM station_latest WHERE is_stale=0 AND (station_age_seconds NOT BETWEEN -60 AND stale_after_seconds OR feed_age_seconds NOT BETWEEN -60 AND stale_after_seconds OR source_regressed=1 OR present_in_latest_poll=0)"}
        live_results={name:db.execute(sql).fetchone()[0] for name,sql in checks_live.items()}
        if any(live_results.values()): raise ValueError('Operational validation failed: '+json.dumps(live_results))
        snapshots=db.execute('SELECT COUNT(*) FROM station_snapshots').fetchone()[0]
        if not snapshots: raise ValueError('No collected snapshots')
        evidence=dict(db.execute("SELECT COUNT(*) AS successful_polls,MIN(observed_at) AS first_poll,MAX(observed_at) AS last_poll FROM live_polls WHERE outcome IN ('processed','repeated')").fetchone())
        evidence['stale_latest']=db.execute('SELECT COUNT(*) FROM station_latest WHERE is_stale=1').fetchone()[0]
        evidence['quality_warning_rows']=db.execute("SELECT COUNT(*) FROM station_snapshots WHERE warnings!='[]'").fetchone()[0]
        evidence['quarantined_records']=db.execute('SELECT COUNT(*) FROM live_quarantine').fetchone()[0]
    subprocess.run([sys.executable,str(ROOT/'compare_inventory.py'),'--baseline-month',c['analysis_month'],'--recorded'],cwd=ROOT,check=True)
    # Exercise integrated serving calculations, without claiming browser validation.
    from platform_dashboard import Platform
    state=Platform(ROOT,c['analysis_month']).state()
    result=dict(status='passed',checked_at=datetime.now(timezone.utc).isoformat(),root=str(ROOT),
        historical_trips=total,historical_checks=len(checks),operational_checks=live_results,
        snapshots=snapshots,evidence=evidence,analysis_trips=state['historical']['stats']['trips'],
        browser_verification='User reported integrated page updates; this command checks data/API calculations, not browser rendering.')
    atomic_json(ROOT/'data/reports/final_acceptance.json',result)
    print(json.dumps(result,indent=2));print('FINAL CHECKS PASSED')


def schedule(c):
    statepath=ROOT/'data/scheduler_state.json'
    with lock(ROOT/'data/workflow_schedule.lock'):
        print('Daily batch at '+c['daily_at_utc']+' UTC. Keep this process running. Ctrl+C stops it.',flush=True)
        while True:
            now=datetime.now(timezone.utc)
            state=json.loads(statepath.read_text()) if statepath.exists() else {}
            if due(c,now,state):
                state=dict(last_attempt_date=str(now.date()),started_at=now.isoformat(),status='running')
                atomic_json(statepath,state)
                try: batch(c);state['status']='passed'
                except (RuntimeError,OSError) as error:
                    state['status']='failed';state['error']=str(error);print(error,flush=True)
                state['finished_at']=datetime.now(timezone.utc).isoformat();atomic_json(statepath,state)
            time.sleep(30)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['batch','schedule','check'])
    parser.add_argument('--config',type=Path,default=ROOT/'workflow.json')
    args=parser.parse_args()
    try:
        c=config(args.config)
        {'batch':batch,'schedule':schedule,'check':acceptance}[args.action](c)
    except KeyboardInterrupt: print('Stopped. Committed data and workflow logs remain.')
    except (OSError,ValueError,RuntimeError,sqlite3.Error,subprocess.CalledProcessError) as error:
        if args.action=='check':
            atomic_json(ROOT/'data/reports/final_acceptance.json',dict(status='failed',checked_at=datetime.now(timezone.utc).isoformat(),error=str(error)))
        parser.exit(1,str(error)+'\n')

if __name__=='__main__':main()
