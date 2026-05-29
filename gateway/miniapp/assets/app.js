const STORAGE_KEY = 'hermes-miniapp-board-v1';

const state = {
  panX: 0,
  panY: 0,
  zoom: 1,
  activeTool: 'pan',
  pointer: null,
  lastTapAt: 0,
  items: [],
  revision: 0,
  boardEndpoint: '/miniapp/api/board',
  remoteSaveTimer: null,
  isApplyingRemote: false,
};

const els = {
  root: document.querySelector('.collaboration-board'),
  canvas: document.querySelector('#board-canvas'),
  title: document.querySelector('#board-title'),
  subtitle: document.querySelector('#board-subtitle'),
  telegramStatus: document.querySelector('#telegram-status'),
  zoomStatus: document.querySelector('#zoom-status'),
  actionStatus: document.querySelector('#action-status'),
  reactionFeed: document.querySelector('#reaction-feed'),
  hermesCursor: document.querySelector('#hermes-cursor'),
  hermesAvatar: document.querySelector('#hermes-avatar'),
  tools: [...document.querySelectorAll('.tool[data-tool]')],
  empty: document.querySelector('.empty-state'),
};

const REACTIONS = {
  note: ['I added a note shell', 'Good, capture the raw idea here', 'I am watching this note'],
  frame: ['Frame ready — put a flow inside', 'Nice, let us group this', 'I marked a space for structure'],
  move: ['Moved — layout is getting clearer', 'I see the arrangement change', 'Position noted'],
  edit: ['Text updated', 'I see the wording change', 'Saved this wording locally'],
  tool: ['Tool switched', 'Ready for the next action'],
  clear: ['Board cleared', 'Fresh canvas again'],
};

function setStatus(text) {
  if (els.actionStatus) els.actionStatus.textContent = text;
}

function pickReaction(kind) {
  const list = REACTIONS[kind] || REACTIONS.tool;
  return list[Math.floor(Math.random() * list.length)];
}

function boardToViewport(point) {
  const rect = els.root.getBoundingClientRect();
  return {
    x: rect.width / 2 + state.panX + point.x * state.zoom,
    y: rect.height / 2 + state.panY + point.y * state.zoom,
  };
}

function pulseHermes() {
  els.hermesAvatar?.classList.remove('is-reacting');
  void els.hermesAvatar?.offsetWidth;
  els.hermesAvatar?.classList.add('is-reacting');
}

function moveHermesCursor(point) {
  if (!els.hermesCursor || !point) return;
  const viewport = boardToViewport(point);
  els.hermesCursor.style.setProperty('--cursor-x', `${viewport.x}px`);
  els.hermesCursor.style.setProperty('--cursor-y', `${viewport.y}px`);
  els.hermesCursor.classList.add('is-visible');
}

function showHermesReaction(kind, point, detail = '') {
  const message = detail || pickReaction(kind);
  setStatus(`Hermes: ${message}`);
  pulseHermes();
  moveHermesCursor(point || centerBoardPoint(-28, -16));

  if (!els.reactionFeed) return;
  const row = document.createElement('div');
  row.className = 'reaction-row';
  row.innerHTML = `<span class="reaction-speaker">H</span><span>${message}</span>`;
  els.reactionFeed.prepend(row);
  [...els.reactionFeed.children].slice(4).forEach((node) => node.remove());
}

function setBoardTransform() {
  document.documentElement.style.setProperty('--pan-x', `${state.panX}px`);
  document.documentElement.style.setProperty('--pan-y', `${state.panY}px`);
  document.documentElement.style.setProperty('--zoom', `${state.zoom}`);
  els.zoomStatus.textContent = `${Math.round(state.zoom * 100)}%`;
}

function saveBoard() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.items));
  } catch (_) {}
  if (!state.isApplyingRemote) scheduleRemoteSave();
}

function latestRemoteEvent(board) {
  if (!board?.events?.length) return null;
  return board.events[board.events.length - 1];
}

async function postBoardAction(payload) {
  const response = await fetch(state.boardEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`board HTTP ${response.status}`);
  const result = await response.json();
  if (result?.board?.revision !== undefined) state.revision = result.board.revision;
  return result;
}

function scheduleRemoteSave() {
  clearTimeout(state.remoteSaveTimer);
  state.remoteSaveTimer = setTimeout(() => {
    postBoardAction({ action: 'set', items: state.items, detail: 'Aidyn updated the board' })
      .catch(() => setStatus('Saved locally · server sync pending'));
  }, 180);
}

function applyRemoteBoard(board, announce = true) {
  if (!board || !Array.isArray(board.items)) return;
  if ((board.revision || 0) < state.revision) return;
  state.isApplyingRemote = true;
  state.items = board.items;
  state.revision = board.revision || 0;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.items));
  } catch (_) {}
  renderItems();
  state.isApplyingRemote = false;
  const event = latestRemoteEvent(board);
  if (announce && event?.actor === 'Hermes') {
    showHermesReaction(event.action || 'tool', event, event.detail || 'Board updated by Hermes');
  }
}

