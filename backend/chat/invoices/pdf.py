"""Generate a simple, clearly marked sample invoice PDF without external dependencies."""
import sqlite3
from io import BytesIO
from pathlib import Path

DB = Path(__file__).resolve().parents[3] / 'results' / 'live_chat.sqlite'


def invoice_for_customer(invoice_number):
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('''SELECT i.invoice_number,i.amount_cents,i.currency,
             o.order_number,o.item_name,u.name
             FROM invoices i JOIN orders o ON i.order_id=o.id
             JOIN users u ON u.id=o.user_id
             WHERE i.invoice_number=? AND u.email=? AND i.is_sample=1''',
             (invoice_number,'example.user@example.com')).fetchone()
        return dict(row) if row else None


def make_pdf(record):
    def safe(value):
        return str(value).encode('ascii', 'replace').decode('ascii').replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    amount=f"{record['amount_cents']/100:.2f} {record['currency']}"
    lines=[('SHOPLY',22),('SAMPLE INVOICE - NOT A REAL INVOICE',14),
           ('For demonstration and testing only. No actual charge.',10),
           ('Invoice: '+record['invoice_number'],12),('Order: '+record['order_number'],12),
           ('Customer: '+record['name'],12),('Product: '+record['item_name'],12),
           ('Example amount: '+amount,12),
           ('This document is fictional and not valid for tax or payment purposes.',9)]
    commands=['BT']
    y=760
    for line,size in lines:
        commands.extend([f'/F1 {size} Tf',f'1 0 0 1 55 {y} Tm',f'({safe(line)}) Tj'])
        y-=55 if size==22 else 38
    commands.append('ET')
    stream='\n'.join(commands).encode('ascii')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
             b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    out=BytesIO();out.write(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(out.tell());out.write(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=out.tell();out.write(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for off in offsets[1:]:out.write(f'{off:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return out.getvalue()
