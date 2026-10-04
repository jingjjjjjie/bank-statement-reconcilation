import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';
import { evidenceLocation } from '../evidenceLocation.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, navigate, routeQuery } = page;
let token;
/* Present cached evidence; Python validates and persists every human decision. */
let reviewData, activeId, saving = false, previewSerial = 0, previewState;
let savedDraft = '', transactionPage = 0;
const expandedCandidates = new Set(), expandedAllocations = new Set(), returnedCandidates = new Set();
const selected = new Map(), allocationRoles = new Map(), allocationAmounts = new Map();
function allocationRole(id) {
  /* Preserve an explicit money role while its amount field is temporarily empty. */
  return allocationRoles.get(id) || (selected.get(id) === '' ? 'support' : 'money');
}
function draftSnapshot() {
  /* Track unsaved allocations independently of display preferences. */
  return JSON.stringify({allocations: [...selected].map(([id, amount]) => [id, amount, allocationRole(id)])});
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
  $('#matching-load-note').hidden = !!reviewData.live_pieces;
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
    const number = rows.indexOf(b) + 1;
    const finished = ['approved', 'denied'].includes(b.review_status) && !b.stale;
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
    activeId = null; selected.clear(); allocationRoles.clear(); allocationAmounts.clear(); savedDraft = draftSnapshot();
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
function chooseBank(id, addItem, preservePreview = false) {
  /* Start a draft from this transaction's saved choice, or its cached proposal. */
  if (saving) return;
  activeId = id; selected.clear(); allocationRoles.clear(); allocationAmounts.clear(); error();
  expandedCandidates.clear(); expandedAllocations.clear(); returnedCandidates.clear();
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
  $('#approve-match').textContent = b.review_status === 'approved' ? 'Save & next' : 'Confirm & next';
  const detail = $('#transaction-detail'); detail.replaceChildren();
  const header = node('div', 'transaction-header');
  const party = node('div', 'transaction-party');
  party.append(node('span', 'transaction-direction', b.direction === 'in' ? 'Pay from' : 'Pay to'),
    node('h2', 'transaction-title', b.parties.join(' / ') || 'Party unknown'));
  header.append(party, node('strong', 'bank-amount', formatMoney(b.amount, b.currency)));
  const meta = node('div', 'bank-meta');
  meta.title = b.id;
  const status = {pending: 'Awaiting review', approved: 'Approved', denied: 'Rejected'}[b.review_status] || b.review_status;
  meta.append(node('span', 'payment-date', `Payment date: ${b.date || 'Not provided'}`),
    node('span', `payment-tag review-state ${b.review_status}`, status));
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
  if (!preservePreview) { if (first) showEvidence('item', first); else showEvidence('bank', id); }
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
  /* Render matching supporting pieces in one scrollable list. */
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
  $('#candidate-count').textContent = items.length ? `${items.length} candidates` : 'No candidates';
  for (const item of [...selected.keys()].map(id => itemById.get(id)).filter(Boolean).concat(items)) {
    const card = node('article', `candidate-card ${selected.has(item.id) ? 'selected' : ''}`);
    card.classList.toggle('suggested', suggested.has(item.id));
    if (suggested.has(item.id)) card.dataset.confidence = b.confidence.level || 'none';
    card.dataset.itemId = item.id;
    card.setAttribute('aria-label', `Candidate ${item.id}`);
    if (previewState?.kind === 'item' && previewState.id === item.id) card.classList.add('previewing');
    const isSelected = selected.has(item.id);
    card.dataset.role = isSelected ? allocationRole(item.id) : b.suggestion.allocations.some(a => a.item_id === item.id && a.amount === '') ? 'support' : 'money';
    const control = isSelected ? button('\u00d7', () => {
      selected.delete(item.id); allocationRoles.delete(item.id); allocationAmounts.delete(item.id); returnedCandidates.add(item.id);
      $('#candidate-query').value = '';
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
    const documentAmount = node('strong', 'candidate-amount', formatMoney(item.amount, item.currency));
    documentAmount.prepend(node('small', 'document-amount-label', 'Document amount'));
    summary.append(node('span', 'candidate-name', item.parties.join(' / ') || 'Party unknown'), documentAmount);

    details.append(summary);
    details.ontoggle = () => {
      if (details.open) {
        const newlyOpened = !expandedCandidates.has(item.id);
        expandedCandidates.add(item.id);
        if (newlyOpened) showEvidence('item', item.id);
      } else expandedCandidates.delete(item.id);
    };
    const body = node('div', 'candidate-body');
    const source = node('details', 'source-details candidate-source');
    const meta = node('div', 'candidate-meta');
    if (suggested.has(item.id)) {
      meta.append(node('span', 'candidate-confidence', confidenceLabel[b.confidence.level || 'none']));
      if (b.suggestion.reason) source.append(node('p', 'candidate-reason', b.suggestion.reason));
    }
    source.prepend(node('summary', '', 'Details'));
    if (item.description) source.append(node('p', 'candidate-description', item.description));
    const dates = item.dates?.length ? item.dates.map(d => typeof d === 'string' ? d : d.value).join(', ') : item.date;
    source.append(node('p', 'candidate-info', [dates, item.filename, item.location].filter(Boolean).join(' / ')));
    const retrievalReason = b.evidence_reasons?.[item.id];
    if (retrievalReason) source.append(node('p', 'candidate-reason', retrievalReason));
    meta.append(source); body.append(meta);
    if (item.currency === b.currency && cents(item.amount) !== null && cents(item.amount) !== cents(b.amount)) body.append(node('p', 'warning', `Bank minus source: ${formatMoney(((cents(b.amount) - cents(item.amount)) / 100).toFixed(2), b.currency)}`));
    if (item.used !== '0') body.append(node('p', 'warning', `Reserved: ${formatMoney(item.used, item.currency)} · Available here: ${available(item) === null ? 'unknown' : formatMoney((available(item) / 100).toFixed(2), item.currency)}`));
    if (item.stale) body.append(node('p', 'warning', 'Source changed or unavailable. Approval blocked.'));
    if (item.boundary_unresolved) body.append(node('p', 'warning', 'Check receipt boundaries against the original.'));
    details.append(body);
    const content = node('div', 'candidate-content'); content.append(details);
    const proposal = b.suggestion.allocations.find(a => a.item_id === item.id);
    if (proposal) content.append(node('p', 'suggested-allocation', proposal.amount === ''
      ? `Suggested: Supporting only (${formatMoney('0', b.currency)} allocated)`
      : `Suggested allocation: ${formatMoney(proposal.amount, b.currency)}`));
    const actions = node('div', 'candidate-bottom candidate-actions');
    if (isSelected) {
      const editor = node('details', 'allocation-editor'), toggle = node('summary', '', 'Edit allocation');
      toggle.setAttribute('aria-label', `Edit allocation ${item.id}`);
      editor.open = expandedAllocations.has(item.id);
      editor.ontoggle = () => { if (editor.open) expandedAllocations.add(item.id); else expandedAllocations.delete(item.id); };
      editor.append(toggle, allocationControls(item)); actions.append(editor);
    }
    actions.append(button('Show', () => showEvidence('item', item.id), 'candidate-preview show-evidence'));
    content.append(actions);
    card.append(control, content); (isSelected ? tray : list).append(card);
  }
  if (!items.length) list.append(node('p', 'empty-state', 'No candidates found. Search all pieces or change your search.'));
}
function allocationControls(item) {
  /* Change the draft role explicitly; supporting evidence is serialized as an empty amount. */
  const controls = node('div', 'allocation-controls');
  const roleLabel = node('label', 'allocation-label', 'Use as'), role = node('select');
  role.setAttribute('aria-label', `Use as ${item.id}`);
  const monetary = node('option', '', 'Counts toward amount'); monetary.value = 'money';
  monetary.disabled = !item.currency || item.currency !== bank().currency || !(cents(item.amount) > 0) || !(available(item) > 0);
  const supporting = node('option', '', 'Supporting only'); supporting.value = 'support';
  role.append(monetary, supporting); role.value = allocationRole(item.id); roleLabel.append(role);
  const label = node('label', 'allocation-label', `Allocation (${bank().currency || 'currency unknown'})`);
  const input = node('input'); input.type = 'text'; input.inputMode = 'decimal'; input.value = selected.get(item.id);
  input.setAttribute('aria-label', `Allocation ${item.id}`);
  label.hidden = role.value === 'support'; label.append(input);
  const note = node('span', 'allocation-note', 'No amount allocated'); note.hidden = role.value !== 'support';
  role.onchange = () => {
    if (role.value === 'support') {
      allocationAmounts.set(item.id, selected.get(item.id)); selected.set(item.id, '');
    } else selected.set(item.id, allocationAmounts.get(item.id) ?? defaultAllocation(item));
    allocationRoles.set(item.id, role.value);
    input.value = selected.get(item.id); label.hidden = role.value === 'support'; note.hidden = !label.hidden;
    updateSummary();
  };
  input.oninput = () => { selected.set(item.id, input.value.trim()); updateSummary(); };
  controls.append(roleLabel, label, note);
  return controls;
}
function updateSummary() {
  /* Make incomplete, excessive or invalid allocations visible before submitting. */
  const b = bank(), values = [...selected.values()], total = values.reduce((sum, v) => sum + (cents(v) || 0), 0), difference = cents(b.amount) - total;
  root.querySelectorAll('.candidate-card').forEach(card => {
    const id = card.dataset.itemId, proposal = b.suggestion.allocations.find(a => a.item_id === id);
    card.dataset.role = selected.has(id) ? allocationRole(id) : proposal?.amount === '' ? 'support' : 'money';
  });
  const invalidAmount = [...selected].some(([id, value]) => allocationRole(id) === 'money' && (cents(value) === null || cents(value) <= 0));
  const summary = $('#selection-summary'); summary.replaceChildren();
  summary.classList.toggle('balanced', difference === 0 && !invalidAmount);
  summary.append(node('strong', '', `${selected.size} selected · ${formatMoney((total / 100).toFixed(2), b.currency)} allocated`));
  summary.append(node('div', difference ? 'difference' : '', difference === 0 ? 'The allocation equals the bank payment.' : `Difference: ${formatMoney((difference / 100).toFixed(2), b.currency)}`));
  if ([...selected.keys()].some(id => allocationRole(id) === 'support')) summary.append(node('div', 'allocation-note', 'Supporting-only documents do not add to the allocated amount.'));
  if (values.some(v => v !== '' && cents(v) === null)) summary.append(node('div', 'warning', 'Enter valid amounts with up to two decimal places.'));
  if ([...selected.keys()].filter(id => allocationRole(id) === 'money').length > 1) summary.append(node('div', 'warning', 'Check that the documents represent separate expenses, not an invoice and its payment proof.'));
  const flagged = difference !== 0 || selected.size > 1 || [...selected].some(([id, value]) => value === '' || itemById.get(id).boundary_unresolved || (cents(value) !== null && cents(value) < cents(itemById.get(id).amount)));
  summary.hidden = !flagged || !selected.size;
  const unchanged = draftSnapshot() === savedDraft;
  $('#support-heading').textContent = 'Available candidates';
  $('#support-status').textContent = b.decision && unchanged
    ? `${b.support_status}. ${b.review_status === 'denied' ? 'Suggestion rejected; other evidence may exist.' : 'Saved review decision.'}`
    : `${selected.size} selected · Not confirmed`;
  $('#approve-match').textContent = difference === 0 && values.some(v => v !== '') ? 'Confirm supporting' : 'Save partial / contextual evidence';
  const missingAmount = [...selected].some(([id, value]) => allocationRole(id) === 'money' && !value);
  if (missingAmount) summary.append(node('div', 'warning', 'Enter an allocation amount or choose Supporting only.'));
  root.querySelectorAll('.allocation-controls input, .allocation-controls select').forEach(control => control.disabled = saving);
  $('#approve-match').disabled = missingAmount || saving || !selected.size || b.stale || difference < 0 || values.some(v => v !== '' && (cents(v) === null || cents(v) <= 0));
}
async function saveDecision(action) {
  /* Send explicit user intent, then reload the authoritative ledger and balances. */
  if (saving) return;
  saving = true; error(); $('#save-status').textContent = 'Saving your decision…';
  updateSummary();
  const queue = visibleBanks(), position = queue.findIndex(row => row.id === activeId);
  const nextId = action === 'approve' ? queue[position + 1]?.id : null;
  let persisted = false;
  root.querySelectorAll('.decision-actions button').forEach(b => b.disabled = true);
  try {
    const result = await api('/api/matching-decide', {bank_id:activeId,action,note:bank().decision?.note || '',
      binding:reviewData.binding,version:reviewData.version,
      allocations:[...selected].map(([item_id, amount]) => ({item_id,amount}))});
    persisted = true;
    reviewData.version = result.version; reviewData.binding = result.binding;
    Object.assign(bank(), result.bank);
    result.items.forEach(item => Object.assign(itemById.get(item.id), item));
    saving = false; chooseBank(nextId || activeId, undefined, !nextId);
    renderBankPicker(); renderUnmatched();
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
    const location = kind === 'item' ? evidenceLocation(itemById.get(id), info) : {page: bank().page};
    previewState = {kind,id,info,location};
    const select = $('#preview-page'); select.replaceChildren();
    info.labels.forEach((label, n) => { const option = node('option', '', label); option.value = n; select.append(option); });
    const preferred = location.page;
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
      renderOfficePreview(target, data, n === previewState.location.page ? previewState.location.highlight : null);
      target.querySelector('.source-cell-highlight')?.scrollIntoView({block:'center', inline:'center'});
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
  renderCandidates();
  (panel.hidden ? control : $('#candidate-query')).focus();
}
$('#toggle-candidate-search').onclick = toggleCandidateSearch;
$('#candidate-query').onkeydown = event => { if (event.key === 'Escape') { event.preventDefault(); toggleCandidateSearch(); } };
$('#candidate-query').oninput = () => { renderCandidates(); $('#candidate-list').scrollTop = 0; };
$('#restore-suggestion').onclick = () => { selected.clear(); allocationRoles.clear(); allocationAmounts.clear(); bank().suggestion.allocations.forEach(a => selected.set(a.item_id, a.amount)); renderCandidates(); updateSummary(); };
$('#approve-match').onclick = () => saveDecision('approve'); $('#deny-match').onclick = () => saveDecision('deny'); $('#undo-match').onclick = () => saveDecision('undo');
$('#preview-bank').onclick = () => { if (activeId) showEvidence('bank', activeId); };
$('#preview-page').onchange = () => renderEvidencePage();
$('#preview-prev').onclick = () => { $('#preview-page').selectedIndex--; renderEvidencePage(); };
$('#preview-next').onclick = () => { $('#preview-page').selectedIndex++; renderEvidencePage(); };
$('#bank-tab').onclick = () => changeTab(false); $('#document-tab').onclick = () => changeTab(true); $('#document-query').oninput = renderUnmatched;
$('#unmatched-bank-query').oninput = renderBankPicker;
initialize();


let matchingWasRunning = false;
async function matchingProgress() {
  /* Refresh completed proposals without displaying job controls on the review page. */
  if (!reviewData?.live_pieces) return;
  const state = await api('/api/matching-run');
  if (matchingWasRunning && !state.running && draftSnapshot() === savedDraft) {
    await refresh(); if (activeId) chooseBank(activeId);
  }
  matchingWasRunning = !!state.running;
}
pollVisible(matchingProgress, 2000);
page.onLive(['/api/matching']);
page.onRefresh(async () => { await refresh(); if (activeId) chooseBank(activeId, undefined, true); }, ['/api/matching-decide', '/api/matching-pieces', '/api/matching-run', '/api/receipts/', '/api/content/']);
}
