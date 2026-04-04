import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
PILLS_FILE = os.path.join(DATA_DIR, 'pills.json')


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
