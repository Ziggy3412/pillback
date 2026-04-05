import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
PILLS_FILE = os.path.join(DATA_DIR, 'pills.json')
REMINDERS_FILE = os.path.join(DATA_DIR, 'reminders.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')


def load_pills():
    if not os.path.exists(PILLS_FILE):
        return []
    try:
        with open(PILLS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_pills(pills):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PILLS_FILE, 'w', encoding='utf-8') as f:
        json.dump(pills, f, indent=2)


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return []
    try:
        with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_reminders(reminders):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(reminders, f, indent=2)


def load_users() -> dict:
    """Returns a dict keyed by user id."""
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)


def upsert_user(user_id: str, base_info: dict) -> dict:
    """
    Create the user record if it doesn't exist (onboarded=False),
    or return the existing record unchanged.
    Returns the current user record.
    """
    users = load_users()
    if user_id not in users:
        users[user_id] = {
            **base_info,
            'onboarded': False,
            'patientName': None,
            'patientPhone': None,
            'caregiverPhones': [],
        }
        save_users(users)
    return users[user_id]


def get_user(user_id: str) -> dict | None:
    return load_users().get(user_id)


def update_user(user_id: str, fields: dict) -> dict:
    users = load_users()
    if user_id not in users:
        users[user_id] = {}
    users[user_id].update(fields)
    save_users(users)
    return users[user_id]
