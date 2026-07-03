import urllib.request
import json
import uuid

payload = {
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "1292589239343299",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "15550750524",
              "phone_number_id": "1152249817976388"
            },
            "contacts": [{"profile": {"name": "Test User"}, "wa_id": "917978806779"}],
            "messages": [
              {
                "from": "917978806779",
                "id": str(uuid.uuid4()),
                "timestamp": "1234567890",
                "text": {"body": "hi"},
                "type": "text"
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}

req = urllib.request.Request(
    'https://ai-agency-production-a6a9.up.railway.app/webhooks/whatsapp', 
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json'}
)

try:
    res = urllib.request.urlopen(req)
    print("Status:", res.status)
    print("Response:", res.read().decode())
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code)
    print("Response:", e.read().decode())
except Exception as e:
    print("Error:", e)
