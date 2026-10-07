// Missing Entities (primary view): never-credited entities, grouped by continent.
'use strict';

const state = { data: null, status: null, marks: [], sort: 'easy', group: 'continent', hideAwaiting: false };

const SORTS = {
  easy: ['Most Wanted, easiest first', (a, b) => rankKey(a, true) - rankKey(b, true) || byName(a, b)],
  rare: ['Most Wanted, rarest first', (a, b) => rankKey(a, false) - rankKey(b, false) || byName(a, b)],
  name: ['Entity name', (a, b) => byName(a, b)],
  prefix: ['Prefix', (a, b) => a.prefix.localeCompare(b.prefix) || byName(a, b)],
};
const byName = (a, b) => a.name.localeCompare(b.name);
// Club Log rank 1 = most wanted. Easiest first = highest rank number first.
// Entities without a rank always sort last.
function rankKey(e, easiest) {
  if (e.mw_rank == null) return 1e6;
  return easiest ? -e.mw_rank : e.mw_rank;
}

function entRow(e) {
  const tags = slotTags(e, 'MIXED') + (e.sat_credited ? '<span class="tag sat" title="Already credited for Satellite DXCC">SAT</span>' : '');
  const rank = e.mw_rank != null ? `<span class="rk" title="Club Log Most Wanted rank">#${e.mw_rank}</span>` : '';
  return `<button type="button" class="ent click" data-dxcc="${e.dxcc}" title="Mark ${esc(e.name)} as awaiting credit or won't submit"><div class="px">${esc(e.prefix || '—')}</div><div class="nm">${esc(e.name)}</div>${tags}${rank}</button>`;
}

