import hashlib
import hmac
import json
import math
import os
import secrets
import string
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

import database

# Priority to Google Calendar Color ID mapping
PRIORITY_COLOR_MAP = {
    "high": "11",     # Tomato Red
    "medium": "5",    # Banana Yellow / Amber
    "low": "9",       # Blueberry
}

WORD_BANK = [
    "amber", "anchor", "apollo", "arctic", "atlas", "aurora", "basalt", "beacon",
    "bison", "breeze", "canyon", "carbon", "cedar", "cipher", "cobalt", "comet",
    "condor", "coral", "cosmos", "crater", "crystal", "cyclone", "delta", "dynamo",
    "eclipse", "ember", "emerald", "enigma", "equinox", "falcon", "fjord", "flint",
    "forest", "fusion", "galaxy", "garnet", "glacier", "granite", "harbor", "helium",
    "horizon", "indigo", "ion", "jasper", "juniper", "krypton", "lagoon", "lantern",
    "lumen", "magnet", "marble", "matrix", "meadow", "mercury", "meteor", "mirage",
    "monolith", "nebula", "nectar", "neon", "nexus", "nimbus", "obsidian", "onyx",
    "orbit", "osprey", "oxygen", "paradox", "pegasus", "phoenix", "photon", "pioneer",
    "plasma", "polaris", "prism", "pulsar", "pyrite", "quantum", "quartz", "quasar",
    "radon", "raptor", "redwood", "relativity", "ridge", "ripple", "sapphire", "saturn",
    "sequoia", "shadow", "sierra", "silicon", "solstice", "sonar", "spark", "spectrum",
    "sphinx", "summit", "tempest", "titanium", "topaz", "tundra", "turbine", "vector",
    "velvet", "vertex", "vortex", "vulcan", "whisper", "zenith", "zephyr", "zircon",
]


def build_gcal_template_url(
    title: str,
    action_date: str,
    start_time: str,
    end_time: str,
    description: str = "",
    tz_name: str = "Asia/Kolkata",
) -> str:
    """Create a 1-click Google Calendar template URL as an instant companion link."""
    clean_date = action_date.replace("-", "")
    clean_start = start_time.replace(":", "") + "00"
    clean_end = end_time.replace(":", "") + "00"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{clean_date}T{clean_start}/{clean_date}T{clean_end}",
        "details": description or "Scheduled via Daily Activity AI Agent",
        "ctz": tz_name,
    }
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"


def _resolve_google_access_token(settings: Dict[str, str]) -> Optional[str]:
    """Resolve Google Calendar OAuth2 token from settings, env, or Service Account JSON."""
    direct_token = (
        settings.get("google_calendar_access_token", "").strip()
        or os.getenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "").strip()
    )
    if direct_token:
        return direct_token

    sa_path = (
        settings.get("google_service_account_path", "").strip()
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    )
    if sa_path and os.path.isfile(sa_path):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                sa_path,
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            creds.refresh(Request())
            return creds.token
        except Exception:
            return None
    return None


