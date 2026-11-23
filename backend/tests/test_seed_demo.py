import sqlite3
import tempfile
import unittest
from pathlib import Path
from backend.chat.seed_demo import seed

class DemoSeedTests(unittest.TestCase):
    def test_fresh_clone_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath = Path(tmp)/'results'/'live_chat.sqlite'
            seed(dbpath)
            seed(dbpath)
            with sqlite3.connect(dbpath) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM products').fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT name FROM users WHERE email='example.user@example.com'").fetchone()[0], 'Example User')
    def test_existing_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath=Path(tmp)/'live_chat.sqlite'
            seed(dbpath)
            with sqlite3.connect(dbpath) as db:
                db.execute("UPDATE orders SET status='delivered' WHERE order_number='DEMO-HEADSET-001'")
            seed(dbpath)
            with sqlite3.connect(dbpath) as db:
                self.assertEqual(db.execute("SELECT status FROM orders WHERE order_number='DEMO-HEADSET-001'").fetchone()[0], 'delivered')
