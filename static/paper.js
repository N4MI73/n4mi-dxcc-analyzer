// Paper QSLs: cards held or submitted that ARRL hasn't credited yet.
// Never counted as credits; cleared automatically when an import credits them.
'use strict';

const BANDS = ['160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M', '2M'];
const MODES = [['CW', 'CW'], ['PHONE', 'Phone'], ['DIGITAL', 'Digital'], ['SAT', 'Satellite']];
const state = { cards: [], entities: [], removing: null,
  form: { ent: '', band: '20M', mode: 'CW', call: '', date: '', st: 'in_hand', note: '' } };

function entKey(e) { return `${e.prefix || '—'} — ${e.name}`; }
function findEnt(text) {
  const t = text.trim().toUpperCase();
  return state.entities.find((e) => entKey(e).toUpperCase() === t)
    || state.entities.find((e) => e.name.toUpperCase() === t)
    || null;
}

function cardRow(c) {
  const fills = c.fills.length ? c.fills.map((f) => `<span class="tag card">${esc(label(f))}</span>`).join('')
    : '<span class="tag wont">outside profile</span>';
  const detail = [c.call, c.qso_date, c.note].filter(Boolean).map(esc).join(' · ') || '&nbsp;';
  const rm = state.removing === c.id
    ? `<button class="btn small" data-rm-yes="${c.id}" style="border-color:var(--red);color:var(--red-text)">Confirm remove</button><button class="btn quiet small" data-rm-no="1">Keep</button>`
    : `<button class="btn quiet small" data-rm="${c.id}" aria-label="Remove card for ${esc(c.name)}">Remove</button>`;
  return `<div class="cardrow">
    <span class="px mono">${esc(c.prefix || '—')}</span>
    <span class="cn"><span>${esc(c.name)}</span><span class="muted small">${detail}</span></span>
    <span class="mono">${c.band ? esc(label(c.band)) : '—'}</span>
    <span>${esc(label(c.mode))}</span>
    <span class="fills">${fills}</span>
    <span class="acts"><button class="btn small" data-toggle="${c.id}">${c.state === 'in_hand' ? 'Mark submitted' : 'Back to in hand'}</button>${rm}</span>
  </div>`;
}

function render() {
  const hand = state.cards.filter((c) => c.state === 'in_hand');
  const sub = state.cards.filter((c) => c.state === 'submitted');
  const slots = state.cards.reduce((n, c) => n + c.fills.length, 0);
  const f = state.form;
  const isSat = f.mode === 'SAT';
  const group = (title, hint, items) => `<div class="panel" style="display:flex;flex-direction:column;gap:10px">
    <div><div class="mono small" style="letter-spacing:.1em;font-weight:600">${title}</div><div class="muted small">${hint}</div></div>
    ${items.map(cardRow).join('') || '<div class="muted">None</div>'}</div>`;

  document.getElementById('main').innerHTML = `
    <div class="legend"><span class="tag card">${CARD_ICON}CARD</span> paper QSL in hand or submitted
      <span class="tag await">AWAITING</span> confirmed in LoTW, not yet credited <span class="muted">Both tags can appear on the same slot.</span></div>
    <div class="cols">
      <main>
        <section aria-labelledby="cards-h" style="display:flex;flex-direction:column;gap:16px">
          <div class="head"><h2 id="cards-h">Cards <span style="color:var(--card)">${state.cards.length}</span></h2>
            <div class="muted small">${hand.length} in hand · ${sub.length} submitted · ${slots} needed slot${slots === 1 ? '' : 's'} covered</div></div>
          ${group('IN HAND', 'Waiting until you have enough to submit', hand)}
          ${group('SUBMITTED', 'Sent to ARRL or checked, awaiting credit', sub)}
          <div class="muted small">A card clears itself when an import shows everything it covers credited. Cards are left out of the LoTW Account Status check, because LoTW doesn't know about paper cards.</div>
          <div id="listmsg" role="status"></div>
        </section>
      </main>
      <aside class="panel" aria-labelledby="add-h" style="gap:14px">
        <h2 id="add-h">Add a card</h2>
        <div><label class="muted small" for="f-ent">Entity</label>
          <input id="f-ent" class="txt" list="ents" value="${esc(f.ent)}" placeholder="Type a prefix or name" autocomplete="off">
          <datalist id="ents">${state.entities.map((e) => `<option value="${esc(entKey(e))}">`).join('')}</datalist></div>
        <div class="two" style="gap:12px">
          <div><label class="muted small" for="f-band">Band</label>
            <select id="f-band" style="width:100%"${isSat ? ' disabled' : ''}>${isSat ? '<option>— (satellite)</option>'
              : BANDS.map((b) => `<option value="${b}"${b === f.band ? ' selected' : ''}>${esc(label(b))}</option>`).join('')}</select></div>
          <div><label class="muted small" for="f-mode">Mode</label>
            <select id="f-mode" style="width:100%">${MODES.map(([v, t]) => `<option value="${v}"${v === f.mode ? ' selected' : ''}>${t}</option>`).join('')}</select></div>
        </div>
        <div class="two" style="gap:12px">
          <div><label class="muted small" for="f-call">Call worked (optional)</label><input id="f-call" class="txt" value="${esc(f.call)}" placeholder="e.g. 5Z4XX"></div>
          <div><label class="muted small" for="f-date">QSO date (optional)</label><input id="f-date" type="date" value="${esc(f.date)}"></div>
        </div>
        ${isSat ? '<div class="muted small">Satellite DXCC is a separate award: a satellite card counts toward Satellite only — not Mixed, a mode or a band — so no band is needed.</div>' : ''}
        <fieldset style="border:0;padding:0;margin:0;display:flex;gap:18px"><legend class="muted small" style="margin-bottom:6px">Status</legend>
          <label class="chk"><input type="radio" name="f-st" value="in_hand"${f.st === 'in_hand' ? ' checked' : ''}> In hand</label>
          <label class="chk"><input type="radio" name="f-st" value="submitted"${f.st === 'submitted' ? ' checked' : ''}> Submitted</label></fieldset>
        <div><label class="muted small" for="f-note">Note (optional)</label><input id="f-note" class="txt" value="${esc(f.note)}" placeholder="Bureau or direct, manager…"></div>
        <div id="pv" role="status" class="pv"></div>
        <button class="btn primary" id="add" disabled>Add card</button>
      </aside>
    </div>`;
  wire();
  preview();
}

