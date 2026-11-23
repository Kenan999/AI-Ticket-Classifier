"""Local sample invoice fixtures for the customer-support demonstration."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[3] / 'results' / 'live_chat.sqlite'


def ensure_sample_invoices():
    with sqlite3.connect(DB) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE,
            invoice_number TEXT NOT NULL UNIQUE, currency TEXT NOT NULL,
            amount_cents INTEGER NOT NULL, is_sample INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(order_id) REFERENCES orders(id))''')
        for order_number, invoice_number, cents in (
            ('HEADSET-001', 'INV-HEADSET-001', 7999),
            ('LAMPE-002', 'INV-LAMPE-002', 1299),
        ):
            row = db.execute('SELECT id FROM orders WHERE order_number=?', (order_number,)).fetchone()
            if row:
                db.execute('''INSERT OR IGNORE INTO invoices
                    (order_id,invoice_number,currency,amount_cents,is_sample)
                    VALUES (?,?,?,?,1)''', (row[0], invoice_number, 'EUR', cents))


def customer_invoices(db, user_id):
    return [dict(row) for row in db.execute('''
        SELECT i.invoice_number, o.order_number, o.item_name,
               i.currency, i.amount_cents, i.is_sample
        FROM invoices i JOIN orders o ON o.id=i.order_id
        WHERE o.user_id=? ORDER BY o.id''', (user_id,))]
