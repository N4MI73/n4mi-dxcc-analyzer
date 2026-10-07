// Missing Band Slots: one tile per band/mode in the profile; pick one to see
// its chase list (credited entities still needing that slot), by continent.
'use strict';

const state = { data: null, sel: null, sort: 'fewest', group: 'continent', hideMarked: false };

const byName = (a, b) => a.name.localeCompare(b.name);
const rankKey = (e, easiest) => (e.mw_rank == null ? 1e6 : easiest ? -e.mw_rank : e.mw_rank);
const SORTS = {
  fewest: ['Fewest other needs first', (a, b) => a.slots_needed - b.slots_needed || byName(a, b)],
  easy: ['Most Wanted, easiest first', (a, b) => rankKey(a, true) - rankKey(b, true) || byName(a, b)],
  rare: ['Most Wanted, rarest first', (a, b) => rankKey(a, false) - rankKey(b, false) || byName(a, b)],
  name: ['Entity name', byName],
};
const marked = (e, cat) => !!(e.marks[cat] || (e.cards[cat] || []).length);

function render() {
  const d = state.data;
  const cats = d.categories;
  if (!cats.some((c) => c.category === state.sel)) state.sel = (cats.find((c) => c.entities.length) || cats[0]).category;
  const max = Math.max(1, ...cats.map((c) => c.entities.length));
  const cur = cats.find((c) => c.category === state.sel);
  const isSat = cur.category === 'SAT';

  let list = cur.entities.slice();
  if (state.hideMarked) list = list.filter((e) => !marked(e, cur.category));
  list.sort(SORTS[state.sort][1]);
  const groups = state.group === 'continent'
    ? CONTINENTS.map(([c, name]) => ({ name, items: list.filter((e) => e.continent === c) })).filter((g) => g.items.length)
    : [{ name: SORTS[state.sort][0].toUpperCase(), items: list }];

  const row = (e) => {
    // Satellite is a separate award, so "other needs" (band/mode slots) don't apply.
    const others = isSat ? '' : e.slots_needed <= 1 ? '<span class="ot" title="This is its last missing slot">Done</span>'
      : `<span class="ot" title="Other slots this entity still needs in your profile">+${e.slots_needed - 1}</span>`;
    return `<div class="ent"><div class="px">${esc(e.prefix || '—')}</div><div class="nm">${esc(e.name)}</div>${slotTags(e, cur.category)}${others}</div>`;
  };

  document.getElementById('main').innerHTML = `
    <section aria-labelledby="pick-h" style="display:flex;flex-direction:column;gap:14px">
      <div class="head"><h2 id="pick-h">What's needed on each band or mode</h2>
        <div class="muted small">Credited entities still missing each slot · pick one to see the chase list</div></div>
      <div class="tiles noprint">${cats.map((c) => {
        const pend = c.entities.filter((e) => marked(e, c.category)).length;
        return `<button type="button" class="tile" data-cat="${c.category}" aria-pressed="${c.category === state.sel}">
          <span class="l">${esc(label(c.category))}</span><span class="c">${c.entities.length}</span>
          <span class="bar"><span style="width:${Math.round(c.entities.length / max * 100)}%"></span></span>
          <span class="p">${pend ? pend + ' awaiting' : '&nbsp;'}</span></button>`;
      }).join('')}</div>
    </section>
    <section aria-labelledby="list-h" style="display:flex;flex-direction:column;gap:16px">
      <div class="head">
        <h2 id="list-h">Needed on ${esc(label(cur.category))} <span class="n">${list.length}</span></h2>
        <div class="controls noprint">
          <label>Sort <select id="sort">${Object.entries(SORTS).map(([k, [t]]) =>
            `<option value="${k}"${k === state.sort ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
          <label>Show <select id="group">
            <option value="continent"${state.group === 'continent' ? ' selected' : ''}>By continent</option>
            <option value="list"${state.group === 'list' ? ' selected' : ''}>One list</option></select></label>
          <label class="chk"><input type="checkbox" id="hide"${state.hideMarked ? ' checked' : ''}> Hide slots awaiting credit</label>
        </div>
      </div>
      ${isSat ? '<div class="muted small">Satellite DXCC is a separate award: this list covers every current entity without Satellite credit, whether or not you have it on other bands and modes.</div>' : ''}
      <div class="groups${state.group === 'list' ? ' one' : ''}">
        ${groups.map((g) => `<div class="group"><div class="gh"><span>${esc(g.name)}</span><span class="n">${g.items.length}</span></div>
          ${g.items.map(row).join('')}</div>`).join('') || '<div class="muted">Nothing needed here. Nice work.</div>'}
      </div>
      ${isSat ? '' : '<div class="muted small">“+N” = other slots that entity still needs in your profile. “Done” means this is its last missing slot.</div>'}
    </section>`;

  document.querySelectorAll('.tile').forEach((b) => (b.onclick = () => {
    state.sel = b.dataset.cat; history.replaceState(null, '', '#' + state.sel); render();
  }));
  document.getElementById('sort').onchange = (e) => { state.sort = e.target.value; render(); };
  document.getElementById('group').onchange = (e) => { state.group = e.target.value; render(); };
  document.getElementById('hide').onchange = (e) => { state.hideMarked = e.target.checked; render(); };
}

async function load() {
  try {
    const data = await api('/api/view/slots');
    if (data.no_data) {
      renderChrome({ title: 'Missing band slots', subtitle: 'No matrix imported yet' });
      document.getElementById('main').innerHTML = NO_DATA_HTML;
      return;
    }
    state.data = data;
    state.sel = location.hash.slice(1) || null;
    const s = data.summary;
    renderChrome({
      title: `${data.callsign || 'DXCC'} · Missing band slots`,
      subtitle: `${num(s.slots_missing)} slots on ${s.entities_credited} credited entities · ${esc(profileText(data.profile))}`,
      actions: '<a class="btn primary" href="/import">Paste new matrix</a><button class="btn" onclick="window.print()">Print</button>',
    });
    render();
  } catch (err) {
    renderChrome({ title: 'Missing band slots' });
    showError('main', err);
  }
}
load();
