// Full Matrix: credited entities with gaps in the profile, closest to complete
// first. One column per profile band and mode. Select a needed cell to mark it.
'use strict';

const state = { data: null, max: 2, sort: 'fewest', continent: '', hidden: new Set() };
const FILTERS = [[1, '1 away'], [2, '≤ 2'], [4, '≤ 4'], [99, 'All']];
const byName = (a, b) => a.name.localeCompare(b.name);
const rankKey = (e, easiest) => (e.mw_rank == null ? 1e6 : easiest ? -e.mw_rank : e.mw_rank);
const SORTS = {
  fewest: ['Fewest slots needed first', (a, b) => a.n - b.n || byName(a, b)],
  most: ['Most slots needed first', (a, b) => b.n - a.n || byName(a, b)],
  name: ['Entity name', byName],
  easy: ['Most Wanted, easiest first', (a, b) => rankKey(a, true) - rankKey(b, true) || byName(a, b)],
  rare: ['Most Wanted, rarest first', (a, b) => rankKey(a, false) - rankKey(b, false) || byName(a, b)],
};
const SHORT = { CW: 'CW', PHONE: 'PH', DIGITAL: 'DIG', SAT: 'SAT' };

function columns(p) {
  // Bands first, then modes — the mockup's order.
  return p.bands.concat(p.modes);
}

function cell(e, c) {
  const m = e.marks[c], cards = e.cards[c] || [];
  const need = e.needed.includes(c);
  let cls = 'done', what = 'credited';
  if (need) {
    cls = 'need'; what = 'needed';
    if (cards.length) { cls = 'card'; what = 'paper QSL, not yet credited'; }
    if (m && m.state === 'awaiting') { cls = 'await'; what = 'confirmed in LoTW, awaiting credit'; }
    if (m && m.state === 'wont_submit') { cls = 'wont'; what = "marked won't submit"; }
  }
  const t = `${e.name} · ${label(c)}: ${what}`;
  return need
    ? `<td><button type="button" class="cell ${cls}" data-dxcc="${e.dxcc}" data-cat="${c}" title="${esc(t)}" aria-label="${esc(t)}"></button></td>`
    : `<td><span class="cell ${cls}" title="${esc(t)}"></span></td>`;
}

function hiddenNote(p) {
  const off = [];
  if (!p.bands.includes('2M')) off.push('2 m');
  if (!p.modes.includes('SAT')) off.push('Satellite');
  if (!off.length) return '';
  return `; ${off.join(' and ')} ${off.length > 1 ? 'are' : 'is'} imported but not shown (turn on in Settings)`;
}

