import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Present cached evidence; Python validates and persists every human decision. */
let reviewData, activeId, saving = false, previewSerial = 0, previewState;
let savedDraft = '', candidatePage = 0, transactionPage = 0;
const expandedCandidates = new Set(), returnedCandidates = new Set();
const selected = new Map();
function draftSnapshot() {
  /* Track unsaved allocations independently of display preferences. */
  return JSON.stringify({allocations: [...selected]});
}
page.dirty(() => !!activeId && draftSnapshot() !== savedDraft);
const itemById = new Map();
const confidenceLabel = {high: 'High confidence', low: 'Low confidence', none: 'No match', failed: 'Failed', unresolved: 'Unresolved', outdated: 'Outdated'};

function preference(key, fallback) {
  /* Read remembered filters without making local storage a source of decisions. */
  try { return localStorage.getItem(`final-review:${key}`) || fallback; } catch { return fallback; }
}
function remember(key, value) {
  /* Storage restrictions must not prevent reviewing. */
  try { localStorage.setItem(`final-review:${key}`, value); } catch {}
}
function formatMoney(value, currency = 'MYR') {
  /* Format displayed amounts without changing stored monetary facts. */
  return value === '' || value === undefined ? 'Amount unknown' : `${currency || 'Currency unknown'} ${Number(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
}
function cents(value) {
  /* Use integer cents for the draft summary; the server validates exact decimals. */
  if (!/^\d+(\.\d{1,2})?$/.test(String(value))) return null;
  const [whole, fraction = ''] = String(value).split('.');
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
}
function bank() { /* Resolve the active transaction. */ return reviewData.banks.find(b => b.id === activeId); }
function error(message = '') {
  /* Keep action errors visible until the user corrects or reloads them. */
  $('#matching-error').textContent = message; $('#matching-error').hidden = !message;
}
function button(label, action, className = 'text-button') {
  /* Create safe controls with explicit labels and handlers. */
  const element = node('button', className, label); element.type = 'button'; element.onclick = action; return element;
}
async function refresh() {
  /* Reload durable state rather than optimistically claiming a save succeeded. */
  reviewData = await api('/api/matching');
  error('');
  itemById.clear(); reviewData.items.forEach(i => itemById.set(i.id, i));
  $('#use-pieces').hidden = !!reviewData.live_pieces;
  $('#generate-matches').hidden = !reviewData.live_pieces;
  $('#matching-outdated').hidden = !reviewData.banks.some(b => b.suggestion.outdated);
  renderQueue(); renderBankPicker(); renderUnmatched();
}
function visibleBanks() {
  /* Filter confidence separately from the saved human decision. */
  const confidence = $('#confidence-filter').value;
  const decision = $('#bank-filter').value;
  return reviewData.banks.filter(b => (decision === 'all' || b.review_status === decision) &&
    (confidence === 'all' || (b.confidence.level || 'none') === confidence));
}
function renderQueue() {
  /* Navigate one bank transaction at a time; candidate navigation is independent. */
  const rows = visibleBanks(), pages = $('#transaction-pages'); pages.replaceChildren();
  transactionPage = Math.min(transactionPage, Math.max(0, Math.ceil(rows.length / 10) - 1));
  const index = rows.findIndex(b => b.id === activeId);
  for (const b of rows.slice(transactionPage * 10, transactionPage * 10 + 10)) {
    const number = reviewData.banks.indexOf(b) + 1;
    const finished = ['approved', 'denied'].includes(b.review_status);
    const control = button(String(number), () => requestBank(b.id), `transaction-number ${finished ? 'finished' : ''}`);
    control.dataset.bankId = b.id;
    control.setAttribute('aria-label', `Transaction ${number}, ${b.review_status === 'denied' ? 'rejected' : b.review_status}`);
    control.title = `${b.parties.join(' / ')} \u00b7 ${formatMoney(b.amount, b.currency)}`;
    if (b.id === activeId) control.setAttribute('aria-current', 'page');
    if (finished) { const tick = node('span', 'completion-tick', '\u2713'); tick.setAttribute('aria-hidden', 'true'); control.append(tick); }
    control.disabled = saving;
    pages.append(control);
  }
  $('#queue-count').textContent = `${rows.length} transactions`;
  $('#previous-transactions').disabled = saving || transactionPage === 0;
  $('#next-transactions').disabled = saving || (transactionPage + 1) * 10 >= rows.length;
  $('#next-review-transaction').disabled = saving || !rows.length || index < 0 || index === rows.length - 1;
}
function applyFilters(control, key) {
  /* Keep the open payment inside the filtered queue without losing unsaved edits. */
  if (control && (saving || (activeId && draftSnapshot() !== savedDraft &&
      !window.confirm('Change filters and discard unsaved allocation changes?')))) {
    control.value = preference(key, 'all');
    return;
  }
  if (control) remember(key, control.value);
  const rows = visibleBanks();
  transactionPage = 0;
  $('#filtered-empty').hidden = !!rows.length;
  $('#bank-view').hidden = !rows.length;
  if (!rows.length) {
    activeId = null; selected.clear(); savedDraft = draftSnapshot();
    previewSerial++; previewState = null;
    $('#transaction-detail').replaceChildren();
    $('#review-editor').hidden = true;
    renderQueue();
  } else {
    chooseBank(rows.find(row => row.id === activeId)?.id || rows[0].id);
  }
}

function requestBank(id) {
  /* Protect edited allocations when navigating between transactions. */
  if (saving || id === activeId) return;
  if (activeId && draftSnapshot() !== savedDraft && !window.confirm('Leave this transaction and discard unsaved changes?')) return;
  chooseBank(id);
}
function chooseBank(id, addItem) {
  /* Start a draft from this transaction's saved choice, or its cached proposal. */
  if (saving) return;
  activeId = id; selected.clear(); error();
  candidatePage = 0; expandedCandidates.clear(); returnedCandidates.clear();
  const b = bank(), source = b.decision ? b.decision.allocations : b.suggestion.allocations;
  source.forEach(a => { if (itemById.has(a.item_id)) selected.set(a.item_id, a.amount); });
  if (addItem) selected.set(addItem, defaultAllocation(itemById.get(addItem)));
  $('#candidate-query').value = '';
  $('#candidate-search').hidden = true;
  $('#toggle-candidate-search').setAttribute('aria-expanded', 'false');
  $('#toggle-candidate-search').textContent = 'Search';
  transactionPage = Math.floor(Math.max(0, visibleBanks().findIndex(row => row.id === id)) / 10);
  $('#save-status').textContent = b.decision ? `Saved · ${new Date(b.decision.at).toLocaleString()}` : '';
  $('#review-editor').hidden = false; $('#undo-match').hidden = !b.decision;
  $('#deny-match').disabled = false;
  $('#approve-match').textContent = b.review_status === 'approved' ? 'Save changes' : 'Confirm supporting';
  const detail = $('#transaction-detail'); detail.replaceChildren();
  const header = node('div', 'transaction-header');
  const party = node('div', 'transaction-party');
  party.append(node('span', 'transaction-direction', b.direction === 'in' ? 'Pay from' : 'Pay to'),
    node('h2', 'transaction-title', b.parties.join(' / ') || 'Party unknown'));
  header.append(party, node('strong', 'bank-amount', formatMoney(b.amount, b.currency)));
  const meta = node('div', 'bank-meta');
  meta.title = b.id;
  const status = {pending: 'Awaiting review', approved: 'Approved', denied: 'Rejected'}[b.review_status] || b.review_status;
  meta.append(node('span', '', b.date), node('span', `review-state ${b.review_status}`, status));
  const narration = node('p', 'payment-description', b.description || 'Payment description unavailable');
  narration.setAttribute('aria-label', 'Payment details');
  detail.append(header, meta, narration);
  if (b.suggestion.outdated) detail.append(node('p', 'warning', 'Saved proposal is outdated. Recheck current evidence or generate matches again.'));
  if (b.suggestion.failed) detail.append(node('p', 'warning', b.suggestion.reason));
  if (b.stale) detail.append(node('p', 'warning', 'Original evidence changed. This transaction cannot be treated as supported until rechecked.'));
  for (const flag of b.decision?.flags || []) detail.append(node('p', 'warning', flag));
  renderQueue(); renderCandidates(); updateSummary(); remember('active', id);
  savedDraft = draftSnapshot(); updateSummary();
  const first = addItem || selected.keys().next().value;
  if (first) showEvidence('item', first); else showEvidence('bank', id);
}
function available(item) {
  /* Editing a saved approval may reuse its own currently reserved allocation. */
  const current = bank()?.decision?.allocations.find(a => a.item_id === item.id)?.amount || '0';
  return item.remaining === '' ? null : (cents(item.remaining) ?? 0) + (cents(current) ?? 0);
}
function defaultAllocation(item) {
  /* Missing monetary facts remain blank; no amount is inferred from the bank. */
  if (!item.currency || item.currency !== bank().currency || available(item) === null) return '';
  return (Math.max(0, Math.min(available(item), cents(bank().amount))) / 100).toFixed(2);
}
function renderCandidates() {
  /* Compare shortlisted supporting pieces openly, five compact cards at a time. */
  const b = bank(), query = $('#candidate-query').value.trim().toLowerCase(), list = $('#candidate-list');
  list.replaceChildren();
  const tray = $('#selected-candidates'); tray.replaceChildren();
  $('#selected-count').textContent = String(selected.size);
  if (!selected.size) tray.append(node('p', 'tray-empty', 'Tick a candidate below to add it.'));
  const suggested = new Set(b.suggestion.allocations.map(a => a.item_id));
  const keys = new Set([...b.candidates, ...returnedCandidates]);
  const items = reviewData.items.filter(i => !selected.has(i.id) && !i.excluded && (!$('#candidate-search').hidden || keys.has(i.id)) &&
    ( `${i.id} ${i.filename} ${i.amount} ${i.description} ${i.parties.join(' ')} ${(i.references || []).join(' ')}`.toLowerCase().includes(query)));
  items.sort((a, c) => Number(returnedCandidates.has(c.id)) - Number(returnedCandidates.has(a.id)) || Number(suggested.has(c.id)) - Number(suggested.has(a.id)));
  candidatePage = Math.max(0, Math.min(candidatePage, Math.ceil(items.length / 5) - 1));
  const start = candidatePage * 5;
  $('#candidate-count').textContent = items.length ? `${start + 1}–${Math.min(start + 5, items.length)} of ${items.length} candidates` : 'No candidates';
  $('#candidate-prev').disabled = candidatePage === 0;
  $('#candidate-next').disabled = start + 5 >= items.length;
  for (const item of [...selected.keys()].map(id => itemById.get(id)).filter(Boolean).concat(items.slice(start, start + 5))) {
    const card = node('article', `candidate-card ${selected.has(item.id) ? 'selected' : ''}`);
    card.classList.toggle('suggested', suggested.has(item.id));
    card.dataset.itemId = item.id;
    card.setAttribute('aria-label', `Candidate ${item.id}`);
    if (previewState?.kind === 'item' && previewState.id === item.id) card.classList.add('previewing');
    const isSelected = selected.has(item.id);
    const control = isSelected ? button('\u00d7', () => {
      selected.delete(item.id); returnedCandidates.add(item.id);
      $('#candidate-query').value = ''; candidatePage = 0;
      renderCandidates(); updateSummary();
      [...list.querySelectorAll('.candidate-card')].find(c => c.dataset.itemId === item.id)?.querySelector('input').focus();
    }, 'remove-candidate') : node('input');
    if (isSelected) {
      control.setAttribute('aria-label', `Remove ${item.id} from selected`);
      control.title = 'Remove from selected';
    } else {
      control.type = 'checkbox'; control.disabled = item.stale;
      control.setAttribute('aria-label', `Select ${item.id} ${item.filename}`);
      control.onchange = () => {
        selected.set(item.id, defaultAllocation(item)); returnedCandidates.delete(item.id);
        renderCandidates(); updateSummary();
        [...tray.querySelectorAll('.candidate-card')].find(c => c.dataset.itemId === item.id)?.querySelector('.remove-candidate').focus();
      };
    }
    const details = node('details', 'candidate-details'); details.open = expandedCandidates.has(item.id);
    const summary = node('summary', 'candidate-summary');
    summary.setAttribute('aria-label', `Inspect ${item.id} ${item.filename}`);
    summary.append(node('span', 'candidate-name', item.parties.join(' / ') || 'Party unknown'), node('strong', 'candidate-amount', formatMoney(item.amount, item.currency)));
    if (suggested.has(item.id)) summary.querySelector('.candidate-name').prepend(node('span', 'suggested-label', 'Suggested: '));
    details.append(summary);
    details.ontoggle = () => {
      if (details.open) {
        const newlyOpened = !expandedCandidates.has(item.id);
        expandedCandidates.add(item.id);
        if (newlyOpened) showEvidence('item', item.id);
      } else expandedCandidates.delete(item.id);
    };
    const body = node('div', 'candidate-body');
    if (suggested.has(item.id)) {
      const reason = node('section', 'suggestion-explanation');
      reason.setAttribute('aria-label', 'Why suggested');
      reason.append(node('strong', '', confidenceLabel[b.confidence.level || 'none']),
        node('p', '', b.suggestion.reason || 'No saved explanation available.'));
      body.append(reason);
    }
    const dates = item.dates?.length ? item.dates.map(d => typeof d === 'string' ? d : d.value).join(', ') : item.date || 'Date unknown';
    const source = node('details', 'source-details');
    source.append(node('summary', '', 'Source details'));
    source.append(node('p', 'candidate-description', item.description || 'Description unavailable'));
    source.append(node('p', 'candidate-info', `${dates} · ${item.filename} · ${item.location || 'Location unknown'}`));
    const retrievalReason = b.evidence_reasons?.[item.id] || '';
    source.append(node('p', 'candidate-reason', retrievalReason));
    if (retrievalReason.includes('no exact extracted party-name match')) {
      body.append(node('p', 'warning', 'Name differs from extracted text; verify the original.'));
    } else if (retrievalReason && !suggested.has(item.id)) {
      body.append(node('p', 'candidate-reason', retrievalReason));
    }
    body.append(source);
    if (item.currency === b.currency && cents(item.amount) !== null && cents(item.amount) !== cents(b.amount)) body.append(node('p', 'warning', `Bank minus source: ${formatMoney(((cents(b.amount) - cents(item.amount)) / 100).toFixed(2), b.currency)}`));
    if (item.used !== '0') body.append(node('p', 'warning', `Reserved: ${formatMoney(item.used, item.currency)} · Available here: ${available(item) === null ? 'unknown' : formatMoney((available(item) / 100).toFixed(2), item.currency)}`));
    if (item.stale) body.append(node('p', 'warning', 'Source changed or unavailable. Approval blocked.'));
    if (item.boundary_unresolved) body.append(node('p', 'warning', 'Check receipt boundaries against the original.'));
    if (selected.has(item.id)) {
      const label = node('label', 'allocation-label', `Allocation (${b.currency || 'currency unknown'})`);
      const input = node('input'); input.type = 'text'; input.inputMode = 'decimal'; input.value = selected.get(item.id); input.placeholder = 'Evidence only';
      input.disabled = !item.currency || item.currency !== b.currency || item.amount === '';
      input.setAttribute('aria-label', `Allocation ${item.id}`);
      input.oninput = () => { selected.set(item.id, input.value.trim()); updateSummary(); };
      label.append(input); body.append(label);
    }
    const actions = node('div', 'candidate-bottom');
    actions.append(button('View evidence', () => showEvidence('item', item.id), 'candidate-preview'));
    const use = button('Use only this', () => {
      selected.clear(); selected.set(item.id, defaultAllocation(item));
      renderCandidates(); updateSummary(); showEvidence('item', item.id);
    }, 'candidate-preview');
    use.disabled = item.stale || item.excluded;
    if (selected.size !== 1 || !selected.has(item.id)) actions.append(use);
    body.append(actions); details.append(body); card.append(control, details); (isSelected ? tray : list).append(card);
  }
  if (!items.length) list.append(node('p', 'empty-state', 'No candidates found. Search all pieces or change your search.'));
}
function updateSummary() {
  /* Make incomplete, excessive or invalid allocations visible before submitting. */
  const b = bank(), values = [...selected.values()], total = values.reduce((sum, v) => sum + (cents(v) || 0), 0), difference = cents(b.amount) - total;
  const summary = $('#selection-summary'); summary.replaceChildren();
  $('#footer-summary').classList.toggle('allocation-warning', difference !== 0 && selected.size > 0);
  summary.append(node('strong', '', `${selected.size} selected · ${formatMoney((total / 100).toFixed(2), b.currency)} allocated`));
  summary.append(node('div', difference ? 'difference' : '', difference === 0 ? 'The allocation equals the bank payment.' : `Difference: ${formatMoney((difference / 100).toFixed(2), b.currency)}`));
  $('#footer-summary').textContent = `${selected.size} selected · ${formatMoney((total / 100).toFixed(2), b.currency)} allocated${difference ? ' · Difference ' + formatMoney((difference / 100).toFixed(2), b.currency) : ''}`;
  if (values.some(v => v === '')) summary.append(node('div', 'warning', 'Blank allocations link contextual evidence only.'));
  if (values.some(v => v !== '' && cents(v) === null)) summary.append(node('div', 'warning', 'Enter valid amounts with up to two decimal places.'));
  if (selected.size > 1) summary.append(node('div', 'warning', 'Check that the documents represent separate expenses, not an invoice and its payment proof.'));
  const flagged = difference !== 0 || selected.size > 1 || [...selected].some(([id, value]) => value === '' || itemById.get(id).boundary_unresolved || (cents(value) !== null && cents(value) < cents(itemById.get(id).amount)));
  summary.hidden = !flagged || !selected.size;
  const unchanged = draftSnapshot() === savedDraft;
  $('#support-heading').textContent = 'Available candidates';
  $('#support-status').textContent = b.decision && unchanged
    ? `${b.support_status}. ${b.review_status === 'denied' ? 'Suggestion rejected; other evidence may exist.' : 'Saved review decision.'}`
    : `${selected.size} selected · Not confirmed`;
  $('#approve-match').textContent = difference === 0 && values.some(v => v !== '') ? 'Confirm supporting' : 'Save partial / contextual evidence';
  $('#approve-match').disabled = saving || !selected.size || b.stale || difference < 0 || values.some(v => v !== '' && (cents(v) === null || cents(v) <= 0));
}
async function saveDecision(action) {
  /* Send explicit user intent, then reload the authoritative ledger and balances. */
  if (saving) return;
  saving = true; error(); $('#save-status').textContent = 'Saving your decision…';
  let persisted = false;
  root.querySelectorAll('.decision-actions button').forEach(b => b.disabled = true);
  try {
    await api('/api/matching-decide', {bank_id:activeId,action,note:bank().decision?.note || '',
      binding:reviewData.binding,version:reviewData.version,
      allocations:[...selected].map(([item_id, amount]) => ({item_id,amount}))});
    persisted = true;
    await refresh(); saving = false; chooseBank(activeId);
    toast(action === 'undo' ? 'Decision undone. Amounts are available again.' : 'Decision saved.');
  } catch (e) { error(e.message); $('#save-status').textContent = persisted ? 'Decision saved, but refresh failed. Reload to see the latest state.' : 'Decision was not saved. Your draft is still here.'; }
  finally { saving = false; root.querySelectorAll('.decision-actions button').forEach(b => b.disabled = false); updateSummary(); renderQueue(); }
}
async function showEvidence(kind, id) {
  /* Ignore late responses when the reviewer switches documents quickly. */
  const serial = ++previewSerial, query = new URLSearchParams({kind,id});
  previewState = null;
  $('#preview-prev').disabled = true; $('#preview-next').disabled = true;
  $('#preview-zoom').value = '1'; applyZoom();
  const sources = $('#preview-source'); sources.replaceChildren();
  const ids = new Set(selected.keys()); if (kind === 'item') ids.add(id);
  for (const itemId of ids) {
    const item = itemById.get(itemId);
    if (!item) continue;
    const option = node('option', '', `${item.parties.join(' / ') || item.filename} · ${item.filename}`);
    option.value = itemId; sources.append(option);
  }
  const bankOption = node('option', '', 'Original bank statement'); bankOption.value = '__bank__'; sources.append(bankOption);
  sources.value = kind === 'bank' ? '__bank__' : id;
  root.querySelectorAll('.candidate-card').forEach(card => card.classList.toggle('previewing', kind === 'item' && card.dataset.itemId === id));
  $('#evidence-content').replaceChildren(node('div', 'empty-state', 'Loading original evidence…'));
  $('#evidence-title').textContent = kind === 'bank' ? 'Original bank statement' : itemById.get(id).filename;
  $('#evidence-original').href = `/api/matching-file?${query}`; $('#evidence-original').hidden = false;
  try {
    const info = await api(`/api/matching-preview?${query}`); if (serial !== previewSerial) return;
    previewState = {kind,id,info};
    const select = $('#preview-page'); select.replaceChildren();
    info.labels.forEach((label, n) => { const option = node('option', '', label); option.value = n; select.append(option); });
    const preferred = kind === 'bank' ? bank().page : Math.max(0, itemById.get(id).unit);
    select.value = String(Math.min(Math.max(0, info.pages - 1), preferred));
    await renderEvidencePage(serial);
  } catch (e) { if (serial === previewSerial) $('#evidence-content').replaceChildren(node('div', 'empty-state', e.message)); }
}
async function renderEvidencePage(serial = ++previewSerial) {
  /* Render PDFs/images or safe structured Office previews, with page navigation. */
  if (!previewState) return;
  const {kind,id,info} = previewState, n = Number($('#preview-page').value || 0), target = $('#evidence-content');
  const query = new URLSearchParams({kind,id,page:n});
  $('#preview-prev').disabled = n <= 0; $('#preview-next').disabled = n >= info.pages - 1;
  target.replaceChildren(node('div', 'empty-state', 'Loading page…'));
  try {
    if (info.kind === 'text') target.replaceChildren(node('pre', '', info.text));
    else if (info.kind === 'unsupported') target.replaceChildren(node('div', 'empty-state', info.message));
    else if (['word', 'spreadsheet'].includes(info.kind) && n < info.office_pages) {
      const data = await api(`/api/matching-office?${query}`); if (serial !== previewSerial) return;
      renderOfficePreview(target, data);
    } else {
      const image = node('img'); image.alt = `${$('#evidence-title').textContent} · ${info.labels[n]}`;
      image.onload = () => { if (serial === previewSerial) target.replaceChildren(image); };
      image.onerror = () => { if (serial === previewSerial) target.replaceChildren(node('div', 'empty-state', 'Preview unavailable. Use Open original.')); };
      image.src = `/api/matching-image?${query}`;
    }
  } catch (e) { if (serial === previewSerial) target.replaceChildren(node('div', 'empty-state', e.message)); }
}
function applyZoom() {
  /* Zoom the original inside its own scroll area without widening the page. */
  $('#evidence-content').style.setProperty('--preview-scale', $('#preview-zoom').value);
}
function changeTab(documents) {
  /* Both views read the same ledger and remaining balances. */
  $('#matching-options').hidePopover();
  $('#transaction-toolbar').hidden = documents;
  $('#bank-view').hidden = documents || !visibleBanks().length; $('#document-view').hidden = !documents;
  $('#filtered-empty').hidden = documents || !!visibleBanks().length;
  $('#bank-tab').classList.toggle('selected', !documents); $('#document-tab').classList.toggle('selected', documents);
  if (documents) renderUnmatched();
}
function renderUnmatched() {
  /* Keep partially allocated items visible with their remaining capacity. */
  const query = $('#document-query').value.toLowerCase(), list = $('#unmatched-list'); list.replaceChildren();
  const rows = reviewData.items.filter(i => !i.excluded && (i.remaining === '' || Number(i.remaining) > 0) && `${i.filename} ${i.parties.join(' ')} ${i.amount} ${i.description} ${(i.references || []).join(' ')}`.toLowerCase().includes(query));
  for (const item of rows) {
    const row = node('div', 'unmatched-row'), description = node('div');
    description.append(node('h3', '', item.description || item.payee || item.filename), node('p', '', `${item.filename} · ${item.location}`), node('p', '', item.parties.join(' / ')));
    const remaining = node('div'); remaining.append(node('strong', '', item.remaining === '' ? 'Contextual evidence' : formatMoney(item.remaining, item.currency)), node('p', '', item.remaining === '' ? 'No extracted monetary balance' : 'Remaining amount'));
    const actions = node('div', 'unmatched-actions');
    actions.append(button('Review with transaction →', () => { const select = $('#unmatched-bank'); if (!select.value) { select.focus(); toast('Choose a bank transaction above first.'); return; } changeTab(false); chooseBank(select.value, item.id); }, 'button secondary'));
    row.append(description, remaining, actions); list.append(row);
  }
  if (!rows.length) list.append(node('p', 'empty-state', 'No unallocated supporting items in this search.'));
}
function renderBankPicker() {
  /* Share one searchable transaction selector instead of duplicating it per document. */
  const select = $('#unmatched-bank'), current = select.value, query = $('#unmatched-bank-query').value.toLowerCase(); select.replaceChildren();
  const placeholder = node('option', '', 'Choose a transaction…'); placeholder.value = ''; select.append(placeholder);
  for (const b of reviewData.banks.filter(b => `${b.id} ${b.parties.join(' ')} ${b.amount} ${b.description}`.toLowerCase().includes(query))) {
    const option = node('option', '', `${b.id} · ${b.parties.join(' / ')} · ${b.amount}`); option.value = b.id; select.append(option);
  }
  if ([...select.options].some(option => option.value === current)) select.value = current;
}
async function initialize() {
  /* Restore display preferences, then fetch the saved corpus and session token. */
  $('#bank-filter').value = preference('filter', 'all');
  if (!$('#bank-filter').value) $('#bank-filter').value = 'all';
  $('#confidence-filter').value = preference('confidence', 'all');
  if (!$('#confidence-filter').value) $('#confidence-filter').value = 'all';
  try {
    token = (await api('/api/session')).token; await refresh();
    const rows = visibleBanks(), remembered = preference('active', '');
    const initial = rows.find(b => b.id === remembered) || rows[0];
    if (initial) chooseBank(initial.id); else applyFilters();
  } catch (e) { error(e.message); }
}
$('#bank-filter').onchange = event => applyFilters(event.target, 'filter');
$('#confidence-filter').onchange = event => applyFilters(event.target, 'confidence');
$('#previous-transactions').onclick = () => { transactionPage--; renderQueue(); };
$('#next-transactions').onclick = () => { transactionPage++; renderQueue(); };
$('#next-review-transaction').onclick = () => {
  const rows = visibleBanks(), index = rows.findIndex(b => b.id === activeId);
  if (rows[index + 1]) requestBank(rows[index + 1].id);
};
$('#candidate-prev').onclick = () => { candidatePage--; renderCandidates(); };
$('#candidate-next').onclick = () => { candidatePage++; renderCandidates(); };
$('#preview-source').onchange = () => {
  const id = $('#preview-source').value;
  showEvidence(id === '__bank__' ? 'bank' : 'item', id === '__bank__' ? activeId : id);
};
$('#preview-zoom').onchange = applyZoom;
function toggleCandidateSearch() {
  /* Expand all-piece search without changing the draft supporting selection. */
  const panel = $('#candidate-search'), control = $('#toggle-candidate-search');
  panel.hidden = !panel.hidden;
  control.setAttribute('aria-expanded', String(!panel.hidden));
  control.textContent = panel.hidden ? 'Search' : 'Close search';
  if (panel.hidden) $('#candidate-query').value = '';
  candidatePage = 0; renderCandidates();
  (panel.hidden ? control : $('#candidate-query')).focus();
}
$('#toggle-candidate-search').onclick = toggleCandidateSearch;
$('#candidate-query').onkeydown = event => { if (event.key === 'Escape') { event.preventDefault(); toggleCandidateSearch(); } };
$('#candidate-query').oninput = () => { candidatePage = 0; renderCandidates(); };
$('#restore-suggestion').onclick = () => { selected.clear(); bank().suggestion.allocations.forEach(a => selected.set(a.item_id, a.amount)); renderCandidates(); updateSummary(); };
$('#approve-match').onclick = () => saveDecision('approve'); $('#deny-match').onclick = () => saveDecision('deny'); $('#undo-match').onclick = () => saveDecision('undo');
$('#preview-bank').onclick = () => { if (activeId) showEvidence('bank', activeId); };
$('#preview-page').onchange = () => renderEvidencePage();
$('#preview-prev').onclick = () => { $('#preview-page').selectedIndex--; renderEvidencePage(); };
$('#preview-next').onclick = () => { $('#preview-page').selectedIndex++; renderEvidencePage(); };
$('#bank-tab').onclick = () => changeTab(false); $('#document-tab').onclick = () => changeTab(true); $('#document-query').oninput = renderUnmatched;
$('#unmatched-bank-query').oninput = renderBankPicker;
initialize();


$('#use-pieces').onclick = async () => {
  try {
    await api('/api/matching-pieces', {}); await refresh();
    const target = reviewData.banks.find(b => b.id === activeId) || reviewData.banks[0];
    if (target) chooseBank(target.id);
  }
  catch (e) { error(e.message); }
};
let matchingWasRunning = false, matchingStarting = false;
function renderMatchingProgress(state) {
  /* Display real processed counts; failures and stopped work never imply successful completion. */
  const total = state.total || 0, completed = state.completed || 0;
  const running = !!state.running, stopping = !!state.stop_requested;
  const percent = total ? Math.min(100, Math.floor(completed / total * 100)) : 0;
  const panel = $('#matching-progress'), bar = $('#matching-progress-bar');
  panel.hidden = !running && !total && !state.error;
  panel.dataset.running = String(running);
  panel.dataset.error = String(!!state.error);
  panel.setAttribute('aria-busy', String(running));
  $('#generate-matches').disabled = running;
  $('#stop-matches').hidden = !running || matchingStarting;
  $('#stop-matches').disabled = stopping;
  $('#matching-run-status').textContent = running
    ? stopping ? 'Stopping…' : matchingStarting ? 'Starting matching…' : 'Generating matches'
    : stopping ? 'Stopped' : state.error ? 'Finished with errors' : completed < total ? 'Stopped' : 'Matching complete';
  $('#matching-progress-count').textContent = total ? `${completed} / ${total} processed (${percent}%)` : '';
  if (matchingStarting || !total) bar.removeAttribute('value');
  else bar.value = percent;
  $('#matching-progress-detail').textContent = [
    running && state.active_processes ? `${state.active_processes} active` : '',
    state.failed ? `${state.failed} failed` : '',
    state.error && !state.failed ? state.error : '',
  ].filter(Boolean).join(' · ');
}
async function matchingProgress() {
  /* Poll model work separately so unsaved allocation edits are never overwritten. */
  if (!reviewData?.live_pieces || matchingStarting) return;
  const state = await api('/api/matching-run');
  if (matchingStarting) return;
  renderMatchingProgress(state);
  if (matchingWasRunning && !state.running && draftSnapshot() === savedDraft) {
    await refresh(); if (activeId) chooseBank(activeId);
  }
  matchingWasRunning = !!state.running;
}
$('#generate-matches').onclick = async () => {
  if (matchingStarting) return;
  matchingStarting = true;
  renderMatchingProgress({running:true});
  try {
    const state = await api('/api/matching-run', {});
    matchingStarting = false;
    renderMatchingProgress(state);
    matchingWasRunning = true;
    await matchingProgress();
  } catch (e) {
    matchingStarting = false;
    renderMatchingProgress({error:e.message});
    error(e.message);
  }
};
$('#stop-matches').onclick = async () => {
  $('#stop-matches').disabled = true;
  $('#matching-run-status').textContent = 'Stopping…';
  try { renderMatchingProgress(await api('/api/matching-stop', {})); }
  catch (e) { $('#stop-matches').disabled = false; error(e.message); }
};
pollVisible(matchingProgress, 2000);
page.onRefresh(refresh, ['/api/matching-decide', '/api/receipts/', '/api/content/']);
}
