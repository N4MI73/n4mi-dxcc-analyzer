// Import: paste or upload -> Check -> preview -> Save (or Save anyway for a
// held import). Nothing is saved before Save. Import history on the right.
'use strict';

const ORDER = ['MIXED', 'CW', 'PHONE', 'DIGITAL', 'SAT', '160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M', '2M'];
const state = { preview: null, current: null, history: [], confirmed: false, deleting: null };

const ICON = {
  ok: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#5fd39a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
  held: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#f5a524" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  bad: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ff8f82" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>',
};

function inputForm() {
  return `<section class="panel" aria-labelledby="paste-h" style="display:flex;flex-direction:column;gap:18px;padding:24px">
    <h2 id="paste-h">Paste from LoTW</h2>
    <ol class="steps">
      <li>In LoTW, open <strong>Awards › DXCC › Award Credit Matrix</strong>.</li>
      <li>Select the whole table, from <span class="mono small">DXCC Award Credit Report</span> down to the last row, and copy it.</li>
      <li>Paste it below and press <strong>Check paste</strong>. Nothing is saved until you press Save.</li>
    </ol>
    <label for="paste-box" class="mono small muted" style="letter-spacing:.1em">MATRIX TEXT</label>
    <textarea id="paste-box" rows="10" spellcheck="false" placeholder="DXCC Award Credit Report&#10;Your Name, CALLSIGN&#10;Prefix&#10;…"></textarea>
    <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
      <button type="button" class="btn primary" id="check">Check paste</button>
      <span class="muted">or</span>
      <label class="btn" for="upload" style="gap:10px">Upload a file <span class="muted small">.txt · .csv · .xlsx</span></label>
      <input id="upload" type="file" accept=".txt,.tsv,.csv,.xlsx" style="position:absolute;width:1px;height:1px;opacity:0">
      <span id="busy" class="muted" role="status"></span>
    </div>
  </section>`;
}

function notice(p) {
  if (p.status === 'clean') {
    return `<div class="notice ok" role="status">${ICON.ok}<div><div class="t">Ready to save</div>
      <div>${p.rows_read} rows read${p.callsign ? ' · callsign ' + esc(p.callsign) : ''} · no warnings</div></div></div>`;
  }
  if (p.status === 'held') {
    return `<div class="notice held" role="alert">${ICON.held}<div style="display:flex;flex-direction:column;gap:8px">
      <div class="t">Held for review — ${p.warnings.length} warning${p.warnings.length === 1 ? '' : 's'}</div>
      <ul>${p.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>
      <div class="muted">Credits normally only go up, so this usually means part of the table didn't copy. Copy it again from LoTW. Save anyway only if LoTW really removed a credit.</div></div></div>`;
  }
  return `<div class="notice bad" role="alert">${ICON.bad}<div style="display:flex;flex-direction:column;gap:8px">
    <div class="t">Not imported — nothing was changed</div>
    <ul>${p.errors.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>
    <div class="muted">Copy the whole table again from LoTW and paste it fresh.${state.current ? ` Your current data from ${esc(when(state.current.saved_at))} is still in use.` : ''}</div></div></div>`;
}

function detail(p) {
  const before = state.current ? state.current.totals : {};
  const rows = ORDER.map((c) => {
    const a = before[c] ?? 0, b = p.totals[c] ?? 0, dlt = b - a;
    const cls = dlt > 0 ? 'up' : dlt < 0 ? 'down' : 'off';
    return `<tr><td>${esc(label(c))}</td><td class="muted">${state.current ? a : '—'}</td><td>${b}</td>
      <td class="${cls}">${state.current ? (dlt > 0 ? '+' + dlt : dlt < 0 ? dlt : '·') : ''}</td></tr>`;
  }).join('');
  const ch = p.changes;
  const bySlot = {};
  ch.new_slots.forEach((x) => { bySlot[x.category] = (bySlot[x.category] || 0) + 1; });
  const slotTxt = Object.keys(bySlot).length
    ? ORDER.filter((c) => bySlot[c]).map((c) => `${esc(label(c))} +${bySlot[c]}`).join(' · ') : 'None.';
  const first = !state.current;
  const marks = [p.marks_to_clear && `${p.marks_to_clear} pending mark${p.marks_to_clear === 1 ? '' : 's'} will clear (now credited)`,
    p.cards_to_credit && `${p.cards_to_credit} paper card${p.cards_to_credit === 1 ? '' : 's'} will be marked credited`]
    .filter(Boolean).join(' · ') || 'No pending marks or paper cards are affected.';
  return `<div class="two">
    <div class="panel" style="display:flex;flex-direction:column;gap:10px">
      <div class="mono small muted" style="letter-spacing:.1em">CREDITS · CURRENT → THIS PASTE</div>
      <table class="tot"><thead><tr><th>Category</th><th>Now</th><th>Paste</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    </div>
    <div class="panel" style="display:flex;flex-direction:column;gap:14px">
      <div class="mono small muted" style="letter-spacing:.1em">WHAT CHANGES IN YOUR PROFILE</div>
      ${first ? '<div class="muted">First import — everything is new.</div>' : `
      <div><div style="font-weight:600">New entities (${ch.new_entities.length})</div>
        ${ch.new_entities.map((e) => `<div>${esc(e.name)}</div>`).join('') || '<div class="muted">None.</div>'}</div>
      <div><div style="font-weight:600">New band and mode slots (${ch.new_slots.length})</div><div class="muted">${slotTxt}</div></div>
      ${ch.lost.length ? `<div><div class="down">Lost (${ch.lost.length})</div>
        <div class="muted">${ch.lost.map((x) => `${esc(x.name)} — ${esc(label(x.category))}`).join('<br>')}</div></div>` : ''}`}
      <div style="border-top:1px solid var(--line);padding-top:12px" class="muted">${marks}</div>
    </div></div>`;
}

