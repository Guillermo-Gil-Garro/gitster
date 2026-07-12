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

const PRINT_SECTION_IDS = ['sec-expansions', 'sec-coverage', 'sec-years', 'sec-new'];
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
  renderExpansionChips();
  renderDeckTable();
}

document.addEventListener('DOMContentLoaded', () => {
  initReportTheme();
  initPdfExport();
  initDeckTableUI();
});
