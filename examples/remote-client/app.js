const state = {
  eventSource: null,
  connection: {
    status: "disconnected",
    host: "127.0.0.1",
    port: "8765",
    token: "",
  },
  currentSessionId: "desktop:demo",
  sessions: [],
  messages: [],
  activeTurn: null,
};

const els = {
  host: document.querySelector("#host"),
  port: document.querySelector("#port"),
  token: document.querySelector("#token"),
  sessionId: document.querySelector("#sessionId"),
  connectBtn: document.querySelector("#connectBtn"),
  disconnectBtn: document.querySelector("#disconnectBtn"),
  refreshSessionsBtn: document.querySelector("#refreshSessionsBtn"),
  loadHistoryBtn: document.querySelector("#loadHistoryBtn"),
  getStatusBtn: document.querySelector("#getStatusBtn"),
  interruptBtn: document.querySelector("#interruptBtn"),
  sendBtn: document.querySelector("#sendBtn"),
  sessionList: document.querySelector("#sessionList"),
  connectionStatus: document.querySelector("#connectionStatus"),
  serverInfo: document.querySelector("#serverInfo"),
  activeSessionLabel: document.querySelector("#activeSessionLabel"),
  messages: document.querySelector("#messages"),
  eventLog: document.querySelector("#eventLog"),
  statusPanel: document.querySelector("#statusPanel"),
  messageInput: document.querySelector("#messageInput"),
};

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function isConnected() {
  return Boolean(state.eventSource) && state.connection.status === "connected";
}

function baseUrl() {
  return `http://${state.connection.host}:${state.connection.port}`;
}

function apiHeaders() {
  return state.connection.token ? { Authorization: `Bearer ${state.connection.token}` } : {};
}

