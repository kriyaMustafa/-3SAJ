import json
import urllib.request
import time
from googletrans import Translator

project_id = '27299abd-a243-46f9-895b-eb4c11dcb130'
url = f'http://127.0.0.1:8000/api/projects/{project_id}'

req = urllib.request.Request(url)
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())

segments = data.get('segments', [])
segments = sorted(segments, key=lambda x: x['segment_index'])

translator = Translator()

translations = []
print(f"Translating {len(segments)} segments...")

for s in segments:
    # Use googletrans
    try:
        res = translator.translate(s['original_text'], dest='km')
        khmer_text = res.text
    except Exception as e:
        print("Translate error:", e)
        khmer_text = s['original_text'] # fallback
    
    translations.append({
        'segment_id': s['id'],
        'translated_text': khmer_text
    })

print(f"Translated {len(translations)} segments.")

if translations:
    print('Submitting to batch-translate API...')
    batch_url = f'http://127.0.0.1:8000/api/projects/{project_id}/segments/batch-translate'
    payload = json.dumps({'translations': translations}).encode('utf-8')
    req_post = urllib.request.Request(batch_url, data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req_post) as response:
            result = json.loads(response.read().decode())
            print(result)
    except Exception as e:
        print('Error submitting:', e)