function render() {
  const d = state.data;
  const s = d.summary;
  const awaitingEntities = d.entities.filter((e) => (e.marks.MIXED || {}).state === 'awaiting').length;
  const cardEntities = d.entities.filter((e) => (e.cards.MIXED || []).length).length;
  const slotCats = new Set(d.profile.bands.concat(d.profile.modes));
  const slotMarks = state.marks.filter((m) => m.state === 'awaiting' && slotCats.has(m.category)).length;
  const check = state.status && state.status.last_status_check;
  const checkTxt = !check ? 'Mixed · not yet checked against LoTW Account Status'
    : check.snapshot_id !== d.snapshot_id ? 'Mixed · last LoTW check was on an earlier import'
    : check.reconciled ? 'Mixed · matches LoTW Account Status' : '<span class="err">Mixed · does NOT match LoTW Account Status</span>';

  let list = d.entities.slice();
  if (state.hideAwaiting) list = list.filter((e) => (e.marks.MIXED || {}).state !== 'awaiting');
  list.sort(SORTS[state.sort][1]);
  let groups;
  if (state.group === 'continent') {
    groups = CONTINENTS.map(([c, name]) => ({ name, items: list.filter((e) => e.continent === c) }))
      .filter((g) => g.items.length);
  } else {
    groups = [{ name: SORTS[state.sort][0].toUpperCase(), items: list }];
  }

  const since = d.since_last;
  let sinceTxt = 'First import — changes appear here after the next one.';
  if (since) {
    const n1 = since.new_entities.length, n2 = since.new_slots.length, n3 = since.lost.length;
    sinceTxt = (n1 || n2 || n3)
      ? [n1 && `+${n1} entit${n1 === 1 ? 'y' : 'ies'}${n1 <= 5 ? ' (' + since.new_entities.map((x) => esc(x.name)).join(', ') + ')' : ''}`,
         n2 && `+${n2} band and mode slot${n2 === 1 ? '' : 's'}`,
         n3 && `<span class="err">${n3} credit${n3 === 1 ? '' : 's'} lost</span>`].filter(Boolean).join(' · ')
      : 'No change in your profile.';
    sinceTxt += ` <span class="muted small">(compared with the import of ${esc(when(since.previous_saved_at))})</span>`;
  }

  const mw = d.most_wanted_fetched_at
    ? `Club Log Most Wanted ranks from ${esc(when(d.most_wanted_fetched_at))}.`
    : 'No Club Log Most Wanted list yet, so the Most Wanted sorts fall back to name.';

  document.getElementById('main').innerHTML = `
    <section class="stats" aria-label="Summary">
      <div class="panel stat"><div class="k">ENTITIES CREDITED</div>
        <div class="v">${s.entities_credited} <small>/ ${s.entities_current}</small></div>
        <div class="muted small">${checkTxt}</div></div>
      <div class="panel stat hot"><div class="k">NEVER CONFIRMED</div><div class="v">${s.entities_missing}</div>
        <div class="muted small">${awaitingEntities} awaiting credit in LoTW${cardEntities ? ` · ${cardEntities} with a paper card` : ''}</div></div>
      <div class="panel stat"><div class="k">MISSING BAND SLOTS</div><div class="v">${num(s.slots_missing)}</div>
        <div class="muted small">On credited entities · ${slotMarks} awaiting credit</div></div>
      <div class="panel stat"><div class="k">COMPLETE IN PROFILE</div><div class="v">${s.complete}</div>
        <div class="muted small">${s.one_slot_away} more are one slot away</div></div>
    </section>
    ${s.satellite_missing != null ? `<div class="strip"><div class="k">SATELLITE</div><div>${s.satellite_missing} entities still needed for Satellite DXCC (a separate award) · see Missing Band Slots</div></div>` : ''}
    <section class="strip" aria-label="Since last import"><div class="k">SINCE LAST IMPORT</div><div>${sinceTxt}</div></section>
    <section aria-labelledby="me-h" style="display:flex;flex-direction:column;gap:16px">
      <div class="head">
        <h2 id="me-h">Missing entities <span class="n">${list.length}</span></h2>
        <div class="controls noprint">
          <label>Sort <select id="sort">${Object.entries(SORTS).map(([k, [t]]) =>
            `<option value="${k}"${k === state.sort ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
          <label>Show <select id="group">
            <option value="continent"${state.group === 'continent' ? ' selected' : ''}>By continent</option>
            <option value="list"${state.group === 'list' ? ' selected' : ''}>One list</option></select></label>
          <label class="chk"><input type="checkbox" id="hide"${state.hideAwaiting ? ' checked' : ''}> Hide entities awaiting credit</label>
        </div>
      </div>
      <div class="legend"><span class="tag await">AWAITING</span> confirmed in LoTW, not yet credited
        <span class="tag card">${CARD_ICON}CARD</span> paper QSL, not yet credited</div>
      <div class="groups${state.group === 'list' ? ' one' : ''}">
        ${groups.map((g) => `<div class="group"><div class="gh"><span>${esc(g.name)}</span><span class="n">${g.items.length}</span></div>
          ${g.items.map(entRow).join('')}</div>`).join('') || '<div class="muted">Nothing to show.</div>'}
      </div>
      <div class="muted small">${mw} <a class="noprint" href="/settings">Refresh in Settings</a> · Select an entity to mark it awaiting credit.</div>
    </section>`;

  document.getElementById('sort').onchange = (e) => { state.sort = e.target.value; render(); };
  document.getElementById('group').onchange = (e) => { state.group = e.target.value; render(); };
  document.getElementById('hide').onchange = (e) => { state.hideAwaiting = e.target.checked; render(); };
  document.querySelectorAll('.ent.click').forEach((b) => (b.onclick = () => {
    const ent = state.data.entities.find((e) => e.dxcc === +b.dataset.dxcc);
    openMarkMenu(ent, 'MIXED', load);
  }));
}

async function load() {
  try {
    const [data, status, marks] = await Promise.all([api('/api/view/entities'), api('/api/status'), api('/api/marks')]);
    if (data.no_data) {
      renderChrome({ title: 'What\'s still needed', subtitle: 'No matrix imported yet' });
      document.getElementById('main').innerHTML = NO_DATA_HTML;
      return;
    }
    Object.assign(state, { data, status, marks: marks.marks });
    renderChrome({
      title: `${data.callsign || 'DXCC'} · What's still needed`,
      subtitle: `Matrix imported ${esc(when(data.saved_at || data.imported_at))} · ${esc(profileText(data.profile))}`,
      actions: '<a class="btn primary" href="/import">Paste new matrix</a>' + EXPORT_MENU + '<button class="btn" onclick="window.print()">Print</button>',
    });
    render();
  } catch (err) {
    renderChrome({ title: 'What\'s still needed' });
    showError('main', err);
  }
}
load();
