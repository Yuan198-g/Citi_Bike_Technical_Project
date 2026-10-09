import csv
from contextlib import closing
import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from pipeline import ingest, normalize, utc_time

class PipelineTests(unittest.TestCase):
    def row(self, **changes):
        row = dict(ride_id='a',rideable_type='classic_bike',started_at='2025-09-01 08:00:00',
                   ended_at='2025-09-01 08:10:00',start_station_id='',end_station_id='JC1',
                   member_casual='member')
        row.update(changes)
        return row

    def test_time_and_invalid_duration(self):
        self.assertEqual(normalize(self.row())[8],600)
        self.assertIsNone(normalize(self.row())[9])
        with self.assertRaises(ValueError):
            normalize(self.row(ended_at='2025-09-01 07:00:00'))
        for value in ['2025-11-02 01:30:00','2025-03-09 02:30:00']:
            with self.assertRaises(ValueError): utc_time(value)

    def make_zip(self, path, rows):
        text = io.StringIO(); writer = csv.DictWriter(text,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
        with zipfile.ZipFile(path,'w') as z: z.writestr('trips.csv',text.getvalue())

    def test_duplicates_incremental_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'one.zip'
            self.make_zip(path,[self.row(),self.row(),self.row(ride_id='b',ended_at='bad')])
            result=ingest(path,root)
            self.assertEqual((result['inserted'],result['duplicates'],result['rejected']),(1,1,1))
            self.assertEqual(ingest(path,root)['total_trips'],1)
            path=root/'two.zip'
            self.make_zip(path,[self.row(),self.row(ride_id='c'),self.row(ended_at='2025-09-01 08:20:00')])
            result=ingest(path,root)
            self.assertEqual((result['inserted'],result['duplicates'],result['conflicts']),(1,1,1))
            bad=root/'bad.zip'
            with zipfile.ZipFile(bad,'w') as z:
                text=io.StringIO(); writer=csv.DictWriter(text,fieldnames=list(self.row()))
                writer.writeheader();writer.writerow(self.row(ride_id='d'))
                z.writestr('a.csv',text.getvalue()); z.writestr('z.csv','wrong_schema\nx\n')
            with self.assertRaises(ValueError): ingest(bad,root)
            with closing(sqlite3.connect(root/'data'/'citibike.sqlite')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM fact_trip').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT sum(trips) FROM trips_daily').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM processed_files').fetchone()[0],2)

if __name__=='__main__': unittest.main()
