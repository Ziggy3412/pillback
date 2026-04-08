from dotenv import load_dotenv
load_dotenv()

import logging
import os
import sys
import time
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
)

# Validate required env vars before any other module reads them
REQUIRED_ENV = ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'JWT_SECRET']
missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
if missing:
    print(f"\n[backend] Missing required environment variables: {', '.join(missing)}")
    print('[backend] Copy backend/.env.example → backend/.env and fill in the values.\n')
    sys.exit(1)

from flask import Flask, g, jsonify, request
from flask_cors import CORS

from src.config.oauth import init_oauth
from src.middleware.protect import protect
from src.routes.auth import auth_bp
from src.scheduler import init_scheduler, schedule_reminder
from src.store import load_pills, save_pills, load_reminders, save_reminders, get_user, update_user

app = Flask(__name__)
PORT = int(os.getenv('PORT', 3000))

# Secret key used for Flask session (OAuth handshake state only – JWT handles auth)
app.secret_key = os.getenv('SESSION_SECRET', 'change-me-in-production')

# ── Allowed origins ───────────────────────────────────────────────────────────
# Web dev server + Expo web (19006) + Expo Go / metro bundler (8081)
ALLOWED_ORIGINS = [
    os.getenv('CLIENT_URL', 'http://localhost:5173'),
    'http://localhost:19006',
    'http://localhost:8081',
    'https://ziggy3412.github.io',
]
backend_url = os.getenv('BACKEND_URL', '')
if backend_url.startswith('https://'):
    ALLOWED_ORIGINS.append(backend_url)

CORS(app, origins=ALLOWED_ORIGINS, supports_credentials=True)

# ── OAuth (Google) ────────────────────────────────────────────────────────────
init_oauth(app)

# ── Scheduler ─────────────────────────────────────────────────────────────────
init_scheduler()

# Re-register all saved reminders so jobs survive Railway redeploys
# (in-memory jobstore is wiped on every restart)
_startup_reminders = load_reminders()
print(f'[APP] Re-registering {len(_startup_reminders)} reminder(s) from JSON store on startup')
for _r in _startup_reminders:
    try:
        schedule_reminder(_r)
    except Exception as _e:
        import traceback as _tb
        print(f'[APP] Failed to re-register reminder {_r.get("id")}: {_tb.format_exc()}')

# ── Routes ────────────────────────────────────────────────────────────────────
app.register_blueprint(auth_bp, url_prefix='/auth')


@app.get('/api/health')
def health():
    from src.scheduler import scheduler as _sched
    jobs = _sched.get_jobs() if _sched else []
    return jsonify({'status': 'ok', 'scheduler_jobs': len(jobs)})


# ── Protected pill routes ─────────────────────────────────────────────────────
pills = load_pills()
reminders = load_reminders()


@app.get('/api/pills')
@protect
def get_pills():
    return jsonify([p for p in pills if p.get('userId') == g.user['id']])


@app.post('/api/pills')
@protect
def create_pill():
    pill = {'id': int(time.time() * 1000), 'userId': g.user['id'], **request.get_json()}
    pills.append(pill)
    save_pills(pills)
    return jsonify(pill), 201


@app.put('/api/pills/<int:pill_id>')
@protect
def update_pill(pill_id):
    global pills
    body = request.get_json() or {}
    updated = None
    for i, p in enumerate(pills):
        if p.get('id') == pill_id and p.get('userId') == g.user['id']:
            pills[i] = {**p, **body, 'id': pill_id, 'userId': g.user['id']}
            updated = pills[i]
            break
    if updated is None:
        return jsonify({'error': 'Not found'}), 404
    save_pills(pills)
    return jsonify(updated)


@app.delete('/api/pills/<int:pill_id>')
@protect
def delete_pill(pill_id):
    global pills
    pills = [p for p in pills if not (p.get('id') == pill_id and p.get('userId') == g.user['id'])]
    save_pills(pills)
    return '', 204


# ── Reminders ─────────────────────────────────────────────────────────────────

