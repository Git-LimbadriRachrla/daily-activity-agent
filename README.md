# PulseOps — Daily Activity, Calendar & Password Hygiene AI Agent

A full-stack **Web Dashboard + Autonomous AI Agent** built with **FastAPI**, the **Gemini 3.8 Flash Interactions API (`google-genai`)**, and the **Google Antigravity SDK (`google-antigravity`)**.

## Core Capabilities

1. **Daily-Wise Timesheet Tracking & External Webhook/API Submission**
   - Log daily tasks by project, ticket ID, hours, and billable status.
   - Dispatch daily timesheets as signed JSON payloads (`HMAC-SHA256` + `Bearer` token) to any external Timesheet Webhook or REST API (`TIMESHEET_WEBHOOK_URL`).
   - One-click CSV export (`/api/timesheets/export.csv`).

2. **Day-Start Action Planner & Direct Google Calendar API v3 Sync**
   - Note morning action items with priority (`high`, `medium`, `low`), category (`deep_work`, `meeting`, `security`, `admin`), and start/end time blocks.
   - Automatically syncs blocks to **Google Calendar API v3** (`https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events`) via OAuth2 Bearer Token or Service Account JSON.
   - Includes instant 1-click Google Calendar template deep-links and RFC 5545 `.ics` calendar export (`/api/actions/calendar.ics`) out of the box.

3. **Zero-Knowledge Password Rotation Tracker & CSPRNG Suggestion Studio**
   - Tracks only account rotation metadata (`service_name`, `account_identifier`, `rotation_interval_days`, `last_changed_date`, `min_length`, `require_symbols`). **Never stores plaintext or encrypted passwords.**
   - Automatically flags **Overdue** and **Due Soon** accounts.
   - Generates high-entropy random passwords, 32-character vault keys, memorable Diceware passphrases, and segmented CLI tokens in memory using Python's cryptographic `secrets` CSPRNG.

4. **AI Agent Copilot (`gemini-3.8-flash` + Google Antigravity SDK)**
   - Multi-turn conversational agent in the Web UI using the `google-genai` Interactions API and Function Calling tools (`get_daily_briefing`, `log_timesheet_entry`, `submit_daily_timesheet`, `plan_day_start_action`, `sync_google_calendar`, `check_password_rotations`, `suggest_strong_password`).
   - Includes a standalone background/CLI agent (`antigravity_agent.py`) powered by `google-antigravity` with periodic triggers (`every`) for proactive EOD timesheet and password hygiene checks.

---

## Quick Start

### 1. Set Active Workspace
In Antigravity IDE, set your active workspace to:
```
C:\Users\2461995\.gemini\antigravity\scratch\daily-activity-agent
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Configure Environment Variables (Optional — Works Out-of-the-Box!)
Copy `.env.example` to `.env` and add your keys:
```powershell
Copy-Item .env.example .env
```
- **Gemini API Key**: Get a key at [Google AI Studio](https://aistudio.google.com/app/api-keys) and set `GEMINI_API_KEY=...` in `.env`. *(Note: Even before setting `GEMINI_API_KEY`, the built-in local tool orchestrator executes all agent commands in the dashboard!)*
- **Google Calendar API & Timesheet Webhook**: Can be configured either in `.env` or live inside the Web Dashboard by clicking **Integrations & API Keys**.

### 4. Run the Full-Stack Web Dashboard
```powershell
python app.py
```
Then open **http://127.0.0.1:8000** in your browser.

### 5. Run the Autonomous Google Antigravity SDK Agent (Optional CLI + Background Triggers)
```powershell
python antigravity_agent.py
```
