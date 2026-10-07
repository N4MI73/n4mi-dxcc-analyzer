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

// Pages not built yet appear in the navigation, greyed out, so the layout
// matches the mockups. They become links in Build Step 2b-2b.
const PAGES = [
  ['/', 'Missing Entities'], ['/slots', 'Missing Band Slots'], [null, 'Full Matrix'],
  [null, 'Paper QSLs'], ['/import', 'Import'], [null, 'Settings'],
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
    </nav>`;
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
