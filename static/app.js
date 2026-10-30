const state = {
  activeDate: new Date().toISOString().slice(0, 10),
  previousInteractionId: null,
  activePasswordAccount: null,
  dashboard: null,
};

function showToast(message) {
  const banner = document.getElementById("toastBanner");
  banner.textContent = message;
  banner.hidden = false;
  clearTimeout(banner._timer);
  banner._timer = setTimeout(() => {
    banner.hidden = true;
  }, 4200);
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatMarkdownLite(text) {
  let safe = escapeHtml(text);
  safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
  safe = safe.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="btn-link">$1</a>'
  );
  return safe.replace(/\n/g, "<br/>");
}

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(errText || `HTTP ${resp.status}`);
  }
  return resp.json();
}

async function loadDashboard() {
  try {
    const data = await apiFetch(`/api/dashboard?target_date=${encodeURIComponent(state.activeDate)}`);
    state.dashboard = data;
    renderDashboard(data);
  } catch (err) {
    showToast(`Failed loading dashboard: ${err.message}`);
  }
}

function renderDashboard(data) {
  const { briefing, password_accounts, settings, integration_logs } = data;
  const ts = briefing.timesheet_summary;
  const cal = briefing.calendar_schedule;
  const pw = briefing.password_security;

  // 1. Update Top Bar Integration Pills
  const pillGcal = document.getElementById("pillGcal");
  const pillWebhook = document.getElementById("pillWebhook");
  const pillGemini = document.getElementById("pillGemini");

  pillGcal.classList.toggle("connected", Boolean(settings.has_gcal_token));
  pillGcal.title = settings.has_gcal_token
    ? `Connected to Google Calendar (${settings.google_calendar_id})`
    : "Using 1-click Google Calendar links (add OAuth token in Integrations for direct API push)";

  pillWebhook.classList.toggle("connected", Boolean(settings.timesheet_webhook_url));
  pillWebhook.title = `Webhook: ${settings.timesheet_webhook_url}`;

  pillGemini.classList.toggle("connected", Boolean(settings.has_gemini_key));
  pillGemini.title = settings.has_gemini_key
    ? "Gemini 3.8 Flash Interactions API Active"
    : "Built-in Tool Router Active (Set GEMINI_API_KEY in .env for Gemini 3.8 Flash)";

  // Update export links for active date
  document.getElementById("linkDownloadIcs").href = `/api/actions/calendar.ics?target_date=${encodeURIComponent(state.activeDate)}`;
  document.getElementById("linkExportCsv").href = `/api/timesheets/export.csv?work_date=${encodeURIComponent(state.activeDate)}`;

  // 2. Update KPI Cards
  document.getElementById("kpiHoursValue").textContent = `${ts.logged_hours.toFixed(1)}h / ${ts.target_hours.toFixed(1)}h`;
  const billableTotal = ts.entries
    .filter((e) => e.billable)
    .reduce((acc, e) => acc + Number(e.hours), 0);
  document.getElementById("kpiBillableText").textContent = `${billableTotal.toFixed(1)}h billable (${ts.entries_count} tasks)`;

  const pct = Math.min(100, Math.round((ts.logged_hours / (ts.target_hours || 8)) * 100));
  document.getElementById("kpiHoursProgressFill").style.width = `${pct}%`;

  const tsBadge = document.getElementById("kpiTimesheetStatusBadge");
  if (ts.all_submitted) {
    tsBadge.textContent = "Submitted";
    tsBadge.className = "badge badge-success";
  } else if (ts.logged_hours >= ts.target_hours) {
    tsBadge.textContent = "Ready to Submit";
    tsBadge.className = "badge badge-info";
  } else {
    tsBadge.textContent = "In Progress";
    tsBadge.className = "badge badge-warning";
  }

  document.getElementById("kpiActionsCount").textContent = `${cal.total_actions} Scheduled`;
  document.getElementById("kpiActionsCompleted").textContent = `${cal.completed_actions} of ${cal.total_actions} completed`;

  document.getElementById("kpiOverdueCount").textContent = `${pw.overdue_count} Overdue`;
  document.getElementById("kpiDueSoonCount").textContent = `${pw.due_soon_count} due within 10 days`;
  const pwBadge = document.getElementById("kpiPasswordAlertBadge");
  if (pw.overdue_count > 0) {
    pwBadge.textContent = "Action Required";
    pwBadge.className = "badge badge-danger";
  } else if (pw.due_soon_count > 0) {
    pwBadge.textContent = "Due Soon";
    pwBadge.className = "badge badge-warning";
  } else {
    pwBadge.textContent = "All Healthy";
    pwBadge.className = "badge badge-success";
  }

  // 3. Render Day-Start Calendar Timeline
  renderCalendarTimeline(cal.all_actions);

  // 4. Render Daily Timesheets
  renderTimesheetEntries(ts.entries);

  // 5. Render Password Accounts
  renderPasswordAccounts(password_accounts);

  // 6. Render Integration Logs in Modal
  renderIntegrationLogs(integration_logs);
}

