const state = {
  socket: null,
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
  return Boolean(state.socket) && state.socket.readyState === WebSocket.OPEN;
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
  els.disconnectBtn.disabled = !state.socket;
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
    const meta = [
      message.role || message.kind,
      message.status || "final",
      message.sessionId,
    ]
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
    option.value = session.key;
    option.textContent = session.key;
    if (session.key === state.currentSessionId) {
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

function addUserMessage(sessionId, content) {
  pushMessage({
    kind: "user",
    role: "user",
    sessionId,
    content,
    status: "sent",
  });
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

function finalizeTurnMessage(sessionId, content) {
  const turn = ensureActiveTurn(sessionId);
  if (turn.messageIndex === null) {
    state.messages.push({
      kind: "assistant",
      role: "assistant",
      sessionId,
      content: content || "",
      status: "final",
    });
    renderMessages();
    return;
  }
  const target = state.messages[turn.messageIndex];
  if (target) {
    target.content = content || target.content || turn.draftText;
    target.status = "final";
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

function sendCommand(command) {
  if (!isConnected()) {
    logEvent("local-error", { message: "socket is not connected" });
    return false;
  }
  state.socket.send(JSON.stringify(command));
  logEvent("command", command);
  return true;
}

function bindCurrentSession() {
  const sessionId = els.sessionId.value.trim();
  if (!sessionId) {
    setConnectionStatus("error", "session_id 不能为空");
    return;
  }
  setCurrentSession(sessionId);
  sendCommand({ type: "bind_session", session_id: sessionId });
}

function handleEvent(event) {
  logEvent(event.type, event);
  switch (event.type) {
    case "ready":
      setConnectionStatus("connected", `已连接到 ${event.host}:${event.port}`);
      break;
    case "session_bound":
      setCurrentSession(event.session_id);
      setStatusText("session bound", event);
      break;
    case "turn_started":
      ensureActiveTurn(event.session_id);
      break;
    case "progress":
      addProgressMessage(event.session_id, event.content || "", Boolean(event.tool_hint));
      break;
    case "delta":
      appendDelta(event.session_id, event.content || "");
      break;
    case "stream_end":
      setStatusText("stream end", event);
      break;
    case "message":
      finalizeTurnMessage(event.session_id, event.content || "");
      break;
    case "turn_completed":
      markTurnCompleted(event.session_id, event.stop_reason || "completed");
      setStatusText("turn completed", event);
      break;
    case "interrupt_result":
      setStatusText("interrupt result", event.result || event);
      break;
    case "status_result":
      setStatusText("status result", event.snapshot || event);
      break;
    case "history_snapshot":
      replaceHistory(event.session_id, event.messages || []);
      setStatusText("history snapshot", {
        session_id: event.session_id,
        total_messages: event.total_messages,
        cursor: event.cursor,
        next_cursor: event.next_cursor,
      });
      break;
    case "session_list":
      state.sessions = event.sessions || [];
      renderSessions();
      setStatusText("session list", event.sessions || []);
      break;
    case "task_delivered":
      addTaskMessage(event.session_id, event.task_id, event.content || "");
      break;
    case "error":
      setConnectionStatus("error", event.message || "未知错误");
      setStatusText("error", event);
      break;
    default:
      setStatusText("unhandled event", event);
      break;
  }
}

function disconnectRemote() {
  if (state.socket) {
    try {
      state.socket.close();
    } catch (error) {
      logEvent("disconnect-error", { message: String(error) });
    }
  }
  state.socket = null;
  setConnectionStatus("disconnected", "连接已断开");
}

function connectRemote() {
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
  setConnectionStatus("connecting", "正在建立连接...");

  const url = new URL(`ws://${host}:${port}/ws`);
  url.searchParams.set("token", token);
  const socket = new WebSocket(url.toString());
  state.socket = socket;
  syncControls();

  socket.addEventListener("open", () => {
    bindCurrentSession();
  });

  socket.addEventListener("message", (raw) => {
    try {
      handleEvent(JSON.parse(raw.data));
    } catch (error) {
      logEvent("parse-error", { message: String(error), raw: raw.data });
    }
  });

  socket.addEventListener("close", () => {
    state.socket = null;
    setConnectionStatus("disconnected", "连接已断开");
  });

  socket.addEventListener("error", () => {
    setConnectionStatus("error", "WebSocket 连接失败");
  });
}

function sendCurrentMessage() {
  const sessionId = els.sessionId.value.trim();
  const content = els.messageInput.value.trim();
  if (!sessionId || !content) {
    return;
  }
  setCurrentSession(sessionId);
  addUserMessage(sessionId, content);
  resetActiveTurn();
  const ok = sendCommand({
    type: "send_message",
    session_id: sessionId,
    content,
    client_id: "remote-client-demo",
  });
  if (ok) {
    els.messageInput.value = "";
  }
}

function loadHistory() {
  sendCommand({
    type: "load_history",
    session_id: state.currentSessionId,
    limit: 100,
  });
}

function requestStatus() {
  sendCommand({
    type: "get_status",
    session_id: state.currentSessionId,
  });
}

function requestSessions() {
  sendCommand({ type: "list_sessions" });
}

function interruptTurn() {
  sendCommand({
    type: "interrupt_turn",
    session_id: state.currentSessionId,
  });
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
  bindCurrentSession();
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
