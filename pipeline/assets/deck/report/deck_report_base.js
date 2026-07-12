/* Gitster deck report — dependency-free client logic.
 * Ported from the v2 pipeline report and adapted to per-player expansions:
 * expansion filter chips recompute the visible stats client-side. */

function asText(value) {
  if (value === null || value === undefined) return '';
  return String(value);
}

function asNumber(value) {
  const n = parseFloat(asText(value).replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

function debounce(fn, waitMs) {
  let timer = null;
  return function(...args) {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => fn.apply(this, args), waitMs);
  };
}

function csvEscape(value) {
  const text = asText(value);
  return '"' + text.replace(/"/g, '""') + '"';
}

/* Static tables rendered server-side use this via th onclick. */
function sortTable(tableId, colIdx) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const asc = table.getAttribute('data-sort-col') != colIdx || table.getAttribute('data-sort-dir') != 'asc';
  rows.sort((a, b) => {
    const ta = (a.cells[colIdx].textContent || '').trim();
    const tb = (b.cells[colIdx].textContent || '').trim();
    const na = parseFloat(ta.replace(',', '.'));
    const nb = parseFloat(tb.replace(',', '.'));
    if (!isNaN(na) && !isNaN(nb)) return asc ? na - nb : nb - na;
    return asc ? ta.localeCompare(tb) : tb.localeCompare(ta);
  });
  rows.forEach((r) => tbody.appendChild(r));
  table.setAttribute('data-sort-col', colIdx);
  table.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
}

function parseReportData() {
  const node = document.getElementById('report-data');
  if (!node) return {};
  try {
    return JSON.parse(node.textContent || '{}');
  } catch (err) {
    console.error('[deck-report] report-data parse error', err);
    return {};
  }
}

/* ---------------- theme ---------------- */

function getThemeStorageKey(reportData) {
  const meta = (reportData && reportData.meta) ? reportData.meta : {};
  const reportIdRaw = asText(meta.report_id || 'report').trim() || 'report';
  const reportId = reportIdRaw.replace(/[^a-zA-Z0-9._:-]/g, '_').slice(0, 180);
  return 'gitster_report_theme_' + reportId;
}

function normalizeTheme(value) {
  const t = asText(value).trim().toLowerCase();
  return t === 'light' ? 'light' : 'dark';
}

function updateThemeToggleLabel(currentTheme) {
  const toggle = document.getElementById('theme-toggle');
  if (!toggle) return;
  toggle.setAttribute('aria-pressed', currentTheme === 'dark' ? 'true' : 'false');
  const label = toggle.querySelector('.btn-label');
  const text = currentTheme === 'dark' ? 'Light' : 'Dark';
  if (label) label.textContent = text;
  else toggle.textContent = text;
}

function setTheme(theme) {
  const root = document.documentElement;
  const nextTheme = normalizeTheme(theme);
  root.classList.remove('theme-dark', 'theme-light');
  root.classList.add('theme-' + nextTheme);
  root.setAttribute('data-theme', nextTheme);
  updateThemeToggleLabel(nextTheme);
}

function initReportTheme() {
  const reportData = parseReportData();
  const storageKey = getThemeStorageKey(reportData);
  const toggle = document.getElementById('theme-toggle');

  let theme = 'dark';
  try {
    if (window.localStorage) {
      const saved = window.localStorage.getItem(storageKey);
      if (saved === 'dark' || saved === 'light') {
        theme = saved;
      } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        theme = 'light';
      }
    }
  } catch (_ignored) {}

  setTheme(theme);

  if (!toggle) return;
  toggle.addEventListener('click', () => {
    const current = document.documentElement.classList.contains('theme-light') ? 'light' : 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      if (window.localStorage) window.localStorage.setItem(storageKey, next);
    } catch (_ignored) {}
  });
}

/* ---------------- print / PDF export ---------------- */

const PRINT_SECTION_IDS = ['sec-expansions', 'sec-new'];
let printModeActive = false;
let printRestoreHandlers = [];
let printCleanupTimer = null;
let printMediaEventsBound = false;

function setPdfButtonBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = !!busy;
  btn.setAttribute('aria-busy', busy ? 'true' : 'false');
  const label = btn.querySelector('.btn-label');
  const text = busy ? 'Print...' : 'PDF';
  if (label) label.textContent = text;
  else btn.textContent = text;
}

function expandSectionsForPrint() {
  const restoreHandlers = [];
  PRINT_SECTION_IDS.forEach((id) => {
    const node = document.getElementById(id);
    if (!node || !node.tagName || node.tagName.toLowerCase() !== 'details') return;
    const wasOpen = node.hasAttribute('open');
    if (!wasOpen) node.setAttribute('open', '');
    restoreHandlers.push(() => {
      if (!wasOpen) node.removeAttribute('open');
    });
  });
  return restoreHandlers;
}

function runPrintRestoreHandlers() {
  while (printRestoreHandlers.length) {
    const restore = printRestoreHandlers.pop();
    try {
      if (typeof restore === 'function') restore();
    } catch (_ignored) {}
  }
}

function setPrintMode(active) {
  const body = document.body;
  if (!body) return;
  if (active) {
    if (!printModeActive) printRestoreHandlers = expandSectionsForPrint();
    printModeActive = true;
    body.classList.add('print-mode');
    return;
  }
  body.classList.remove('print-mode');
  if (printModeActive) runPrintRestoreHandlers();
  printModeActive = false;
}

function clearPrintCleanupTimer() {
  if (printCleanupTimer) {
    window.clearTimeout(printCleanupTimer);
    printCleanupTimer = null;
  }
}

function onBeforePrint() {
  setPrintMode(true);
}

function onAfterPrint() {
  setPrintMode(false);
  clearPrintCleanupTimer();
  setPdfButtonBusy(document.getElementById('pdf-export'), false);
}

function bindPrintMediaEvents() {
  if (printMediaEventsBound) return;
  printMediaEventsBound = true;
  window.addEventListener('beforeprint', onBeforePrint);
  window.addEventListener('afterprint', onAfterPrint);
}

function triggerPrintPdf() {
  const button = document.getElementById('pdf-export');
  if (button && button.disabled) return;
  setPdfButtonBusy(button, true);
  setPrintMode(true);
  clearPrintCleanupTimer();
  printCleanupTimer = window.setTimeout(onAfterPrint, 15000);
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => window.print()));
}

function initPdfExport() {
  bindPrintMediaEvents();
  const button = document.getElementById('pdf-export');
  if (!button) return;
  button.addEventListener('click', triggerPrintPdf);
}

/* ---------------- client-side charts ----------------
 * All charts render from the same filtered rows as the table and KPIs,
 * building inline SVG by hand (no dependencies). */

const MAX_COMBO_BARS = 20;

const chartState = {
  yearBin: 5,
  ownerNames: {},
  ownerColors: {},
};

