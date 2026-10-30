import csv
import io
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent_service
import database
import integrations

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(
    title="Daily Activity & Security Operations AI Agent",
    description=(
        "Full-stack AI Agent for daily timesheet webhook submission, "
        "day-start action planning with Google Calendar API sync, and "
        "zero-knowledge password rotation suggestions."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Pydantic Request Schemas
# ============================================================================

class TimesheetCreateRequest(BaseModel):
    work_date: Optional[str] = None
    project: str = Field(..., min_length=1)
    task_description: str = Field(..., min_length=1)
    hours: float = Field(..., gt=0, le=24)
    billable: bool = True
    ticket_id: str = ""


class TimesheetSubmitRequest(BaseModel):
    work_date: Optional[str] = None
    notes: str = ""


class DailyActionCreateRequest(BaseModel):
    action_date: Optional[str] = None
    title: str = Field(..., min_length=1)
    description: str = ""
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    priority: str = "medium"
    category: str = "deep_work"
    sync_to_google: bool = True


class DailyActionStatusUpdate(BaseModel):
    status: str


class PasswordAccountCreateRequest(BaseModel):
    service_name: str = Field(..., min_length=1)
    account_identifier: str = Field(..., min_length=1)
    category: str = "developer_tools"
    rotation_interval_days: int = Field(90, ge=7, le=365)
    last_changed_date: Optional[str] = None
    min_length: int = Field(20, ge=14, le=64)
    require_symbols: bool = True
    mfa_enabled: bool = True
    notes: str = ""


class PasswordSuggestRequest(BaseModel):
    service_name: str = "General Service"
    length: int = Field(24, ge=14, le=64)
    require_symbols: bool = True
    account_id: Optional[int] = None
    mark_rotated: bool = False


class SettingsUpdateRequest(BaseModel):
    google_calendar_id: Optional[str] = None
    google_calendar_access_token: Optional[str] = None
    google_service_account_path: Optional[str] = None
    timesheet_webhook_url: Optional[str] = None
    timesheet_api_key: Optional[str] = None
    timesheet_employee_id: Optional[str] = None
    timezone: Optional[str] = None
    daily_target_hours: Optional[str] = None


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    previous_interaction_id: Optional[str] = None


# ============================================================================
# Unified Dashboard State Endpoint
# ============================================================================

@app.get("/api/dashboard")
async def get_dashboard_state(target_date: Optional[str] = Query(None)):
    d = target_date or date.today().isoformat()
    briefing = await agent_service.execute_agent_tool("get_daily_briefing", {"target_date": d})
    settings = database.get_settings()
    logs = database.get_integration_logs(limit=15)
    passwords = database.list_password_accounts()
    gemini_configured = bool(
        os.getenv("GEMINI_API_KEY", "").strip()
        and os.getenv("GEMINI_API_KEY", "").strip() != "your_gemini_api_key_here"
    )
    gcal_configured = bool(
        settings.get("google_calendar_access_token", "").strip()
        or settings.get("google_service_account_path", "").strip()
    )

    # Enrich actions with instant 1-click Google Calendar template links if not already set
    tz_name = settings.get("timezone", "Asia/Kolkata")
    for act in briefing["calendar_schedule"]["all_actions"]:
        if not act.get("gcal_html_link"):
            act["gcal_html_link"] = integrations.build_gcal_template_url(
                title=act["title"],
                action_date=act["action_date"],
                start_time=act["start_time"],
                end_time=act["end_time"],
                description=act.get("description", ""),
                tz_name=tz_name,
            )

    return {
        "date": d,
        "briefing": briefing,
        "password_accounts": passwords,
        "settings": {
            **settings,
            # Mask secret tokens for display safety while indicating presence
            "has_gcal_token": gcal_configured,
            "has_gemini_key": gemini_configured,
        },
        "integration_logs": logs,
    }


# ============================================================================
# Timesheet Endpoints
# ============================================================================

@app.get("/api/timesheets")
async def api_list_timesheets(work_date: Optional[str] = Query(None)):
    return {"entries": database.list_timesheets(work_date)}


@app.post("/api/timesheets")
async def api_create_timesheet(req: TimesheetCreateRequest):
    d = req.work_date or date.today().isoformat()
    entry = database.add_timesheet_entry(
        work_date=d,
        project=req.project,
        task_description=req.task_description,
        hours=req.hours,
        billable=req.billable,
        ticket_id=req.ticket_id,
    )
    return {"entry": entry}


@app.delete("/api/timesheets/{entry_id}")
async def api_delete_timesheet(entry_id: int):
    deleted = database.delete_timesheet_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Timesheet entry not found")
    return {"deleted": True, "id": entry_id}


@app.post("/api/timesheets/submit")
async def api_submit_timesheets(req: TimesheetSubmitRequest):
    d = req.work_date or date.today().isoformat()
    result = await integrations.submit_timesheet_to_webhook(work_date=d, notes=req.notes)
    return result


@app.get("/api/timesheets/export.csv")
async def api_export_timesheets_csv(work_date: Optional[str] = Query(None)):
    entries = database.list_timesheets(work_date)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Date", "Project", "Ticket ID", "Task Description", "Hours", "Billable", "Status", "Submitted At"]
    )
    for e in entries:
        writer.writerow(
            [
                e["id"],
                e["work_date"],
                e["project"],
                e.get("ticket_id", ""),
                e["task_description"],
                e["hours"],
                "Yes" if e.get("billable") else "No",
                e["status"],
                e.get("submitted_at") or "",
            ]
        )
    output.seek(0)
    filename = f"timesheet_{work_date or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# Day-Start Actions & Google Calendar Sync Endpoints
# ============================================================================

@app.get("/api/actions")
async def api_list_actions(action_date: Optional[str] = Query(None)):
    return {"actions": database.list_daily_actions(action_date)}


@app.post("/api/actions")
async def api_create_action(req: DailyActionCreateRequest):
    d = req.action_date or date.today().isoformat()
    action = database.add_daily_action(
        action_date=d,
        title=req.title,
        description=req.description,
        start_time=req.start_time,
        end_time=req.end_time,
        priority=req.priority,
        category=req.category,
        status="planned",
    )
    gcal_sync = None
    if req.sync_to_google:
        gcal_sync = await integrations.push_action_to_google_calendar(action)
        action = gcal_sync.get("action") or action
    return {"action": action, "google_calendar_sync": gcal_sync}


@app.patch("/api/actions/{action_id}")
async def api_update_action_status(action_id: int, req: DailyActionStatusUpdate):
    updated = database.update_daily_action_status(action_id=action_id, status=req.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Action not found")
    return {"action": updated}


@app.delete("/api/actions/{action_id}")
async def api_delete_action(action_id: int):
    deleted = database.delete_daily_action(action_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Action not found")
    return {"deleted": True, "id": action_id}


@app.post("/api/actions/sync-calendar")
async def api_sync_calendar(target_date: Optional[str] = Query(None)):
    d = target_date or date.today().isoformat()
    return await integrations.sync_day_schedule_with_google_calendar(d)


@app.get("/api/actions/calendar.ics")
async def api_export_calendar_ics(target_date: Optional[str] = Query(None)):
    ics_content = integrations.generate_ics_calendar(target_date)
    filename = f"schedule_{target_date or 'all'}.ics"
    return PlainTextResponse(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# Password Rotation & CSPRNG Suggestion Endpoints
# ============================================================================

@app.get("/api/passwords")
async def api_list_passwords():
    return {"accounts": database.list_password_accounts()}


@app.post("/api/passwords")
async def api_add_password_account(req: PasswordAccountCreateRequest):
    account = database.add_password_account(
        service_name=req.service_name,
        account_identifier=req.account_identifier,
        category=req.category,
        rotation_interval_days=req.rotation_interval_days,
        last_changed_date=req.last_changed_date,
        min_length=req.min_length,
        require_symbols=req.require_symbols,
        mfa_enabled=req.mfa_enabled,
        notes=req.notes,
    )
    return {"account": account}


@app.post("/api/passwords/{account_id}/rotate")
async def api_mark_password_rotated(account_id: int):
    updated = database.mark_password_rotated(account_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account": updated}


@app.delete("/api/passwords/{account_id}")
async def api_delete_password_account(account_id: int):
    deleted = database.delete_password_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": True, "id": account_id}


@app.post("/api/passwords/suggest")
async def api_suggest_passwords(req: PasswordSuggestRequest):
    suggestions = integrations.generate_password_suggestions(
        length=req.length,
        require_symbols=req.require_symbols,
        service_name=req.service_name,
    )
    updated_account = None
    if req.mark_rotated and req.account_id:
        updated_account = database.mark_password_rotated(req.account_id)
    return {**suggestions, "updated_account": updated_account}


# ============================================================================
# Settings, Logs & Conversational AI Agent Endpoints
# ============================================================================

@app.get("/api/settings")
async def api_get_settings():
    return database.get_settings()


@app.put("/api/settings")
async def api_update_settings(req: SettingsUpdateRequest):
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = database.update_settings(payload)
    return {"settings": updated}


@app.get("/api/logs")
async def api_get_logs():
    return {"logs": database.get_integration_logs(limit=25)}


@app.post("/api/agent/chat")
async def api_agent_chat(req: AgentChatRequest):
    response = await agent_service.chat_with_agent(
        user_message=req.message,
        previous_interaction_id=req.previous_interaction_id,
    )
    return response


# ============================================================================
# Serve Static Frontend
# ============================================================================

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("app:app", host=host, port=port, reload=True)
