import os
import json
import sqlite3
import urllib.request
import re
from dotenv import load_dotenv

load_dotenv('backend/.env')

api_key = os.getenv('GEMINI_API_KEY')
from google import genai
client = genai.Client(api_key=api_key)

project_id = '27299abd-a243-46f9-895b-eb4c11dcb130'
url = f'http://127.0.0.1:8000/api/projects/{project_id}'

req = urllib.request.Request(url)
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())

segments = data.get('segments', [])
segments = sorted(segments, key=lambda x: x['segment_index'])

# Prepare prompt
prompt = "Translate these lines from a documentary to Khmer. ONLY output the lines in format [ID] <Khmer text>. Keep translations natural and concise.\n\n"
for s in segments:
    prompt += f"[{s['id']}] {s['original_text']}\n"

print("Calling Gemini...")
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=prompt,
)

result_text = response.text
print("Gemini response received.")

translations = []
for line in result_text.split('\n'):
    match = re.search(r'\[(\d+)\]\s*(.+)', line)
    if match:
        seg_id = int(match.group(1))
        khmer_text = match.group(2).strip()
        translations.append({
            'segment_id': seg_id,
            'translated_text': khmer_text
        })

print(f"Parsed {len(translations)} translations.")

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
        print('Error:', e)
