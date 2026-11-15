// Shared helpers for every page: fetch, escaping, header, navigation, tags.
// Vanilla JS, no build step.
'use strict';

const LABEL = { MIXED: 'Mixed', PHONE: 'Phone', CW: 'CW', DIGITAL: 'Digital', SAT: 'Satellite' };
const label = (c) => LABEL[c] || c.replace('M', ' m');
const CONTINENTS = [['AF', 'AFRICA'], ['AS', 'ASIA'], ['OC', 'OCEANIA'], ['EU', 'EUROPE'],
  ['SA', 'SOUTH AMERICA'], ['NA', 'NORTH AMERICA'], ['AN', 'ANTARCTICA']];

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const num = (n) => Number(n).toLocaleString('en-US');

// Dates are stored in UTC; show them in local time as "2026-10-05 16:20".
function when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);   // show odd values as they came
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) {
    const msg = body && body.detail ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
      : `The server answered ${r.status}.`;
    throw new Error(msg);
  }
  return body;
}
const postJSON = (path, data) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data ?? {}) });

const PAGES = [
  ['/', 'Missing Entities'], ['/slots', 'Missing Band Slots'], ['/matrix', 'Full Matrix'],
  ['/advisor', 'Suggestions'], ['/paper', 'Paper QSLs'], ['/import', 'Import'], ['/settings', 'Settings'],
  ['/help', 'Help'],
];

// Each page's section in the user guide (D58). The Help link in the header
// opens the guide there. tests/test_help.py checks every anchor exists.
const HELP_SECTIONS = {
  '/': 'missing-entities', '/slots': 'missing-band-slots', '/matrix': 'full-matrix',
  '/advisor': 'suggestions-for-dx-monitor', '/paper': 'paper-qsls',
  '/import': 'getting-your-lotw-data-in-import', '/settings': 'settings',
  '/entity': 'entity-search-and-report',
};
const HELP_ICON = '<b aria-hidden="true">?</b>';

function profileText(p) {
  const order = ['160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M', '2M'];
  const bands = order.filter((b) => p.bands.includes(b));
  let bandTxt = bands.map(label).join(', ');
  const i = order.indexOf(bands[0]);
  if (bands.length > 2 && order.slice(i, i + bands.length).join() === bands.join()) {
    bandTxt = `${bands[0].replace('M', '')}–${bands[bands.length - 1].replace('M', '')} m`;
  }
  return `Profile ${bandTxt} · ${p.modes.map(label).join(' / ')}`;
}

function renderChrome({ title, subtitle, actions = '' }) {
  const here = location.pathname;
  const help = HELP_SECTIONS[here]
    ? `<a class="helplink" href="/help#${HELP_SECTIONS[here]}" title="Open the user guide at this page's section">${HELP_ICON}Help</a>` : '';
  document.getElementById('chrome').innerHTML = `
    <header class="top">
      <div>
        <div class="brand">N4MI DXCC ANALYZER<span class="ver" id="appver"></span></div>
        <h1>${esc(title)}</h1>
        <div class="sub">${subtitle || ''}</div>
      </div>
      <div class="noprint hdr-actions">${SEARCH_HTML}${help}${actions}</div>
    </header>
    <nav class="views" aria-label="Views">
      ${PAGES.map(([href, name]) => href
        ? `<a href="${href}"${href === here ? ' aria-current="page"' : ''}>${name}</a>`
        : `<span title="Coming in the next build step">${name}</span>`).join('')}
    </nav>
    <div id="health" role="alert"></div>`;
  checkHealth();
  showDXMonExport();
  wireSearch();
}

// ---------- Entity search in the header (D61) ----------
// Type-ahead over every current entity (deleted ones are never listed). The
// list is fetched once, the first time the box is used, and matched here in
// the browser, so typing never waits on the server. Choosing an entity opens
// its report at /entity#<DXCC number>.
const SEARCH_HTML = `<div class="esearch" role="search">
  <label class="sr" for="esq">Find an entity</label>
  <div class="ebox"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
    <input id="esq" type="text" role="combobox" aria-expanded="false" aria-controls="eslist" aria-autocomplete="list"
      placeholder="Find an entity" autocomplete="off" spellcheck="false"><kbd aria-hidden="true" title="Press / to search">/</kbd></div>
  <ul id="eslist" class="elist" role="listbox" aria-label="Matching entities" hidden></ul></div>`;
const SEARCH_MAX = 8;
let searchIndex = null;      // a promise, so several keystrokes share one fetch

function normText(s) {
  return String(s || '').toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9/ ]+/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

