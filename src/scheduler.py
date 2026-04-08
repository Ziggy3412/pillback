"""
APScheduler setup and job definitions.

Uses in-memory jobstore (Railway filesystem is ephemeral — SQLite jobs were
lost on every redeploy). app.py re-registers all saved reminders on startup.
"""

import logging
import os
import traceback
from datetime import datetime, timedelta

import pytz
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

TZ = pytz.timezone('America/Los_Angeles')

# Module-level scheduler instance – imported by app.py and job functions below.
scheduler: BackgroundScheduler = None  # type: ignore[assignment]


def init_scheduler() -> BackgroundScheduler:
    global scheduler
    scheduler = BackgroundScheduler(
        jobstores={'default': MemoryJobStore()},
        job_defaults={'misfire_grace_time': 60 * 60},  # 1 hour grace window
        timezone=TZ,
    )
    scheduler.start()
    job_count = len(scheduler.get_jobs())
    print(f'[SCHEDULER] Scheduler started (in-memory, timezone=America/Los_Angeles). Jobs loaded: {job_count}')
    logger.info('Scheduler started (in-memory, timezone=America/Los_Angeles). Jobs loaded: %d', job_count)
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

    print(f'[SCHEDULER] Job fired — sending WhatsApp to {patient_phone} for {medication} (reminder_id={reminder_id}, patient={patient_name})')
    logger.info('Job fired — sending WhatsApp to %s for %s (reminder_id=%s, patient=%s)', patient_phone, medication, reminder_id, patient_name)
    try:
        sent = send_patient_reminder(patient_phone, medication, dosage)
    except Exception:
        print(f'[SCHEDULER] Exception in send_reminder_job:\n{traceback.format_exc()}')
        logger.error('Exception in send_reminder_job:\n%s', traceback.format_exc())
        return

    if sent:
        # Unique key for this specific fire so multiple fires don't collide
        key = f"{reminder_id}_{int(datetime.now(tz=TZ).timestamp())}"
        add_confirmation(key, patient_phone, patient_name, medication, dosage, caregiver_phones)

        scheduler.add_job(
            check_confirmation_job,
            'date',
            run_date=datetime.now(tz=TZ) + timedelta(minutes=5),
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
    patient_name = reminder.get('patientName', '?')
    medication = reminder.get('medication', '?')
    print(f'[SCHEDULER] Scheduling reminder for {patient_name} | medication={medication} | times={times} | frequency={frequency}')
    logger.info('Scheduling reminder for %s | medication=%s | times=%s | frequency=%s', patient_name, medication, times, frequency)
    start_date_str = sched.get('startDate') or datetime.now(tz=TZ).strftime('%Y-%m-%d')
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

        try:
            # Build tz-aware start datetime so APScheduler fires in LA local time
            naive_start = datetime.strptime(f"{start_date_str} {hour:02d}:{minute:02d}:00", '%Y-%m-%d %H:%M:%S')
            start_dt_la = TZ.localize(naive_start)

            if frequency == 'interval':
                scheduler.add_job(
                    send_reminder_job,
                    'interval',
                    days=interval_days,
                    start_date=start_dt_la,
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
                    start_date=start_dt_la,
                    timezone=TZ,
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
                    start_date=start_dt_la,
                    timezone=TZ,
                    id=job_id,
                    replace_existing=True,
                    args=args,
                )
            print(f'[SCHEDULER] Registered job {job_id} (freq={frequency}, time={time_str}, phone={args[1]})')
            logger.info('Registered job %s (freq=%s, time=%s, phone=%s)', job_id, frequency, time_str, args[1])
        except Exception:
            print(f'[SCHEDULER] Failed to register job {job_id}:\n{traceback.format_exc()}')
            logger.error('Failed to register job %s:\n%s', job_id, traceback.format_exc())
