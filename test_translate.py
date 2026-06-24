import urllib.request
import json

project_id = '27299abd-a243-46f9-895b-eb4c11dcb130'
url = f'http://127.0.0.1:8000/api/projects/{project_id}'

req = urllib.request.Request(url)
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())

segments = data.get('segments', [])
translations = []

for seg in segments:
    if seg.get('status') == 'needs_manual_translation':
        # Simple mock translation just to test the pipeline
        original = seg.get('original_text', '')
        # We will just prefix it with a Khmer word to simulate translation
        khmer_mock = 'សួស្តី ' + original
        translations.append({
            'segment_id': seg['id'],
            'translated_text': khmer_mock
        })

if not translations:
    print('No segments need translation.')
else:
    print(f'Submitting {len(translations)} translations...')
    batch_url = f'http://127.0.0.1:8000/api/projects/{project_id}/segments/batch-translate'
    payload = json.dumps({'translations': translations}).encode('utf-8')
    req_post = urllib.request.Request(batch_url, data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req_post) as response:
            result = json.loads(response.read().decode())
            print(result)
    except Exception as e:
        print('Error:', e)