function loadSearchIndex() {
  if (!searchIndex) {
    searchIndex = api('/api/entities/index').then((r) => {
      for (const e of r.entities) {
        e._px = e.prefix.toLowerCase().split(/[ ,]+/).filter(Boolean);
        e._names = [e.name, e.lotw_name].concat(e.aliases || []).map(normText);
      }
      return r;
    }).catch((err) => { searchIndex = null; throw err; });
  }
  return searchIndex;
}

// Best first: DXCC number, exact prefix, prefix start, name start, word starts, anywhere.
function searchScore(e, q, words) {
  if (/^\d+$/.test(q) && Number(q) === e.dxcc) return 100;
  const qp = q.replace(/ /g, '');
  if (e._px.includes(qp)) return 90;
  if (e._px.some((p) => p.startsWith(qp))) return 80;
  let best = 0;
  for (const n of e._names) {
    if (n.startsWith(q)) best = Math.max(best, 70);
    const ws = n.split(' ');
    if (words.every((w) => ws.some((x) => x.startsWith(w)))) best = Math.max(best, 60);
    else if (n.includes(q)) best = Math.max(best, 40);
  }
  if (!best && /^\d+$/.test(q) && String(e.dxcc).startsWith(q)) best = 30;
  return best;
}

function searchStatus(e, hasData) {
  if (!hasData) return '';
  if (e.new) return '<span class="st new">NEW</span>';
  if (e.needed) return `<span class="st">${e.needed} needed</span>`;
  if (e.pending) return '<span class="st">pending</span>';
  return '<span class="st done">complete</span>';
}

function wireSearch() {
  const box = document.getElementById('esq');
  const list = document.getElementById('eslist');
  if (!box) return;
  let hits = [], sel = 0;
  const close = () => { list.hidden = true; box.setAttribute('aria-expanded', 'false'); box.removeAttribute('aria-activedescendant'); };
  const open = (e) => { location.href = `/entity#${e.dxcc}`; close(); box.value = ''; box.blur(); };
  const draw = (idx) => {
    if (!hits.length) {
      list.innerHTML = '<li class="hint" role="presentation">No current entity matches. Try a prefix, a name or a DXCC number.</li>';
    } else {
      list.innerHTML = hits.map((e, i) => `<li id="es-${i}" role="option" aria-selected="${i === sel}"${i === sel ? ' class="sel"' : ''} data-i="${i}">
        <span class="px">${esc(e.prefix || '—')}</span><span class="nm">${esc(e.name)}</span>${searchStatus(e, idx.has_data)}</li>`).join('')
        + '<li class="hint" role="presentation">↑ ↓ to move · Enter to open · name, prefix or DXCC number</li>';
      box.setAttribute('aria-activedescendant', `es-${sel}`);
    }
    list.hidden = false;
    box.setAttribute('aria-expanded', 'true');
  };
  const update = async () => {
    const q = normText(box.value);
    if (!q) { close(); return; }
    let idx;
    try { idx = await loadSearchIndex(); } catch (err) {
      list.innerHTML = `<li class="hint" role="presentation">Search isn't available: ${esc(err.message)}</li>`;
      list.hidden = false; return;
    }
    // A newer keystroke has taken over, or the box was closed while waiting.
    if (normText(box.value) !== q || document.activeElement !== box) return;
    const words = q.split(' ');
    hits = idx.entities.map((e) => [searchScore(e, q, words), e]).filter(([s]) => s > 0)
      .sort((a, b) => b[0] - a[0] || a[1].name.localeCompare(b[1].name)).slice(0, SEARCH_MAX).map(([, e]) => e);
    sel = 0;
    draw(idx);
  };
  box.addEventListener('focus', () => { loadSearchIndex().catch(() => {}); });
  box.addEventListener('input', update);
  box.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') { close(); box.blur(); return; }
    if (list.hidden || !hits.length) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      sel = (sel + (ev.key === 'ArrowDown' ? 1 : hits.length - 1)) % hits.length;
      loadSearchIndex().then(draw);
    } else if (ev.key === 'Enter') { ev.preventDefault(); open(hits[sel]); }
  });
  // mousedown, not click: it fires before the box loses focus.
  list.addEventListener('mousedown', (ev) => {
    const li = ev.target.closest('li[data-i]');
    if (li) { ev.preventDefault(); open(hits[+li.dataset.i]); }
  });
  box.addEventListener('blur', () => setTimeout(close, 150));
  if (!window.__searchKey) {
    window.__searchKey = true;
    document.addEventListener('keydown', (ev) => {
      const t = ev.target;
      const typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      if (ev.key === '/' && !typing && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        const b = document.getElementById('esq');
        if (b) { ev.preventDefault(); b.focus(); }
      }
    });
  }
}

