import os
import logging

logger = logging.getLogger(__name__)

WHATSAPP_FROM = 'whatsapp:+14155238886'  # Twilio sandbox number


def _client():
    from twilio.rest import Client
    return Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))


def _wa(phone: str) -> str:
    """Ensure a number is prefixed with whatsapp:"""
    return phone if phone.startswith('whatsapp:') else f'whatsapp:{phone}'


def send_whatsapp(to: str, body: str) -> bool:
    """Send a WhatsApp message via Twilio. Returns True on success."""
    sid = os.getenv('TWILIO_ACCOUNT_SID')
    token = os.getenv('TWILIO_AUTH_TOKEN')

    if not (sid and token):
        logger.warning('Twilio credentials not configured — skipping WhatsApp to %s', to)
        return False

    try:
        _client().messages.create(body=body, from_=WHATSAPP_FROM, to=_wa(to))
        logger.info('WhatsApp sent to %s', to)
        return True
    except Exception:
        logger.exception('Failed to send WhatsApp to %s', to)
        return False


def send_patient_reminder(patient_phone: str, medication: str, dosage: str) -> bool:
    return send_whatsapp(
        patient_phone,
        f"💊 PillPal Reminder: Time to take your {medication} {dosage}. Reply TAKEN to confirm.",
    )


def send_caregiver_alert(caregiver_phone: str, patient_name: str, medication: str, dosage: str) -> bool:
    return send_whatsapp(
        caregiver_phone,
        f"⚠️ {patient_name} hasn't confirmed taking their {medication} {dosage}. Please check on them.",
    )