function previewView(p) {
  if (p.status === 'rejected') {
    return `${notice(p)}<div><button class="btn" id="back">Paste again</button></div>`;
  }
  const held = p.status === 'held';
  return `<section aria-labelledby="prev-h" style="display:flex;flex-direction:column;gap:20px">
    <h2 id="prev-h">Check before saving</h2>
    ${notice(p)}${detail(p)}
    ${held ? `<label class="chk"><input type="checkbox" id="confirm"${state.confirmed ? ' checked' : ''}> I checked LoTW, and this drop is real.</label>` : ''}
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      ${held ? `<button class="btn primary" id="save"${state.confirmed ? '' : ' disabled'}>Save anyway</button>`
             : '<button class="btn primary" id="save">Save</button>'}
      <button class="btn" id="back">Discard and start over</button>
      <span id="busy" class="muted" role="status"></span>
    </div></section>`;
}

function savedView(r, p) {
  const ch = p.changes;
  const bits = [`Mixed ${p.totals.MIXED}`];
  if (!state.firstSave) bits.push(`${ch.new_entities.length} new entit${ch.new_entities.length === 1 ? 'y' : 'ies'}`,
    `${ch.new_slots.length} new band and mode slots`);
  if (r.marks_cleared) bits.push(`${r.marks_cleared} pending mark${r.marks_cleared === 1 ? '' : 's'} cleared`);
  if (r.cards_credited) bits.push(`${r.cards_credited} paper card${r.cards_credited === 1 ? '' : 's'} credited`);
  return `<section class="panel" role="status" style="border-color:var(--green);display:flex;flex-direction:column;gap:12px;padding:24px">
    <h2 style="color:var(--green-text)">Saved — this is now your current data</h2>
    <div class="muted">${bits.join(' · ')}.${state.firstSave ? '' : ' The previous import stays in the history if you need to roll back.'}</div>
    <div style="display:flex;gap:12px;flex-wrap:wrap"><a class="btn primary" href="/">View missing entities</a>
      <button class="btn" id="back">Import another</button></div></section>`;
}

function historyView() {
  const items = state.history.map((h) => {
    const t = h.totals || {};
    const detail = `${esc(h.source === 'paste' ? 'Pasted' : h.source)} · Mixed ${t.MIXED ?? '—'}${h.callsign ? ' · ' + esc(h.callsign) : ''}`;
    const canAct = h.status === 'previous';
    const conf = state.deleting === h.id;
    return `<div class="hist">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">
        <span class="mono small" style="font-weight:600">${esc(when(h.saved_at || h.imported_at))}</span>
        <span class="badge ${h.status}">${h.status === 'preview' ? 'NOT SAVED' : h.status.toUpperCase()}</span></div>
      <div class="muted small">${detail}</div>
      ${canAct ? `<div style="display:flex;gap:8px">
        <button class="btn small" data-restore="${h.id}">Make current</button>
        ${conf ? `<button class="btn small" data-delete-yes="${h.id}" style="border-color:var(--red);color:var(--red-text)">Confirm delete</button>
                  <button class="btn quiet small" data-delete-no="1">Keep</button>`
               : `<button class="btn quiet small" data-delete="${h.id}">Delete</button>`}</div>` : ''}
    </div>`;
  }).join('');
  return `<aside class="panel" aria-labelledby="hist-h"><h2 id="hist-h" style="font-size:16px">Import history</h2>
    ${items || '<div class="muted small">No imports yet.</div>'}
    <div class="muted small">Rolling back does not bring back pending marks that a later import cleared.</div>
    <div id="histmsg" role="status"></div></aside>`;
}

