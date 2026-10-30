import json
import os
import re
from datetime import date
from typing import Any, Dict, List, Optional

import database
import integrations

MODEL_ID = "gemini-3.8-flash"

SYSTEM_INSTRUCTION = """You are the Daily Activity & Security Operations AI Agent.
You assist the user with three primary daily workflows:
1. Daily-Wise Timesheet Tracking & Submission:
   - Log work hours by project, task description, ticket ID, and billable flag.
   - Submit daily timesheets to external webhooks/APIs and report HTTP delivery status.
2. Day-Start Action Noting & Google Calendar Schedule Sync:
   - Capture morning action items with time blocks (start_time, end_time), priority, and category.
   - Automatically push and sync day-start actions into the user's Google Calendar schedule.
3. Zero-Knowledge Password Rotation & Strong Password Suggestions:
   - Track account rotation intervals and last-changed dates (never store actual passwords).
   - Identify overdue or expiring credentials and generate high-entropy password & passphrase suggestions tailored to each service's policy.

Always use your function tools when the user asks to log hours, submit timesheets, note or schedule day-start actions, sync Google Calendar, check password rotation status, or generate strong password suggestions.
Be concise, proactive, and structured in your responses.
"""

AGENT_TOOLS = [
    {
        "type": "function",
        "name": "get_daily_briefing",
        "description": "Retrieves a comprehensive summary of today's calendar schedule, day-start actions, timesheet hours logged vs target, and overdue/due-soon password rotations.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "ISO date YYYY-MM-DD (defaults to today).",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "log_timesheet_entry",
        "description": "Logs a new daily timesheet entry for a specific project and task.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project or client name, e.g. 'Core Platform API'",
                },
                "task_description": {
                    "type": "string",
                    "description": "Detailed description of work completed",
                },
                "hours": {
                    "type": "number",
                    "description": "Number of hours spent (e.g. 2.5)",
                },
                "ticket_id": {
                    "type": "string",
                    "description": "Optional Jira/Linear ticket identifier, e.g. 'PLAT-405'",
                },
                "billable": {
                    "type": "boolean",
                    "description": "Whether the hours are billable (default true)",
                },
                "work_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (defaults to today)",
                },
            },
            "required": ["project", "task_description", "hours"],
        },
    },
    {
        "type": "function",
        "name": "submit_daily_timesheet",
        "description": "Submits all timesheet entries for a given date to the configured external Timesheet Webhook / REST API.",
        "parameters": {
            "type": "object",
            "properties": {
                "work_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (defaults to today)",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional submission comment or summary note",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "plan_day_start_action",
        "description": "Notes a day-start action item, schedules it in a calendar time slot, and pushes it to Google Calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Action item or calendar event title",
                },
                "start_time": {
                    "type": "string",
                    "description": "24-hour start time HH:MM, e.g. '11:00'",
                },
                "end_time": {
                    "type": "string",
                    "description": "24-hour end time HH:MM, e.g. '12:30'",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Priority level of the action item",
                },
                "category": {
                    "type": "string",
                    "enum": ["deep_work", "meeting", "admin", "security"],
                    "description": "Category of the action block",
                },
                "description": {
                    "type": "string",
                    "description": "Additional context or acceptance criteria",
                },
                "action_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (defaults to today)",
                },
            },
            "required": ["title", "start_time", "end_time"],
        },
    },
    {
        "type": "function",
        "name": "sync_google_calendar",
        "description": "Synchronizes all day-start actions for a given date with the Google Calendar API.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (defaults to today)",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "check_password_rotations",
        "description": "Audits tracked accounts for overdue or upcoming password rotations (zero-knowledge metadata only).",
        "parameters": {
            "type": "object",
            "properties": {
                "only_due": {
                    "type": "boolean",
                    "description": "If true, returns only overdue or due-soon accounts",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "suggest_strong_password",
        "description": "Generates cryptographically secure password and passphrase suggestions for a service and optionally marks its rotation timestamp as updated today.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the service or account (e.g. 'AWS Production Console')",
                },
                "length": {
                    "type": "integer",
                    "description": "Desired password length (14 to 64, default 24)",
                },
                "require_symbols": {
                    "type": "boolean",
                    "description": "Whether to include special symbols (default true)",
                },
                "mark_rotated": {
                    "type": "boolean",
                    "description": "If true, also marks the matching account as rotated today",
                },
            },
            "required": ["service_name"],
        },
    },
]


