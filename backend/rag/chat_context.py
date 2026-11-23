"""Read-only policy context for injection into either customer chat provider.

Import from the chat backend when the RAG feature is merged; no order DB access.
"""
from .retriever import retrieve

POLICY_HINTS = ('shipping', 'delivery', 'deliver', 'parcel', 'package', 'tracking',
                'return', 'refund', 'cancel', 'damaged', 'missing', 'express',
                'courier', 'address', 'postage', 'lost', 'dispatch', 'ship',
                'versand', 'liefer', 'retoure', 'rückgabe', 'erstattung')


def policy_context(question, limit=3):
    if not isinstance(question, str) or not any(term in question.lower() for term in POLICY_HINTS):
        return {'context': '', 'sources': []}
    matches = retrieve(question, limit=limit)
    matches = [item for item in matches if item['id'].startswith('shipping/')]
    if not matches:
        return {'context': '', 'sources': []}
    text = ('SHOPLY SHIPPING POLICY REFERENCE. Use only these documents for policy '
            'claims. Cite policy IDs, distinguish estimates from guarantees, '
            'and do not invent facts. If unclear, offer human support.\n\n')
    text += '\n\n'.join('Source: '+item['id']+'\n'+item['text'] for item in matches)
    return {'context': text, 'sources': [item['id'] for item in matches]}
