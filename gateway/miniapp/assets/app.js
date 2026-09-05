const state = {
  endpoint: '/miniapp/api/report/latest',
  configUrl: document.querySelector('.report-app')?.dataset.configUrl || '/miniapp/config.json',
};

const els = {
  title: document.querySelector('#report-title'),
  status: document.querySelector('#status'),
  report: document.querySelector('#report'),
  refresh: document.querySelector('#refresh-report'),
  close: document.querySelector('#close-miniapp'),
};

const SUPPORTED_TYPES = new Set([
  'metric', 'progress', 'timeline', 'gantt', 'kanban', 'priority_matrix', 'dependency_graph',
  'flow', 'flowchart', 'comparison_table', 'chart', 'canvas_network', 'three_scene', 'details',
  'key_points', 'insight_cards', 'sequence', 'checklist', 'callout', 'markdown', 'mermaid',
]);

function text(value, fallback = '') {
  if (value === null || value === undefined) return fallback;
  return String(value);
}

function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === false || value === null || value === undefined) return;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = text(value);
    else node.setAttribute(key, text(value));
  });
  const list = Array.isArray(children) ? children : [children];
  list.forEach((child) => {
    if (child === null || child === undefined) return;
    node.append(child instanceof Node ? child : document.createTextNode(text(child)));
  });
  return node;
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.hidden = false;
  els.status.dataset.state = isError ? 'error' : 'info';
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function list(items, ordered = false) {
  const node = el(ordered ? 'ol' : 'ul');
  (items || []).forEach((item) => node.append(el('li', { text: text(item.text || item.title || item.label || item) })));
  return node;
}

function blockShell(block) {
  return el('section', { class: `report-block block-${text(block.type)}` }, [
    el('p', { class: 'block-label', text: text(block.type).replaceAll('_', ' ') }),
    el('h2', { text: text(block.title || block.label || 'Report section') }),
  ]);
}

function renderMetric(block) {
  const section = blockShell(block);
  const box = el('div', { class: 'metric-box' }, [
    el('span', { text: block.label || block.title || 'Metric' }),
    el('strong', { text: block.value || '' }),
  ]);
  if (block.trend?.label) box.append(el('p', { text: block.trend.label }));
  section.append(box);
  return section;
}

function renderProgress(block) {
  const section = blockShell(block);
  (block.items || [block]).forEach((item) => {
    const value = Math.max(0, Math.min(100, number(item.value)));
    section.append(el('div', { class: 'progress-row' }, [
      el('strong', { text: `${text(item.label || block.label || 'Progress')} — ${value}%` }),
      el('div', { class: 'progress-track', role: 'img', 'aria-label': `${value}%` }, [el('span', { class: 'progress-fill', style: `width:${value}%` })]),
      item.detail ? el('p', { text: item.detail }) : null,
    ]));
  });
  return section;
}

function renderTimeline(block) {
  const section = blockShell(block);
  const items = el('ol', { class: 'timeline-list' });
  (block.items || []).forEach((item) => items.append(el('li', { class: 'timeline-item' }, [
    el('time', { text: item.start || item.end || item.label || item.status || '' }),
    el('strong', { text: item.title || item.label || '' }),
    el('p', { text: item.detail || item.owner || item.status || '' }),
  ])));
  section.append(items);
  return section;
}

function renderGantt(block) {
  const section = blockShell(block);
  const columns = block.columns || [];
  const grid = el('div', { class: 'gantt-grid', style: `grid-template-columns:minmax(110px,1.2fr) repeat(${Math.max(1, columns.length)}, minmax(74px,1fr))` });
  grid.append(el('div'));
  columns.forEach((column) => grid.append(el('div', { class: 'block-label', text: column })));
  (block.lanes || []).forEach((lane) => {
    grid.append(el('div', { text: lane.label }));
    const cell = el('div', { style: `grid-column:2/${columns.length + 2}` });
    (lane.segments || []).forEach((segment) => cell.append(el('div', { class: 'gantt-segment', text: `${segment.label} (${segment.start}–${segment.end})` })));
    grid.append(cell);
  });
  section.append(el('div', { class: 'gantt' }, grid));
  return section;
}

function renderKanban(block) {
  const section = blockShell(block);
  const kanbanGrid = el('div', { class: 'kanban' });
  (block.columns || []).forEach((column) => {
    const col = el('section', { class: 'kanban-column' }, el('h3', { text: column.title }));
    (column.items || column.cards || []).forEach((card) => col.append(el('article', { class: 'kanban-card' }, [
      el('strong', { text: card.title || card.label || '' }),
      card.detail || card.meta ? el('p', { text: card.detail || card.meta }) : null,
      card.tag ? el('p', { class: 'block-label', text: card.tag }) : null,
    ])));
    kanbanGrid.append(col);
  });
  section.append(kanbanGrid);
  return section;
}

