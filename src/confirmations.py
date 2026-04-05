"""
Tracks pending dose confirmations.

When a reminder WhatsApp message is sent we add an entry here. The patient
replies "TAKEN" to confirm. A follow-up job checks 5 minutes later; if the
entry is still unconfirmed it alerts the caregivers.

Stored in data/confirmations.json so it survives restarts.
"""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
CONFIRM_FILE = os.path.join(DATA_DIR, 'confirmations.json')


def _load() -> dict:
    if not os.path.exists(CONFIRM_FILE):
        return {}
    try:
        with open(CONFIRM_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIRM_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def add(key: str, patient_phone: str, patient_name: str,
        medication: str, dosage: str, caregiver_phones: list) -> None:
    data = _load()
    data[key] = {
        'patientPhone': patient_phone,
        'patientName': patient_name,
        'medication': medication,
        'dosage': dosage,
        'caregiverPhones': caregiver_phones,
        'confirmed': False,
    }
    _save(data)


def mark_confirmed_by_phone(patient_phone: str) -> None:
    """
    Mark every pending entry for this phone number as confirmed.
    The phone may arrive with or without the 'whatsapp:' prefix — normalise it.
    """
    # Strip whatsapp: prefix for comparison since numbers are stored without it
    normalised = patient_phone.replace('whatsapp:', '')
    data = _load()
    changed = False
    for entry in data.values():
        stored = entry.get('patientPhone', '').replace('whatsapp:', '')
        if stored == normalised and not entry.get('confirmed'):
            entry['confirmed'] = True
            changed = True
    if changed:
        _save(data)


def is_confirmed(key: str) -> bool:
    data = _load()
    return data.get(key, {}).get('confirmed', False)


def remove(key: str) -> None:
    data = _load()
    data.pop(key, None)
    _save(data)