// The For DX Monitor export appears only while DX Monitor is switched on in
// Settings (D53). Reading the setting makes no call to DX Monitor itself.
async function showDXMonExport() {
  const item = document.querySelector('[data-dxmon]');
  if (!item) return;
  try {
    const s = await (await fetch('/api/settings/dxmon')).json();
    if (s.url) item.hidden = false;
  } catch (e) { /* leave it hidden */ }
}

// Every page shows a plain warning when the app reports a problem: an
// unreadable database, a missing data folder, or stored data the entity table
// doesn't know (spec section 12).
async function checkHealth() {
  try {
    const st = await (await fetch('/api/status')).json();
    if (st.version) document.getElementById('appver').textContent = `v${st.version}`;
    if (!st.ok && st.error) {
      document.getElementById('health').innerHTML =
        `<div class="notice bad" style="margin-top:16px"><div><div class="t">Problem</div><div>${esc(st.error)}</div></div></div>`;
    }
  } catch (e) { /* the page's own request will show the error */ }
}

const CARD_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h6M7 14h4"/></svg>';

// Tags for one slot of one entity: LoTW mark and/or paper cards.
function slotTags(ent, cat) {
  let out = '';
  const m = (ent.marks || {})[cat];
  if (m && m.state === 'awaiting') out += '<span class="tag await" title="Confirmed in LoTW, not yet credited">AWAITING</span>';
  if (m && m.state === 'wont_submit') out += '<span class="tag wont" title="Marked: won\'t submit">WON\'T SUBMIT</span>';
  const cards = (ent.cards || {})[cat] || [];
  if (cards.length) {
    const sub = cards.some((c) => c.state === 'submitted');
    out += `<span class="tag card" title="Paper QSL ${sub ? 'submitted' : 'in hand'}, not yet credited">${CARD_ICON}CARD</span>`;
  }
  return out;
}

function showError(where, err) {
  document.getElementById(where).innerHTML =
    `<div class="notice bad" role="alert"><div><div class="t">Something went wrong</div><div>${esc(err.message || err)}</div></div></div>`;
}

const NO_DATA_HTML = `<div class="panel empty"><h2>No import yet</h2>
  <p class="muted">Paste your LoTW Award Credit Matrix to see what you still need.</p>
  <a class="btn primary" href="/import">Import the matrix</a></div>`;

