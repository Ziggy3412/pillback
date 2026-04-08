"""
One-time script to create the PillPal reminder Content Template in Twilio.

Run once locally (with .env loaded) or on Railway via a one-off command:
    python create_template.py

Copy the printed SID into your .env / Railway env vars as TWILIO_CONTENT_SID.
"""

from dotenv import load_dotenv
load_dotenv()

import os
from twilio.rest import Client
from twilio.rest.content.v1.content import ContentList

sid = os.getenv('TWILIO_ACCOUNT_SID')
token = os.getenv('TWILIO_AUTH_TOKEN')

if not (sid and token):
    print('ERROR: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env')
    raise SystemExit(1)

client = Client(sid, token)

# Build the request using the SDK's typed objects (twilio 9.x API)
action = ContentList.QuickReplyAction({
    'title': '✅ Taken',
    'id': 'taken',
})

quick_reply = ContentList.TwilioQuickReply({
    'body': '💊 PillPal Reminder: Time to take your {{1}} {{2}}. Did you take it?',
    'actions': [action],
})

types = ContentList.Types({
    'twilio/quick-reply': quick_reply,
})

request = ContentList.ContentCreateRequest({
    'friendly_name': 'pillpal_reminder_v1',
    'language': 'en',
    'variables': {'1': 'medication', '2': 'dosage'},
    'types': types,
})

content = client.content.v1.contents.create(request)

print()
print('Template created!')
print(f'  SID:           {content.sid}')
print(f'  Friendly name: {content.friendly_name}')
print()
print('Add to .env and Railway environment variables:')
print(f'  TWILIO_CONTENT_SID={content.sid}')
print()
print('NOTE: For production WhatsApp (non-sandbox), the template also needs')
print('Meta approval. Submit it in the Twilio Console under Content Templates.')
