import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from poll_stations import open_db, process, stamp

class StationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.root=Path(self.folder.name)
        self.db=open_db(self.root)
        self.args=SimpleNamespace(interval=60,stale_after=300,low_bikes=3,low_docks=3)
        self.t=int(time.time())-120
    def tearDown(self):
        self.db.close();self.folder.cleanup()
    def payload(self,t,bikes=14,docks=6):
        info={'version':'2.3','ttl':60,'last_updated':t,'data':{'stations':[
          dict(station_id='uuid-a',short_name='JC009',name='Test station',lat=40.72,lon=-74.04,capacity=20,region_id='70'),
          dict(station_id='uuid-b',short_name='HB501',name='Other',lat=40.74,lon=-74.03,capacity=10,region_id='311')]}}
        status={'version':'2.3','ttl':60,'last_updated':t,'data':{'stations':[
          dict(station_id='uuid-a',num_bikes_available=bikes,num_docks_available=docks,
            num_bikes_disabled=0,num_docks_disabled=0,is_installed=1,is_renting=1,is_returning=1,last_reported=t),
          dict(station_id='uuid-b',num_bikes_available=5,num_docks_available=5,
            num_bikes_disabled=0,num_docks_disabled=0,is_installed=1,is_renting=1,is_returning=1,last_reported=t)]}}
        return info,status
    def collect(self,info,status,t):
        return process(self.db,self.root,info,status,json.dumps(info),json.dumps(status),stamp(t),self.args)
    def test_repeat_restart_and_net_change(self):
        i,s=self.payload(self.t);self.collect(i,s,self.t)
        self.assertEqual(self.collect(i,s,self.t+1)['outcome'],'repeated')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM station_snapshots').fetchone()[0],2)
        self.db.close();self.db=open_db(self.root)
        i,s=self.payload(self.t+60,11,9);self.collect(i,s,self.t+60)
        row=self.db.execute("SELECT net_bike_inventory_change FROM station_inventory_changes WHERE short_name='JC009' ORDER BY observed_at DESC LIMIT 1").fetchone()
        self.assertEqual(row[0],-3)
        self.assertEqual(self.db.execute("SELECT bikes_available FROM station_latest WHERE short_name='JC009'").fetchone()[0],11)
    def test_source_regression(self):
        i,s=self.payload(self.t);self.collect(i,s,self.t)
        i,s=self.payload(self.t-30,1,19);self.collect(i,s,self.t+60)
        row=self.db.execute("SELECT bikes_available,source_regressed,is_stale FROM station_latest WHERE short_name='JC009'").fetchone()
        self.assertEqual(tuple(row),(14,1,1))
    def test_stale_and_disabled_flags(self):
        i,s=self.payload(self.t-600,0,20);self.collect(i,s,self.t)
        row=self.db.execute("SELECT is_stale,low_bike FROM station_latest WHERE short_name='JC009'").fetchone()
        self.assertEqual(tuple(row),(1,1)) # Consumers must also filter is_stale=0.
        i,s=self.payload(self.t+60,0,20);s['data']['stations'][0]['is_renting']=0
        self.collect(i,s,self.t+60)
        self.assertEqual(self.db.execute("SELECT low_bike FROM station_latest WHERE short_name='JC009'").fetchone()[0],0)
    def test_invalid_count_and_missing_station(self):
        i,s=self.payload(self.t);self.collect(i,s,self.t)
        i,s=self.payload(self.t+60);s['data']['stations'][0]['num_bikes_available']=-1
        self.collect(i,s,self.t+60)
        row=self.db.execute("SELECT present_in_latest_poll,is_stale FROM station_latest WHERE short_name='JC009'").fetchone()
        self.assertEqual(tuple(row),(0,1))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM live_quarantine').fetchone()[0],1)
        i,s=self.payload(self.t+90);s['data']['stations']=s['data']['stations'][1:]
        result=self.collect(i,s,self.t+90)
        self.assertEqual(result['information_without_status'],1)
    def test_capacity_warning_and_transaction_rollback(self):
        i,s=self.payload(self.t,14,7);self.collect(i,s,self.t)
        row=self.db.execute("SELECT warnings,utilization FROM station_latest WHERE short_name='JC009'").fetchone()
        self.assertIn('inventory_capacity_mismatch',row[0])
        i,s=self.payload(self.t+60);i['data']['stations'][0]['capacity']=0
        self.collect(i,s,self.t+60)
        self.assertIsNone(self.db.execute("SELECT utilization FROM station_latest WHERE short_name='JC009'").fetchone()[0])
        i,s=self.payload(self.t+90);s['data']['stations'].append(s['data']['stations'][0])
        before=self.db.execute('SELECT COUNT(*) FROM station_snapshots').fetchone()[0]
        with self.assertRaises(ValueError): self.collect(i,s,self.t+90)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM station_snapshots').fetchone()[0],before)

if __name__=='__main__': unittest.main()
