import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "activity_agent.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize SQLite schema and seed realistic initial data if empty."""
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS timesheet_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            project TEXT NOT NULL,
            task_description TEXT NOT NULL,
            hours REAL NOT NULL,
            billable INTEGER NOT NULL DEFAULT 1,
            ticket_id TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            webhook_response TEXT DEFAULT '',
            submitted_at TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_date TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            category TEXT NOT NULL DEFAULT 'deep_work',
            status TEXT NOT NULL DEFAULT 'planned',
            gcal_event_id TEXT DEFAULT '',
            gcal_html_link TEXT DEFAULT '',
            sync_status TEXT NOT NULL DEFAULT 'local_only',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS password_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            account_identifier TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'developer_tools',
            rotation_interval_days INTEGER NOT NULL DEFAULT 90,
            last_changed_date TEXT NOT NULL,
            min_length INTEGER NOT NULL DEFAULT 20,
            require_symbols INTEGER NOT NULL DEFAULT 1,
            mfa_enabled INTEGER NOT NULL DEFAULT 1,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS integration_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS integration_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            integration_type TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            success INTEGER NOT NULL,
            payload_summary TEXT NOT NULL,
            response_excerpt TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )

    # Default integration settings from environment variables
    now_iso = datetime.now().isoformat(timespec="seconds")
    default_settings = {
        "google_calendar_id": os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        "google_calendar_access_token": os.getenv("GOOGLE_CALENDAR_ACCESS_TOKEN", ""),
        "google_service_account_path": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        "timesheet_webhook_url": os.getenv("TIMESHEET_WEBHOOK_URL", "https://httpbin.org/post"),
        "timesheet_api_key": os.getenv("TIMESHEET_API_KEY", ""),
        "timesheet_employee_id": os.getenv("TIMESHEET_EMPLOYEE_ID", "EMP-2026-01"),
        "timezone": os.getenv("TIMEZONE", "Asia/Kolkata"),
        "daily_target_hours": "8.0",
    }
    for key, val in default_settings.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO integration_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, val, now_iso),
        )

    # Seed initial entries if tables are empty
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    cur.execute("SELECT COUNT(*) FROM timesheet_entries")
    if cur.fetchone()[0] == 0:
        sample_timesheets = [
            (
                today_str,
                "Core Platform API",
                "Implemented OAuth2 token refresh & webhook retry pipeline",
                3.5,
                1,
                "PLAT-402",
                "draft",
                "",
                None,
                now_iso,
            ),
            (
                today_str,
                "AI Agent Automation",
                "Sprint planning, architecture review & calendar sync integration",
                2.0,
                1,
                "AI-118",
                "draft",
                "",
                None,
                now_iso,
            ),
            (
                yesterday_str,
                "Core Platform API",
                "Database query optimization and API schema validation",
                8.0,
                1,
                "PLAT-399",
                "submitted",
                '{"status": "accepted", "provider": "TimesheetWebhook"}',
                now_iso,
                now_iso,
            ),
        ]
        cur.executemany(
            """
            INSERT INTO timesheet_entries
            (work_date, project, task_description, hours, billable, ticket_id, status, webhook_response, submitted_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_timesheets,
        )

    cur.execute("SELECT COUNT(*) FROM daily_actions")
    if cur.fetchone()[0] == 0:
        sample_actions = [
            (
                today_str,
                "Day-Start Triage & Sprint Standup",
                "Review blockers, confirm daily deliverables, and align calendar blocks",
                "09:30",
                "10:00",
                "high",
                "meeting",
                "completed",
                "local-evt-101",
                "",
                "local_only",
                now_iso,
            ),
            (
                today_str,
                "Deep Work: Webhook & Calendar Sync Engine",
                "Complete Google Calendar API event push and timesheet webhook payload signing",
                "10:30",
                "13:00",
                "high",
                "deep_work",
                "in_progress",
                "local-evt-102",
                "",
                "local_only",
                now_iso,
            ),
            (
                today_str,
                "Security Hygiene: Rotate Production AWS & GitHub Tokens",
                "Audit expiring credentials and update rotation timestamps",
                "15:00",
                "15:45",
                "medium",
                "security",
                "planned",
                "local-evt-103",
                "",
                "local_only",
                now_iso,
            ),
            (
                today_str,
                "End-of-Day Timesheet Submission & Wrap-up",
                "Verify 8.0h target logged and dispatch daily timesheet webhook",
                "17:30",
                "18:00",
                "high",
                "admin",
                "planned",
                "local-evt-104",
                "",
                "local_only",
                now_iso,
            ),
        ]
        cur.executemany(
            """
            INSERT INTO daily_actions
            (action_date, title, description, start_time, end_time, priority, category, status, gcal_event_id, gcal_html_link, sync_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_actions,
        )

    cur.execute("SELECT COUNT(*) FROM password_accounts")
    if cur.fetchone()[0] == 0:
        d_overdue_1 = (date.today() - timedelta(days=98)).isoformat()
        d_overdue_2 = (date.today() - timedelta(days=65)).isoformat()
        d_due_soon = (date.today() - timedelta(days=85)).isoformat()
        d_healthy_1 = (date.today() - timedelta(days=18)).isoformat()
        d_healthy_2 = (date.today() - timedelta(days=32)).isoformat()

        sample_passwords = [
            (
                "AWS Production Console",
                "admin-prod@company.io",
                "cloud_infra",
                90,
                d_overdue_1,
                24,
                1,
                1,
                "IAM root/admin role — requires 24+ chars & symbols every 90 days",
                now_iso,
            ),
            (
                "PostgreSQL Analytics Cluster",
                "db_analytics_rw",
                "database",
                60,
                d_overdue_2,
                24,
                1,
                1,
                "Rotate every 60 days; update secret manager after rotation",
                now_iso,
            ),
            (
                "GitHub Enterprise & PAT",
                "dev-handle@company.io",
                "developer_tools",
                90,
                d_due_soon,
                20,
                1,
                1,
                "Fine-grained token + account password rotation due within 5 days",
                now_iso,
            ),
            (
                "Google Workspace Corporate SSO",
                "user@company.io",
                "corporate_sso",
                90,
                d_healthy_1,
                20,
                1,
                1,
                "Primary identity provider with hardware security key",
                now_iso,
            ),
            (
                "Corporate VPN & Bastion Host",
                "vpn-tunnel-01",
                "cloud_infra",
                60,
                d_healthy_2,
                22,
                1,
                1,
                "WireGuard / OpenVPN passphrase",
                now_iso,
            ),
        ]
        cur.executemany(
            """
            INSERT INTO password_accounts
            (service_name, account_identifier, category, rotation_interval_days, last_changed_date, min_length, require_symbols, mfa_enabled, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_passwords,
        )

    conn.commit()
    conn.close()


# ============================================================================
# Settings Helpers
# ============================================================================

def get_settings() -> Dict[str, str]:
    conn = get_connection()
    rows = conn.execute("SELECT setting_key, setting_value FROM integration_settings").fetchall()
    conn.close()
    return {r["setting_key"]: r["setting_value"] for r in rows}


def update_settings(updates: Dict[str, Any]) -> Dict[str, str]:
    conn = get_connection()
    now_iso = datetime.now().isoformat(timespec="seconds")
    for k, v in updates.items():
        if v is not None:
            conn.execute(
                """
                INSERT INTO integration_settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                (k, str(v), now_iso),
            )
    conn.commit()
    conn.close()
    return get_settings()


def log_integration_event(
    integration_type: str,
    endpoint: str,
    status_code: int,
    success: bool,
    payload_summary: str,
    response_excerpt: str = "",
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO integration_logs
        (integration_type, endpoint, status_code, success, payload_summary, response_excerpt, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            integration_type,
            endpoint,
            status_code,
            1 if success else 0,
            payload_summary,
            response_excerpt[:500],
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def get_integration_logs(limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM integration_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
# Timesheet CRUD
# ============================================================================

def list_timesheets(work_date: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    if work_date:
        rows = conn.execute(
            "SELECT * FROM timesheet_entries WHERE work_date = ? ORDER BY id DESC",
            (work_date,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM timesheet_entries ORDER BY work_date DESC, id DESC LIMIT 100"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_timesheet_entry(
    work_date: str,
    project: str,
    task_description: str,
    hours: float,
    billable: bool = True,
    ticket_id: str = "",
) -> Dict[str, Any]:
    conn = get_connection()
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO timesheet_entries
        (work_date, project, task_description, hours, billable, ticket_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)
        """,
        (work_date, project, task_description, float(hours), 1 if billable else 0, ticket_id, now_iso),
    )
    entry_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM timesheet_entries WHERE id = ?", (entry_id,)).fetchone()
    conn.close()
    return dict(row)


def delete_timesheet_entry(entry_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM timesheet_entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def mark_timesheets_submitted(
    work_date: str, status: str, webhook_response: str
) -> List[Dict[str, Any]]:
    conn = get_connection()
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        UPDATE timesheet_entries
        SET status = ?, webhook_response = ?, submitted_at = ?
        WHERE work_date = ?
        """,
        (status, webhook_response, now_iso, work_date),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM timesheet_entries WHERE work_date = ? ORDER BY id ASC",
        (work_date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
# Day-Start Actions & Calendar Schedule CRUD
# ============================================================================

def list_daily_actions(action_date: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    if action_date:
        rows = conn.execute(
            "SELECT * FROM daily_actions WHERE action_date = ? ORDER BY start_time ASC",
            (action_date,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM daily_actions ORDER BY action_date DESC, start_time ASC LIMIT 100"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_daily_action(
    action_date: str,
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    priority: str = "medium",
    category: str = "deep_work",
    status: str = "planned",
    gcal_event_id: str = "",
    gcal_html_link: str = "",
    sync_status: str = "local_only",
) -> Dict[str, Any]:
    conn = get_connection()
    now_iso = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO daily_actions
        (action_date, title, description, start_time, end_time, priority, category, status, gcal_event_id, gcal_html_link, sync_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_date,
            title,
            description,
            start_time,
            end_time,
            priority,
            category,
            status,
            gcal_event_id,
            gcal_html_link,
            sync_status,
            now_iso,
        ),
    )
    action_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM daily_actions WHERE id = ?", (action_id,)).fetchone()
    conn.close()
    return dict(row)


def update_daily_action_status(
    action_id: int,
    status: Optional[str] = None,
    gcal_event_id: Optional[str] = None,
    gcal_html_link: Optional[str] = None,
    sync_status: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM daily_actions WHERE id = ?", (action_id,)).fetchone()
    if not row:
        conn.close()
        return None
    current = dict(row)
    new_status = status if status is not None else current["status"]
    new_gcal_id = gcal_event_id if gcal_event_id is not None else current["gcal_event_id"]
    new_gcal_link = gcal_html_link if gcal_html_link is not None else current["gcal_html_link"]
    new_sync = sync_status if sync_status is not None else current["sync_status"]

    conn.execute(
        """
        UPDATE daily_actions
        SET status = ?, gcal_event_id = ?, gcal_html_link = ?, sync_status = ?
        WHERE id = ?
        """,
        (new_status, new_gcal_id, new_gcal_link, new_sync, action_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM daily_actions WHERE id = ?", (action_id,)).fetchone()
    conn.close()
    return dict(updated)


def delete_daily_action(action_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM daily_actions WHERE id = ?", (action_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ============================================================================
# Password Metadata & Rotation Tracking CRUD (Zero-Knowledge: No Passwords Stored)
# ============================================================================

def enrich_password_account(row_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Compute days_since_change, days_remaining, and rotation_status."""
    today = date.today()
    try:
        last_changed = date.fromisoformat(row_dict["last_changed_date"])
    except ValueError:
        last_changed = today
    interval = int(row_dict.get("rotation_interval_days", 90))
    next_due = last_changed + timedelta(days=interval)
    days_since = (today - last_changed).days
    days_remaining = (next_due - today).days

    if days_remaining < 0:
        rotation_status = "overdue"
        urgency_score = abs(days_remaining) + 100
    elif days_remaining <= 10:
        rotation_status = "due_soon"
        urgency_score = 50 - days_remaining
    else:
        rotation_status = "healthy"
        urgency_score = 0

    return {
        **row_dict,
        "next_due_date": next_due.isoformat(),
        "days_since_change": days_since,
        "days_remaining": days_remaining,
        "rotation_status": rotation_status,
        "urgency_score": urgency_score,
    }


def list_password_accounts() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM password_accounts ORDER BY id ASC").fetchall()
    conn.close()
    enriched = [enrich_password_account(dict(r)) for r in rows]
    enriched.sort(key=lambda x: x["days_remaining"])
    return enriched


def add_password_account(
    service_name: str,
    account_identifier: str,
    category: str = "developer_tools",
    rotation_interval_days: int = 90,
    last_changed_date: Optional[str] = None,
    min_length: int = 20,
    require_symbols: bool = True,
    mfa_enabled: bool = True,
    notes: str = "",
) -> Dict[str, Any]:
    conn = get_connection()
    now_iso = datetime.now().isoformat(timespec="seconds")
    changed_str = last_changed_date or date.today().isoformat()
    cur = conn.execute(
        """
        INSERT INTO password_accounts
        (service_name, account_identifier, category, rotation_interval_days, last_changed_date, min_length, require_symbols, mfa_enabled, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            service_name,
            account_identifier,
            category,
            int(rotation_interval_days),
            changed_str,
            int(min_length),
            1 if require_symbols else 0,
            1 if mfa_enabled else 0,
            notes,
            now_iso,
        ),
    )
    acc_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM password_accounts WHERE id = ?", (acc_id,)).fetchone()
    conn.close()
    return enrich_password_account(dict(row))


def mark_password_rotated(account_id: int, rotated_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    new_date = rotated_date or date.today().isoformat()
    cur = conn.execute(
        "UPDATE password_accounts SET last_changed_date = ? WHERE id = ?",
        (new_date, account_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        conn.close()
        return None
    row = conn.execute("SELECT * FROM password_accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    return enrich_password_account(dict(row))


def delete_password_account(account_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM password_accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0