async def push_action_to_google_calendar(action: Dict[str, Any]) -> Dict[str, Any]:
    """
    Push a day-start action item to the Google Calendar v3 API.
    If credentials are not yet configured, attaches a 1-click Google Calendar deep link
    and marks sync_status cleanly so the user can test both modes seamlessly.
    """
    settings = database.get_settings()
    calendar_id = settings.get("google_calendar_id") or "primary"
    tz_name = settings.get("timezone") or "Asia/Kolkata"
    access_token = _resolve_google_access_token(settings)

    template_url = build_gcal_template_url(
        title=action["title"],
        action_date=action["action_date"],
        start_time=action["start_time"],
        end_time=action["end_time"],
        description=action.get("description", ""),
        tz_name=tz_name,
    )

    event_payload = {
        "summary": f"[{action.get('category', 'action').upper()}] {action['title']}",
        "description": (
            f"{action.get('description', '')}\n\n"
            f"Priority: {action.get('priority', 'medium').upper()}\n"
            f"Created by: Daily Activity AI Agent"
        ).strip(),
        "start": {
            "dateTime": f"{action['action_date']}T{action['start_time']}:00",
            "timeZone": tz_name,
        },
        "end": {
            "dateTime": f"{action['action_date']}T{action['end_time']}:00",
            "timeZone": tz_name,
        },
        "colorId": PRIORITY_COLOR_MAP.get(action.get("priority", "medium"), "5"),
    }

    if not access_token:
        # Update with deep link and mark as ready for OAuth token or 1-click web add
        updated = database.update_daily_action_status(
            action_id=action["id"],
            gcal_html_link=template_url,
            sync_status="deep_link_ready",
        )
        database.log_integration_event(
            integration_type="google_calendar",
            endpoint=f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            status_code=200,
            success=True,
            payload_summary=f"Prepared Google Calendar deep-link for '{action['title']}' ({action['start_time']}-{action['end_time']})",
            response_excerpt="No OAuth token configured; generated instant Google Calendar template deep-link.",
        )
        return {
            "synced_via_api": False,
            "mode": "deep_link_fallback",
            "message": "Google Calendar OAuth token not set — generated 1-click Google Calendar web link.",
            "action": updated,
            "gcal_template_url": template_url,
        }

    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=event_payload)
            if resp.status_code in (200, 201):
                data = resp.json()
                evt_id = data.get("id", "")
                html_link = data.get("htmlLink", template_url)
                updated = database.update_daily_action_status(
                    action_id=action["id"],
                    gcal_event_id=evt_id,
                    gcal_html_link=html_link,
                    sync_status="synced",
                )
                database.log_integration_event(
                    integration_type="google_calendar",
                    endpoint=url,
                    status_code=resp.status_code,
                    success=True,
                    payload_summary=f"Created Google Calendar event '{action['title']}' -> ID {evt_id}",
                    response_excerpt=json.dumps({"id": evt_id, "htmlLink": html_link}),
                )
                return {
                    "synced_via_api": True,
                    "mode": "google_calendar_api_v3",
                    "message": "Successfully created event in Google Calendar!",
                    "action": updated,
                    "gcal_event_id": evt_id,
                    "gcal_html_link": html_link,
                }
            else:
                updated = database.update_daily_action_status(
                    action_id=action["id"],
                    gcal_html_link=template_url,
                    sync_status="api_error_fallback",
                )
                database.log_integration_event(
                    integration_type="google_calendar",
                    endpoint=url,
                    status_code=resp.status_code,
                    success=False,
                    payload_summary=f"Failed pushing '{action['title']}' to Google Calendar API",
                    response_excerpt=resp.text,
                )
                return {
                    "synced_via_api": False,
                    "mode": "api_error_fallback",
                    "message": f"Google Calendar API returned HTTP {resp.status_code}. Provided 1-click template link instead.",
                    "action": updated,
                    "gcal_template_url": template_url,
                }
    except Exception as exc:
        updated = database.update_daily_action_status(
            action_id=action["id"],
            gcal_html_link=template_url,
            sync_status="api_error_fallback",
        )
        database.log_integration_event(
            integration_type="google_calendar",
            endpoint=url,
            status_code=500,
            success=False,
            payload_summary=f"Exception pushing '{action['title']}' to Google Calendar",
            response_excerpt=str(exc),
        )
        return {
            "synced_via_api": False,
            "mode": "exception_fallback",
            "message": f"Connection error ({exc}). Provided 1-click Google Calendar link.",
            "action": updated,
            "gcal_template_url": template_url,
        }


async def sync_day_schedule_with_google_calendar(target_date: str) -> Dict[str, Any]:
    """
    Sync all day-start actions for `target_date` to Google Calendar API
    and optionally fetch existing Google Calendar events for that day.
    """
    actions = database.list_daily_actions(target_date)
    pushed_count = 0
    results = []
    for action in actions:
        if action.get("sync_status") != "synced":
            res = await push_action_to_google_calendar(action)
            results.append(res)
            pushed_count += 1

    # Also attempt to list events from Google Calendar API if token is configured
    settings = database.get_settings()
    access_token = _resolve_google_access_token(settings)
    calendar_id = settings.get("google_calendar_id") or "primary"
    imported_count = 0

    if access_token:
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
        params = {
            "timeMin": f"{target_date}T00:00:00Z",
            "timeMax": f"{target_date}T23:59:59Z",
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    existing_ids = {a.get("gcal_event_id") for a in database.list_daily_actions(target_date)}
                    for item in items:
                        evt_id = item.get("id", "")
                        if not evt_id or evt_id in existing_ids:
                            continue
                        start_raw = item.get("start", {}).get("dateTime", "")
                        end_raw = item.get("end", {}).get("dateTime", "")
                        start_hhmm = start_raw[11:16] if len(start_raw) >= 16 else "09:00"
                        end_hhmm = end_raw[11:16] if len(end_raw) >= 16 else "10:00"
                        database.add_daily_action(
                            action_date=target_date,
                            title=item.get("summary", "Calendar Event"),
                            start_time=start_hhmm,
                            end_time=end_hhmm,
                            description=item.get("description", "Imported from Google Calendar"),
                            priority="medium",
                            category="meeting",
                            status="planned",
                            gcal_event_id=evt_id,
                            gcal_html_link=item.get("htmlLink", ""),
                            sync_status="synced",
                        )
                        imported_count += 1
        except Exception:
            pass

    updated_actions = database.list_daily_actions(target_date)
    return {
        "date": target_date,
        "pushed_actions": pushed_count,
        "imported_events": imported_count,
        "google_api_connected": bool(access_token),
        "actions": updated_actions,
    }


def generate_ics_calendar(target_date: Optional[str] = None) -> str:
    """Export daily actions as a standard RFC 5545 iCalendar (.ics) file."""
    actions = database.list_daily_actions(target_date)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Antigravity//Daily Activity AI Agent//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for act in actions:
        d_clean = act["action_date"].replace("-", "")
        s_clean = act["start_time"].replace(":", "") + "00"
        e_clean = act["end_time"].replace(":", "") + "00"
        uid = f"action-{act['id']}-{d_clean}@daily-activity-agent.local"
        summary = act["title"].replace("\n", " ")
        desc = (act.get("description") or "").replace("\n", "\\n")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_utc}",
                f"DTSTART:{d_clean}T{s_clean}",
                f"DTEND:{d_clean}T{e_clean}",
                f"SUMMARY:[{act['priority'].upper()}] {summary}",
                f"DESCRIPTION:{desc}",
                f"STATUS:{'CONFIRMED' if act['status'] != 'completed' else 'COMPLETED'}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ============================================================================