function render(mainHtml) {
  document.getElementById('main').innerHTML = `<div class="cols"><main>${mainHtml}</main>${historyView()}</div>`;
  wire();
}

function showInput() { state.preview = null; state.confirmed = false; render(inputForm()); }

async function runPreview(form) {
  const busy = document.getElementById('busy');
  busy.textContent = 'Checking…';
  try {
    const p = await api('/api/import/preview', { method: 'POST', body: form });
    state.preview = p; state.confirmed = false;
    await loadHistory();
    render(previewView(p));
  } catch (err) {
    busy.innerHTML = `<span class="err">${esc(err.message)}</span>`;
  }
}

async function save() {
  const p = state.preview;
  const busy = document.getElementById('busy');
  busy.textContent = 'Saving…';
  try {
    state.firstSave = !state.current;
    const r = await postJSON(`/api/import/${p.id}/save`, { save_anyway: p.status === 'held' && state.confirmed });
    state.preview = null;            // saved: nothing left to discard
    await loadHistory();
    render(savedView(r, p));
  } catch (err) {
    busy.innerHTML = `<span class="err">${esc(err.message)}</span>`;
  }
}

function wire() {
  const $ = (id) => document.getElementById(id);
  if ($('check')) $('check').onclick = () => {
    const text = $('paste-box').value;
    if (!text.trim()) { $('busy').innerHTML = '<span class="err">Paste the matrix first.</span>'; return; }
    const f = new FormData(); f.append('text', text); runPreview(f);
  };
  if ($('upload')) $('upload').onchange = (e) => {
    const file = e.target.files[0]; if (!file) return;
    const f = new FormData(); f.append('file', file); runPreview(f);
  };
  if ($('confirm')) $('confirm').onchange = (e) => { state.confirmed = e.target.checked; $('save').disabled = !state.confirmed; };
  if ($('save')) $('save').onclick = save;
  if ($('back')) $('back').onclick = async () => {
    if (state.preview && state.preview.id) {
      try { await postJSON(`/api/import/${state.preview.id}/discard`); } catch (e) { /* already gone */ }
    }
    await loadHistory(); showInput();
  };
  const msg = (t) => { $('histmsg').innerHTML = t; };
  document.querySelectorAll('[data-restore]').forEach((b) => (b.onclick = async () => {
    try {
      const r = await postJSON(`/api/snapshots/${b.dataset.restore}/make-current`);
      await loadHistory(); showInput();
      msg(`<span class="up small">Rolled back.${r.marks_cleared ? ` ${r.marks_cleared} marks cleared.` : ''}</span>`);
    } catch (err) { msg(`<span class="err small">${esc(err.message)}</span>`); }
  }));
  document.querySelectorAll('[data-delete]').forEach((b) => (b.onclick = () => { state.deleting = +b.dataset.delete; rerender(); }));
  document.querySelectorAll('[data-delete-no]').forEach((b) => (b.onclick = () => { state.deleting = null; rerender(); }));
  document.querySelectorAll('[data-delete-yes]').forEach((b) => (b.onclick = async () => {
    try { await api(`/api/snapshots/${b.dataset.deleteYes}`, { method: 'DELETE' }); state.deleting = null; await loadHistory(); rerender(); }
    catch (err) { msg(`<span class="err small">${esc(err.message)}</span>`); }
  }));
}

// Re-draw the history without losing what is in the paste box.
function rerender() {
  const box = document.getElementById('paste-box');
  const text = box ? box.value : null;
  state.preview ? render(previewView(state.preview)) : render(inputForm());
  if (text !== null && document.getElementById('paste-box')) document.getElementById('paste-box').value = text;
}

async function loadHistory() {
  const h = await api('/api/snapshots');
  state.history = h.snapshots.filter((s) => s.status !== 'preview' && s.status !== 'held' || (state.preview && s.id === state.preview.id));
  state.current = h.snapshots.find((s) => s.status === 'current') || null;
}

async function load() {
  try {
    const [, prof] = await Promise.all([loadHistory(), api('/api/settings/profile')]);
    renderChrome({
      title: 'Import the Award Credit Matrix',
      subtitle: (state.current ? `Current data: matrix imported ${esc(when(state.current.saved_at))}` : 'No data yet')
        + ` · ${esc(profileText(prof))}`,
    });
    showInput();
  } catch (err) {
    renderChrome({ title: 'Import the Award Credit Matrix' });
    showError('main', err);
  }
}
load();
