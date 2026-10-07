// Settings: operating profile, Club Log Most Wanted, LoTW Account Status check.
'use strict';

const BANDS = ['160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M', '2M'];
const MODES = ['CW', 'PHONE', 'DIGITAL', 'SAT'];
const DEFAULT = { bands: BANDS.slice(0, 10), modes: ['CW', 'PHONE', 'DIGITAL'] };
const state = { mx: null, saved: null, draft: null, check: null, mwMsg: '', profMsg: '', asMsg: '' };

// Missing count per category, independent of the profile: band/mode slots on
// Mixed-credited entities; Satellite across every current entity (a separate award).
function missingCounts() {
  const out = {};
  const ents = state.mx.entities;
  for (const c of BANDS.concat(MODES)) {
    out[c] = c === 'SAT'
      ? ents.filter((e) => !e.credited.includes('SAT')).length
      : ents.filter((e) => e.credited.includes('MIXED') && !e.credited.includes(c)).length;
  }
  return out;
}

const same = (a, b) => a.bands.join() === b.bands.join() && a.modes.join() === b.modes.join();

function profileSection() {
  const n = missingCounts(), d = state.draft;
  const box = (c, on, group) => `<label><input type="checkbox" data-${group}="${c}"${on ? ' checked' : ''}>
    <span>${esc(label(c))}</span><span class="cnt">${n[c]} missing</span></label>`;
  const slots = d.bands.concat(d.modes.filter((m) => m !== 'SAT')).reduce((t, c) => t + n[c], 0);
  const dirty = !same(d, state.saved);
  return `<section class="panel" aria-labelledby="prof-h" style="display:flex;flex-direction:column;gap:18px">
    <div><h2 id="prof-h">Operating profile</h2>
      <div class="muted small">What counts as “needed” in every view and export</div></div>
    <fieldset class="plain"><legend>BANDS</legend><div class="checks">${BANDS.map((b) => box(b, d.bands.includes(b), 'band')).join('')}</div></fieldset>
    <fieldset class="plain"><legend>MODES</legend><div class="checks">${MODES.map((m) => box(m, d.modes.includes(m), 'mode')).join('')}</div></fieldset>
    <div style="display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap">
      <div><div><span class="mono" style="font-size:22px;font-weight:700">${num(slots)}</span> missing band and mode slots with this profile${d.modes.includes('SAT') ? ` · plus ${n.SAT} for Satellite` : ''}</div>
        <div class="muted small" style="max-width:720px">Mixed (new entities) is always tracked. 2 m and Satellite are off by default; tick them if you chase them. Satellite DXCC is a separate award, so its count covers every entity. Changing the profile recalculates every view; nothing is re-imported. 70 cm can't be tracked: LoTW's matrix has no 70 cm column.</div></div>
      <div style="display:flex;gap:10px;align-items:center">
        <span class="small ${dirty ? 'err' : 'muted'}" role="status">${dirty ? 'Not saved' : state.profMsg}</span>
        <button class="btn" id="reset">Reset to 160–6 m</button>
        <button class="btn primary" id="saveprof"${dirty ? '' : ' disabled'}>Save profile</button>
      </div>
    </div>
  </section>`;
}

function clubLogSection() {
  const ranked = state.mx.entities.filter((e) => e.mw_rank != null);
  const top = ranked.find((e) => e.mw_rank === 1);
  const fetched = state.mwFetched;
  return `<section class="panel" aria-labelledby="cl-h" style="display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap">
    <div><h2 id="cl-h">Club Log Most Wanted</h2>
      <div class="muted small">Used for the <strong>Easiest first</strong> and <strong>Rarest first</strong> sorts. Public list; no Club Log account is used.</div>
      <div class="small" style="margin-top:6px">${fetched ? `Rankings from <span class="mono">${esc(when(fetched))}</span> · ${ranked.length} entities${top ? ` · #1 ${esc(top.name)}` : ''}` : 'Not fetched yet.'}</div>
      <div class="small" role="status">${state.mwMsg}</div></div>
    <button class="btn" id="mw">Refresh rankings</button>
  </section>`;
}

