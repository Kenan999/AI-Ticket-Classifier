"""Deterministic, sentence-aware RAG chunks without tokenizer dependencies.

The byte budget is deliberately conservative: UTF-8 bytes upper-bound the
number of byte-level BPE tokens. This is not an exact model token count.
"""
import re

MAX_INPUT_BYTES = 1800


def split_sentences(text):
    return re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“])', text.strip())


def bounded_sections(section, budget=MAX_INPUT_BYTES):
    """Yield ordered text pieces, preserving paragraphs and sentences where possible."""
    if budget < 32:
        raise ValueError('Chunk budget must be at least 32 bytes')
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', section) if p.strip()]
    pieces = []
    for paragraph in paragraphs:
        if len(paragraph.encode('utf-8')) <= budget:
            pieces.append(paragraph)
            continue
        for sentence in split_sentences(paragraph):
            if len(sentence.encode('utf-8')) <= budget:
                pieces.append(sentence)
                continue
            # Only split inside a sentence when the input cannot otherwise fit.
            words = re.findall(r'\S+\s*', sentence)
            current = ''
            for word in words:
                if len((current + word).encode('utf-8')) > budget and current:
                    pieces.append(current.strip())
                    current = ''
                if len(word.encode('utf-8')) > budget:
                    for character in word:
                        if len((current + character).encode('utf-8')) > budget and current:
                            pieces.append(current.strip())
                            current = ''
                        current += character
                else:
                    current += word
            if current.strip():
                pieces.append(current.strip())
    current = ''
    for piece in pieces:
        candidate = current + ('\n\n' if current else '') + piece
        if len(candidate.encode('utf-8')) > budget and current:
            yield current
            current = piece
        else:
            current = candidate
    if current:
        yield current