function renderCalendarTimeline(actions) {
  const container = document.getElementById("calendarTimelineList");
  if (!actions || actions.length === 0) {
    container.innerHTML = `<div class="item-card"><p class="item-meta">No day-start actions scheduled for ${escapeHtml(state.activeDate)} yet. Add one above or ask the AI Agent!</p></div>`;
    return;
  }

  container.innerHTML = actions
    .map((act) => {
      const priorityBadge =
        act.priority === "high"
          ? "badge-danger"
          : act.priority === "medium"
          ? "badge-warning"
          : "badge-info";
      const isCompleted = act.status === "completed";
      const nextStatus = isCompleted ? "planned" : "completed";
      const syncLabel =
        act.sync_status === "synced"
          ? `<span class="badge badge-success">Synced to GCal API</span>`
          : `<span class="badge badge-info">GCal Link Ready</span>`;

      return `
        <article class="item-card" role="listitem">
          <div class="item-top">
            <div>
              <span class="time-pill">${escapeHtml(act.start_time)} – ${escapeHtml(act.end_time)}</span>
              <h3 class="item-title ${isCompleted ? "completed" : ""}" style="margin-top:5px;">
                ${escapeHtml(act.title)}
              </h3>
            </div>
            <span class="badge ${priorityBadge}">${escapeHtml(act.priority)}</span>
          </div>
          ${act.description ? `<p class="item-meta" style="margin:0;">${escapeHtml(act.description)}</p>` : ""}
          <div class="item-actions">
            <div class="item-meta">
              ${syncLabel}
              <a href="${escapeHtml(act.gcal_html_link || "#")}" target="_blank" rel="noopener noreferrer" class="btn-link">
                Open in Google Calendar &nearr;
              </a>
            </div>
            <div class="btn-group">
              <button type="button" class="btn btn-sm btn-secondary" onclick="toggleActionStatus(${act.id}, '${nextStatus}')">
                ${isCompleted ? "Reopen" : "Mark Done"}
              </button>
              <button type="button" class="btn btn-sm btn-secondary" onclick="removeAction(${act.id})" title="Delete">
                &times;
              </button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderTimesheetEntries(entries) {
  const container = document.getElementById("timesheetEntriesList");
  if (!entries || entries.length === 0) {
    container.innerHTML = `<div class="item-card"><p class="item-meta">No timesheet hours logged for ${escapeHtml(state.activeDate)} yet.</p></div>`;
    return;
  }

  container.innerHTML = entries
    .map((entry) => {
      const isSubmitted = entry.status === "submitted";
      const statusBadge = isSubmitted ? "badge-success" : "badge-warning";
      return `
        <article class="item-card" role="listitem">
          <div class="item-top">
            <div>
              <h3 class="item-title">
                ${escapeHtml(entry.project)}
                ${entry.ticket_id ? `<span class="time-pill">${escapeHtml(entry.ticket_id)}</span>` : ""}
              </h3>
              <p class="item-meta" style="margin:4px 0 0;">${escapeHtml(entry.task_description)}</p>
            </div>
            <div style="text-align:right;">
              <strong style="font-size:1rem;">${Number(entry.hours).toFixed(2)}h</strong>
              <div><span class="badge ${statusBadge}">${escapeHtml(entry.status)}</span></div>
            </div>
          </div>
          <div class="item-actions">
            <span class="item-meta">
              ${entry.billable ? "Billable" : "Non-Billable"} • Date: ${escapeHtml(entry.work_date)}
            </span>
            <button type="button" class="btn btn-sm btn-secondary" onclick="removeTimesheet(${entry.id})">
              Delete
            </button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderPasswordAccounts(accounts) {
  const container = document.getElementById("passwordAccountsList");
  if (!accounts || accounts.length === 0) {
    container.innerHTML = `<div class="item-card"><p class="item-meta">No services tracked yet.</p></div>`;
    return;
  }

  container.innerHTML = accounts
    .map((acc) => {
      let badgeClass = "badge-success";
      let statusLabel = `${acc.days_remaining}d left`;
      if (acc.rotation_status === "overdue") {
        badgeClass = "badge-danger";
        statusLabel = `OVERDUE BY ${Math.abs(acc.days_remaining)}D`;
      } else if (acc.rotation_status === "due_soon") {
        badgeClass = "badge-warning";
        statusLabel = `DUE IN ${acc.days_remaining}D`;
      }

      return `
        <article class="item-card" role="listitem">
          <div class="item-top">
            <div>
              <h3 class="item-title">${escapeHtml(acc.service_name)}</h3>
              <span class="item-meta">${escapeHtml(acc.account_identifier)} • Policy: ${acc.min_length}+ chars, every ${acc.rotation_interval_days}d</span>
            </div>
            <span class="badge ${badgeClass}">${escapeHtml(statusLabel)}</span>
          </div>
          <div class="item-meta">
            <span>Last changed: <strong>${escapeHtml(acc.last_changed_date)}</strong></span>
            <span>•</span>
            <span>Next due: <strong>${escapeHtml(acc.next_due_date)}</strong></span>
          </div>
          <div class="item-actions">
            <button
              type="button"
              class="btn btn-sm btn-primary"
              onclick="openPasswordStudio(${acc.id}, '${escapeHtml(acc.service_name)}', ${acc.min_length}, ${Boolean(acc.require_symbols)})"
            >
              Suggest New Password
            </button>
            <div class="btn-group">
              <button
                type="button"
                class="btn btn-sm btn-secondary"
                onclick="markAccountRotated(${acc.id})"
                title="Update last_changed_date to today"
              >
                Mark Rotated Today
              </button>
              <button
                type="button"
                class="btn btn-sm btn-secondary"
                onclick="removePasswordAccount(${acc.id})"
                title="Delete tracked service"
              >
                &times;
              </button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderIntegrationLogs(logs) {
  const container = document.getElementById("integrationLogsContainer");
  if (!logs || logs.length === 0) {
    container.innerHTML = `<p class="item-meta">No external API or webhook calls logged yet.</p>`;
    return;
  }
  container.innerHTML = logs
    .map(
      (log) => `
      <div class="item-card">
        <div class="item-top">
          <strong>${escapeHtml(log.integration_type.toUpperCase())} — ${escapeHtml(log.payload_summary)}</strong>
          <span class="badge ${log.success ? "badge-success" : "badge-danger"}">HTTP ${log.status_code}</span>
        </div>
        <div class="item-meta">
          <code>${escapeHtml(log.endpoint)}</code> • ${escapeHtml(log.created_at)}
        </div>
        ${
          log.response_excerpt
            ? `<pre style="margin:4px 0 0; font-size:0.72rem; color:#94a3b8; white-space:pre-wrap;">${escapeHtml(
                log.response_excerpt
              )}</pre>`
            : ""
        }
      </div>
    `
    )
    .join("");
}

// ============================================================================
// Action Handlers
// ============================================================================

window.toggleActionStatus = async function (actionId, newStatus) {
  try {
    await apiFetch(`/api/actions/${actionId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: newStatus }),
    });
    await loadDashboard();
  } catch (err) {
    showToast(`Failed updating status: ${err.message}`);
  }
};

window.removeAction = async function (actionId) {
  try {
    await apiFetch(`/api/actions/${actionId}`, { method: "DELETE" });
    await loadDashboard();
  } catch (err) {
    showToast(`Failed deleting action: ${err.message}`);
  }
};

window.removeTimesheet = async function (entryId) {
  try {
    await apiFetch(`/api/timesheets/${entryId}`, { method: "DELETE" });
    await loadDashboard();
  } catch (err) {
    showToast(`Failed deleting timesheet entry: ${err.message}`);
  }
};

window.markAccountRotated = async function (accountId) {
  try {
    const res = await apiFetch(`/api/passwords/${accountId}/rotate`, { method: "POST" });
    showToast(`Marked '${res.account.service_name}' password as rotated today!`);
    await loadDashboard();
  } catch (err) {
    showToast(`Error marking rotated: ${err.message}`);
  }
};

window.removePasswordAccount = async function (accountId) {
  try {
    await apiFetch(`/api/passwords/${accountId}`, { method: "DELETE" });
    await loadDashboard();
  } catch (err) {
    showToast(`Failed removing account: ${err.message}`);
  }
};

window.openPasswordStudio = async function (
  accountId = null,
  serviceName = "General Account",
  minLength = 24,
  requireSymbols = true
) {
  state.activePasswordAccount = accountId ? { id: accountId, serviceName } : null;
  document.getElementById("pwStudioTitle").textContent = `Password Suggestions — ${serviceName}`;
  document.getElementById("studioLength").value = minLength;
  document.getElementById("studioSymbols").checked = Boolean(requireSymbols);

  const rotateBtn = document.getElementById("btnMarkAccountRotated");
  rotateBtn.hidden = !accountId;

  const dialog = document.getElementById("dialogPasswordStudio");
  if (!dialog.open) dialog.showModal();
  await fetchPasswordSuggestions();
};

async function fetchPasswordSuggestions() {
  const length = Number(document.getElementById("studioLength").value) || 24;
  const requireSymbols = document.getElementById("studioSymbols").checked;
  const serviceName = state.activePasswordAccount?.serviceName || "Custom Credential";

  const data = await apiFetch("/api/passwords/suggest", {
    method: "POST",
    body: JSON.stringify({
      service_name: serviceName,
      length,
      require_symbols: requireSymbols,
    }),
  });

  const container = document.getElementById("pwSuggestionsContainer");
  container.innerHTML = data.suggestions
    .map(
      (sug) => `
      <div class="pw-candidate-card">
        <div class="item-top">
          <div>
            <strong>${escapeHtml(sug.type)}</strong>
            <div class="item-meta">${escapeHtml(sug.label)}</div>
          </div>
          <span class="badge badge-success">${sug.entropy_bits} bits entropy</span>
        </div>
        <div class="pw-secret-row">
          <code>${escapeHtml(sug.value)}</code>
          <button
            type="button"
            class="btn btn-sm btn-secondary"
            onclick="copySuggestedPassword('${escapeHtml(sug.value)}')"
          >
            Copy
          </button>
        </div>
      </div>
    `
    )
    .join("");
}

window.copySuggestedPassword = async function (val) {
  try {
    await navigator.clipboard.writeText(val);
    showToast("Strong password copied to clipboard! (Zero-knowledge: not saved anywhere)");
  } catch {
    showToast("Copied password candidate!");
  }
};

// ============================================================================
// Conversational AI Agent Chat
// ============================================================================

function appendChatMessage(role, htmlContent, executedTools = []) {
  const container = document.getElementById("agentChatMessages");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;

  let toolsHtml = "";
  if (executedTools && executedTools.length > 0) {
    toolsHtml =
      `<div style="margin-bottom:6px;">` +
      executedTools
        .map((t) => `<span class="tool-call-badge">&#9889; ${escapeHtml(t.tool)}()</span>`)
        .join("") +
      `</div>`;
  }

  bubble.innerHTML = `${toolsHtml}<div>${htmlContent}</div>`;
  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

async function sendAgentMessage(messageText) {
  appendChatMessage("user", escapeHtml(messageText));
  const btn = document.getElementById("btnSendChat");
  btn.disabled = true;
  btn.textContent = "Thinking...";

  try {
    const res = await apiFetch("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({
        message: messageText,
        previous_interaction_id: state.previousInteractionId,
      }),
    });
    if (res.interaction_id) {
      state.previousInteractionId = res.interaction_id;
    }
    document.getElementById("agentModelLabel").textContent = `Active: ${res.model}`;
    appendChatMessage("agent", formatMarkdownLite(res.reply), res.executed_tools || []);
    await loadDashboard();
  } catch (err) {
    appendChatMessage("agent", `Error communicating with agent: ${escapeHtml(err.message)}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Send";
  }
}

// ============================================================================
// Event Listeners Initialization
// ============================================================================

document.addEventListener("DOMContentLoaded", async () => {
  const dateInput = document.getElementById("activeDateInput");
  dateInput.value = state.activeDate;
  document.getElementById("pwLastChanged").value = state.activeDate;

  dateInput.addEventListener("change", async (e) => {
    state.activeDate = e.target.value || state.activeDate;
    await loadDashboard();
  });

  // Add Day-Start Action Form
  document.getElementById("formAddAction").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      action_date: state.activeDate,
      title: document.getElementById("actionTitle").value.trim(),
      category: document.getElementById("actionCategory").value,
      start_time: document.getElementById("actionStart").value,
      end_time: document.getElementById("actionEnd").value,
      priority: document.getElementById("actionPriority").value,
      description: document.getElementById("actionDescription").value.trim(),
      sync_to_google: true,
    };
    try {
      const res = await apiFetch("/api/actions", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      document.getElementById("actionTitle").value = "";
      document.getElementById("actionDescription").value = "";
      showToast(res.google_calendar_sync?.message || "Added action to schedule!");
      await loadDashboard();
    } catch (err) {
      showToast(`Error adding action: ${err.message}`);
    }
  });

  // Sync Google Calendar Buttons
  async function handleCalendarSync() {
    try {
      showToast("Syncing day-start actions with Google Calendar...");
      const res = await apiFetch(
        `/api/actions/sync-calendar?target_date=${encodeURIComponent(state.activeDate)}`,
        { method: "POST" }
      );
      showToast(
        `Synced ${res.pushed_actions} action(s) for ${res.date} (Imported: ${res.imported_events}).`
      );
      await loadDashboard();
    } catch (err) {
      showToast(`Calendar sync error: ${err.message}`);
    }
  }
  document.getElementById("btnSyncCalendar").addEventListener("click", handleCalendarSync);
  document.getElementById("btnSyncCalendarQuick").addEventListener("click", handleCalendarSync);

  // Add Timesheet Form
  document.getElementById("formAddTimesheet").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      work_date: state.activeDate,
      project: document.getElementById("tsProject").value.trim(),
      ticket_id: document.getElementById("tsTicket").value.trim(),
      task_description: document.getElementById("tsDescription").value.trim(),
      hours: Number(document.getElementById("tsHours").value),
      billable: document.getElementById("tsBillable").checked,
    };
    try {
      await apiFetch("/api/timesheets", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      document.getElementById("tsDescription").value = "";
      document.getElementById("tsTicket").value = "";
      showToast(`Logged ${payload.hours}h under ${payload.project}!`);
      await loadDashboard();
    } catch (err) {
      showToast(`Error logging hours: ${err.message}`);
    }
  });

  // Submit Daily Timesheet to External Webhook
  document.getElementById("btnSubmitTimesheet").addEventListener("click", async () => {
    try {
      showToast(`Dispatching ${state.activeDate} timesheet to webhook...`);
      const res = await apiFetch("/api/timesheets/submit", {
        method: "POST",
        body: JSON.stringify({
          work_date: state.activeDate,
          notes: "Submitted from PulseOps Web Dashboard",
        }),
      });
      showToast(res.message);
      await loadDashboard();
    } catch (err) {
      showToast(`Webhook submission error: ${err.message}`);
    }
  });

  // Add Tracked Password Account Form
  document.getElementById("formAddPasswordAccount").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      service_name: document.getElementById("pwServiceName").value.trim(),
      account_identifier: document.getElementById("pwIdentifier").value.trim(),
      rotation_interval_days: Number(document.getElementById("pwInterval").value) || 90,
      last_changed_date: document.getElementById("pwLastChanged").value || state.activeDate,
      min_length: Number(document.getElementById("pwMinLen").value) || 24,
      require_symbols: true,
      mfa_enabled: true,
    };
    try {
      await apiFetch("/api/passwords", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      document.getElementById("pwServiceName").value = "";
      document.getElementById("pwIdentifier").value = "";
      showToast(`Now tracking rotation policy for ${payload.service_name}!`);
      await loadDashboard();
    } catch (err) {
      showToast(`Error adding service: ${err.message}`);
    }
  });

  // Password Studio Modal Controls
  const dialogPw = document.getElementById("dialogPasswordStudio");
  document.getElementById("btnQuickGenerator").addEventListener("click", () => {
    window.openPasswordStudio(null, "Ad-Hoc Strong Password", 24, true);
  });
  document.getElementById("btnRegeneratePasswords").addEventListener("click", fetchPasswordSuggestions);
  document.getElementById("btnClosePwStudio").addEventListener("click", () => dialogPw.close());
  document.getElementById("btnClosePwStudioBottom").addEventListener("click", () => dialogPw.close());
  document.getElementById("btnMarkAccountRotated").addEventListener("click", async () => {
    if (state.activePasswordAccount?.id) {
      await window.markAccountRotated(state.activePasswordAccount.id);
      dialogPw.close();
    }
  });

  // Settings Modal Controls
  const dialogSettings = document.getElementById("dialogSettings");
  document.getElementById("btnOpenSettings").addEventListener("click", async () => {
    const s = await apiFetch("/api/settings");
    document.getElementById("setGcalId").value = s.google_calendar_id || "primary";
    document.getElementById("setGcalToken").value = s.google_calendar_access_token || "";
    document.getElementById("setGcalSaPath").value = s.google_service_account_path || "";
    document.getElementById("setTimezone").value = s.timezone || "Asia/Kolkata";
    document.getElementById("setWebhookUrl").value = s.timesheet_webhook_url || "https://httpbin.org/post";
    document.getElementById("setWebhookKey").value = s.timesheet_api_key || "";
    document.getElementById("setEmployeeId").value = s.timesheet_employee_id || "EMP-2026-01";
    document.getElementById("setTargetHours").value = s.daily_target_hours || "8.0";
    dialogSettings.showModal();
  });
  document.getElementById("btnCloseSettings").addEventListener("click", () => dialogSettings.close());
  document.getElementById("btnCancelSettings").addEventListener("click", () => dialogSettings.close());

  document.getElementById("formSettings").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      google_calendar_id: document.getElementById("setGcalId").value.trim(),
      google_calendar_access_token: document.getElementById("setGcalToken").value.trim(),
      google_service_account_path: document.getElementById("setGcalSaPath").value.trim(),
      timezone: document.getElementById("setTimezone").value.trim(),
      timesheet_webhook_url: document.getElementById("setWebhookUrl").value.trim(),
      timesheet_api_key: document.getElementById("setWebhookKey").value.trim(),
      timesheet_employee_id: document.getElementById("setEmployeeId").value.trim(),
      daily_target_hours: document.getElementById("setTargetHours").value.trim(),
    };
    try {
      await apiFetch("/api/settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      dialogSettings.close();
      showToast("Saved Google Calendar & Timesheet Webhook integration settings!");
      await loadDashboard();
    } catch (err) {
      showToast(`Error saving settings: ${err.message}`);
    }
  });

  // Logs Modal Controls
  const dialogLogs = document.getElementById("dialogLogs");
  document.getElementById("btnOpenLogs").addEventListener("click", async () => {
    await loadDashboard();
    dialogLogs.showModal();
  });
  document.getElementById("btnCloseLogs").addEventListener("click", () => dialogLogs.close());
  document.getElementById("btnCloseLogsBottom").addEventListener("click", () => dialogLogs.close());

  // AI Agent Chat Controls
  document.getElementById("formAgentChat").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("agentChatInput");
    const msg = input.value.trim();
    if (!msg) return;
    input.value = "";
    await sendAgentMessage(msg);
  });

  document.querySelectorAll(".chip[data-prompt]").forEach((chip) => {
    chip.addEventListener("click", async () => {
      const prompt = chip.getAttribute("data-prompt");
      if (prompt) await sendAgentMessage(prompt);
    });
  });

  document.getElementById("btnResetAgentChat").addEventListener("click", () => {
    state.previousInteractionId = null;
    document.getElementById("agentChatMessages").innerHTML = "";
    appendChatMessage(
      "agent",
      "Conversation reset. Ask me to log timesheet hours, submit your daily timesheet webhook, schedule a day-start action to Google Calendar, or suggest strong replacement passwords!"
    );
  });

  // Initial Load & Greeting
  await loadDashboard();
  appendChatMessage(
    "agent",
    formatMarkdownLite(
      "Hello! I'm your **Daily Activity & Security Hygiene Agent**.\n\n" +
        "I can:\n" +
        "- **Log & Submit Timesheets** to your configured external webhook\n" +
        "- **Note Day-Start Actions** and sync time-blocks to **Google Calendar**\n" +
        "- **Audit Password Rotation Timers** (zero-knowledge) & generate CSPRNG replacement credentials\n\n" +
        "Click any quick action chip above or type a command below!"
    )
  );
});