function render() {
  const d = state.data;
  const cols = columns(d.profile).filter((c) => !state.hidden.has(c));
  const slotCats = columns(d.profile).filter((c) => c !== 'SAT');
  const credited = d.entities.filter((e) => e.credited.includes('MIXED'))
    .map((e) => Object.assign(e, { n: e.needed.filter((c) => slotCats.includes(c)).length }));
  const gaps = credited.filter((e) => e.n > 0);
  const complete = credited.filter((e) => e.n === 0).sort(byName);
  let rows = gaps.filter((e) => e.n <= state.max && (!state.continent || e.continent === state.continent));
  rows.sort(SORTS[state.sort][1]);

  document.getElementById('main').innerHTML = `
    <section aria-labelledby="mx-h" style="display:flex;flex-direction:column;gap:16px">
      <div class="head">
        <h2 id="mx-h">Closest to complete <span class="n">${rows.length}</span> <span class="muted small" style="font-family:var(--sans);font-weight:400">of ${gaps.length} credited entities with gaps</span></h2>
        <div role="group" aria-label="Filter by slots missing" class="noprint" style="display:flex;gap:8px">
          ${FILTERS.map(([v, t]) => `<button type="button" class="btn small pill" data-max="${v}" aria-pressed="${v === state.max}">${t}</button>`).join('')}
        </div>
      </div>
      <div class="controls noprint">
        <label>Sort <select id="sort">${Object.entries(SORTS).map(([k, [t]]) => `<option value="${k}"${k === state.sort ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
        <label>Continent <select id="cont"><option value="">All</option>${CONTINENTS.map(([c, n]) => `<option value="${c}"${c === state.continent ? ' selected' : ''}>${n[0] + n.slice(1).toLowerCase()}</option>`).join('')}</select></label>
        <span>Columns: ${columns(d.profile).map((c) => `<label class="chk" style="margin-right:6px"><input type="checkbox" data-col="${c}"${state.hidden.has(c) ? '' : ' checked'}>${esc(SHORT[c] || c.replace('M', ''))}</label>`).join('')}</span>
      </div>
      <div class="legend">
        <span class="lg"><span class="cell need"></span> Needed</span>
        <span class="lg"><span class="cell await"></span> Confirmed, awaiting credit</span>
        <span class="lg"><span class="cell card"></span> Paper QSL</span>
        <span class="lg"><span class="cell wont"></span> Won't submit</span>
        <span class="lg"><span class="cell done"></span> Credited</span>
      </div>
      <div class="mxwrap"><table class="mx">
        <thead><tr><th>Prefix</th><th>Entity</th><th class="num">Need</th>${cols.map((c) => `<th>${esc(SHORT[c] || c.replace('M', ''))}</th>`).join('')}</tr></thead>
        <tbody>${rows.map((e) => `<tr><td class="px">${esc(e.prefix || '—')}</td><td class="nm">${esc(e.name)}</td><td class="num">${e.n}</td>${cols.map((c) => cell(e, c)).join('')}</tr>`).join('')
          || `<tr><td colspan="${cols.length + 3}" class="muted">No entities match this filter.</td></tr>`}</tbody>
      </table></div>
      <div class="muted small">Columns follow your operating profile${hiddenNote(d.profile)}. Never-confirmed entities are on Missing Entities. Select a needed cell to mark it.</div>
      <details class="panel"><summary>${complete.length} entities complete in your profile</summary>
        <div class="muted small" style="margin-top:10px;columns:3">${complete.map((e) => `<div>${esc(e.prefix)} · ${esc(e.name)}</div>`).join('')}</div></details>
    </section>`;

  document.querySelectorAll('[data-max]').forEach((b) => (b.onclick = () => { state.max = +b.dataset.max; render(); }));
  document.getElementById('sort').onchange = (e) => { state.sort = e.target.value; render(); };
  document.getElementById('cont').onchange = (e) => { state.continent = e.target.value; render(); };
  document.querySelectorAll('[data-col]').forEach((b) => (b.onchange = () => {
    b.checked ? state.hidden.delete(b.dataset.col) : state.hidden.add(b.dataset.col); render();
  }));
  document.querySelectorAll('button.cell').forEach((b) => (b.onclick = () => {
    const ent = d.entities.find((e) => e.dxcc === +b.dataset.dxcc);
    openMarkMenu(ent, b.dataset.cat, load);
  }));
}

async function load() {
  try {
    const data = await api('/api/view/matrix');
    if (data.no_data) {
      renderChrome({ title: 'Full matrix', subtitle: 'No matrix imported yet' });
      document.getElementById('main').innerHTML = NO_DATA_HTML;
      return;
    }
    state.data = data;
    renderChrome({
      title: `${data.callsign || 'DXCC'} · Full matrix`,
      subtitle: `Matrix imported ${esc(when(data.saved_at || data.imported_at))} · ${esc(profileText(data.profile))}`,
      actions: '<a class="btn primary" href="/import">Paste new matrix</a>' + EXPORT_MENU + '<button class="btn" onclick="window.print()">Print</button>',
    });
    render();
  } catch (err) {
    renderChrome({ title: 'Full matrix' });
    showError('main', err);
  }
}
load();
