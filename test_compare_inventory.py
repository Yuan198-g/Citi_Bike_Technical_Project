import json
import unittest
from datetime import datetime, timezone
from compare_inventory import mapping, signal

class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,9,12,30,tzinfo=timezone.utc)
        self.row=dict(latitude=40.7,longitude=-74.0,name='Example Station',
            present_in_latest_poll=1,source_regressed=0,source_reported_at=self.now.timestamp()-10,
            source_feed_time=self.now.timestamp()-5,stale_after_seconds=300,is_operational=1,
            warnings='[]',bikes_available=6,docks_available=15,low_bike_threshold=3,low_dock_threshold=3)
        self.base=dict(sample_days=5,avg_net_outflow=14)
        self.profile=dict(latitude=40.7,longitude=-74.,name='Example Station',samples=20)

    def test_mapping_requires_location_name_and_unique_id(self):
        self.assertEqual(mapping(self.row,self.profile)[0],'supported_by_id_name_location')
        self.assertEqual(mapping(self.row,self.profile,True)[0],'ambiguous_live_short_name')
        self.assertEqual(mapping(self.row,{**self.profile,'latitude':40.8})[0],'location_mismatch')
        self.assertEqual(mapping(self.row,{**self.profile,'name':'Other'})[0],'name_mismatch_review')

    def test_remaining_hour_and_direction(self):
        self.assertEqual(signal(self.row,self.base,True,self.now),('historical_outflow_pressure',7.0))
        self.assertEqual(signal(self.row,{**self.base,'avg_net_outflow':10},True,self.now)[0],'no_threshold_trigger')
        self.assertEqual(signal(self.row,{**self.base,'avg_net_outflow':-40},True,self.now)[0],'historical_inflow_pressure')

    def test_stale_mapping_and_quality_suppress_signal(self):
        self.assertEqual(signal(self.row,self.base,False,self.now)[0],'mapping_not_supported')
        old={**self.row,'source_reported_at':self.now.timestamp()-301}
        self.assertEqual(signal(old,self.base,True,self.now)[0],'stale_or_unreliable_source')
        warning={**self.row,'warnings':json.dumps(['inventory_capacity_mismatch'])}
        self.assertEqual(signal(warning,self.base,True,self.now)[0],'quality_warning_review')
        self.assertEqual(signal({**self.row,'source_regressed':1},self.base,True,self.now)[0],'stale_or_unreliable_source')

    def test_small_sample_and_restricted_station(self):
        self.assertEqual(signal(self.row,{**self.base,'sample_days':2},True,self.now)[0],'insufficient_baseline_days')
        self.assertEqual(signal({**self.row,'is_operational':0},self.base,True,self.now)[0],'not_fully_operational')

if __name__=='__main__': unittest.main()