async function api(path, options = {}) {
  const headers = { ...apiHeaders(), ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${baseUrl()}${path}`, { ...options, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload?.error?.message || `HTTP ${response.status}`);
  }
  return payload;
}

function setConnectionStatus(status, detail = "") {
  state.connection.status = status;
  els.connectionStatus.textContent = status;
  els.connectionStatus.className = `status-pill ${status}`;
  els.serverInfo.textContent = detail || "尚未连接";
  syncControls();
}

function syncControls() {
  const connected = isConnected();
  els.connectBtn.disabled = connected || state.connection.status === "connecting";
  els.disconnectBtn.disabled = !state.eventSource;
  els.sendBtn.disabled = !connected;
  els.interruptBtn.disabled = !connected;
  els.refreshSessionsBtn.disabled = !connected;
  els.loadHistoryBtn.disabled = !connected;
  els.getStatusBtn.disabled = !connected;
}

function logEvent(kind, payload) {
  const card = document.createElement("div");
  card.className = "event-card";
  card.innerHTML = `
    <div class="event-meta">${new Date().toLocaleTimeString()} · ${escapeHtml(kind)}</div>
    <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
  `;
  els.eventLog.prepend(card);
}

function setStatusText(title, payload) {
  els.statusPanel.textContent = `${title}\n${JSON.stringify(payload, null, 2)}`;
}

function renderMessages() {
  els.messages.innerHTML = "";
  if (!state.messages.length) {
    const empty = document.createElement("div");
    empty.className = "message-card progress";
    empty.textContent = "当前还没有消息。";
    els.messages.appendChild(empty);
    return;
  }
  for (const message of state.messages) {
    const card = document.createElement("div");
    card.className = `message-card ${message.kind}`;
    const meta = [message.role || message.kind, message.status || "final", message.sessionId]
      .filter(Boolean)
      .join(" · ");
    card.innerHTML = `
      <div class="message-meta">${escapeHtml(meta)}</div>
      <div class="message-content">${escapeHtml(message.content || "")}</div>
    `;
    els.messages.appendChild(card);
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  for (const session of state.sessions) {
    const option = document.createElement("option");
    option.value = session.session_id || session.key;
    option.textContent = `${option.value} (${session.message_count ?? 0})`;
    if (option.value === state.currentSessionId) {
      option.selected = true;
    }
    els.sessionList.appendChild(option);
  }
}

function setCurrentSession(sessionId) {
  state.currentSessionId = sessionId;
  els.sessionId.value = sessionId;
  els.activeSessionLabel.textContent = `当前会话：${sessionId}`;
}

function resetActiveTurn() {
  state.activeTurn = null;
}

function ensureActiveTurn(sessionId) {
  if (!state.activeTurn || state.activeTurn.sessionId !== sessionId) {
    state.activeTurn = {
      sessionId,
      messageIndex: null,
      draftText: "",
      completed: false,
      stopReason: null,
    };
  }
  return state.activeTurn;
}

function pushMessage(message) {
  state.messages.push(message);
  renderMessages();
}

function addMessageFromSessionEvent(sessionId, message) {
  if (sessionId !== state.currentSessionId) {
    return;
  }
  pushMessage({
    kind: message.role === "assistant" ? "assistant" : "user",
    role: message.role,
    sessionId,
    content: message.content || "",
    status: "live",
  });
}

function addUserMessage(sessionId, content) {
  pushMessage({ kind: "user", role: "user", sessionId, content, status: "queued" });
}

function addProgressMessage(sessionId, content, toolHint) {
  pushMessage({
    kind: "progress",
    role: toolHint ? "tool_hint" : "progress",
    sessionId,
    content,
    status: toolHint ? "tool_hint" : "progress",
  });
}

function addTaskMessage(sessionId, taskId, content) {
  pushMessage({
    kind: "task",
    role: "task",
    sessionId,
    content: `[task:${taskId}] ${content || ""}`,
    status: "task_delivered",
  });
}

function ensureDraftMessage(sessionId) {
  const turn = ensureActiveTurn(sessionId);
  if (turn.messageIndex !== null) {
    return turn;
  }
  state.messages.push({
    kind: "assistant",
    role: "assistant",
    sessionId,
    content: "",
    status: "streaming",
  });
  turn.messageIndex = state.messages.length - 1;
  renderMessages();
  return turn;
}

function appendDelta(sessionId, content) {
  const turn = ensureDraftMessage(sessionId);
  turn.draftText += content || "";
  const target = state.messages[turn.messageIndex];
  if (target) {
    target.content = turn.draftText;
    target.status = "streaming";
  }
  renderMessages();
}

function markTurnCompleted(sessionId, stopReason) {
  if (!state.activeTurn || state.activeTurn.sessionId !== sessionId) {
    return;
  }
  state.activeTurn.completed = true;
  state.activeTurn.stopReason = stopReason;
  if (state.activeTurn.messageIndex !== null) {
    const target = state.messages[state.activeTurn.messageIndex];
    if (target) {
      target.status = stopReason || "completed";
    }
  }
  renderMessages();
}

function replaceHistory(sessionId, messages) {
  state.messages = (messages || []).map((message) => ({
    kind: message.role === "assistant" ? "assistant" : "user",
    role: message.role,
    sessionId,
    content: message.content || "",
    status: "history",
  }));
  resetActiveTurn();
  renderMessages();
}

function mergeSession(session) {
  const sessionId = session.session_id || session.key;
  const index = state.sessions.findIndex((item) => (item.session_id || item.key) === sessionId);
  if (index >= 0) {
    state.sessions[index] = session;
  } else {
    state.sessions.unshift(session);
  }
  renderSessions();
}

function handleSseEnvelope(envelope) {
  logEvent(envelope.type, envelope);
  const data = envelope.data || {};
  switch (envelope.type) {
    case "runtime.connected":
      setConnectionStatus("connected", `已连接到 ${baseUrl()}`);
      break;
    case "runtime.resync_required":
      loadBootstrap();
      break;
    case "session.created":
    case "session.updated":
      mergeSession(data.session);
      break;
    case "session.deleted":
      state.sessions = state.sessions.filter(
        (item) => (item.session_id || item.key) !== data.session?.session_id,
      );
      renderSessions();
      break;
    case "session.message_appended":
      addMessageFromSessionEvent(data.session_id, data.message || {});
      break;
    case "turn.started":
      ensureActiveTurn(data.session_id);
      break;
    case "turn.progress":
      addProgressMessage(data.session_id, data.content || "", Boolean(data.tool_hint));
      break;
    case "turn.delta":
      appendDelta(data.session_id, data.content || "");
      break;
    case "turn.stream_end":
      setStatusText("stream end", data);
      break;
    case "turn.completed":
    case "turn.failed":
    case "turn.interrupted":
      markTurnCompleted(data.session_id, data.stop_reason || envelope.type);
      setStatusText(envelope.type, data);
      break;
    case "task.delivered":
      addTaskMessage(data.session_id, data.task_id, data.content || "");
      break;
    case "sidebar.snapshot":
      setStatusText("sidebar", data.sidebar || data);
      break;
    default:
      setStatusText("event", envelope);
      break;
  }
}

function disconnectRemote() {
  if (state.eventSource) {
    state.eventSource.close();
  }
  state.eventSource = null;
  setConnectionStatus("disconnected", "连接已断开");
}

async function ensureCurrentSession() {
  try {
    await api(`/v1/sessions/${encodeURIComponent(state.currentSessionId)}`);
  } catch (_error) {
    await api("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.currentSessionId,
        title: state.currentSessionId,
      }),
    });
  }
}

async function loadBootstrap() {
  const bootstrap = await api("/v1/bootstrap");
  state.sessions = bootstrap.sessions || [];
  renderSessions();
  setStatusText("bootstrap", bootstrap.status || bootstrap);
}

async function connectRemote() {
  const host = els.host.value.trim();
  const port = els.port.value.trim();
  const token = els.token.value.trim();
  const sessionId = els.sessionId.value.trim();

  state.connection.host = host;
  state.connection.port = port;
  state.connection.token = token;

  if (!host || !port || !token || !sessionId) {
    setConnectionStatus("error", "host / port / token / session_id 不能为空");
    return;
  }

  disconnectRemote();
  setCurrentSession(sessionId);
  setConnectionStatus("connecting", "正在拉取 bootstrap...");

  try {
    await ensureCurrentSession();
    await loadBootstrap();
    const url = new URL(`${baseUrl()}/v1/events`);
    url.searchParams.set("token", token);
    const eventSource = new EventSource(url.toString());
    state.eventSource = eventSource;

    eventSource.addEventListener("open", () => {
      setConnectionStatus("connected", `SSE 已连接到 ${baseUrl()}`);
    });
    eventSource.addEventListener("error", () => {
      setConnectionStatus("error", "SSE 连接失败或已断开");
    });

    for (const type of [
      "runtime.connected",
      "runtime.resync_required",
      "session.created",
      "session.updated",
      "session.deleted",
      "session.message_appended",
      "turn.started",
      "turn.progress",
      "turn.delta",
      "turn.stream_end",
      "turn.completed",
      "turn.failed",
      "turn.interrupted",
      "task.created",
      "task.updated",
      "task.deleted",
      "task.delivered",
      "provider.state_changed",
      "provider.settings_updated",
      "provider.active_changed",
      "sidebar.snapshot",
      "skill.installed",
      "skill.uninstalled",
      "mcp.created",
      "mcp.updated",
      "mcp.deleted",
      "mcp.enabled",
      "mcp.disabled",
    ]) {
      eventSource.addEventListener(type, (raw) => handleSseEnvelope(JSON.parse(raw.data)));
    }
  } catch (error) {
    setConnectionStatus("error", String(error));
    logEvent("connect-error", { message: String(error) });
  }
}

async function sendCurrentMessage() {
  const sessionId = els.sessionId.value.trim();
  const content = els.messageInput.value.trim();
  if (!sessionId || !content) {
    return;
  }
  setCurrentSession(sessionId);
  addUserMessage(sessionId, content);
  resetActiveTurn();
  try {
    const response = await api(`/v1/sessions/${encodeURIComponent(sessionId)}/turns`, {
      method: "POST",
      body: JSON.stringify({ content, client_id: "remote-client-demo" }),
    });
    logEvent("http.turns", response);
    els.messageInput.value = "";
  } catch (error) {
    logEvent("send-error", { message: String(error) });
  }
}

async function loadHistory() {
  try {
    const payload = await api(
      `/v1/sessions/${encodeURIComponent(state.currentSessionId)}/messages?limit=100`,
    );
    replaceHistory(payload.session_id, payload.messages || []);
    setStatusText("messages", payload);
  } catch (error) {
    logEvent("history-error", { message: String(error) });
  }
}

async function requestStatus() {
  try {
    setStatusText("status", await api("/v1/status"));
  } catch (error) {
    logEvent("status-error", { message: String(error) });
  }
}

async function requestSessions() {
  try {
    const payload = await api("/v1/sessions");
    state.sessions = payload.sessions || [];
    renderSessions();
    setStatusText("sessions", payload);
  } catch (error) {
    logEvent("sessions-error", { message: String(error) });
  }
}

async function interruptTurn() {
  try {
    const payload = await api(`/v1/sessions/${encodeURIComponent(state.currentSessionId)}/interrupt`, {
      method: "POST",
    });
    setStatusText("interrupt", payload);
  } catch (error) {
    logEvent("interrupt-error", { message: String(error) });
  }
}

els.connectBtn.addEventListener("click", connectRemote);
els.disconnectBtn.addEventListener("click", disconnectRemote);
els.refreshSessionsBtn.addEventListener("click", requestSessions);
els.loadHistoryBtn.addEventListener("click", loadHistory);
els.getStatusBtn.addEventListener("click", requestStatus);
els.interruptBtn.addEventListener("click", interruptTurn);
els.sendBtn.addEventListener("click", sendCurrentMessage);
els.sessionList.addEventListener("change", () => {
  if (!els.sessionList.value) {
    return;
  }
  setCurrentSession(els.sessionList.value);
  loadHistory();
});
els.messageInput.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    sendCurrentMessage();
  }
});

renderMessages();
renderSessions();
syncControls();