function checkResult(r) {
  if (!r || r.none) return '';
  const bad = r.reconciliation.filter((x) => !x.ok);
  const okIcon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#5fd39a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  const warnIcon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f5a524" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>';
  const stale = r.is_current_import === false ? '<div class="err small">This check was made against an earlier import. Paste a fresh Account Status table to check the current data.</div>' : '';
  const recon = bad.length
    ? `<div class="notice bad" role="alert"><div><div class="t">${bad.length} categor${bad.length === 1 ? 'y does' : 'ies do'} not match LoTW</div>
        <ul>${bad.map((x) => `<li>${esc(x.label)}: this app counts ${x.app}, LoTW shows ${x.lotw} credits awarded.</li>`).join('')}</ul>
        <div class="muted">Usually the matrix and the Account Status table came from different days. Paste both from the same LoTW session.</div></div></div>`
    : `<div class="notice ok">${okIcon}<div><div class="t">Credits match LoTW in all ${r.reconciliation.length} categories</div><div class="muted small">Checked ${esc(when(r.checked_at))}</div></div></div>`;
  const pend = r.pending.filter((x) => !x.ok);
  const marked = r.pending.reduce((t, x) => t + x.app, 0), lotw = r.pending.reduce((t, x) => t + x.lotw, 0);
  const pending = pend.length
    ? `<div class="notice held" role="alert">${warnIcon}<div style="display:flex;flex-direction:column;gap:6px">
        ${pend.map((x) => `<div><span class="t">${esc(x.label)}: LoTW shows ${x.lotw} pending, you have marked ${x.app}.</span>
          <span class="muted">${x.lotw > x.app ? 'A confirmation is missing a mark: open LoTW\'s pending list for this category and mark the slot.'
            : 'You have an extra mark: it may be for a QSO not yet confirmed in LoTW, or one LoTW has already processed.'}</span></div>`).join('')}
        <div class="muted"><a href="/slots">Go to Missing Band Slots</a> to add or clear marks.</div></div></div>`
    : `<div class="notice ok">${okIcon}<div class="t">Your pending marks match LoTW (${marked} marked · ${lotw} new or in process)</div></div>`;
  return `${stale}${recon}
    <div class="recon">${r.reconciliation.map((x) => `<div><span>${esc(x.label)}</span><span class="${x.ok ? '' : 'down'}">${x.app} ${x.ok ? '<span class="muted">= LoTW</span>' : '≠ ' + x.lotw}</span></div>`).join('')}</div>
    ${pending}
    ${r.not_checked.length ? `<div class="muted small">Not checked: ${r.not_checked.map((c) => esc(c === 'SAT' ? 'Satellite (not listed by LoTW)' : c === 'CHALLENGE' ? 'Challenge' : c === '70CM' ? '70 cm (no matrix column)' : c)).join(' · ')}. Paper cards are never part of this check.</div>` : ''}`;
}

function statusSection() {
  return `<section class="panel" aria-labelledby="as-h" style="display:flex;flex-direction:column;gap:14px">
    <div><h2 id="as-h">Check against LoTW Account Status</h2>
      <div class="muted small">Optional. Copy the <strong>Account Status</strong> table from LoTW's DXCC page and paste it here. The app checks its credit counts against “DXCC Credits Awarded”, and your pending marks against “New LoTW QSLs” plus “LoTW QSLs in Process”.</div></div>
    <label for="as-box" class="mono small muted" style="letter-spacing:.1em">ACCOUNT STATUS TABLE</label>
    <textarea id="as-box" rows="5" spellcheck="false" style="min-height:120px" placeholder="Award&#9;New LoTW QSLs&#9;LoTW QSLs in Process&#9;DXCC Credits Awarded&#9;Total&#10;Mixed *&#9;…"></textarea>
    <div style="display:flex;gap:12px;align-items:center"><button class="btn primary" id="check">Check</button><span class="small" role="status">${state.asMsg}</span></div>
    <div id="result" style="display:flex;flex-direction:column;gap:12px">${checkResult(state.check)}</div>
  </section>`;
}

