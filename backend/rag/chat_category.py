"""Chat-to-category orchestration for the backend chat API.

The chat API calls detect_chat_category(messages, classifier=...). The caller's
existing LLM classifier receives the conversation and retrieved training examples.
No category is displayed when evidence is insufficient.
"""
from .ticket_categories import CATEGORIES, retrieve_examples


def customer_issue(messages, max_messages=8):
    """Use customer turns only; assistant replies must not influence the intent."""
    if not isinstance(messages, list):
        raise ValueError('Messages must be a list')
    texts = [m['content'].strip() for m in messages
             if isinstance(m, dict) and m.get('sender') in ('customer', 'user')
             and isinstance(m.get('content'), str) and m['content'].strip()]
    return '\n'.join(texts[-max_messages:])[:6000]


def detect_chat_category(messages, *, classifier, retriever=retrieve_examples,
                         min_confidence=0.75):
    """Return a UI-safe result; classifier(issue, examples) returns category/confidence.

    The classifier adapter can use local Qwen, OpenAI or Gemini. No guessing or
    keyword fallback if the vector index or classifier is unavailable.
    """
    issue = customer_issue(messages)
    if len(issue) < 10:
        return {'category': None, 'status': 'insufficient_context', 'confidence': None}
    examples = retriever(issue, limit=5)
    if not examples:
        return {'category': None, 'status': 'insufficient_context', 'confidence': None}
    prediction = classifier(issue, examples)
    if isinstance(prediction, dict):
        category, confidence = prediction.get('category'), prediction.get('confidence')
    else:
        category, confidence = prediction.category, prediction.confidence
    if category not in CATEGORIES or isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError('Invalid classifier result')
    return {'category': category if confidence >= min_confidence else None,
            'suggested_category': category,
            'status': 'classified' if confidence >= min_confidence else 'uncertain',
            'confidence': float(confidence),
            'retrieved_example_ids': [item['id'] for item in examples]}
