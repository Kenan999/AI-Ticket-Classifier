"""Create reproducible, fictional Shoply demo data without touching existing records."""
import argparse
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[2] / 'results' / 'live_chat.sqlite'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL,
 email TEXT NOT NULL COLLATE NOCASE UNIQUE,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')));
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(trim(name)) > 0),
 image_url TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')));
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 order_number TEXT NOT NULL UNIQUE, item_name TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','processing','shipped','delivered','cancelled')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT, UNIQUE(id,user_id));
'''


def seed(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(SCHEMA)
        db.execute('INSERT OR IGNORE INTO users(name,email) VALUES (?,?)',
                   ('Example User', 'example.user@example.com'))
        user_id = db.execute('SELECT id FROM users WHERE email=?',
                             ('example.user@example.com',)).fetchone()[0]
        for name, image, order, status in (
            ('Headset', 'chat-clone/assets/products/headset.jpg', 'DEMO-HEADSET-001', 'processing'),
            ('Lampe', 'chat-clone/assets/products/lampe.jpg', 'DEMO-LAMPE-002', 'shipped'),
        ):
            if not db.execute('SELECT 1 FROM products WHERE name=?', (name,)).fetchone():
                db.execute('INSERT INTO products(name,image_url) VALUES (?,?)', (name, image))
            db.execute('INSERT OR IGNORE INTO orders(user_id,order_number,item_name,status) VALUES (?,?,?,?)',
                       (user_id, order, name, status))
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    print('Demo database initialized:', seed(args.db))