def _calc_next_fire(schedule: dict) -> str | None:
    """
    Return an ISO-8601 datetime string for the next scheduled fire time.
    Uses schedule.startDate (YYYY-MM-DD) and the first entry in schedule.times
    (e.g. "8:30 AM"). Advances by schedule.interval days when frequency is
    'interval', otherwise treats startDate as the base and uses today if it
    has already passed.
    """
    try:
        start_str = schedule.get('startDate', '')
        times = schedule.get('times') or []
        time_str = times[0] if times else '8:00 AM'
        frequency = schedule.get('frequency', 'daily')
        interval = int(schedule.get('interval') or 1)

        base = datetime.strptime(f"{start_str} {time_str}", '%Y-%m-%d %I:%M %p')
        now = datetime.utcnow()

        if base >= now:
            return base.isoformat()

        if frequency == 'interval':
            # advance by `interval` days until we're in the future
            delta = timedelta(days=interval)
            while base < now:
                base += delta
            return base.isoformat()

        # daily / weekly / specific-days — just use tomorrow's equivalent
        delta = timedelta(days=1) if frequency != 'weekly' else timedelta(weeks=1)
        while base < now:
            base += delta
        return base.isoformat()
    except Exception:
        return None


@app.post('/api/reminders')
@protect
def create_reminder():
    body = request.get_json() or {}
    pill_id = body.get('pillId')

    # Look up the pill so we can embed its data in the reminder
    pill = next(
        (p for p in pills if p.get('id') == pill_id and p.get('userId') == g.user['id']),
        None,
    )
    if pill is None:
        return jsonify({'error': 'Pill not found'}), 404

    schedule = pill.get('schedule') or {}
    next_fire = _calc_next_fire(schedule)

    reminder = {
        'id': int(time.time() * 1000),
        'userId': g.user['id'],
        # contact info
        'caregiverPhones': body.get('caregiverPhones') or [],
        'patientName': body.get('patientName'),
        'patientPhone': body.get('patientPhone'),
        'notes': body.get('notes'),
        # embedded pill data (everything needed to send the SMS later)
        'pillId': pill_id,
        'pillName': pill.get('name'),
        'medication': pill.get('medication'),
        'dosage': pill.get('dosage'),
        'urgency': pill.get('urgency'),
        'schedule': schedule,
        # computed
        'nextFireTime': next_fire,
        'sent': False,
    }
    reminders.append(reminder)
    save_reminders(reminders)

    # Register recurring WhatsApp jobs with APScheduler
    schedule_reminder(reminder)

    return jsonify(reminder), 200


# ── User / onboarding routes ─────────────────────────────────────────────────

@app.get('/api/user/me')
@protect
def user_me():
    profile = get_user(g.user['id'])
    if profile is None:
        return jsonify({'onboarded': False})
    return jsonify({
        'id': profile.get('id', g.user['id']),
        'displayName': profile.get('displayName'),
        'email': profile.get('email'),
        'photo': profile.get('photo'),
        'onboarded': profile.get('onboarded', False),
        'patientName': profile.get('patientName'),
        'patientPhone': profile.get('patientPhone'),
        'caregiverPhones': profile.get('caregiverPhones', []),
    })


@app.post('/api/onboarding')
@protect
def complete_onboarding():
    body = request.get_json() or {}
    patient_name = body.get('patientName')
    patient_phone = body.get('patientPhone')
    caregiver_phones = body.get('caregiverPhones') or []

    if not patient_name or not patient_phone:
        return jsonify({'error': 'patientName and patientPhone are required'}), 400

    profile = update_user(g.user['id'], {
        'patientName': patient_name,
        'patientPhone': patient_phone,
        'caregiverPhones': caregiver_phones,
        'onboarded': True,
    })
    return jsonify({'onboarded': True, 'profile': profile})


@app.get('/api/onboarding/whatsapp-check')
@protect
def whatsapp_check():
    # Twilio's WhatsApp sandbox has no API to check if a number has opted in.
    # Return manual=True so the frontend knows to ask the user to confirm themselves.
    return jsonify({'joined': False, 'manual': True})


# ── WhatsApp reply webhook (no auth — called by Twilio, not the app) ─────────

@app.post('/whatsapp/reply')
def whatsapp_reply():
    """
    Twilio calls this URL when a patient sends a WhatsApp message.
    Only "TAKEN" (case-insensitive) marks the dose as confirmed.
    Configure this as the WhatsApp webhook in your Twilio sandbox settings.
    """
    from src.confirmations import mark_confirmed_by_phone
    from_number = request.form.get('From', '')  # arrives as "whatsapp:+1..."
    body = request.form.get('Body', '').strip().upper()

    if from_number and body == 'TAKEN':
        mark_confirmed_by_phone(from_number)

    return '<Response></Response>', 200, {'Content-Type': 'text/xml'}


# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'PillPal backend listening on 0.0.0.0:{PORT} (accessible from all network interfaces)')
    app.run(host='0.0.0.0', port=PORT, debug=os.getenv('NODE_ENV') != 'production')