let pvTimer = null;
function body() {
  const f = state.form, e = findEnt(f.ent);
  if (!e) return null;
  return { dxcc: e.dxcc, band: f.mode === 'SAT' ? null : f.band, mode: f.mode, state: f.st,
    call: f.call.trim().toUpperCase(), qso_date: f.date, note: f.note.trim() };
}

function preview() {
  clearTimeout(pvTimer);
  pvTimer = setTimeout(async () => {
    const pv = document.getElementById('pv'), add = document.getElementById('add');
    const b = body();
    if (!b) {
      pv.className = 'pv'; add.disabled = true;
      pv.innerHTML = state.form.ent ? '<div class="t">Pick an entity from the list</div>' : '<div class="muted">Choose the entity, band and mode to see what this card would fill.</div>';
      return;
    }
    try {
      const r = await postJSON('/api/paper/preview', b);
      add.disabled = !r.ok;
      if (!r.ok) { pv.className = 'pv bad'; pv.innerHTML = `<div class="t">Nothing new</div><div>${esc(r.message)}</div>`; }
      else if (!r.fills.length) { pv.className = 'pv'; pv.innerHTML = `<div class="t">Outside your profile</div><div>${esc(r.message)} It can still be saved.</div>`; }
      else {
        pv.className = 'pv ok';
        pv.innerHTML = `<div class="t">This card would fill</div><div>${r.fills.map(label).map(esc).join(' · ')}${r.fills[0] === 'MIXED' ? ' — a new entity' : ''}</div>`;
      }
    } catch (err) { pv.className = 'pv bad'; pv.innerHTML = `<div>${esc(err.message)}</div>`; add.disabled = true; }
  }, 150);
}

function wire() {
  const $ = (id) => document.getElementById(id);
  const f = state.form;
  const keep = (id, key, rerender) => { $(id).oninput = $(id).onchange = (e) => { f[key] = e.target.value; rerender ? render() : preview(); }; };
  keep('f-ent', 'ent'); keep('f-band', 'band'); keep('f-mode', 'mode', true);
  keep('f-call', 'call'); keep('f-date', 'date'); keep('f-note', 'note');
  document.querySelectorAll('input[name=f-st]').forEach((r) => (r.onchange = () => { f.st = r.value; }));
  $('add').onclick = async () => {
    try {
      await postJSON('/api/paper', body());
      Object.assign(f, { ent: '', call: '', date: '', note: '' });
      await load();
    } catch (err) { $('pv').className = 'pv bad'; $('pv').innerHTML = `<div>${esc(err.message)}</div>`; }
  };
  const msg = (t) => { $('listmsg').innerHTML = `<span class="err small">${esc(t)}</span>`; };
  document.querySelectorAll('[data-toggle]').forEach((b) => (b.onclick = async () => {
    const c = state.cards.find((x) => x.id === +b.dataset.toggle);
    try {
      await api(`/api/paper/${c.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: c.state === 'in_hand' ? 'submitted' : 'in_hand', note: c.note }) });
      await load();
    } catch (err) { msg(err.message); }
  }));
  document.querySelectorAll('[data-rm]').forEach((b) => (b.onclick = () => { state.removing = +b.dataset.rm; render(); }));
  document.querySelectorAll('[data-rm-no]').forEach((b) => (b.onclick = () => { state.removing = null; render(); }));
  document.querySelectorAll('[data-rm-yes]').forEach((b) => (b.onclick = async () => {
    try { await api(`/api/paper/${b.dataset.rmYes}`, { method: 'DELETE' }); state.removing = null; await load(); }
    catch (err) { msg(err.message); }
  }));
}

async function load() {
  try {
    const [mx, cards] = await Promise.all([api('/api/view/matrix'), api('/api/paper')]);
    if (mx.no_data) {
      renderChrome({ title: 'Paper QSLs', subtitle: 'No matrix imported yet' });
      document.getElementById('main').innerHTML = NO_DATA_HTML;
      return;
    }
    state.entities = mx.entities.slice().sort((a, b) => a.name.localeCompare(b.name));
    state.cards = cards.cards;
    renderChrome({ title: 'Paper QSL cards',
      subtitle: 'Cards you hold or have submitted that ARRL hasn\'t credited yet · never counted as credits' });
    render();
  } catch (err) {
    renderChrome({ title: 'Paper QSL cards' });
    showError('main', err);
  }
}
load();