async function fetchRemoteBoard(announce = true) {
  const response = await fetch(state.boardEndpoint, { cache: 'no-store' });
  if (!response.ok) throw new Error(`board HTTP ${response.status}`);
  const result = await response.json();
  const board = result?.board;
  if (board && (board.revision || 0) > state.revision) applyRemoteBoard(board, announce);
  return board;
}

function loadBoard() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    if (Array.isArray(parsed)) state.items = parsed.slice(0, 80);
  } catch (_) {
    state.items = [];
  }
}

function updateEmptyState() {
  els.empty?.classList.toggle('is-hidden', state.items.length > 0);
}

function makeId() {
  return `item-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function viewportToBoard(clientX, clientY) {
  const rect = els.root.getBoundingClientRect();
  return {
    x: (clientX - rect.left - rect.width / 2 - state.panX) / state.zoom,
    y: (clientY - rect.top - rect.height / 2 - state.panY) / state.zoom,
  };
}

function centerBoardPoint(offsetX = 0, offsetY = 0) {
  const rect = els.root.getBoundingClientRect();
  return viewportToBoard(rect.left + rect.width / 2 + offsetX, rect.top + rect.height / 2 + offsetY);
}

function itemTemplate(item) {
  const node = document.createElement('article');
  node.className = `board-item ${item.type === 'frame' ? 'board-frame' : 'sticky-note'}`;
  node.dataset.id = item.id;
  node.style.setProperty('--item-x', `${item.x}px`);
  node.style.setProperty('--item-y', `${item.y}px`);
  node.style.setProperty('--item-w', `${item.w || 180}px`);
  node.style.setProperty('--item-h', `${item.h || 120}px`);

  if (item.type === 'frame') {
    node.innerHTML = `
      <div class="item-handle" aria-hidden="true"></div>
      <div class="frame-title" contenteditable="true" data-field="text" spellcheck="false"></div>
    `;
  } else {
    node.innerHTML = `
      <div class="item-handle" aria-hidden="true"></div>
      <div class="note-body" contenteditable="true" data-field="text" spellcheck="false"></div>
    `;
  }

  const text = node.querySelector('[data-field="text"]');
  text.textContent = item.text || (item.type === 'frame' ? 'New frame' : 'New note');
  text.addEventListener('input', () => {
    const current = state.items.find((entry) => entry.id === item.id);
    if (current) {
      current.text = text.textContent.trim() || (current.type === 'frame' ? 'New frame' : 'New note');
      saveBoard();
      showHermesReaction('edit', { x: current.x, y: current.y });
    }
  });

  node.addEventListener('pointerdown', onItemPointerDown);
  node.addEventListener('dblclick', (event) => {
    event.stopPropagation();
    text.focus();
    document.execCommand?.('selectAll', false, null);
  });

  return node;
}

function renderItems() {
  els.canvas.querySelectorAll('.board-item').forEach((node) => node.remove());
  state.items.forEach((item) => els.canvas.appendChild(itemTemplate(item)));
  updateEmptyState();
}

function addItem(type = 'note', point = centerBoardPoint()) {
  const item = {
    id: makeId(),
    type,
    x: Math.round(point.x),
    y: Math.round(point.y),
    w: type === 'frame' ? 250 : 176,
    h: type === 'frame' ? 160 : 124,
    text: type === 'frame' ? 'New frame' : 'New note',
  };
  state.items.push(item);
  saveBoard();
  renderItems();
  setStatus(`${type === 'frame' ? 'Frame' : 'Note'} added · drag it`);
  showHermesReaction(type === 'frame' ? 'frame' : 'note', item);

  const node = els.canvas.querySelector(`[data-id="${item.id}"]`);
  node?.querySelector('[contenteditable]')?.focus();
  return item;
}

function setTool(tool) {
  state.activeTool = tool;
  els.tools.forEach((button) => button.classList.toggle('is-active', button.dataset.tool === tool));
  setStatus(tool === 'pan' ? 'Drag canvas to pan' : `Tap board to add ${tool}`);
  showHermesReaction('tool', centerBoardPoint(-36, -20), tool === 'pan' ? 'Pan mode active' : `${tool} tool active`);
}

function onToolClick(event) {
  const tool = event.currentTarget.dataset.tool;
  setTool(tool);
  if (tool === 'note') addItem('note', centerBoardPoint(12, 8));
  if (tool === 'frame') addItem('frame', centerBoardPoint(20, 18));
}

function onCanvasPointerDown(event) {
  if (event.button !== undefined && event.button !== 0) return;
  if (event.target.closest('.board-item')) return;

  const now = Date.now();
  const isQuickTap = now - state.lastTapAt < 320;
  state.lastTapAt = now;

  if (state.activeTool === 'note' || state.activeTool === 'frame' || isQuickTap) {
    addItem(state.activeTool === 'frame' ? 'frame' : 'note', viewportToBoard(event.clientX, event.clientY));
    setTool('pan');
    return;
  }

  state.pointer = {
    mode: 'pan',
    id: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    panX: state.panX,
    panY: state.panY,
  };
  els.canvas.classList.add('is-dragging');
  els.canvas.setPointerCapture?.(event.pointerId);
}

function onPointerMove(event) {
  if (!state.pointer || state.pointer.id !== event.pointerId) return;

  if (state.pointer.mode === 'item') {
    const dx = (event.clientX - state.pointer.startX) / state.zoom;
    const dy = (event.clientY - state.pointer.startY) / state.zoom;
    const item = state.items.find((entry) => entry.id === state.pointer.itemId);
    if (!item) return;
    item.x = Math.round(state.pointer.x + dx);
    item.y = Math.round(state.pointer.y + dy);
    state.pointer.node.style.setProperty('--item-x', `${item.x}px`);
    state.pointer.node.style.setProperty('--item-y', `${item.y}px`);
    return;
  }

  state.panX = state.pointer.panX + event.clientX - state.pointer.startX;
  state.panY = state.pointer.panY + event.clientY - state.pointer.startY;
  setBoardTransform();
}

function stopPointer(event) {
  if (!state.pointer || state.pointer.id !== event.pointerId) return;
  if (state.pointer.mode === 'item') {
    state.pointer.node.classList.remove('is-moving');
    state.pointer.node.releasePointerCapture?.(event.pointerId);
    saveBoard();
    setStatus('Object moved');
    const item = state.items.find((entry) => entry.id === state.pointer.itemId);
    showHermesReaction('move', item || centerBoardPoint());
  } else {
    els.canvas.releasePointerCapture?.(event.pointerId);
    els.canvas.classList.remove('is-dragging');
  }
  state.pointer = null;
}

function onItemPointerDown(event) {
  if (event.button !== undefined && event.button !== 0) return;
  if (event.target.matches('[contenteditable]')) return;
  event.stopPropagation();
  const node = event.currentTarget;
  const item = state.items.find((entry) => entry.id === node.dataset.id);
  if (!item) return;

  state.pointer = {
    mode: 'item',
    id: event.pointerId,
    itemId: item.id,
    node,
    startX: event.clientX,
    startY: event.clientY,
    x: item.x,
    y: item.y,
  };
  node.classList.add('is-moving');
  node.setPointerCapture?.(event.pointerId);
}

function onWheel(event) {
  event.preventDefault();
  const direction = event.deltaY > 0 ? -1 : 1;
  const next = Math.min(1.8, Math.max(0.45, state.zoom + direction * 0.05));
  state.zoom = Number(next.toFixed(2));
  setBoardTransform();
}

function clearBoard() {
  state.items = [];
  saveBoard();
  renderItems();
  setTool('pan');
  setStatus('Board cleared');
  showHermesReaction('clear', centerBoardPoint());
}

function applyTelegramTheme() {
  const tg = window.Telegram?.WebApp;
  if (!tg) {
    els.telegramStatus.textContent = 'Browser mode';
    return;
  }

  tg.ready();
  tg.expand();
  els.telegramStatus.textContent = tg.platform ? `Telegram · ${tg.platform}` : 'Telegram WebApp';

  const accent = tg.themeParams?.button_color;
  if (accent) document.documentElement.style.setProperty('--accent', accent);

  tg.MainButton?.setText('Add note');
  tg.MainButton?.show();
  tg.MainButton?.onClick(() => addItem('note', centerBoardPoint(12, 8)));
  if (tg.isVersionAtLeast?.('6.1')) {
    tg.BackButton?.show();
    tg.BackButton?.onClick(clearBoard);
  }
}

function renderConfig(config) {
  if (config?.app_name) els.title.textContent = config.app_name;
  if (config?.description) els.subtitle.textContent = config.description;
  if (config?.accent) document.documentElement.style.setProperty('--accent', config.accent);
}

async function loadConfig() {
  const configUrl = els.root?.dataset.configUrl || '/miniapp/config.json';
  const response = await fetch(configUrl);
  if (!response.ok) throw new Error(`config HTTP ${response.status}`);
  const config = await response.json();
  renderConfig(config);
  if (config?.endpoints?.board) state.boardEndpoint = config.endpoints.board;
}

els.tools.forEach((button) => button.addEventListener('click', onToolClick));
els.canvas.addEventListener('pointerdown', onCanvasPointerDown);
els.canvas.addEventListener('pointermove', onPointerMove);
els.canvas.addEventListener('pointerup', stopPointer);
els.canvas.addEventListener('pointercancel', stopPointer);
els.canvas.addEventListener('wheel', onWheel, { passive: false });

document.addEventListener('keydown', (event) => {
  if (event.key === 'n' && !event.metaKey && !event.ctrlKey) addItem('note', centerBoardPoint(12, 8));
  if (event.key === 'f' && !event.metaKey && !event.ctrlKey) addItem('frame', centerBoardPoint(18, 18));
  if (event.key === '0') {
    state.panX = 0;
    state.panY = 0;
    state.zoom = 1;
    setBoardTransform();
    setStatus('View reset');
  }
});

loadBoard();
renderItems();
setBoardTransform();
window.__hermesMiniappReady = true;
loadConfig()
  .catch(() => {})
  .finally(() => {
    applyTelegramTheme();
    fetchRemoteBoard(false).catch(() => {});
    setInterval(() => fetchRemoteBoard(true).catch(() => {}), 1800);
  });
