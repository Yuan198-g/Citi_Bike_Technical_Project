import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from workflow import due,lock,atomic_json

class WorkflowTests(unittest.TestCase):
    def test_schedule_catchup_and_same_day_restart(self):
        c={'daily_at_utc':'02:00'}
        self.assertFalse(due(c,datetime(2026,10,11,1,tzinfo=timezone.utc),{}))
        self.assertTrue(due(c,datetime(2026,10,11,3,tzinfo=timezone.utc),{}))
        self.assertFalse(due(c,datetime(2026,10,11,3,tzinfo=timezone.utc),{'last_attempt_date':'2026-10-11'}))
    def test_lock_released_after_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'lock'
            with self.assertRaises(ValueError):
                with lock(p): raise ValueError('simulated interruption')
            with lock(p): pass
    def test_state_replaced_without_temp_leftover(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'state.json'
            atomic_json(p,{'status':'running'});atomic_json(p,{'status':'passed'})
            self.assertIn('passed',p.read_text())
            self.assertFalse(p.with_suffix('.tmp').exists())

if __name__=='__main__':unittest.main()
