"""
Autonomous Daily Activity Agent built with the Google Antigravity SDK (`google-antigravity`).

Equipping the agent with:
- Custom tools for daily timesheet logging & external webhook submission
- Day-start action noting & Google Calendar API v3 synchronization
- Zero-knowledge password rotation auditing & CSPRNG password suggestions
- Periodic background triggers (`every`) for proactive daily reminders
"""

import asyncio
import json
import logging
import os
from datetime import date, datetime
from dotenv import load_dotenv

import database
import integrations

load_dotenv()
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


# ============================================================================
# 1. Custom Tools for the Google Antigravity SDK Agent
# ============================================================================

def get_daily_activity_snapshot(target_date: str = "") -> str:
    """Retrieves a snapshot of timesheets, day-start calendar actions, and password rotation alerts.

    Args:
        target_date: Optional ISO date string (YYYY-MM-DD). Defaults to today.
    """
    d = target_date or date.today().isoformat()
    timesheets = database.list_timesheets(d)
    actions = database.list_daily_actions(d)
    passwords = database.list_password_accounts()
    due_passwords = [p for p in passwords if p["rotation_status"] in ("overdue", "due_soon")]
    total_hours = round(sum(float(t["hours"]) for t in timesheets), 2)

    return json.dumps(
        {
            "date": d,
            "timesheet_hours_logged": total_hours,
            "timesheet_entries": timesheets,
            "day_start_actions": actions,
            "passwords_needing_rotation": due_passwords,
        },
        indent=2,
    )


def log_daily_timesheet(
    project: str,
    task_description: str,
    hours: float,
    ticket_id: str = "",
    billable: bool = True,
    work_date: str = "",
) -> str:
    """Logs a daily timesheet entry into the local activity database.

    Args:
        project: Project or client name, e.g. "Core Platform API".
        task_description: Summary of work performed.
        hours: Number of hours worked (e.g. 2.5).
        ticket_id: Optional issue tracker ID, e.g. "PLAT-402".
        billable: Whether the work is billable.
        work_date: Date in YYYY-MM-DD format (defaults to today).
    """
    d = work_date or date.today().isoformat()
    entry = database.add_timesheet_entry(
        work_date=d,
        project=project,
        task_description=task_description,
        hours=hours,
        billable=billable,
        ticket_id=ticket_id,
    )
    return json.dumps({"status": "logged", "entry": entry}, indent=2)


async def submit_daily_timesheet_webhook(work_date: str = "", notes: str = "") -> str:
    """Submits all timesheet entries for the specified date to the external timesheet webhook/API.

    Args:
        work_date: Date in YYYY-MM-DD format (defaults to today).
        notes: Optional submission note.
    """
    d = work_date or date.today().isoformat()
    res = await integrations.submit_timesheet_to_webhook(work_date=d, notes=notes)
    return json.dumps(res, indent=2)


async def note_day_start_action_and_sync_calendar(
    title: str,
    start_time: str,
    end_time: str,
    priority: str = "medium",
    category: str = "deep_work",
    description: str = "",
    action_date: str = "",
) -> str:
    """Records a day-start action item and pushes it directly to the user's Google Calendar schedule.

    Args:
        title: Title of the morning action item or calendar block.
        start_time: Start time in 24h HH:MM format (e.g. "09:30").
        end_time: End time in 24h HH:MM format (e.g. "11:00").
        priority: Priority level ("high", "medium", "low").
        category: Block category ("deep_work", "meeting", "admin", "security").
        description: Optional notes or agenda items.
        action_date: Date in YYYY-MM-DD format (defaults to today).
    """
    d = action_date or date.today().isoformat()
    action = database.add_daily_action(
        action_date=d,
        title=title,
        start_time=start_time,
        end_time=end_time,
        description=description,
        priority=priority,
        category=category,
    )
    sync_result = await integrations.push_action_to_google_calendar(action)
    return json.dumps(sync_result, indent=2)


def get_password_rotation_suggestions(
    service_name: str,
    length: int = 24,
    require_symbols: bool = True,
    mark_as_rotated: bool = False,
) -> str:
    """Audits password rotation metadata and generates CSPRNG strong password suggestions.
    Never stores plaintext passwords.

    Args:
        service_name: Name of the service or account to generate replacement credentials for.
        length: Minimum password length (14-64).
        require_symbols: Whether special characters are required.
        mark_as_rotated: If True, updates the service's last_changed_date to today.
    """
    accounts = database.list_password_accounts()
    matched = next(
        (a for a in accounts if service_name.lower() in a["service_name"].lower()),
        None,
    )
    suggestions = integrations.generate_password_suggestions(
        length=length,
        require_symbols=require_symbols,
        service_name=matched["service_name"] if matched else service_name,
    )
    if mark_as_rotated and matched:
        matched = database.mark_password_rotated(matched["id"])
    return json.dumps(
        {
            "account_metadata": matched,
            "generated_suggestions": suggestions,
        },
        indent=2,
    )


# ============================================================================
# 2. Proactive Periodic Trigger (Google Antigravity SDK `every` trigger)
# ============================================================================

async def run_antigravity_cli() -> None:
    """Launch an interactive CLI + background trigger session using google-antigravity SDK."""
    database.init_db()

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_gemini_api_key_here":
        print(
            "\n[!] GEMINI_API_KEY is not set in your environment or .env file.\n"
            "    Get a Gemini API key from Google AI Studio:\n"
            "    https://aistudio.google.com/app/api-keys\n"
        )
        return

    from google.antigravity import Agent, LocalAgentConfig
    from google.antigravity.triggers import TriggerContext, every

    async def daily_hygiene_check(ctx: TriggerContext) -> None:
        """Periodic check that monitors unsubmitted timesheets and overdue password rotations."""
        today_str = date.today().isoformat()
        entries = database.list_timesheets(today_str)
        hours = sum(float(e["hours"]) for e in entries)
        overdue_pw = [
            p["service_name"]
            for p in database.list_password_accounts()
            if p["rotation_status"] == "overdue"
        ]
        now_hhmm = datetime.now().strftime("%H:%M")
        if now_hhmm >= "17:30" and hours < 8.0:
            await ctx.send(
                f"Proactive EOD Check: Only {hours}h/8.0h logged for {today_str}, and "
                f"{len(overdue_pw)} password(s) are overdue ({', '.join(overdue_pw)}). "
                f"Remind the user briefly."
            )

    hygiene_trigger = every(300, daily_hygiene_check)

    config = LocalAgentConfig(
        api_key=api_key,
        system_instructions=(
            "You are an autonomous Daily Activity & Security Hygiene Agent. "
            "Use your tools to track and submit daily timesheets via webhooks, "
            "note day-start actions and sync them to Google Calendar, and suggest "
            "strong CSPRNG passwords for accounts due for rotation."
        ),
        tools=[
            get_daily_activity_snapshot,
            log_daily_timesheet,
            submit_daily_timesheet_webhook,
            note_day_start_action_and_sync_calendar,
            get_password_rotation_suggestions,
        ],
        triggers=[hygiene_trigger],
    )

    async with Agent(config) as agent:
        print("=== Daily Activity Antigravity Agent Ready (type 'exit' to quit) ===")
        while True:
            user_input = await asyncio.to_thread(input, "\nYou > ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            response = await agent.chat(user_input)
            print("Agent > ", end="", flush=True)
            async for chunk in response:
                print(chunk, end="", flush=True)
            print()


if __name__ == "__main__":
    asyncio.run(run_antigravity_cli())