function render() {
  const box = document.getElementById('as-box');
  const text = box ? box.value : '';
  document.getElementById('main').innerHTML = profileSection() + clubLogSection() + statusSection();
  document.getElementById('as-box').value = text;
  wire();
}

function wire() {
  const $ = (id) => document.getElementById(id);
  const d = state.draft;
  const toggle = (list, c, on) => { const s = new Set(list); on ? s.add(c) : s.delete(c); return [...s]; };
  document.querySelectorAll('[data-band]').forEach((b) => (b.onchange = () => {
    d.bands = BANDS.filter((x) => toggle(d.bands, b.dataset.band, b.checked).includes(x)); state.profMsg = ''; render();
  }));
  document.querySelectorAll('[data-mode]').forEach((b) => (b.onchange = () => {
    d.modes = MODES.filter((x) => toggle(d.modes, b.dataset.mode, b.checked).includes(x)); state.profMsg = ''; render();
  }));
  $('reset').onclick = () => { state.draft = { bands: DEFAULT.bands.slice(), modes: DEFAULT.modes.slice() }; render(); };
  $('saveprof').onclick = async () => {
    try {
      const p = await api('/api/settings/profile', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state.draft) });
      state.saved = { bands: p.bands, modes: p.modes }; state.draft = { bands: p.bands.slice(), modes: p.modes.slice() };
      state.profMsg = '<span class="up">Saved — every view now uses this profile.</span>';
      renderChrome({ title: 'Settings', subtitle: esc(profileText(state.saved)) });
      render();
    } catch (err) { state.profMsg = `<span class="err">${esc(err.message)}</span>`; render(); }
  };
  $('mw').onclick = async () => {
    state.mwMsg = 'Fetching from Club Log…'; render();
    try {
      const r = await postJSON('/api/clublog/refresh');
      state.mwMsg = `<span class="up">Updated: ${r.entities_ranked} entities ranked.</span>`;
      await loadData(); render();
    } catch (err) { state.mwMsg = `<span class="err">${esc(err.message)}</span>`; render(); }
  };
  $('check').onclick = async () => {
    const text = $('as-box').value;
    if (!text.trim()) { state.asMsg = '<span class="err">Paste the Account Status table first.</span>'; render(); return; }
    state.asMsg = 'Checking…'; render();
    try {
      const r = await postJSON('/api/status-check', { text });
      state.check = Object.assign(r, { checked_at: new Date().toISOString(), is_current_import: true });
      state.asMsg = ''; $('as-box').value = ''; render();
    } catch (err) { state.asMsg = `<span class="err">${esc(err.message)}</span>`; render(); }
  };
}

async function loadData() {
  const [mx, prof, status, check] = await Promise.all([api('/api/view/matrix'), api('/api/settings/profile'),
    api('/api/status'), api('/api/status-check/latest')]);
  state.mx = mx.no_data ? { entities: [] } : mx;
  state.saved = { bands: prof.bands, modes: prof.modes };
  if (!state.draft) state.draft = { bands: prof.bands.slice(), modes: prof.modes.slice() };
  state.mwFetched = status.most_wanted_fetched_at;
  state.check = check;
  state.noData = !!mx.no_data;
}

async function load() {
  try {
    await loadData();
    renderChrome({ title: 'Settings', subtitle: esc(profileText(state.saved)) });
    render();
    if (state.noData) {
      document.getElementById('main').insertAdjacentHTML('afterbegin',
        '<div class="notice held"><div><div class="t">No matrix imported yet</div><div>The missing counts appear after your first import. <a href="/import">Import now</a></div></div></div>');
    }
  } catch (err) {
    renderChrome({ title: 'Settings' });
    showError('main', err);
  }
}
load();
