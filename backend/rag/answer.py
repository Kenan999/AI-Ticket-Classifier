"""Standalone RAG policy answering; leaves classification, evaluation and chat unchanged."""
import json
import os
from urllib.request import Request, urlopen
from .retriever import config, retrieve


def answer(question, history=None):
    matches = retrieve(question)
    sources = '\n\n'.join(f"Source {item['id']}: {item['text']}" for item in matches)
    key = os.environ.get('GEMINI_API_KEY') or config().get('GEMINI_API_KEY')
    model = os.environ.get('GEMINI_MODEL') or config().get('GEMINI_MODEL', 'gemini-2.5-flash')
    contents = [{'role': role, 'parts': [{'text': message}]} for role, message in (history or [])]
    contents.append({'role':'user','parts':[{'text':question}]})
    payload = {'systemInstruction': {'parts':[{'text':
        'You are a Shoply support assistant. Reply in English using only the provided '
        'policy sources for policy claims. Do not invent policies, invoice values, tracking, or order data. '
        'If information is missing, say so. Cite the document IDs used.\n'+sources}]},
        'contents':contents,'generationConfig':{'temperature':0.1,'maxOutputTokens':400}}
    req=Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
                data=json.dumps(payload).encode(),method='POST',
                headers={'Content-Type':'application/json','x-goog-api-key':key})
    with urlopen(req,timeout=25) as response:
        result=json.load(response)
    text=''.join(p.get('text','') for p in result['candidates'][0]['content']['parts'])
    return {'answer':text,'sources':[{'id':m['id'],'score':m['score']} for m in matches], 'model':model}

if __name__=='__main__':
    import sys
    print(json.dumps(answer(' '.join(sys.argv[1:])),indent=2))
