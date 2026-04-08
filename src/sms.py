import os
import logging
import traceback

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
        print(f'[SMS] Twilio credentials not configured — skipping WhatsApp to {to}')
        logger.warning('Twilio credentials not configured — skipping WhatsApp to %s', to)
        return False

    to_wa = _wa(to)
    print(f'[SMS] Calling Twilio — from={WHATSAPP_FROM} to={to_wa}')
    print(f'[SMS] Message body: {body}')
    logger.info('Calling Twilio — from=%s to=%s', WHATSAPP_FROM, to_wa)
    logger.info('Message body: %s', body)

    try:
        msg = _client().messages.create(body=body, from_=WHATSAPP_FROM, to=to_wa)
        print(f'[SMS] Twilio response — SID={msg.sid} status={msg.status} error_code={msg.error_code} error_message={msg.error_message}')
        logger.info('Twilio response — SID=%s status=%s error_code=%s error_message=%s', msg.sid, msg.status, msg.error_code, msg.error_message)
        return True
    except Exception:
        tb = traceback.format_exc()
        print(f'[SMS] Failed to send WhatsApp to {to_wa}:\n{tb}')
        logger.error('Failed to send WhatsApp to %s:\n%s', to_wa, tb)
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
