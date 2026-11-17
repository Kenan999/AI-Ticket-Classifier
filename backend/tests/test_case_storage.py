"""Migration and API regressions using temporary databases only."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from backend.app import create_app
from backend.tickets import case_storage


class CaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root/'cases.sqlite'

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        return create_app(review_path=self.root/'reviews.csv', case_db_path=self.db).test_client()

    def test_legacy_migration_preserves_payload_and_unknown_dates(self):
        original = {'ticket_id':'T-OLD','text':'legacy','category':'Orders','status':'classified','confidence':0.8}
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE cases(ticket_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            db.execute('INSERT INTO cases VALUES (?,?)',('T-OLD',json.dumps(original)))
        c=self.client()
        case=c.get('/case/T-OLD').get_json()
        self.assertIsNone(case['created_at'])
        self.assertIsNone(case['updated_at'])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(json.loads(db.execute('SELECT payload FROM cases').fetchone()[0]),original)
            self.assertEqual(db.execute('SELECT category,status,confidence FROM cases').fetchone(),('Orders','classified',0.8))
        self.client()  # Restart migration is idempotent.
        self.assertEqual(c.get('/cases?category=Orders').get_json(),[case])
        case['status']='reviewed'
        case_storage.store(self.db,case)
        self.assertIsNone(case_storage.load(self.db,'T-OLD')['created_at'])
        self.assertIsNotNone(case_storage.load(self.db,'T-OLD')['updated_at'])

    def test_review_preserves_creation_order_and_updates_filters(self):
        c=self.client()
        first=c.post('/classify',json={'text':'My package is missing.','provider':'baseline'}).get_json()
        second=c.post('/classify',json={'text':'My payment failed.','provider':'baseline'}).get_json()
        self.assertTrue(first['created_at'].endswith('Z'))
        self.assertEqual(first['created_at'],first['updated_at'])
        response=c.post('/review',json={'ticket_id':first['ticket_id'],'decision':'correct',
            'reviewer':'Test','final_category':'CONTACT','customer_reply':'We will help with your technical issue.'})
        self.assertEqual(response.status_code,200,response.get_json())
        changed=c.get('/case/'+first['ticket_id']).get_json()
        self.assertEqual(changed['created_at'],first['created_at'])
        self.assertGreater(changed['updated_at'],first['updated_at'])
        self.assertEqual([x['ticket_id'] for x in c.get('/cases').get_json()],[second['ticket_id'],first['ticket_id']])
        self.assertEqual(c.get('/cases?status=reviewed&category=CONTACT').get_json(),[changed])
        self.assertEqual(c.get('/cases?category=DELIVERY').get_json(),[])
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT category,status FROM cases WHERE ticket_id=?',(first['ticket_id'],)).fetchone(),('CONTACT','reviewed'))
        self.assertEqual(self.client().get('/case/'+first['ticket_id']).get_json(),changed)

    def test_filters_are_validated_and_parameterized(self):
        c=self.client()
        for query in ['status=bad','status=reviewed&status=classified','unknown=x','category=']:
            self.assertEqual(c.get('/cases?'+query).status_code,400)
        self.assertEqual(c.get('/cases',query_string={'category':"' OR 1=1 --"}).get_json(),[])

    def test_failed_migration_rolls_back_without_losing_legacy_row(self):
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE cases(ticket_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            db.execute("INSERT INTO cases VALUES ('T-BAD','invalid JSON')")
        with self.assertRaises(ValueError):
            case_storage.initialize(self.db)
        with sqlite3.connect(self.db) as db:
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(cases)')],['ticket_id','payload'])
            self.assertEqual(db.execute('SELECT payload FROM cases').fetchone()[0],'invalid JSON')
