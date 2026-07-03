import os, urllib.request, json
from dotenv import load_dotenv
load_dotenv()
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')

req = urllib.request.Request(f'{url}/rest/v1/events?type=eq.error&select=payload,created_at&order=created_at.desc&limit=2', headers={
    'apikey': key,
    'Authorization': f'Bearer {key}'
})
res = urllib.request.urlopen(req).read().decode()
data = json.loads(res)
print(json.dumps(data, indent=2))