async def execute_agent_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one of the declared agent tools and return structured JSON output."""
    today_str = date.today().isoformat()

    if name == "get_daily_briefing":
        target_date = arguments.get("target_date") or today_str
        timesheets = database.list_timesheets(target_date)
        actions = database.list_daily_actions(target_date)
        passwords = database.list_password_accounts()
        settings = database.get_settings()
        target_hours = float(settings.get("daily_target_hours", "8.0") or 8.0)
        logged_hours = round(sum(float(t["hours"]) for t in timesheets), 2)
        overdue_pw = [p for p in passwords if p["rotation_status"] == "overdue"]
        due_soon_pw = [p for p in passwords if p["rotation_status"] == "due_soon"]

        return {
            "date": target_date,
            "timesheet_summary": {
                "logged_hours": logged_hours,
                "target_hours": target_hours,
                "remaining_hours": max(0.0, round(target_hours - logged_hours, 2)),
                "entries_count": len(timesheets),
                "all_submitted": bool(timesheets) and all(t["status"] == "submitted" for t in timesheets),
                "entries": timesheets,
            },
            "calendar_schedule": {
                "total_actions": len(actions),
                "completed_actions": sum(1 for a in actions if a["status"] == "completed"),
                "planned_actions": [a for a in actions if a["status"] != "completed"],
                "all_actions": actions,
            },
            "password_security": {
                "overdue_count": len(overdue_pw),
                "due_soon_count": len(due_soon_pw),
                "overdue_accounts": overdue_pw,
                "due_soon_accounts": due_soon_pw,
            },
        }

    elif name == "log_timesheet_entry":
        work_date = arguments.get("work_date") or today_str
        entry = database.add_timesheet_entry(
            work_date=work_date,
            project=arguments.get("project", "General Project"),
            task_description=arguments.get("task_description", "Daily development task"),
            hours=float(arguments.get("hours", 1.0)),
            billable=bool(arguments.get("billable", True)),
            ticket_id=arguments.get("ticket_id", ""),
        )
        day_entries = database.list_timesheets(work_date)
        total_day_hours = round(sum(float(e["hours"]) for e in day_entries), 2)
        return {
            "status": "logged",
            "entry": entry,
            "day_total_hours": total_day_hours,
        }

    elif name == "submit_daily_timesheet":
        work_date = arguments.get("work_date") or today_str
        notes = arguments.get("notes", "Submitted via Daily Activity AI Agent")
        return await integrations.submit_timesheet_to_webhook(work_date=work_date, notes=notes)

    elif name == "plan_day_start_action":
        action_date = arguments.get("action_date") or today_str
        action = database.add_daily_action(
            action_date=action_date,
            title=arguments.get("title", "Focus Block"),
            start_time=arguments.get("start_time", "10:00"),
            end_time=arguments.get("end_time", "11:00"),
            description=arguments.get("description", ""),
            priority=arguments.get("priority", "medium"),
            category=arguments.get("category", "deep_work"),
            status="planned",
        )
        gcal_res = await integrations.push_action_to_google_calendar(action)
        return {
            "status": "scheduled",
            "action": gcal_res.get("action", action),
            "google_calendar_sync": gcal_res,
        }

    elif name == "sync_google_calendar":
        target_date = arguments.get("target_date") or today_str
        return await integrations.sync_day_schedule_with_google_calendar(target_date)

    elif name == "check_password_rotations":
        accounts = database.list_password_accounts()
        if arguments.get("only_due"):
            accounts = [
                a for a in accounts if a["rotation_status"] in ("overdue", "due_soon")
            ]
        return {
            "total_returned": len(accounts),
            "accounts": accounts,
        }

    elif name == "suggest_strong_password":
        service_name = arguments.get("service_name", "Service")
        accounts = database.list_password_accounts()
        matched_account = next(
            (
                a
                for a in accounts
                if service_name.lower() in a["service_name"].lower()
                or a["service_name"].lower() in service_name.lower()
            ),
            None,
        )
        length = int(
            arguments.get("length")
            or (matched_account["min_length"] if matched_account else 24)
        )
        require_symbols = (
            bool(arguments["require_symbols"])
            if "require_symbols" in arguments
            else (bool(matched_account["require_symbols"]) if matched_account else True)
        )
        suggestions = integrations.generate_password_suggestions(
            length=length,
            require_symbols=require_symbols,
            service_name=matched_account["service_name"] if matched_account else service_name,
        )
        rotated_record = None
        if arguments.get("mark_rotated") and matched_account:
            rotated_record = database.mark_password_rotated(matched_account["id"])
        return {
            **suggestions,
            "matched_account": rotated_record or matched_account,
            "marked_rotated": bool(rotated_record),
        }

    return {"error": f"Unknown tool: {name}"}


async def chat_with_agent(
    user_message: str,
    previous_interaction_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process a user message using the Gemini `gemini-3.8-flash` Interactions API
    with multi-step Function Calling. Falls back to an intelligent local tool-executing
    engine if GEMINI_API_KEY is not configured yet.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key and api_key != "your_gemini_api_key_here":
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            today_str = date.today().isoformat()
            system_prompt = f"{SYSTEM_INSTRUCTION}\nToday's date is {today_str}."

            create_kwargs: Dict[str, Any] = {
                "model": MODEL_ID,
                "input": user_message,
                "system_instruction": system_prompt,
                "tools": AGENT_TOOLS,
            }
            if previous_interaction_id:
                create_kwargs["previous_interaction_id"] = previous_interaction_id

            interaction = client.interactions.create(**create_kwargs)
            executed_tools: List[Dict[str, Any]] = []

            # Loop up to 4 rounds if the model invokes function_call steps
            for _ in range(4):
                fc_steps = [
                    s for s in (interaction.steps or []) if getattr(s, "type", None) == "function_call"
                ]
                if not fc_steps:
                    break

                function_results = []
                for fc in fc_steps:
                    tool_name = fc.name
                    tool_args = dict(fc.arguments) if fc.arguments else {}
                    tool_output = await execute_agent_tool(tool_name, tool_args)
                    executed_tools.append(
                        {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "result": tool_output,
                        }
                    )
                    function_results.append(
                        {
                            "type": "function_result",
                            "name": tool_name,
                            "call_id": fc.id,
                            "result": [{"type": "text", "text": json.dumps(tool_output)}],
                        }
                    )

                interaction = client.interactions.create(
                    model=MODEL_ID,
                    input=function_results,
                    system_instruction=system_prompt,
                    tools=AGENT_TOOLS,
                    previous_interaction_id=interaction.id,
                )

            return {
                "reply": interaction.output_text or "Action completed.",
                "interaction_id": interaction.id,
                "model": MODEL_ID,
                "mode": "gemini_interactions_api",
                "executed_tools": executed_tools,
            }
        except Exception as exc:
            # Fall through to local tool orchestration with diagnostic note
            fallback = await _local_agent_orchestrator(user_message)
            fallback["note"] = f"Executed via built-in tool router (Gemini API note: {exc})"
            return fallback

    return await _local_agent_orchestrator(user_message)


async def _local_agent_orchestrator(user_message: str) -> Dict[str, Any]:
    """
    Deterministic natural-language tool orchestrator so the user can test all
    agent capabilities immediately even before setting GEMINI_API_KEY.
    """
    msg_lower = user_message.lower()
    executed_tools: List[Dict[str, Any]] = []
    today_str = date.today().isoformat()

    # 1. Check if user wants to log timesheet hours
    hours_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h\b)", msg_lower)
    if ("log" in msg_lower or "timesheet" in msg_lower or "worked" in msg_lower) and hours_match:
        hours_val = float(hours_match.group(1))
        project = "Core Platform API"
        proj_match = re.search(r"(?:on|for|project)\s+([A-Za-z0-9 _\-]{3,35})", user_message, re.I)
        if proj_match:
            project = proj_match.group(1).strip()
        ticket_match = re.search(r"\b([A-Z]{2,6}-\d{1,5})\b", user_message)
        ticket_id = ticket_match.group(1) if ticket_match else ""
        res = await execute_agent_tool(
            "log_timesheet_entry",
            {
                "project": project,
                "task_description": user_message,
                "hours": hours_val,
                "ticket_id": ticket_id,
                "work_date": today_str,
            },
        )
        executed_tools.append({"tool": "log_timesheet_entry", "result": res})
        entry = res["entry"]
        return {
            "reply": (
                f"Logged **{entry['hours']}h** under **{entry['project']}** "
                f"(`{entry['work_date']}`).\n\n"
                f"- **Task:** {entry['task_description']}\n"
                f"- **Total Logged Today:** `{res['day_total_hours']}h`"
            ),
            "interaction_id": None,
            "model": "local-tool-orchestrator (set GEMINI_API_KEY for gemini-3.8-flash)",
            "mode": "local_orchestrator",
            "executed_tools": executed_tools,
        }

    # 2. Check if user wants to submit timesheet
    if "submit" in msg_lower and ("timesheet" in msg_lower or "hours" in msg_lower or "day" in msg_lower):
        res = await execute_agent_tool("submit_daily_timesheet", {"work_date": today_str})
        executed_tools.append({"tool": "submit_daily_timesheet", "result": res})
        return {
            "reply": (
                f"### Timesheet Submission Report (`{today_str}`)\n"
                f"- **Status:** `{res.get('status')}` (HTTP `{res.get('http_status', 'N/A')}`)\n"
                f"- **Total Hours:** `{res.get('total_hours', 0)}h` (`{res.get('billable_hours', 0)}h` billable)\n"
                f"- **Endpoint:** `{res.get('webhook_url', '')}`\n\n"
                f"{res.get('message', '')}"
            ),
            "interaction_id": None,
            "model": "local-tool-orchestrator (set GEMINI_API_KEY for gemini-3.8-flash)",
            "mode": "local_orchestrator",
            "executed_tools": executed_tools,
        }

    # 3. Check if user wants to schedule / note a day-start action or calendar block
    time_range = re.search(
        r"(\d{1,2}:\d{2})\s*(?:to|\-|–|until)\s*(\d{1,2}:\d{2})", msg_lower
    )
    if any(k in msg_lower for k in ("schedule", "calendar", "action", "note", "plan", "standup", "meeting")) and time_range:
        start_t = time_range.group(1).zfill(5)
        end_t = time_range.group(2).zfill(5)
        cleaned_title = re.sub(
            r"^(?:schedule|note|plan|add)\s+(?:an?\s+)?(?:action|meeting|event|block)?\s*(?:for|to|:)?\s*",
            "",
            user_message,
            flags=re.I,
        ).strip()
        priority = "high" if "high" in msg_lower or "urgent" in msg_lower else "medium"
        res = await execute_agent_tool(
            "plan_day_start_action",
            {
                "title": cleaned_title,
                "start_time": start_t,
                "end_time": end_t,
                "priority": priority,
                "category": "deep_work",
                "action_date": today_str,
            },
        )
        executed_tools.append({"tool": "plan_day_start_action", "result": res})
        act = res["action"]
        gcal = res["google_calendar_sync"]
        return {
            "reply": (
                f"Scheduled day-start action **{act['title']}** (`{act['start_time']} - {act['end_time']}`) "
                f"for `{act['action_date']}`.\n\n"
                f"- **Priority:** `{act['priority'].upper()}`\n"
                f"- **Google Calendar Status:** {gcal.get('message')}\n"
                f"- **[Open in Google Calendar]({act.get('gcal_html_link') or gcal.get('gcal_template_url', '#')})**"
            ),
            "interaction_id": None,
            "model": "local-tool-orchestrator (set GEMINI_API_KEY for gemini-3.8-flash)",
            "mode": "local_orchestrator",
            "executed_tools": executed_tools,
        }

    # 4. Check if user asks for password suggestions or rotation audit
    if any(k in msg_lower for k in ("password", "rotate", "rotation", "credential", "secret", "passphrase")):
        accounts = database.list_password_accounts()
        matched = next(
            (a for a in accounts if a["service_name"].lower() in msg_lower or any(w in msg_lower for w in a["service_name"].lower().split() if len(w) > 2)),
            None,
        )
        target_service = matched["service_name"] if matched else (accounts[0]["service_name"] if accounts else "Corporate Service")
        sug = await execute_agent_tool(
            "suggest_strong_password",
            {
                "service_name": target_service,
                "mark_rotated": "mark" in msg_lower and "rotat" in msg_lower,
            },
        )
        rot_check = await execute_agent_tool("check_password_rotations", {"only_due": True})
        executed_tools.append({"tool": "check_password_rotations", "result": rot_check})
        executed_tools.append({"tool": "suggest_strong_password", "result": sug})

        due_lines = "\n".join(
            f"- **{a['service_name']}** (`{a['account_identifier']}`): **{a['rotation_status'].upper()}** "
            f"({abs(a['days_remaining'])} days {'overdue' if a['days_remaining'] < 0 else 'remaining'})"
            for a in rot_check["accounts"]
        )
        cand_lines = "\n".join(
            f"- **{c['type']}** (`{c['entropy_bits']} bits`): `{c['value']}`"
            for c in sug["suggestions"]
        )
        return {
            "reply": (
                f"### Zero-Knowledge Password Rotation Audit\n"
                f"{due_lines or 'All tracked accounts are within their rotation interval.'}\n\n"
                f"### Fresh CSPRNG Suggestions for **{sug['service_name']}**\n"
                f"{cand_lines}\n\n"
                f"*Note: Passwords are generated ephemerally in memory and never stored.*"
            ),
            "interaction_id": None,
            "model": "local-tool-orchestrator (set GEMINI_API_KEY for gemini-3.8-flash)",
            "mode": "local_orchestrator",
            "executed_tools": executed_tools,
        }

    # 5. Check if user asks to sync calendar
    if "sync" in msg_lower and "calendar" in msg_lower:
        res = await execute_agent_tool("sync_google_calendar", {"target_date": today_str})
        executed_tools.append({"tool": "sync_google_calendar", "result": res})
        return {
            "reply": (
                f"Synchronized `{res['pushed_actions']}` day-start action(s) for `{today_str}` "
                f"with Google Calendar (`google_api_connected={res['google_api_connected']}`)."
            ),
            "interaction_id": None,
            "model": "local-tool-orchestrator (set GEMINI_API_KEY for gemini-3.8-flash)",
            "mode": "local_orchestrator",
            "executed_tools": executed_tools,
        }

    # Default: Provide a rich Daily Briefing
    briefing = await execute_agent_tool("get_daily_briefing", {"target_date": today_str})
    executed_tools.append({"tool": "get_daily_briefing", "result": briefing})
    ts = briefing["timesheet_summary"]
    cal = briefing["calendar_schedule"]
    pw = briefing["password_security"]

    return {
        "reply": (
            f"### Daily Activity Briefing (`{today_str}`)\n\n"
            f"1. **Timesheet Progress:** `{ts['logged_hours']}h / {ts['target_hours']}h` logged across "
            f"`{ts['entries_count']}` task(s) ({ts['remaining_hours']}h remaining before EOD submission).\n"
            f"2. **Day-Start Calendar Schedule:** `{cal['total_actions']}` time-blocked actions "
            f"(`{cal['completed_actions']}` completed, `{len(cal['planned_actions'])}` active/upcoming).\n"
            f"3. **Password Hygiene Alerts:** `{pw['overdue_count']}` overdue account(s) and "
            f"`{pw['due_soon_count']}` due soon.\n\n"
            f"**Try asking me:**\n"
            f"- *\"Log 2.5 hours on Core Platform API for OAuth2 calendar sync (PLAT-410)\"*\n"
            f"- *\"Schedule a high priority action from 14:00 to 15:00 for API Security Review\"*\n"
            f"- *\"Suggest a strong password for AWS Production Console\"*\n"
            f"- *\"Submit today's timesheet to the webhook\"*"
        ),
        "interaction_id": None,
        "model": "local-tool-orchestrator (set GEMINI_API_KEY for gemini-3.8-flash)",
        "mode": "local_orchestrator",
        "executed_tools": executed_tools,
    }
