import os, urllib.request, json
from dotenv import load_dotenv
load_dotenv()
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')

# Create a temporary table or just insert into events if we have it?
# We have an 'events' table which has 'client_id', 'type', 'payload'
# But 'client_id' is required as UUID. We can just use the test client ID.
client_id = "ac7a26b7-3522-4fcf-b37f-7d68176c906f"
payload = {"msg": "test_event"}

req = urllib.request.Request(f'{url}/rest/v1/events', data=json.dumps({"client_id": client_id, "type": "webhook_dump", "payload": payload}).encode(), headers={
    'apikey': key,
    'Authorization': f'Bearer {key}',
    'Content-Type': 'application/json'
})
try:
    res = urllib.request.urlopen(req)
    print("Test insert status:", res.status)
except Exception as e:
    print("Error:", e)
