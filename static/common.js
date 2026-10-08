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
  ['/paper', 'Paper QSLs'], ['/import', 'Import'], ['/settings', 'Settings'],
];

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
  document.getElementById('chrome').innerHTML = `
    <header class="top">
      <div>
        <div class="brand">N4MI DXCC ANALYZER</div>
        <h1>${esc(title)}</h1>
        <div class="sub">${subtitle || ''}</div>
      </div>
      <div class="noprint" style="display:flex;gap:12px">${actions}</div>
    </header>
    <nav class="views" aria-label="Views">
      ${PAGES.map(([href, name]) => href
        ? `<a href="${href}"${href === here ? ' aria-current="page"' : ''}>${name}</a>`
        : `<span title="Coming in the next build step">${name}</span>`).join('')}
    </nav>
    <div id="health" role="alert"></div>`;
  checkHealth();
}

// Every page shows a plain warning when the app reports a problem: an
// unreadable database, a missing data folder, or stored data the entity table
// doesn't know (spec section 12).
async function checkHealth() {
  try {
    const st = await (await fetch('/api/status')).json();
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

// ---------- Pending-mark menu (approved Marks mockup) ----------
// One dialog shared by Missing Entities, Missing Band Slots and Full Matrix.
// ent: {dxcc, name, marks}; cat: category code; onDone: reload callback.
function openMarkMenu(ent, cat, onDone) {
  let dlg = document.getElementById('markdlg');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'markdlg';
    dlg.className = 'markdlg';
    document.body.appendChild(dlg);
  }
  const mark = (ent.marks || {})[cat];
  const st = mark ? mark.state : 'awaiting';
  const slot = cat === 'MIXED' ? 'new entity (Mixed)' : label(cat);
  dlg.innerHTML = `<form method="dialog" class="menu" aria-label="Mark ${esc(ent.name)} ${esc(slot)}">
    <div><div class="mt">${esc(ent.name)} · ${esc(slot)}</div>
      <div class="muted small">${mark ? 'Currently marked: ' + (mark.state === 'awaiting' ? 'awaiting credit' : "won't submit") : 'Not marked'}</div></div>
    <fieldset><legend class="muted small">This slot is confirmed in LoTW and…</legend>
      <label class="opt"><input type="radio" name="st" value="awaiting"${st === 'awaiting' ? ' checked' : ''}>
        <span><b>Awaiting credit</b><br><span class="muted small">Not yet credited; you'll submit it with your next application</span></span></label>
      <label class="opt"><input type="radio" name="st" value="wont_submit"${st === 'wont_submit' ? ' checked' : ''}>
        <span><b>Won't submit</b><br><span class="muted small">You won't use this QSL for credit, for example an EchoLink contact</span></span></label>
    </fieldset>
    <label class="muted small" for="mk-note">Note (optional)</label>
    <input id="mk-note" type="text" class="txt" value="${esc(mark ? mark.note : '')}" placeholder="Call worked, mode, date…">
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button type="button" class="btn primary" id="mk-save">Save mark</button>
      ${mark ? '<button type="button" class="btn" id="mk-clear">Clear mark</button>' : ''}
      <button type="button" class="btn quiet" id="mk-cancel">Cancel</button>
    </div>
    <div id="mk-msg" role="status" class="small"></div>
    <div class="muted small">A mark clears itself when an import shows this slot credited.</div>
  </form>`;
  const msg = (t) => { dlg.querySelector('#mk-msg').innerHTML = `<span class="err">${esc(t)}</span>`; };
  dlg.querySelector('#mk-cancel').onclick = () => dlg.close();
  dlg.querySelector('#mk-save').onclick = async () => {
    const state = dlg.querySelector('input[name=st]:checked').value;
    const note = dlg.querySelector('#mk-note').value.trim();
    try {
      if (mark) await api(`/api/marks/${mark.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state, note }) });
      else await postJSON('/api/marks', { dxcc: ent.dxcc, category: cat, state, note });
      dlg.close(); onDone();
    } catch (err) { msg(err.message); }
  };
  const clr = dlg.querySelector('#mk-clear');
  if (clr) clr.onclick = async () => {
    try { await api(`/api/marks/${mark.id}`, { method: 'DELETE' }); dlg.close(); onDone(); }
    catch (err) { msg(err.message); }
  };
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
    <a role="menuitem" href="/export/no_confirms.csv" download><b>For DX Monitor: no_confirms.csv</b><span>Drop-in file for DX Monitor's Trigger Builder picker</span></a>
  </div></details>`;