function escapeHtml(value) {
  return asText(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function chartEmpty(host) {
  host.innerHTML = "<p class='muted'>No data.</p>";
}

/* items: [{label, value, color?}] */
function renderVerticalBarChart(host, items, opts) {
  if (!host) return;
  const values = items.map((item) => Number(item.value) || 0);
  if (!items.length || !values.some((value) => value > 0)) {
    chartEmpty(host);
    return;
  }
  const options = opts || {};
  const width = options.width || 980;
  const height = options.height || 320;
  const marginLeft = 44;
  const marginRight = 16;
  const marginTop = 18;
  const marginBottom = 72;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const maxValue = Math.max(1, Math.max.apply(null, values));
  const barSlot = plotWidth / Math.max(items.length, 1);
  const barWidth = Math.max(10, Math.min(48, barSlot * 0.7));
  const axisY = height - marginBottom;
  const gridValues = Array.from(new Set([0, Math.floor(maxValue / 2), maxValue])).sort((a, b) => a - b);
  const labelStep = items.length <= 16 ? 1 : Math.max(1, Math.floor(items.length / 12));
  const parts = [
    "<svg class='chart chart-svg' viewBox='0 0 " + width + ' ' + height + "' role='img' aria-label='" +
    escapeHtml(options.ariaLabel || 'Bar chart') + "'>",
  ];
  gridValues.forEach((gridValue) => {
    const y = marginTop + plotHeight - (plotHeight * (gridValue / maxValue));
    parts.push("<line class='chart-gridline' x1='" + marginLeft + "' y1='" + y.toFixed(2) + "' x2='" + (width - marginRight) + "' y2='" + y.toFixed(2) + "' />");
    parts.push("<text class='chart-label' x='" + (marginLeft - 8) + "' y='" + (y + 4).toFixed(2) + "' text-anchor='end'>" + gridValue + '</text>');
  });
  parts.push("<line class='chart-axis' x1='" + marginLeft + "' y1='" + axisY + "' x2='" + (width - marginRight) + "' y2='" + axisY + "' />");
  items.forEach((item, index) => {
    const value = Number(item.value) || 0;
    const xCenter = marginLeft + (index * barSlot) + (barSlot / 2);
    const barHeight = plotHeight * (value / maxValue);
    const y = axisY - barHeight;
    const x = xCenter - (barWidth / 2);
    const fill = item.color ? " style='fill: " + escapeHtml(item.color) + "'" : '';
    parts.push("<rect class='chart-bar'" + fill + " x='" + x.toFixed(2) + "' y='" + y.toFixed(2) + "' width='" + barWidth.toFixed(2) + "' height='" + barHeight.toFixed(2) + "' rx='4' ry='4' />");
    parts.push("<text class='chart-value' x='" + xCenter.toFixed(2) + "' y='" + Math.max(y - 6, marginTop + 10).toFixed(2) + "' text-anchor='middle'>" + value + '</text>');
    if (index % labelStep === 0 || index === items.length - 1) {
      parts.push("<text class='chart-label' x='" + xCenter.toFixed(2) + "' y='" + (axisY + 18) + "' text-anchor='middle'>" + escapeHtml(item.label) + '</text>');
    }
  });
  parts.push('</svg>');
  host.innerHTML = parts.join('');
}

/* items: [{label, value, color?}] */
function renderHorizontalBarChart(host, items, opts) {
  if (!host) return;
  const values = items.map((item) => Number(item.value) || 0);
  if (!items.length || !values.some((value) => value > 0)) {
    chartEmpty(host);
    return;
  }
  const options = opts || {};
  const width = options.width || 980;
  const rowHeight = options.rowHeight || 26;
  const height = Math.max(120, 40 + (items.length * rowHeight));
  const maxLabelLen = Math.max.apply(null, items.map((item) => asText(item.label).length).concat([10]));
  const marginLeft = Math.min(300, Math.max(140, 8 * maxLabelLen));
  const marginRight = 50;
  const marginTop = 18;
  const marginBottom = 18;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const slotHeight = plotHeight / Math.max(items.length, 1);
  const barHeight = Math.max(12, Math.min(18, slotHeight * 0.62));
  const maxValue = Math.max(1, Math.max.apply(null, values));
  const gridValues = Array.from(new Set([0, Math.floor(maxValue / 2), maxValue])).sort((a, b) => a - b);
  const parts = [
    "<svg class='chart chart-svg' viewBox='0 0 " + width + ' ' + height + "' role='img' aria-label='" +
    escapeHtml(options.ariaLabel || 'Bar chart') + "'>",
  ];
  gridValues.forEach((gridValue) => {
    const x = marginLeft + (plotWidth * (gridValue / maxValue));
    parts.push("<line class='chart-gridline' x1='" + x.toFixed(2) + "' y1='" + marginTop + "' x2='" + x.toFixed(2) + "' y2='" + (height - marginBottom) + "' />");
    parts.push("<text class='chart-label' x='" + x.toFixed(2) + "' y='" + (height - 2) + "' text-anchor='middle'>" + gridValue + '</text>');
  });
  items.forEach((item, index) => {
    const value = Number(item.value) || 0;
    const yCenter = marginTop + (index * slotHeight) + (slotHeight / 2);
    const y = yCenter - (barHeight / 2);
    const barWidth = plotWidth * (value / maxValue);
    const fill = item.color ? " style='fill: " + escapeHtml(item.color) + "'" : '';
    parts.push("<text class='chart-label-strong' x='" + (marginLeft - 10) + "' y='" + (yCenter + 4).toFixed(2) + "' text-anchor='end'>" + escapeHtml(item.label) + '</text>');
    parts.push("<rect class='chart-bar'" + fill + " x='" + marginLeft + "' y='" + y.toFixed(2) + "' width='" + barWidth.toFixed(2) + "' height='" + barHeight.toFixed(2) + "' rx='4' ry='4' />");
    parts.push("<text class='chart-value' x='" + (marginLeft + barWidth + 8).toFixed(2) + "' y='" + (yCenter + 4).toFixed(2) + "' text-anchor='start'>" + value + '</text>');
  });
  parts.push('</svg>');
  host.innerHTML = parts.join('');
}

function formatYearBinLabel(binStart, binSize) {
  const binEnd = binStart + binSize - 1;
  if (Math.floor(binStart / 100) === Math.floor(binEnd / 100)) {
    return binStart + '–' + String(binEnd % 100).padStart(2, '0');
  }
  return binStart + '–' + binEnd;
}

function buildYearBinItems(rows, binSize) {
  const years = [];
  rows.forEach((row) => {
    const year = asNumber(row.year);
    if (year !== null) years.push(year);
  });
  if (!years.length) return [];
  const minYear = Math.min.apply(null, years);
  const maxYear = Math.max.apply(null, years);
  const baseYear = Math.floor(minYear / binSize) * binSize;
  const topYear = Math.floor(maxYear / binSize) * binSize;
  const counts = new Map();
  years.forEach((year) => {
    const bucketStart = baseYear + Math.floor((year - baseYear) / binSize) * binSize;
    counts.set(bucketStart, (counts.get(bucketStart) || 0) + 1);
  });
  const items = [];
  for (let bucketStart = baseYear; bucketStart <= topYear; bucketStart += binSize) {
    const count = counts.get(bucketStart) || 0;
    if (count <= 0) continue;
    items.push({
      label: binSize === 1 ? String(bucketStart) : formatYearBinLabel(bucketStart, binSize),
      value: count,
    });
  }
  return items;
}

/* How many visible cards each owner appears in (owners list membership). */
function buildOwnerAppearanceItems(rows) {
  const counts = new Map();
  rows.forEach((row) => {
    (Array.isArray(row.owner_ids) ? row.owner_ids : []).forEach((ownerId) => {
      const id = asText(ownerId);
      if (!id) return;
      counts.set(id, (counts.get(id) || 0) + 1);
    });
  });
  return Array.from(counts.entries())
    .map(([id, value]) => ({
      label: chartState.ownerNames[id] || id,
      value,
      color: chartState.ownerColors[id] || '',
    }))
    .sort((a, b) => (b.value - a.value) || a.label.localeCompare(b.label));
}

/* Visible cards grouped by their exact owners set. */
function buildOwnerComboItems(rows) {
  const counts = new Map();
  rows.forEach((row) => {
    const ids = (Array.isArray(row.owner_ids) ? row.owner_ids : []).map(asText).filter(Boolean).sort();
    if (!ids.length) return;
    const key = ids.join('|');
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([key, value]) => ({
      label: key.split('|').map((id) => chartState.ownerNames[id] || id).join(' + '),
      value,
    }))
    .sort((a, b) => (b.value - a.value) || a.label.localeCompare(b.label));
}

/* Primary artist = artists string cut at ' feat. ' (precomputed in Python). */
function buildTopArtistItems(rows, limit) {
  const counts = new Map();
  rows.forEach((row) => {
    const artist = asText(row.primary_artist).trim();
    if (!artist) return;
    counts.set(artist, (counts.get(artist) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => (b.value - a.value) || a.label.localeCompare(b.label))
    .slice(0, limit);
}

function renderCharts(rows) {
  renderVerticalBarChart(document.getElementById('chart-years'), buildYearBinItems(rows, chartState.yearBin), {
    ariaLabel: 'Cards per year',
  });
  renderVerticalBarChart(document.getElementById('chart-owner-appearances'), buildOwnerAppearanceItems(rows), {
    ariaLabel: 'Owner appearances',
  });
  const comboItems = buildOwnerComboItems(rows);
  const shownCombos = comboItems.slice(0, MAX_COMBO_BARS);
  renderHorizontalBarChart(document.getElementById('chart-owner-combos'), shownCombos, {
    ariaLabel: 'Owner combinations',
  });
  const comboNote = document.getElementById('chart-owner-combos-note');
  if (comboNote) {
    comboNote.textContent = comboItems.length > shownCombos.length
      ? '+' + (comboItems.length - shownCombos.length) + ' more combinations not shown'
      : '';
  }
  renderHorizontalBarChart(document.getElementById('chart-top-artists'), buildTopArtistItems(rows, 10), {
    ariaLabel: 'Top 10 artists',
  });
}

function initYearBinToggle() {
  const host = document.getElementById('year-bin-toggle');
  if (!host) return;
  host.addEventListener('click', (ev) => {
    const target = ev.target;
    if (!(target instanceof Element)) return;
    const btn = target.closest('.bin-btn');
    if (!btn) return;
    const bin = parseInt(btn.getAttribute('data-bin'), 10);
    if (!Number.isFinite(bin) || bin < 1) return;
    chartState.yearBin = bin;
    host.querySelectorAll('.bin-btn').forEach((node) => node.classList.toggle('active', node === btn));
    renderCharts(getFilteredRows());
  });
}

/* ---------------- cards table + expansion filter ---------------- */

const DECK_COLUMNS = [
  { key: 'card_id', label: 'card_id' },
  { key: 'expansion', label: 'expansion' },
  { key: 'year', label: 'year' },
  { key: 'title', label: 'title' },
  { key: 'artists', label: 'artists' },
  { key: 'owners', label: 'owners' },
  { key: 'status', label: 'status' },
  { key: 'is_new', label: 'new' },
  { key: 'version', label: 'version' },
];

const deckState = {
  rows: [],
  expansionById: {},
  expansion: '__all',
  search: '',
  yearMin: '',
  yearMax: '',
  sortKey: 'card_id',
  sortDir: 'asc',
};

function rowMatchesExpansion(row) {
  if (deckState.expansion === '__all') return true;
  return asText(row.expansion) === deckState.expansion;
}

function rowMatchesSearch(row) {
  if (!deckState.search) return true;
  const needle = deckState.search;
  for (const col of DECK_COLUMNS) {
    if (asText(row[col.key]).toLowerCase().includes(needle)) return true;
  }
  return false;
}

function rowMatchesYearRange(row) {
  if (!deckState.yearMin && !deckState.yearMax) return true;
  const yearNum = asNumber(row.year);
  if (yearNum === null) return false;
  if (deckState.yearMin !== '' && yearNum < Number(deckState.yearMin)) return false;
  if (deckState.yearMax !== '' && yearNum > Number(deckState.yearMax)) return false;
  return true;
}

function getFilteredRows() {
  return deckState.rows.filter((row) =>
    rowMatchesExpansion(row) && rowMatchesSearch(row) && rowMatchesYearRange(row)
  );
}

function sortRows(rows) {
  if (!deckState.sortKey) return rows.slice();
  const key = deckState.sortKey;
  const dir = deckState.sortDir === 'desc' ? -1 : 1;
  return rows.slice().sort((a, b) => {
    const avNum = asNumber(a[key]);
    const bvNum = asNumber(b[key]);
    let cmp = 0;
    if (avNum !== null && bvNum !== null) {
      cmp = avNum - bvNum;
    } else {
      cmp = asText(a[key]).localeCompare(asText(b[key]), undefined, { sensitivity: 'base' });
    }
    if (cmp === 0) return (Number(a._row_index || 0) - Number(b._row_index || 0)) * dir;
    return cmp * dir;
  });
}

function setStat(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = asText(value);
}

function updateVisibleStats(filteredRows) {
  const total = deckState.rows.length;
  const years = [];
  let pending = 0;
  let printed = 0;
  let newCount = 0;
  filteredRows.forEach((row) => {
    const year = asNumber(row.year);
    if (year !== null) years.push(year);
    if (asText(row.status) === 'pending') pending += 1;
    if (asText(row.status) === 'printed') printed += 1;
    if (row.is_new) newCount += 1;
  });
  const distinctYears = new Set(years);
  setStat('stat-visible', String(filteredRows.length) + ' / ' + String(total));
  setStat('stat-years', distinctYears.size);
  setStat('stat-min-year', years.length ? Math.min.apply(null, years) : '-');
  setStat('stat-max-year', years.length ? Math.max.apply(null, years) : '-');
  setStat('stat-printed', printed);
  setStat('stat-pending', pending);
  setStat('stat-new', newCount);
}

function buildDeckCell(row, colKey) {
  const td = document.createElement('td');
  if (colKey === 'title') {
    const url = asText(row.spotify_url);
    if (url) {
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = asText(row.title) || '-';
      td.appendChild(a);
      return td;
    }
    td.textContent = asText(row.title);
    return td;
  }
  if (colKey === 'is_new') {
    if (row.is_new) {
      const pill = document.createElement('span');
      pill.className = 'new-pill';
      pill.textContent = 'NEW';
      td.appendChild(pill);
    }
    return td;
  }
  if (colKey === 'expansion') {
    const wrap = document.createElement('span');
    wrap.className = 'exp-cell';
    const info = deckState.expansionById[asText(row.expansion)];
    if (info && info.color) {
      const dot = document.createElement('span');
      dot.className = 'chip-dot';
      dot.style.background = info.color;
      wrap.appendChild(dot);
    }
    const text = document.createElement('span');
    text.textContent = (info && info.name) ? info.name : asText(row.expansion);
    wrap.appendChild(text);
    td.appendChild(wrap);
    return td;
  }
  td.textContent = asText(row[colKey]);
  if (colKey === 'year') td.classList.add('num');
  return td;
}

function renderDeckTable() {
  const table = document.getElementById('deck-table');
  if (!table) return;
  if (!table.tHead) table.createTHead();
  if (!table.tBodies.length) table.createTBody();
  const thead = table.tHead;
  const tbody = table.tBodies[0];
  thead.textContent = '';
  tbody.textContent = '';

  const headerRow = document.createElement('tr');
  DECK_COLUMNS.forEach((col) => {
    const th = document.createElement('th');
    const arrow = deckState.sortKey === col.key ? (deckState.sortDir === 'asc' ? ' ▲' : ' ▼') : '';
    th.textContent = col.label + arrow;
    th.title = 'Sort by ' + col.label;
    th.addEventListener('click', () => {
      if (deckState.sortKey === col.key) {
        deckState.sortDir = deckState.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        deckState.sortKey = col.key;
        deckState.sortDir = 'asc';
      }
      renderDeckTable();
    });
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);

  const rows = sortRows(getFilteredRows());
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    DECK_COLUMNS.forEach((col) => tr.appendChild(buildDeckCell(row, col.key)));
    tbody.appendChild(tr);
  });

  const info = document.getElementById('deck-table-stats');
  if (info) info.textContent = 'Showing ' + rows.length + ' of ' + deckState.rows.length + ' cards';
  updateVisibleStats(rows);
  renderCharts(rows);
}

function renderExpansionChips() {
  const chips = document.querySelectorAll('#expansion-filter .exp-chip');
  chips.forEach((chip) => {
    const isActive = asText(chip.getAttribute('data-expansion')) === deckState.expansion;
    chip.classList.toggle('active', isActive);
    chip.setAttribute('aria-pressed', isActive ? 'true' : 'false');
  });
}

function initExpansionFilter() {
  const host = document.getElementById('expansion-filter');
  if (!host) return;
  host.addEventListener('click', (ev) => {
    const target = ev.target;
    if (!(target instanceof Element)) return;
    const chip = target.closest('.exp-chip');
    if (!chip) return;
    deckState.expansion = asText(chip.getAttribute('data-expansion')) || '__all';
    renderExpansionChips();
    renderDeckTable();
  });
}

function resetDeckFilters() {
  deckState.expansion = '__all';
  deckState.search = '';
  deckState.yearMin = '';
  deckState.yearMax = '';
  deckState.sortKey = 'card_id';
  deckState.sortDir = 'asc';
  const search = document.getElementById('deck-search');
  if (search) search.value = '';
  const yearMin = document.getElementById('deck-year-min');
  if (yearMin) yearMin.value = '';
  const yearMax = document.getElementById('deck-year-max');
  if (yearMax) yearMax.value = '';
  renderExpansionChips();
  renderDeckTable();
}

function exportFilteredCsv() {
  const rows = sortRows(getFilteredRows());
  const cols = DECK_COLUMNS.map((col) => col.key).concat(['spotify_url']);
  const lines = [cols.map(csvEscape).join(',')];
  rows.forEach((row) => {
    lines.push(cols.map((col) => csvEscape(col === 'is_new' ? (row.is_new ? 'yes' : '') : row[col])).join(','));
  });
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const meta = parseReportData().meta || {};
  const token = asText(meta.version || 'deck').replace(/[^a-zA-Z0-9._-]+/g, '_') || 'deck';
  const a = document.createElement('a');
  a.href = url;
  a.download = 'deck_cards_' + token + '.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function initDeckTableUI() {
  const reportData = parseReportData();
  const rows = Array.isArray(reportData.cards) ? reportData.cards : [];
  deckState.rows = rows;
  deckState.expansionById = {};
  (Array.isArray(reportData.expansions) ? reportData.expansions : []).forEach((item) => {
    deckState.expansionById[asText(item.id)] = item;
  });
  const owners = (reportData.owners && typeof reportData.owners === 'object') ? reportData.owners : {};
  chartState.ownerNames = (owners.names && typeof owners.names === 'object') ? owners.names : {};
  chartState.ownerColors = (owners.colors && typeof owners.colors === 'object') ? owners.colors : {};

  const searchInput = document.getElementById('deck-search');
  if (searchInput) {
    const onSearch = debounce(() => {
      deckState.search = asText(searchInput.value).toLowerCase().trim();
      renderDeckTable();
    }, 150);
    searchInput.addEventListener('input', onSearch);
  }
  const yearMinInput = document.getElementById('deck-year-min');
  if (yearMinInput) {
    yearMinInput.addEventListener('input', () => {
      deckState.yearMin = asText(yearMinInput.value).trim();
      renderDeckTable();
    });
  }
  const yearMaxInput = document.getElementById('deck-year-max');
  if (yearMaxInput) {
    yearMaxInput.addEventListener('input', () => {
      deckState.yearMax = asText(yearMaxInput.value).trim();
      renderDeckTable();
    });
  }
  const resetBtn = document.getElementById('deck-reset');
  if (resetBtn) resetBtn.addEventListener('click', resetDeckFilters);
  const exportBtn = document.getElementById('deck-export');
  if (exportBtn) exportBtn.addEventListener('click', exportFilteredCsv);

  initExpansionFilter();
  initYearBinToggle();
  renderExpansionChips();
  renderDeckTable();
}

document.addEventListener('DOMContentLoaded', () => {
  initReportTheme();
  initPdfExport();
  initDeckTableUI();
});
