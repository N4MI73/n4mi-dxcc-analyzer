// Entity report (D61): everything the app knows about one current entity.
// Opened from the header search as /entity#<DXCC number>. The number is read
// here, after the "#", so the page route itself takes no parameters.
'use strict';

const CONT = Object.fromEntries(CONTINENTS.map(([c, n]) => [c, n.charAt(0) + n.slice(1).toLowerCase()
  .replace(/ (\w)/g, (m, ch) => ' ' + ch.toUpperCase())]));
const STATUS_TEXT = { credited: 'Credited', needed: 'Needed', awaiting: 'Awaiting credit',
  card: 'Paper card', wont_submit: "Won't submit" };
const CELL = { credited: 'done', needed: 'need', awaiting: 'await', card: 'card', wont_submit: 'wont' };
const MODE_CATS = ['MIXED', 'CW', 'PHONE', 'DIGITAL', 'SAT'];
let report = null;
let dxChecked = false;
let keepHeader = false;      // redraw only the report, not the header (keeps a search in progress)

const day = (iso) => (iso ? when(iso).slice(0, 10) : '');
const dxcc = () => { const m = /^#(\d{1,4})$/.exec(location.hash); return m ? Number(m[1]) : null; };

function emptyPage(title, msg) {
  renderChrome({ title, subtitle: 'Use the search box above to find an entity by name, prefix or DXCC number.' });
  document.getElementById('main').innerHTML = msg
    ? `<div class="notice bad" role="alert"><div><div class="t">Not found</div><div>${esc(msg)}</div></div></div>` : '';
}

async function load() {
  const d = dxcc();
  const keep = keepHeader;
  keepHeader = false;                // used once, whatever happens below
  if (d === null) { emptyPage('Entity report'); return; }
  let r;
  try {
    r = await api(`/api/entity/${d}`);
  } catch (err) {
    if (dxcc() === d) emptyPage('Entity report', err.message);
    return;
  }
  if (dxcc() !== d) return;          // another entity was chosen meanwhile
  const same = report && report.dxcc === d;
  report = r;
  render(same && keep);
  refreshDXMon();
}

// DX Monitor is read from the stored copy so the page never waits on it. If
// that copy is old, refresh it once in the background and redraw.
async function refreshDXMon() {
  if (dxChecked || !report.dxmon || !report.dxmon.enabled) return;
  dxChecked = true;
  try {
    const dx = await api('/api/dxmon');
    if (dx.tried_at && dx.tried_at !== report.dxmon.tried_at) {
      const d = report.dxcc;
      const r = await api(`/api/entity/${d}`);
      if (dxcc() === d) { report = r; render(true); }
    }
  } catch (e) { /* keep showing the stored copy */ }
}

function suggestionFor(cat) {
  const s = report.suggestion;
  if (!s) return '';
  if (s.list === 'entities' && cat === 'MIXED') return `In Suggestions: entity #${s.rank}`;
  if (s.list === 'slots' && (s.bands.includes(label(cat)) || s.modes.includes(label(cat)))) return `In Suggestions: band slot #${s.rank}`;
  return '';
}

function detail(r) {
  const extra = slotTags({ marks: report.marks, cards: report.cards_by_slot }, r.category);
  const note = r.mark && r.mark.note ? `"${esc(r.mark.note)}"` : '';
  switch (r.status) {
    case 'credited': return r.since ? `since the ${esc(day(r.since))} import` : 'credited';
    case 'awaiting': return (note || 'Confirmed in LoTW, not yet credited') + (r.cards.length ? ` ${extra}` : '');
    case 'card': {
      const sub = r.cards.some((c) => c.state === 'submitted');
      return `${sub ? 'Submitted' : 'In hand'} · see Paper cards`;
    }
    case 'wont_submit': return [note, esc(suggestionFor(r.category))].filter(Boolean).join(' · ') || 'Still needed: this confirmation won\'t be submitted';
    default: return esc(suggestionFor(r.category));
  }
}

function statusRow(r) {
  const cls = r.status === 'needed' ? ' class="amber"' : '';
  const txt = r.status === 'needed' ? `<b>${STATUS_TEXT[r.status]}</b>` : STATUS_TEXT[r.status];
  // Any slot not yet credited opens the mark menu with that slot ticked.
  const cell = r.status === 'credited'
    ? `<span class="cell done" aria-hidden="true"></span>`
    : `<button class="cell ${CELL[r.status]}" data-mark="${r.category}" aria-label="Mark ${esc(r.label)}" title="Mark this slot"></button>`;
  return `<tr><td class="mono">${esc(r.label)}</td><td><span class="stc">${cell}<span${cls}>${txt}</span></span></td><td class="muted">${detail(r)}</td></tr>`;
}

function namesPanel() {
  const r = report;
  const adifDiffers = r.adif_name && r.adif_name.toLowerCase() !== r.name.toLowerCase();
  return `<div class="panel"><div class="head"><h2>Names</h2></div><dl class="kv">
    <dt>HamAlert / DX Monitor</dt><dd><b>${esc(r.name)}</b> <button class="btn small" id="copyname">Copy</button><span id="copied" class="small muted" role="status"></span></dd>
    <dt>LoTW</dt><dd class="mono small">${esc(r.lotw_name)}</dd>
    ${adifDiffers ? `<dt>ADIF</dt><dd class="small">${esc(r.adif_name)}</dd>` : ''}
    <dt>DXCC</dt><dd class="mono small">${r.dxcc} · current</dd></dl></div>`;
}

function dxPanel() {
  const dx = report.dxmon || { enabled: false };
  const s = report.suggestion;
  let sug = '<div class="muted">Not in the current Suggestions</div>';
  const beyond = s && !s.shown ? ` <span class="muted">· beyond your top ${s.top}</span>` : '';
  if (s && s.list === 'entities') sug = `<div>Entity #${s.rank}${beyond}</div>`;
  if (s && s.list === 'slots') {
    const b = s.dxmon_bands.map((x) => `<span class="chip">${esc(x)}</span>`).join(' ') || '<span class="chip any">any band</span>';
    const m = s.dxmon_modes.map((x) => `<span class="chip">${esc(x)}</span>`).join(' ') || '<span class="chip any">any mode</span>';
    sug = `<div>Band slot #${s.rank}${beyond}</div><div>${b} with ${m} · worth ${s.credits} credit${s.credits > 1 ? 's' : ''} a contact</div>`;
  }
  const sugRow = `<dt>Suggestions</dt><dd class="stack">${sug}<a class="small" href="/advisor">Open Suggestions</a></dd>`;
  if (!dx.enabled) return `<div class="panel"><div class="head"><h2>Suggestions</h2></div><dl class="kv">${sugRow}</dl></div>`;
  let rows = '';
  if (!dx.fetched_at) {
    rows = `<dt>Status</dt><dd class="muted">${dx.error ? esc(dx.error) : 'Not fetched yet'}</dd>`;
  } else {
    const ex = (dx.dxpeditions || []).map((x) => {
      const tag = x.kind === 'air' ? `<span class="tag air">ON AIR · ${esc(x.callsign)}</span> until ${esc(x.end)}`
        : `<span class="tag soon">${esc(x.begin)} · ${esc(x.callsign)}</span> to ${esc(x.end)}${x.kind === 'later' ? ' <span class="muted">(more than 30 days away)</span>' : ''}`;
      return `<div>${tag} · ${x.watched ? 'watched' : '<span class="nwtext">not watched</span>'}</div>`;
    }).join('') || '<span class="muted">None listed</span>';
    const nd = dx.needed_state === 'not_fetched' ? '<span class="muted">Not fetched yet</span>'
      : dx.needed === null || dx.needed === undefined ? '<span class="muted">Couldn\'t read DX Monitor\'s Needed list</span>'
      : (dx.needed_state === 'stale' ? '<span class="muted small">From an earlier read; the latest one failed</span>' : '')
        + (dx.needed.length ? dx.needed.map((n) => `<div><span class="tag indx">IN DX MONITOR</span> ${esc(n.bands.join(', ') || 'any band')} · ${esc(n.modes.join(', ') || 'any mode')}</div>`).join('')
        : '<span class="muted">No entry for this entity</span>');
    rows = `<dt>DXpedition</dt><dd class="stack">${ex}</dd><dt>Needed list</dt><dd class="stack">${nd}</dd>`;
  }
  const stale = dx.enabled && dx.fetched_at && !dx.ok;
  return `<div class="panel"><div class="head"><h2>DX Monitor</h2><span class="small ${stale ? 'amber' : 'muted'}">${dx.fetched_at ? `${stale ? 'last good list' : 'checked'} ${esc(when(dx.fetched_at).slice(11))}` : ''}</span></div>
    <dl class="kv">${rows}${sugRow}</dl></div>`;
}

function cardsPanel() {
  const cards = report.paper_cards;
  const body = cards.length ? `<table class="st"><tr><th>QSO</th><th>Call · date</th><th>State</th></tr>${cards.map((c) => `<tr>
      <td class="mono">${c.band ? esc(label(c.band)) + ' · ' : ''}${esc(label(c.mode))}</td>
      <td class="small">${esc([c.call, c.qso_date].filter(Boolean).join(' · ') || '—')}</td>
      <td><span class="tag card">${CARD_ICON}${c.state === 'submitted' ? 'Submitted' : 'In hand'}</span></td></tr>
      <tr class="sub"><td colspan="3" class="small muted">${c.fills.length ? `Covers ${c.fills.map(label).map(esc).join(', ')}` : 'Adds credit only outside your profile'}${c.note ? ` · ${esc(c.note)}` : ''}</td></tr>`).join('')}</table>`
    : '<p class="muted small" style="margin:12px 0 0">No paper cards for this entity.</p>';
  return `<div class="panel"><div class="head"><h2>Paper cards</h2><span class="small muted">${cards.length}</span></div>${body}
    <p class="small" style="margin:10px 0 0"><a href="/paper#${report.dxcc}">Add a paper card</a></p></div>`;
}

function historyPanel() {
  const h = report.history;
  const items = h.map((x) => `<li><span class="mono">${esc(day(x.at))}</span>${x.gained.length ? esc(x.gained.map(label).join(', ')) : ''}${x.first ? ' <span class="muted">(first import)</span>' : ''}${x.earliest ? ' <span class="muted">(earliest import kept)</span>' : ''}${x.lost.length ? ` <span class="err">removed: ${esc(x.lost.map(label).join(', '))}</span>` : ''}</li>`).join('');
  return `<div class="panel"><div class="head"><h2>Credit history</h2></div>${items ? `<ul class="hist">${items}</ul>` : '<p class="muted small" style="margin:12px 0 0">No credits yet.</p>'}</div>`;
}

function render(mainOnly) {
  const r = report;
  const sub = [r.prefix, `DXCC ${r.dxcc}`, CONT[r.continent] || r.continent, r.cq_zone ? `CQ zone ${r.cq_zone}` : '',
    r.mw_rank ? `Club Log Most Wanted #${r.mw_rank}` : ''].filter(Boolean).map(esc).join(' · ');
  const actions = r.no_data ? '' : `<a class="btn" href="/paper#${r.dxcc}">Add paper card</a>
    <button class="btn primary" id="markbtn">Mark slots…</button><button class="btn quiet" onclick="window.print()">Print</button>`;
  if (!mainOnly) renderChrome({ title: r.name, actions,
    subtitle: `${r.new ? '<span class="tag new">NEW</span> never confirmed · ' : ''}${sub}${r.no_data ? '' : ` · data from the ${esc(day(r.saved_at || r.imported_at))} import`}` });
  document.title = `${r.name} · N4MI DXCC Analyzer`;
  const main = document.getElementById('main');
  if (r.no_data) {
    main.innerHTML = `<div class="rep-grid"><div>${NO_DATA_HTML}</div><div class="side">${namesPanel()}</div></div>`;
    wire();
    return;
  }
  const s = r.summary;
  const modes = r.slots.filter((x) => MODE_CATS.includes(x.category));
  const bands = r.slots.filter((x) => !MODE_CATS.includes(x.category));
  const outside = r.outside.map((x) => `<tr class="quiet"><td class="mono">${esc(x.label)}</td><td>${x.credited ? 'Credited' : 'Not credited'}</td><td class="muted">${x.credited && x.since ? `since the ${esc(day(x.since))} import · ` : ''}not in your profile</td></tr>`).join('');
  main.innerHTML = `
    <section class="stats" aria-label="Summary">
      <div class="panel stat"><div class="k">CREDITED</div><div class="v">${s.credited}<small> / ${s.total}</small></div></div>
      <div class="panel stat${s.needed ? ' hot' : ''}"><div class="k">NEEDED</div><div class="v">${s.needed}</div></div>
      <div class="panel stat"><div class="k">AWAITING CREDIT</div><div class="v">${s.awaiting}</div></div>
      <div class="panel stat"><div class="k">PAPER CARD</div><div class="v">${s.card}</div></div>
    </section>
    <div class="rep-grid">
      <section class="panel" aria-labelledby="st-h">
        <div class="head"><h2 id="st-h">Status in your profile</h2>
          <div class="legend"><span class="li"><span class="cell need"></span>Needed</span><span class="li"><span class="cell await"></span>Awaiting</span>
            <span class="li"><span class="cell card"></span>Paper card</span><span class="li"><span class="cell wont"></span>Won't submit</span><span class="li"><span class="cell done"></span>Credited</span></div></div>
        <table class="st">
          <tr><th>Category</th><th>Status</th><th>Detail</th></tr>
          <tr class="grp"><td colspan="3">AWARD AND MODES</td></tr>${modes.map(statusRow).join('')}
          <tr class="grp"><td colspan="3">BANDS</td></tr>${bands.map(statusRow).join('')}
          ${outside ? `<tr class="grp"><td colspan="3">OUTSIDE YOUR PROFILE</td></tr>${outside}` : ''}
        </table>
        <p class="small muted" style="margin:12px 0 0">"Since" is the first import that showed the credit, not the QSO date; LoTW's matrix has no QSO dates. Click a slot that isn't credited to mark it.</p>
      </section>
      <div class="side">${namesPanel()}${dxPanel()}${cardsPanel()}${historyPanel()}</div>
    </div>`;
  wire();
}

function markMenu(focus) {
  openMarkMenu({ dxcc: report.dxcc, name: report.name, marks: report.marks, credited: report.credited },
    report.profile, () => { searchIndex = null; keepHeader = true; load(); }, focus);
}

function wire() {
  const cp = document.getElementById('copyname');
  if (cp) cp.onclick = async () => {
    const ok = await copyText(report.name);
    document.getElementById('copied').textContent = ok ? 'Copied' : 'Copy failed: select the name instead';
  };
  const mb = document.getElementById('markbtn');
  if (mb) mb.onclick = () => markMenu();
  document.querySelectorAll('[data-mark]').forEach((b) => (b.onclick = () => markMenu(b.dataset.mark)));
}

window.addEventListener('hashchange', () => { dxChecked = false; load(); });
load();
