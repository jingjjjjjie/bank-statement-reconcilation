import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Present cached evidence; Python validates and persists every human decision. */
let reviewData, activeId, saving = false, previewSerial = 0, previewState;
let savedDraft = '';
const selected = new Map();
function draftSnapshot() {
  /* Track unsaved allocations and notes independently of display preferences. */
  return JSON.stringify({allocations: [...selected], note: $('#decision-note').value});
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
  $('#matching-workspace').textContent = reviewData.workspace;
  const counts = $('#matching-counts');
  const approved = reviewData.banks.filter(b => b.review_status === 'approved').length;
  const denied = reviewData.banks.filter(b => b.review_status === 'denied').length;
  counts.textContent = `${approved + denied} of ${reviewData.banks.length} reviewed`;
  const summary = reviewData.proposal_counts;
  $('#matching-result-summary').textContent = summary ? Object.entries(summary).map(([key, count]) => `${count} ${confidenceLabel[key].toLowerCase()}`).join(' / ') : '';
  $('#matching-outdated').hidden = !reviewData.banks.some(b => b.suggestion.outdated);
  renderQueue(); renderBankPicker(); renderUnmatched();
}
function visibleBanks() {
  /* Filter confidence separately from the saved human decision. */
  const query = $('#bank-query').value.trim().toLowerCase(), filter = $('#bank-filter').value;
  const confidence = $('#confidence-filter').value;
  return reviewData.banks.filter(b => (filter === 'all' || b.review_status === filter) &&
    (confidence === 'all' || (b.confidence.level || 'none') === confidence) &&
    `${b.id} ${b.date} ${b.parties.join(' ')} ${b.amount} ${b.description}`.toLowerCase().includes(query));
}
function renderQueue() {
  /* Keep the active decision open even when saving removes it from the pending filter. */
  const rows = visibleBanks(), list = $('#bank-list'), scroll = list.scrollTop; list.replaceChildren();
  $('#queue-count').textContent = `${rows.length} transactions`;
  for (const b of rows) {
    const row = button('', () => chooseBank(b.id), `bank-row ${b.id === activeId ? 'active' : ''}`);
    row.setAttribute('aria-label', `${b.id} ${b.parties.join(' ')} ${formatMoney(b.amount, b.currency)}`);
    row.setAttribute('aria-pressed', String(b.id === activeId));
    row.append(node('span', 'party', b.parties.join(' / ')));
    const meta = node('span', 'row-meta'); meta.append(node('span', '', b.date), node('span', '', b.id)); row.append(meta);
    row.append(node('span', 'row-money', `${b.direction === 'in' ? '+ ' : ''}${formatMoney(b.amount, b.currency)}`));
    row.append(node('span', `badge confidence-${b.confidence.level || 'none'}`, confidenceLabel[b.confidence.level || 'none']));
    row.append(node('span', `badge ${b.review_status}`, b.review_status === 'denied' ? 'Rejected' : b.review_status));
    if (b.stale) row.append(node('span', 'warning', 'Evidence changed'));
    list.append(row);
  }
  if (!rows.length) list.append(node('div', 'empty-state', 'No transactions in this view. Change the filter or search.'));
  list.scrollTop = scroll;
}
function chooseBank(id, addItem) {
  /* Start a draft from this transaction's saved choice, or its cached proposal. */
  if (saving) return;
  activeId = id; selected.clear(); error();
  const b = bank(), source = b.decision ? b.decision.allocations : b.suggestion.allocations;
  source.forEach(a => { if (itemById.has(a.item_id)) selected.set(a.item_id, a.amount); });
  if (addItem) selected.set(addItem, defaultAllocation(itemById.get(addItem)));
  $('#candidate-query').value = ''; $('#all-candidates').checked = false;
  $('#candidate-picker').open = false; $('#note-details').open = false;
  $('#decision-note').value = b.decision?.note || ''; $('#acknowledge').checked = false;
  $('#save-status').textContent = b.decision ? `Saved · ${new Date(b.decision.at).toLocaleString()}` : '';
  $('#review-editor').hidden = false; $('#undo-match').hidden = !b.decision;
  $('#deny-match').disabled = false;
  $('#approve-match').textContent = b.review_status === 'approved' ? 'Save changes' : 'Confirm supporting';
  const detail = $('#transaction-detail'); detail.replaceChildren();
  detail.append(node('span', `badge ${b.review_status}`, `${b.id} · ${b.review_status === 'denied' ? 'Rejected' : b.review_status}`), node('h2', 'transaction-title', b.parties.join(' / ')), node('div', 'bank-amount', formatMoney(b.amount, b.currency)), node('p', 'bank-meta', `${b.date} · ${b.direction === 'in' ? 'Incoming' : 'Outgoing'}`));
  const reason = node('details', 'transaction-notes');
  reason.append(node('summary', '', 'Payment details'), node('p', '', b.suggestion.reason),
    node('div', 'narration', b.description), node('p', 'subtle', `Saved assessment: ${confidenceLabel[b.confidence.level || 'none']}`));
  detail.append(reason);
  if (b.suggestion.outdated) detail.append(node('p', 'warning', 'Saved proposal is outdated. Recheck current evidence or generate matches again.'));
  if (b.suggestion.failed) detail.append(node('p', 'warning', b.suggestion.reason));
  if (b.stale) detail.append(node('p', 'warning', 'Original evidence changed. This transaction cannot be treated as supported until rechecked.'));
  for (const flag of b.decision?.flags || []) detail.append(node('p', 'warning', flag));
  const history = $('#decision-history'); history.replaceChildren();
  for (const h of b.history.slice().reverse()) history.append(node('p', '', `${new Date(h.at).toLocaleString()} · ${h.action}${h.note ? '\n' + h.note : ''}`));
  $('.history').hidden = !b.history.length;
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
  /* Display suggestions first, with an explicit option to search the entire corpus. */
  const b = bank(), query = $('#candidate-query').value.toLowerCase(), list = $('#candidate-list'); list.replaceChildren();
  const alternatives = $('#alternative-list'); alternatives.replaceChildren();
  const keys = new Set(b.candidates);
  const expanded = $('#candidate-picker').open;
  const items = reviewData.items.filter(i => (selected.has(i.id) || (!i.excluded && expanded && ($('#all-candidates').checked || keys.has(i.id)))) && (selected.has(i.id) || `${i.id} ${i.filename} ${i.amount} ${i.description} ${i.parties.join(' ')} ${(i.references || []).join(' ')} ${(i.dates || []).map(d => typeof d === 'string' ? d : d.value).join(' ')}`.toLowerCase().includes(query)));
  items.sort((a, c) => Number(selected.has(c.id)) - Number(selected.has(a.id)) || Number(b.candidates.includes(c.id)) - Number(b.candidates.includes(a.id)));
  for (const item of items) {
    const card = node('div', `candidate-card ${selected.has(item.id) ? 'selected' : ''}`), top = node('label', 'candidate-top');
    const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(item.id); checkbox.disabled = item.stale;
    checkbox.setAttribute('aria-label', `Select ${item.id} ${item.filename}`);
    checkbox.onchange = () => { if (checkbox.checked) selected.set(item.id, defaultAllocation(item)); else selected.delete(item.id); renderCandidates(); updateSummary(); };
    top.append(checkbox, node('span', 'candidate-name', item.parties.join(' / ') || 'Party unknown')); card.append(top);
    const sourceDetails = node('details', 'source-details');
    sourceDetails.append(node('summary', '', 'Source and allocation'), node('p', 'candidate-info', item.filename), node('p', 'candidate-info', item.location));
    const dates = item.dates?.length ? item.dates.join(', ') : item.date || 'Date unknown';
    card.append(node('div', 'candidate-info', `${formatMoney(item.amount, item.currency)} | ${dates}`));
    card.append(node('p', 'candidate-reason', b.evidence_reasons?.[item.id] || 'Not assessed in the saved shortlist. Verify this evidence before adding it.'));

    if (item.currency === b.currency && cents(item.amount) !== null && cents(item.amount) !== cents(b.amount)) card.append(node('p', 'warning', `Bank minus source amount: ${formatMoney(((cents(b.amount) - cents(item.amount)) / 100).toFixed(2), b.currency)}`));
    if (item.used !== '0') card.append(node('p', 'warning', `Reserved across payments: ${formatMoney(item.used, item.currency)} · Available here: ${available(item) === null ? 'unknown' : formatMoney((available(item) / 100).toFixed(2), item.currency)}`));
    if (item.stale) card.append(node('p', 'warning', 'Source changed or unavailable — approval blocked.'));
    if (item.boundary_unresolved) card.append(node('p', 'warning', 'Check the whole document: receipt boundaries are not assembled.'));
    const bottom = node('div', 'candidate-bottom');
    if (selected.has(item.id)) {
      const label = node('label', 'allocation-label', 'Allocate to this payment');
      const input = node('input'); input.type = 'text'; input.inputMode = 'decimal'; input.value = selected.get(item.id); input.placeholder = 'Evidence only';
      input.disabled = !item.currency || item.currency !== b.currency || item.amount === '';
      input.setAttribute('aria-label', `Allocation ${item.id}`);
      input.oninput = () => { selected.set(item.id, input.value.trim()); updateSummary(); };
      label.append(input); sourceDetails.append(label);
    }
    bottom.append(button('View evidence ↗', () => showEvidence('item', item.id))); card.append(bottom, sourceDetails); (selected.has(item.id) ? list : alternatives).append(card);
  }
  if (!selected.size) list.append(node('p', 'empty-state', 'No supporting evidence selected. Use Change evidence to search; this does not mean no supporting document exists.'));
  if (expanded && !alternatives.children.length) alternatives.append(node('p', 'empty-state', 'No alternatives in this search.'));
}
function updateSummary() {
  /* Make incomplete, excessive or invalid allocations visible before submitting. */
  const b = bank(), values = [...selected.values()], total = values.reduce((sum, v) => sum + (cents(v) || 0), 0), difference = cents(b.amount) - total;
  const summary = $('#selection-summary'); summary.replaceChildren();
  summary.append(node('strong', '', `${selected.size} selected · ${formatMoney((total / 100).toFixed(2), b.currency)} allocated`));
  summary.append(node('div', difference ? 'difference' : '', difference === 0 ? 'The allocation equals the bank payment.' : `Difference: ${formatMoney((difference / 100).toFixed(2), b.currency)}`));
  $('#footer-summary').textContent = `${selected.size} selected · ${formatMoney((total / 100).toFixed(2), b.currency)} allocated${difference ? ' · Difference ' + formatMoney((difference / 100).toFixed(2), b.currency) : ''}`;
  if (values.some(v => v === '')) summary.append(node('div', 'warning', 'Blank allocations link contextual evidence only.'));
  if (values.some(v => v !== '' && cents(v) === null)) summary.append(node('div', 'warning', 'Enter valid amounts with up to two decimal places.'));
  if (selected.size > 1) summary.append(node('div', 'warning', 'Check that the documents represent separate expenses, not an invoice and its payment proof.'));
  const flagged = difference !== 0 || selected.size > 1 || [...selected].some(([id, value]) => value === '' || itemById.get(id).boundary_unresolved || (cents(value) !== null && cents(value) < cents(itemById.get(id).amount)));
  summary.hidden = !flagged || !selected.size;
  const unchanged = draftSnapshot() === savedDraft;
  $('#support-heading').textContent = b.decision && unchanged ? 'Supporting evidence' : 'Suggested support';
  $('#support-status').textContent = b.decision && unchanged
    ? `${b.support_status}. ${b.review_status === 'denied' ? 'Suggestion rejected; other evidence may exist.' : 'Saved review decision.'}`
    : 'Not yet confirmed';
  $('#approve-match').textContent = difference === 0 && values.some(v => v !== '') ? 'Confirm supporting' : 'Save partial / contextual evidence';
  $('#acknowledge-label').hidden = !flagged;
  if (flagged && selected.size) $('#note-details').open = true;
  $('#approve-match').disabled = saving || !selected.size || b.stale || difference < 0 || values.some(v => v !== '' && (cents(v) === null || cents(v) <= 0));
}
async function saveDecision(action) {
  /* Send explicit user intent, then reload the authoritative ledger and balances. */
  if (saving) return;
  saving = true; error(); $('#save-status').textContent = 'Saving your decision…';
  let persisted = false;
  root.querySelectorAll('.decision-actions button').forEach(b => b.disabled = true);
  try {
    await api('/api/matching-decide', {bank_id:activeId,action,note:$('#decision-note').value.trim(),
      binding:reviewData.binding,version:reviewData.version,acknowledged:$('#acknowledge').checked,
      allocations:[...selected].map(([item_id, amount]) => ({item_id,amount}))});
    persisted = true;
    await refresh(); saving = false; chooseBank(activeId);
    toast(action === 'undo' ? 'Decision undone. Amounts are available again.' : 'Decision saved.');
  } catch (e) { error(e.message); $('#save-status').textContent = persisted ? 'Decision saved, but refresh failed. Reload to see the latest state.' : 'Decision was not saved. Your draft is still here.'; }
  finally { saving = false; root.querySelectorAll('.decision-actions button').forEach(b => b.disabled = false); updateSummary(); }
}
async function showEvidence(kind, id) {
  /* Ignore late responses when the reviewer switches documents quickly. */
  const serial = ++previewSerial, query = new URLSearchParams({kind,id});
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
function changeTab(documents) {
  /* Both views read the same ledger and remaining balances. */
  $('#bank-view').hidden = documents; $('#document-view').hidden = !documents;
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
  const previous = preference('filter', 'all');
  $('#bank-filter').value = previous;
  if (!$('#bank-filter').value) $('#bank-filter').value = 'all';
  $('#confidence-filter').value = preference('confidence', {strong:'high', tentative:'low', none:'none'}[previous] || 'all');
  if (!$('#confidence-filter').value) $('#confidence-filter').value = 'all';
  $('#bank-query').value = preference('query', '');
  try {
    token = (await api('/api/session')).token; await refresh();
    const rows = visibleBanks(), remembered = preference('active', '');
    const initial = rows.find(b => b.id === remembered) || rows[0] || reviewData.banks[0];
    if (initial) chooseBank(initial.id);
  } catch (e) { error(e.message); }
}
$('#bank-query').oninput = () => { remember('query', $('#bank-query').value); renderQueue(); };
$('#bank-filter').onchange = () => { remember('filter', $('#bank-filter').value); renderQueue(); };
$('#confidence-filter').onchange = () => { remember('confidence', $('#confidence-filter').value); renderQueue(); };
$('#decision-note').oninput = updateSummary;
$('#candidate-query').oninput = renderCandidates; $('#all-candidates').onchange = renderCandidates;
$('#candidate-picker').ontoggle = () => { if (reviewData && activeId) renderCandidates(); };
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
