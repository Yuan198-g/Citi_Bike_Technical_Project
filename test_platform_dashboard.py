import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from platform_dashboard import historical_data

class HistoricalDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'data').mkdir()
        with closing(sqlite3.connect(self.root/'data/citibike.sqlite')) as db:
            db.executescript('''CREATE TABLE fact_trip(ride_id TEXT,local_date TEXT,local_hour INTEGER,is_weekend INTEGER,
                duration_seconds REAL,start_station_id TEXT,end_station_id TEXT,rider_type TEXT,bike_type TEXT);
                CREATE TABLE trip_arrival_time(ride_id TEXT,local_date TEXT,local_hour INTEGER);
                CREATE VIEW station_hourly_baseline_202509 AS SELECT 'JC009' AS station_id,0 AS weekday,
                8 AS local_hour,5 AS sample_days,1 AS avg_departures,0 AS avg_arrivals,1 AS avg_net_outflow;
                INSERT INTO fact_trip VALUES('a','2025-09-01',8,0,120,'JC009',NULL,'member','classic_bike');
                INSERT INTO fact_trip VALUES('b','2025-09-06',8,1,600,'JC009','JC010','casual','electric_bike');
                INSERT INTO fact_trip VALUES('c','2025-09-30',23,0,900,'JC009','JC010','member','classic_bike');
                INSERT INTO fact_trip VALUES('outside','2025-08-31',23,1,200,'JC009','JC010','casual','classic_bike');
                INSERT INTO trip_arrival_time VALUES('b','2025-09-06',8);
                INSERT INTO trip_arrival_time VALUES('c','2025-10-01',0);
                INSERT INTO trip_arrival_time VALUES('outside','2025-09-01',0);''')
    def tearDown(self): self.temp.cleanup()
    def test_month_filter_zero_days_and_missing_stations(self):
        h,_=historical_data(self.root,'202509')
        self.assertEqual(h['stats']['trips'],3)
        self.assertEqual(h['stats']['missing_destination'],1)
        self.assertEqual(len(h['daily']),30)
        self.assertEqual(len(h['hourly']),24)
        self.assertEqual(h['daily'][1]['trips'],0)
        for key in ('daily','hourly','rider_type','bike_type','duration'):
            self.assertEqual(sum(x['trips'] for x in h[key]),3)
    def test_calendar_denominators_and_arrival_date(self):
        h,_=historical_data(self.root,'202509')
        self.assertEqual(h['calendar_days'],{0:22,1:8})
        weekend=next(x for x in h['weekday'] if x['label']==1)
        self.assertEqual(weekend['average_per_day'],0.12)
        self.assertEqual(h['destinations'],[{'label':'JC010','trips':2}])
    def test_wrong_path_is_read_only(self):
        wrong=self.root/'absent'
        with self.assertRaises(FileNotFoundError):historical_data(wrong,'202509')
        self.assertFalse((wrong/'data/citibike.sqlite').exists())

if __name__=='__main__': unittest.main()
