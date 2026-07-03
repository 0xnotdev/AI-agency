import asyncio
from app.services.llm import generate_reply
payload = {
    'business_name': 'Test Agency',
    'services': 'AI Automation',
    'pricing_notes': '10k',
    'faq': 'No',
    'tone_instructions': 'happy',
    'google_calendar_tokens': None,
    'client_id': 'test'
}
history = [{'direction': 'inbound', 'content': 'hi'}]
try:
    generate_reply(payload, history, 'hi', 'Test User', '1234')
    print('SUCCESS')
except Exception as e:
    import traceback
    traceback.print_exc()
