"""Customer-scoped order status lookup for Gemini function calling."""
DECLARATION = {'functionDeclarations': [{'name': 'get_customer_order_status',
    'description': 'Retrieve current order status from the customer database. Call this when the customer asks about shipping, delivery, processing, or order status. Ask for the order when ambiguous.',
    'parameters': {'type':'OBJECT','properties': {
        'order_number': {'type':'STRING','description':'Order number, or empty if not known'},
        'product_name': {'type':'STRING','description':'Product name, or empty if not known'}},
        'required':['order_number','product_name']}}]}

def execute(db,user_id,args):
    if not isinstance(args,dict): return {'error':'Invalid arguments'}
    number=str(args.get('order_number') or '').strip().lower()
    product=str(args.get('product_name') or '').strip().lower()
    rows=[dict(r) for r in db.execute('SELECT order_number,item_name,status FROM orders WHERE user_id=?',(user_id,))]
    if number: rows=[r for r in rows if r['order_number'].lower()==number]
    if product: rows=[r for r in rows if product in r['item_name'].lower()]
    if not rows:return {'error':'No matching order for this customer'}
    if len(rows)>1:return {'error':'Multiple orders match; ask which order','orders':[{'order_number':r['order_number'],'product':r['item_name']} for r in rows]}
    r=rows[0]
    return {'order_number':r['order_number'],'product':r['item_name'],'status':r['status'], 'tracking_number':None,'delivery_date':None}