function renderPriorityMatrix(block) {
  const section = blockShell(block);
  const grid = el('div', { class: 'matrix' });
  const quadrants = block.quadrants || (block.items || []).map((item) => ({ title: item.quadrant || item.label, items: [item.label] }));
  quadrants.forEach((quadrant) => grid.append(el('section', { class: 'matrix-cell' }, [el('h3', { text: quadrant.title || quadrant.key || 'Priority' }), list(quadrant.items || [])])));
  section.append(grid);
  return section;
}

function renderDependencyGraph(block) {
  const section = blockShell(block);
  const nodes = new Map((block.nodes || []).map((node) => [node.id, node]));
  section.append(list(block.nodes || []));
  (block.edges || []).forEach((edge) => section.append(el('div', { class: 'dependency-edge' }, [
    el('span', { text: nodes.get(edge.from)?.label || edge.from }),
    el('b', { text: '→' }),
    el('span', { text: nodes.get(edge.to)?.label || edge.to }),
    edge.label ? el('em', { text: edge.label }) : null,
  ])));
  return section;
}

function renderFlow(block) {
  const section = blockShell(block);
  const flow = el('ol', { class: 'flow-list' });
  (block.steps || []).forEach((step) => flow.append(el('li', { class: 'flow-step' }, [el('strong', { text: step.title || step.label || '' }), el('p', { text: step.detail || step.status || '' })])));
  section.append(flow);
  return section;
}

function renderTable(block) {
  const section = blockShell(block);
  const table = el('table');
  const headRow = el('tr');
  (block.columns || []).forEach((column) => headRow.append(el('th', { text: column })));
  table.append(el('thead', {}, el('tr', {}, [...headRow.childNodes])));
  const body = el('tbody');
  (block.rows || []).forEach((row) => {
    const values = Array.isArray(row) ? row : [row.label, ...(row.values || [])];
    body.append(el('tr', {}, values.map((cell) => el('td', { text: cell }))));
  });
  table.append(body);
  section.append(el('div', { class: 'table-wrap' }, table));
  return section;
}

function renderChart(block) {
  const section = blockShell(block);
  const data = block.data || [];
  const max = Math.max(1, ...data.map((point) => Math.abs(number(point.value))));
  const bars = el('div', { class: 'chart-bars' });
  data.forEach((point) => {
    const value = number(point.value);
    bars.append(el('div', { class: 'chart-row' }, [
      el('span', { text: point.label }),
      el('span', { class: 'chart-track' }, el('i', { class: 'chart-bar', style: `width:${Math.min(100, Math.abs(value) / max * 100)}%` })),
      el('b', { text: `${value}${block.valueLabel ? ` ${block.valueLabel}` : ''}` }),
    ]));
  });
  section.append(bars, list(data));
  return section;
}

function renderNetwork(block) {
  const section = blockShell(block);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('class', 'static-diagram');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Relationship diagram');
  const nodes = new Map((block.nodes || []).map((node) => [node.id, node]));
  (block.edges || []).forEach((edge) => {
    const from = nodes.get(edge.from) || {};
    const to = nodes.get(edge.to) || {};
    const line = document.createElementNS(svg.namespaceURI, 'line');
    line.setAttribute('x1', number(from.x, 5)); line.setAttribute('y1', number(from.y, 5));
    line.setAttribute('x2', number(to.x, 95)); line.setAttribute('y2', number(to.y, 95));
    line.setAttribute('stroke', 'currentColor'); svg.append(line);
  });
  (block.nodes || []).forEach((node) => {
    const group = document.createElementNS(svg.namespaceURI, 'g');
    const circle = document.createElementNS(svg.namespaceURI, 'circle');
    circle.setAttribute('cx', number(node.x, 50)); circle.setAttribute('cy', number(node.y, 50)); circle.setAttribute('r', '3'); circle.setAttribute('fill', 'currentColor');
    const label = document.createElementNS(svg.namespaceURI, 'text');
    label.setAttribute('x', number(node.x, 50)); label.setAttribute('y', number(node.y, 50) + 8); label.textContent = text(node.label);
    group.append(circle, label); svg.append(group);
  });
  section.append(svg, list(block.edges || []));
  return section;
}