# External Timesheet Webhook / REST API Submission
# ============================================================================

async def submit_timesheet_to_webhook(work_date: str, notes: str = "") -> Dict[str, Any]:
    """
    Dispatch all timesheet entries for `work_date` to the configured external
    Timesheet Webhook / REST API endpoint.
    """
    entries = database.list_timesheets(work_date)
    if not entries:
        return {
            "success": False,
            "work_date": work_date,
            "message": f"No timesheet entries found for {work_date} to submit.",
            "entries": [],
        }

    settings = database.get_settings()
    webhook_url = (
        settings.get("timesheet_webhook_url", "").strip()
        or os.getenv("TIMESHEET_WEBHOOK_URL", "https://httpbin.org/post").strip()
    )
    api_key = (
        settings.get("timesheet_api_key", "").strip()
        or os.getenv("TIMESHEET_API_KEY", "").strip()
    )
    employee_id = settings.get("timesheet_employee_id", "EMP-2026-01")
    target_hours = float(settings.get("daily_target_hours", "8.0") or 8.0)

    total_hours = round(sum(float(e["hours"]) for e in entries), 2)
    billable_hours = round(sum(float(e["hours"]) for e in entries if e.get("billable")), 2)

    payload = {
        "event": "timesheet.daily_submission",
        "employee_id": employee_id,
        "work_date": work_date,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_hours": total_hours,
            "billable_hours": billable_hours,
            "non_billable_hours": round(total_hours - billable_hours, 2),
            "target_hours": target_hours,
            "utilization_pct": round((total_hours / target_hours) * 100, 1) if target_hours else 100.0,
            "entry_count": len(entries),
            "notes": notes,
        },
        "entries": [
            {
                "id": e["id"],
                "project": e["project"],
                "task_description": e["task_description"],
                "hours": e["hours"],
                "billable": bool(e["billable"]),
                "ticket_id": e.get("ticket_id", ""),
            }
            for e in entries
        ],
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Antigravity-DailyActivityAgent/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        signature = hmac.new(api_key.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        headers["X-Timesheet-Signature-256"] = f"sha256={signature}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(webhook_url, content=payload_bytes, headers=headers)
            ok = 200 <= resp.status_code < 300
            status_label = "submitted" if ok else "webhook_failed"
            excerpt = resp.text[:300]
            updated_entries = database.mark_timesheets_submitted(
                work_date=work_date,
                status="submitted" if ok else "draft",
                webhook_response=json.dumps(
                    {
                        "http_status": resp.status_code,
                        "endpoint": webhook_url,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                ),
            )
            database.log_integration_event(
                integration_type="timesheet_webhook",
                endpoint=webhook_url,
                status_code=resp.status_code,
                success=ok,
                payload_summary=f"Submitted {len(entries)} entries ({total_hours}h) for {work_date} by {employee_id}",
                response_excerpt=excerpt,
            )
            return {
                "success": ok,
                "work_date": work_date,
                "webhook_url": webhook_url,
                "http_status": resp.status_code,
                "total_hours": total_hours,
                "billable_hours": billable_hours,
                "status": status_label,
                "message": (
                    f"Timesheet for {work_date} ({total_hours}h across {len(entries)} tasks) "
                    f"successfully dispatched to {webhook_url} (HTTP {resp.status_code})."
                    if ok
                    else f"Webhook returned HTTP {resp.status_code}."
                ),
                "entries": updated_entries,
                "payload_sent": payload,
            }
    except Exception as exc:
        # Even if offline or unreachable, record the attempt and allow local submission fallback
        updated_entries = database.mark_timesheets_submitted(
            work_date=work_date,
            status="submitted_offline",
            webhook_response=json.dumps({"error": str(exc), "endpoint": webhook_url}),
        )
        database.log_integration_event(
            integration_type="timesheet_webhook",
            endpoint=webhook_url,
            status_code=503,
            success=False,
            payload_summary=f"Offline/error submitting {total_hours}h for {work_date}",
            response_excerpt=str(exc),
        )
        return {
            "success": False,
            "work_date": work_date,
            "webhook_url": webhook_url,
            "http_status": 503,
            "total_hours": total_hours,
            "billable_hours": billable_hours,
            "status": "submitted_offline",
            "message": f"Marked as submitted locally; webhook {webhook_url} was unreachable ({exc}).",
            "entries": updated_entries,
            "payload_sent": payload,
        }


# ============================================================================
# Zero-Knowledge Cryptographic Password Suggestion Engine
# ============================================================================

def generate_password_suggestions(
    length: int = 24,
    require_symbols: bool = True,
    service_name: str = "",
) -> Dict[str, Any]:
    """
    Generate cryptographically strong password & passphrase candidates in memory.
    Never logs or persists any generated credentials.
    """
    safe_length = max(14, min(64, int(length)))
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*()-_=+[]{}|;:,.<>?"

    alphabet = lower + upper + digits + (symbols if require_symbols else "")

    def _build_random_password(target_len: int) -> str:
        # Guarantee at least 2 of each required character class
        mandatory = [
            secrets.choice(lower),
            secrets.choice(lower),
            secrets.choice(upper),
            secrets.choice(upper),
            secrets.choice(digits),
            secrets.choice(digits),
        ]
        if require_symbols:
            mandatory.extend([secrets.choice(symbols), secrets.choice(symbols)])
        remaining = [secrets.choice(alphabet) for _ in range(target_len - len(mandatory))]
        combined = mandatory + remaining
        # Cryptographic Fisher-Yates shuffle via SystemRandom
        secrets.SystemRandom().shuffle(combined)
        return "".join(combined)

    def _build_passphrase(word_count: int = 5) -> str:
        words = [secrets.choice(WORD_BANK).capitalize() for _ in range(word_count)]
        num_badge = f"{secrets.randbelow(900) + 100}"
        sep = secrets.choice(["-", ".", "_", "!"]) if require_symbols else "-"
        return sep.join(words) + sep + num_badge

    def _build_segmented_token() -> str:
        # Format: xxxx-XXXX-9999-xxxx! (easy to transcribe, high entropy)
        alnum = lower + upper + digits
        blocks = ["".join(secrets.choice(alnum) for _ in range(5)) for _ in range(4)]
        suffix = secrets.choice("!@#$%&*") if require_symbols else secrets.choice(digits)
        return "-".join(blocks) + suffix

    char_pool_size = len(alphabet)
    random_entropy_bits = round(safe_length * math.log2(char_pool_size), 1)
    passphrase_entropy_bits = round(5 * math.log2(len(WORD_BANK)) + math.log2(900) + 2, 1)

    return {
        "service_name": service_name or "General Service",
        "zero_knowledge_notice": "Generated ephemerally using CSPRNG (Python secrets). Never stored on disk or in database.",
        "policy_applied": {
            "length": safe_length,
            "require_symbols": bool(require_symbols),
            "character_pool_size": char_pool_size,
        },
        "suggestions": [
            {
                "type": "High-Entropy Alphanumeric + Symbols",
                "label": "Recommended for Password Managers & Cloud Consoles",
                "value": _build_random_password(safe_length),
                "entropy_bits": random_entropy_bits,
                "strength": "Excellent (Quantum-Resistant Length)" if random_entropy_bits >= 128 else "Very Strong",
            },
            {
                "type": "Maximum Security Vault Key",
                "label": "Extended 32-Character Credential",
                "value": _build_random_password(max(32, safe_length)),
                "entropy_bits": round(max(32, safe_length) * math.log2(char_pool_size), 1),
                "strength": "Maximum Entropy",
            },
            {
                "type": "Memorable Cryptographic Passphrase",
                "label": "Ideal for Master Passwords, SSO & VPNs",
                "value": _build_passphrase(5),
                "entropy_bits": passphrase_entropy_bits,
                "strength": "Strong & Memorable",
            },
            {
                "type": "Segmented CLI / API Key Format",
                "label": "Easy to Verify Visually",
                "value": _build_segmented_token(),
                "entropy_bits": round(20 * math.log2(62) + 3, 1),
                "strength": "Strong",
            },
        ],
    }
