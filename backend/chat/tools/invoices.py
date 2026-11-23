"""Customer-scoped invoice lookup callable by Gemini, not by keyword rules."""
from urllib.parse import quote
from backend.chat.invoices.service import customer_invoices

DECLARATION = {'functionDeclarations': [{'name': 'find_customer_invoice',
    'description': 'Find a sample invoice PDF belonging to the signed-in customer. Use when the customer wants an invoice, bill, receipt or a copy of an invoice. Ask which order if ambiguous.',
    'parameters': {'type': 'OBJECT', 'properties': {
        'order_number': {'type': 'STRING', 'description': 'Order number when known, otherwise empty string'},
        'product_name': {'type': 'STRING', 'description': 'Product name when known, otherwise empty string'}},
        'required': ['order_number', 'product_name']}}]}


def execute(db, user_id, arguments):
    if not isinstance(arguments, dict):
        return {'error': 'Invalid tool arguments'}
    number = str(arguments.get('order_number') or '').strip().lower()
    product = str(arguments.get('product_name') or '').strip().lower()
    records = customer_invoices(db, user_id)
    if number:
        records = [r for r in records if r['order_number'].lower() == number]
    if product:
        records = [r for r in records if product in r['item_name'].lower()]
    if not records:
        return {'error': 'No matching invoice for this customer'}
    if len(records) != 1:
        return {'error': 'Multiple invoices match; ask the customer to specify an order',
                'available_orders': [{'order_number':r['order_number'],'product':r['item_name']} for r in records]}
    row = records[0]
    return {'invoice_number':row['invoice_number'], 'order_number':row['order_number'],
            'product':row['item_name'], 'amount':f"{row['amount_cents']/100:.2f} {row['currency']}",
            'sample':True, 'pdf_url':'/api/chat/invoice.pdf?invoice='+quote(row['invoice_number'])}