function renderScene(block) {
  const section = blockShell(block);
  const map = el('div', { class: 'scene-map', role: 'img', 'aria-label': 'Spatial layout' });
  (block.objects || []).forEach((object) => {
    const position = object.position || [0, 0, 0];
    map.append(el('span', { class: 'scene-object', style: `left:${50 + number(position[0]) * 8}%;top:${50 - number(position[1]) * 8}%`, text: object.label }));
  });
  section.append(map, list((block.objects || []).map((object) => `${object.label}: position ${(object.position || []).join(', ')}`)));
  return section;
}

function renderDetails(block) {
  const section = blockShell(block);
  (block.sections || []).forEach((part) => section.append(el('details', { open: true }, [el('summary', { text: part.title }), list(part.items || part.content || [])])));
  return section;
}

function renderMarkdown(block) {
  const section = blockShell(block);
  section.append(el('pre', { text: block.markdown || block.text || block.code || '' }));
  return section;
}

function renderInsightCards(block) {
  const section = blockShell(block);
  (block.items || []).forEach((item) => section.append(el('p', {}, [el('strong', { text: item.label || item.value || '' }), document.createTextNode(item.detail ? ` — ${item.detail}` : '')])));
  return section;
}

function renderBlock(block) {
  const type = text(block.type).toLowerCase();
  if (!SUPPORTED_TYPES.has(type)) return renderMarkdown({ ...block, title: block.title || type, text: JSON.stringify(block, null, 2) });
  if (type === 'metric') return renderMetric(block);
  if (type === 'progress') return renderProgress(block);
  if (type === 'timeline') return renderTimeline(block);
  if (type === 'gantt') return renderGantt(block);
  if (type === 'kanban') return renderKanban(block);
  if (type === 'priority_matrix') return renderPriorityMatrix(block);
  if (type === 'dependency_graph') return renderDependencyGraph(block);
  if (type === 'flow' || type === 'flowchart' || type === 'sequence') return renderFlow({ ...block, steps: block.steps || block.items });
  if (type === 'comparison_table') return renderTable(block);
  if (type === 'chart') return renderChart(block);
  if (type === 'canvas_network') return renderNetwork(block);
  if (type === 'three_scene') return renderScene(block);
  if (type === 'details') return renderDetails(block);
  if (type === 'key_points' || type === 'checklist') { const section = blockShell(block); section.append(list(block.items || [])); return section; }
  if (type === 'insight_cards') return renderInsightCards(block);
  if (type === 'callout') { const section = blockShell(block); section.append(el('p', { class: 'callout', text: block.text || '' })); return section; }
  return renderMarkdown(block);
}

function renderReport(payload) {
  const report = payload.report || payload;
  const plan = report.plan || {};
  clear(els.report);
  els.title.textContent = plan.title || 'Latest report';
  const header = el('header', { class: 'report-header' }, [
    el('p', { class: 'kicker', text: 'Latest generated report' }),
    el('h1', { class: 'report-title', text: plan.title || 'Untitled report' }),
    el('p', { class: 'summary', text: plan.summary || '' }),
    el('p', { class: 'meta', text: [report.generated_at, report.context?.topic, report.context?.thread_id].filter(Boolean).join(' · ') }),
  ]);
  const metrics = el('div', { class: 'metrics' });
  (plan.metrics || []).forEach((metric) => metrics.append(el('div', { class: 'metric-box' }, [el('span', { text: metric.label }), el('strong', { text: metric.value })])));
  if (metrics.childNodes.length) header.append(metrics);
  els.report.append(header);
  (plan.blocks || []).forEach((block) => els.report.append(renderBlock(block)));
  if (report.source?.text) {
    els.report.append(el('section', { class: 'report-block' }, [el('h2', { text: 'Source response' }), el('pre', { class: 'source-text', text: report.source.text })]));
  }
  els.report.hidden = false;
  els.status.hidden = true;
  window.__hermesReportReady = true;
}

async function loadConfig() {
  const response = await fetch(state.configUrl, { cache: 'no-store' });
  if (!response.ok) return;
  const config = await response.json();
  if (config?.endpoints?.report_latest) state.endpoint = config.endpoints.report_latest;
}

async function loadReport() {
  setStatus('Loading latest report.');
  els.report.hidden = true;
  try {
    await loadConfig();
    const response = await fetch(state.endpoint, { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
      setStatus(payload.error || 'No report is available yet.', response.status >= 500);
      return;
    }
    renderReport(payload);
  } catch (error) {
    setStatus(`Could not load report: ${error.message}`, true);
  }
}

function boot() {
  window.__hermesMiniappReady = true;
  const tg = window.Telegram?.WebApp;
  tg?.ready?.();
  tg?.expand?.();
  els.refresh?.addEventListener('click', loadReport);
  els.close?.addEventListener('click', () => tg?.close?.());
  loadReport();
}

document.addEventListener('DOMContentLoaded', boot);
