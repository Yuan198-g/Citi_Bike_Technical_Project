import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from poll_stations import open_db, process, stamp
from operations_dashboard import get_state

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=open_db(self.root)
        self.args=SimpleNamespace(interval=60,stale_after=300,low_bikes=3,low_docks=3)
    def tearDown(self):
        self.db.close();self.temp.cleanup()
    def add(self,t,bikes=6,docks=17):
        info=dict(version='2.3',ttl=60,last_updated=t,data=dict(stations=[
          dict(station_id='source-a',short_name='JC009',name='Hamilton Park',lat=40.72,lon=-74.04,capacity=26)]))
        status=dict(version='2.3',ttl=60,last_updated=t,data=dict(stations=[
          dict(station_id='source-a',num_bikes_available=bikes,num_docks_available=docks,
            num_bikes_disabled=3,num_docks_disabled=0,is_installed=1,is_renting=1,is_returning=1,last_reported=t)]))
        process(self.db,self.root,info,status,json.dumps(info),json.dumps(status),stamp(t),self.args)
    def test_snapshot_history_and_warning(self):
        t=int(time.time())-120;self.add(t);self.add(t+60,docks=16)
        data=get_state(self.root/'data/operations.sqlite')
        self.assertEqual(data['evidence']['snapshot_rows'],2)
        self.assertEqual(data['selected_station_id'],'source-a')
        self.assertEqual(data['history'][0]['net_bike_inventory_change'],None)
        self.assertEqual(data['history'][1]['net_bike_inventory_change'],0)
        self.assertEqual(data['stations'][0]['warnings'],['inventory_capacity_mismatch'])
        self.assertEqual(data['stations'][0]['is_stale'],0)
    def test_old_data_remains_visible_and_stale(self):
        self.add(int(time.time())-1200)
        data=get_state(self.root/'data/operations.sqlite')
        self.assertEqual(len(data['stations']),1)
        self.assertEqual(data['stations'][0]['bikes_available'],6)
        self.assertEqual(data['stations'][0]['is_stale'],1)
    def test_wrong_path_does_not_create_database(self):
        wrong=self.root/'nonexistent.sqlite'
        with self.assertRaises(FileNotFoundError):get_state(wrong)
        self.assertFalse(wrong.exists())

if __name__=='__main__':unittest.main()
