"""Persistent confidence cutoff shared by ticket and chat classification."""
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[1].parent / 'AI-Ticket-Classifier-Backend' / 'results' / 'review_threshold.json'
DEFAULT = 0.75

def get_threshold():
    try:
        value = json.loads(PATH.read_text())['threshold']
        if type(value) in (int, float) and 0 <= value <= 1:
            return float(value)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return DEFAULT

def set_threshold(value):
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError('Threshold must be a number from 0 to 1')
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps({'threshold': float(value)}))
    temp.replace(PATH)
    return get_threshold()
