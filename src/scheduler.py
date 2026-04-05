"""
APScheduler setup and job definitions.

Jobs are persisted to data/jobs.db (SQLite) so they survive restarts.
"""

import logging
import os
from datetime import datetime, timedelta

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
DB_PATH = os.path.join(DATA_DIR, 'jobs.db')

# Module-level scheduler instance – imported by app.py and job functions below.
scheduler: BackgroundScheduler = None  # type: ignore[assignment]


def init_scheduler() -> BackgroundScheduler:
    global scheduler
    os.makedirs(DATA_DIR, exist_ok=True)
    scheduler = BackgroundScheduler(
        jobstores={'default': SQLAlchemyJobStore(url=f'sqlite:///{DB_PATH}')},
        job_defaults={'misfire_grace_time': 60 * 60},  # 1 hour grace window
    )
    scheduler.start()
    logger.info('Scheduler started (job store: %s)', DB_PATH)
    return scheduler


# ── Time helpers ──────────────────────────────────────────────────────────────

_DAY_MAP = {
    'monday': 'mon', 'tuesday': 'tue', 'wednesday': 'wed',
    'thursday': 'thu', 'friday': 'fri', 'saturday': 'sat', 'sunday': 'sun',
    # also accept short forms and numeric strings
    'mon': 'mon', 'tue': 'tue', 'wed': 'wed', 'thu': 'thu',
    'fri': 'fri', 'sat': 'sat', 'sun': 'sun',
    '0': 'mon', '1': 'tue', '2': 'wed', '3': 'thu',
    '4': 'fri', '5': 'sat', '6': 'sun',
}


def _parse_time(time_str: str) -> tuple[int, int]:
    """'8:30 AM' -> (8, 30)"""
    dt = datetime.strptime(time_str.strip(), '%I:%M %p')
    return dt.hour, dt.minute


def _map_days(days: list) -> str:
    """['Monday', 'Wednesday'] -> 'mon,wed'"""
    mapped = [_DAY_MAP.get(str(d).lower(), str(d).lower()[:3]) for d in days]
    return ','.join(mapped) if mapped else 'mon'


# ── Job functions ─────────────────────────────────────────────────────────────

def send_reminder_job(
    reminder_id: int,
    patient_phone: str,
    patient_name: str,
    medication: str,
    dosage: str,
    caregiver_phones: list,
) -> None:
    """Send the dose reminder via WhatsApp and schedule the 5-min confirmation check."""
    from src.sms import send_patient_reminder
    from src.confirmations import add as add_confirmation

    logger.info('Sending WhatsApp reminder %s to %s', reminder_id, patient_phone)
    sent = send_patient_reminder(patient_phone, medication, dosage)

    if sent:
        # Unique key for this specific fire so multiple fires don't collide
        key = f"{reminder_id}_{int(datetime.utcnow().timestamp())}"
        add_confirmation(key, patient_phone, patient_name, medication, dosage, caregiver_phones)

        scheduler.add_job(
            check_confirmation_job,
            'date',
            run_date=datetime.now() + timedelta(minutes=5),
            args=[key, patient_name, medication, dosage, caregiver_phones],
            id=f'check_{key}',
            replace_existing=True,
        )


def check_confirmation_job(
    key: str,
    patient_name: str,
    medication: str,
    dosage: str,
    caregiver_phones: list,
) -> None:
    """Alert caregivers if the patient hasn't confirmed 30 min after reminder."""
    from src.sms import send_caregiver_alert
    from src.confirmations import is_confirmed, remove

    if not is_confirmed(key):
        logger.info('No confirmation for %s — alerting %d caregiver(s)', key, len(caregiver_phones))
        for phone in caregiver_phones:
            send_caregiver_alert(phone, patient_name, medication, dosage)
    else:
        logger.info('Confirmation received for %s — no caregiver alert needed', key)

    remove(key)


# ── Scheduling helper called from app.py ──────────────────────────────────────

def schedule_reminder(reminder: dict) -> None:
    """
    Register APScheduler jobs for a reminder based on its pill's schedule.

    Supported frequencies:
      - 'daily'    → cron every day at each time in schedule.times
      - 'weekly'   → cron on schedule.days at each time
      - 'interval' → every schedule.interval days starting at startDate + first time
      - anything else treated as daily
    """
    sched = reminder.get('schedule') or {}
    frequency = sched.get('frequency', 'daily')
    times = sched.get('times') or ['8:00 AM']
    start_date_str = sched.get('startDate') or datetime.now().strftime('%Y-%m-%d')
    days = sched.get('days') or []
    interval_days = int(sched.get('interval') or 1)

    rid = reminder['id']
    args = [
        rid,
        reminder.get('patientPhone', ''),
        reminder.get('patientName', ''),
        reminder.get('medication', ''),
        reminder.get('dosage', ''),
        reminder.get('caregiverPhones') or [],
    ]

    for i, time_str in enumerate(times):
        try:
            hour, minute = _parse_time(time_str)
        except ValueError:
            logger.warning('Could not parse time "%s" for reminder %s — skipping', time_str, rid)
            continue

        job_id = f'reminder_{rid}_{i}'

        if frequency == 'interval':
            start_dt = f"{start_date_str} {hour:02d}:{minute:02d}:00"
            scheduler.add_job(
                send_reminder_job,
                'interval',
                days=interval_days,
                start_date=start_dt,
                id=job_id,
                replace_existing=True,
                args=args,
            )
        elif frequency == 'weekly':
            scheduler.add_job(
                send_reminder_job,
                'cron',
                day_of_week=_map_days(days),
                hour=hour,
                minute=minute,
                start_date=start_date_str,
                id=job_id,
                replace_existing=True,
                args=args,
            )
        else:  # daily (and anything unrecognised)
            scheduler.add_job(
                send_reminder_job,
                'cron',
                hour=hour,
                minute=minute,
                start_date=start_date_str,
                id=job_id,
                replace_existing=True,
                args=args,
            )

        logger.info('Scheduled job %s (freq=%s, time=%s)', job_id, frequency, time_str)