// ---------- Pending-mark menu (D51: "slots in one go") ----------
// One QSO is credited to its band AND its mode, plus Mixed for a new entity,
// wherever each is not yet credited. So the menu marks every slot a
// confirmation covers at once. Used by Missing Entities, Band Slots and the
// Full Matrix. Credited slots are shown greyed out and can't be marked.
// ent: {dxcc, name, marks, credited}; profile: {bands, modes};
// onDone: reload callback; focus: the slot that was clicked (pre-ticked).
function openMarkMenu(ent, profile, onDone, focus) {
  let dlg = document.getElementById('markdlg');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'markdlg';
    dlg.className = 'markdlg';
    document.body.appendChild(dlg);
  }
  const marks = ent.marks || {};
  const slots = profile.bands.concat(profile.modes);
  const have = new Set(ent.credited || []);
  const credited = (c) => have.has(c);
  const isNew = !have.has('MIXED');
  const nMarked = Object.keys(marks).length;
  // Pre-tick: existing marks, the slot clicked, and Mixed for a new entity
  // being marked for the first time (a new entity's first QSO counts there too).
  const ticked = (c) => !!marks[c] || c === focus || (c === 'MIXED' && isNew && !nMarked);
  const first = (focus && marks[focus]) || marks.MIXED || Object.values(marks)[0];
  const st = first ? first.state : 'awaiting';
  const note0 = first ? first.note : '';
  const SHORTL = { CW: 'CW', PHONE: 'Phone', DIGITAL: 'Digital', SAT: 'SAT' };
  const box = (c) => credited(c)
    ? `<label title="Already credited"><input type="checkbox" disabled><span class="cr">${esc(SHORTL[c] || c.replace('M', ' m'))}</span></label>`
    : `<label><input type="checkbox" data-cat="${c}"${ticked(c) ? ' checked' : ''}>${esc(SHORTL[c] || c.replace('M', ' m'))}</label>`;
  dlg.innerHTML = `<form method="dialog" class="menu" aria-label="Mark ${esc(ent.name)}">
    <div><div class="mt">${esc(ent.name)}</div>
      <div class="muted small">${nMarked ? `${nMarked} slot${nMarked > 1 ? 's' : ''} marked` : 'Not marked'} · ${isNew ? 'never confirmed' : 'entity credited; greyed slots are credited'}</div></div>
    ${isNew ? `<label class="opt"><input type="checkbox" data-cat="MIXED"${ticked('MIXED') ? ' checked' : ''}>
      <span><b>New entity (Mixed)</b></span></label>` : ''}
    <fieldset><legend class="muted small">Bands and modes this confirmation covers</legend>
      <div class="slots">${slots.map(box).join('')}</div></fieldset>
    <fieldset><legend class="muted small">These slots are confirmed in LoTW and…</legend>
      <label class="opt"><input type="radio" name="st" value="awaiting"${st === 'awaiting' ? ' checked' : ''}>
        <span><b>Awaiting credit</b><br><span class="muted small">Not yet credited; you'll submit them with your next application</span></span></label>
      <label class="opt"><input type="radio" name="st" value="wont_submit"${st === 'wont_submit' ? ' checked' : ''}>
        <span><b>Won't submit</b><br><span class="muted small">You won't use this QSL for credit, for example an EchoLink contact</span></span></label>
    </fieldset>
    <label class="muted small" for="mk-note">Note (optional)</label>
    <input id="mk-note" type="text" class="txt" value="${esc(note0)}" placeholder="Call worked, mode, date…">
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button type="button" class="btn primary" id="mk-save">Save marks</button>
      ${nMarked ? '<button type="button" class="btn" id="mk-clear">Clear all</button>' : ''}
      <button type="button" class="btn quiet" id="mk-cancel">Cancel</button>
    </div>
    <div id="mk-msg" role="status" class="small"></div>
    <div class="muted small">Unticking a slot clears its mark. Marks clear themselves when an import shows the slot credited.</div>
  </form>`;
  const msg = (t) => { dlg.querySelector('#mk-msg').innerHTML = `<span class="err">${esc(t)}</span>`; };
  const noteEl = dlg.querySelector('#mk-note');
  let noteEdited = false;
  noteEl.oninput = () => { noteEdited = true; };
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  // Save every change; report any that failed without hiding the ones that worked.
  async function apply(want) {
    const state = dlg.querySelector('input[name=st]:checked').value;
    const note = noteEl.value.trim();
    const errs = [];
    for (const c of ['MIXED'].concat(slots)) {
      const m = marks[c];
      try {
        if (want.has(c) && !m) await postJSON('/api/marks', { dxcc: ent.dxcc, category: c, state, note });
        // An untouched note field never overwrites a slot's own note.
        else if (want.has(c) && (m.state !== state || (noteEdited && m.note !== note)))
          await api(`/api/marks/${m.id}`, json('PATCH', { state, note: noteEdited ? note : m.note }));
        else if (!want.has(c) && m) await api(`/api/marks/${m.id}`, { method: 'DELETE' });
      } catch (err) { errs.push(`${c === 'MIXED' ? 'Mixed' : label(c)}: ${err.message}`); }
    }
    if (errs.length) { msg(errs.join(' · ')); onDone(); } else { dlg.close(); onDone(); }
  }
  dlg.querySelector('#mk-cancel').onclick = () => dlg.close();
  dlg.querySelector('#mk-save').onclick = () =>
    apply(new Set([...dlg.querySelectorAll('input[data-cat]:checked')].map((b) => b.dataset.cat)));
  const clr = dlg.querySelector('#mk-clear');
  if (clr) clr.onclick = () => apply(new Set());
  dlg.showModal();
}

// Export menu for the page headers. Files follow the operating profile,
// never a page's temporary filters.
const EXPORT_MENU = `<details class="exportmenu">
  <summary class="btn">Export</summary>
  <div class="exportlist" role="menu">
    <a role="menuitem" href="/export/workbook.xlsx" download><b>Workbook (.xlsx)</b><span>Summary, missing entities and slots, by band, matrix, marks, paper QSLs</span></a>
    <a role="menuitem" href="/export/missing_entities.csv" download><b>Missing entities (.csv)</b><span>With Most Wanted rank, marks and paper cards</span></a>
    <a role="menuitem" href="/export/missing_slots.csv" download><b>Missing band slots (.csv)</b><span>One column per band and mode in your profile</span></a>
    <a role="menuitem" href="/export/no_confirms.csv" download data-dxmon hidden><b>For DX Monitor: no_confirms.csv</b><span>Drop-in file for DX Monitor's Trigger Builder picker</span></a>
  </div></details>`;

// Copy text to the clipboard. The app is served over plain http on the LAN,
// where browsers withhold navigator.clipboard, so fall back to a hidden textarea.
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch (e) { /* fall through */ }
  const t = document.createElement('textarea');
  t.value = text;
  t.setAttribute('readonly', '');
  t.style.position = 'fixed'; t.style.opacity = '0';
  document.body.appendChild(t);
  t.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  t.remove();
  return ok;
}
