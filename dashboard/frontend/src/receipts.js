import { node } from './dom.js';

// Share receipt editing between views without global variables.
export function installReceipts(page, hooks = {}) {
const { $, api, toast } = page;
let token;
/* Keep receipt pieces separate until a reviewer explicitly allocates them. */
let receiptData = null, receiptBusy = false;
let regenerationJobs = {};
const relevanceLabels = {potential_support:'Potential supporting document', not_supporting:'Clearly unrelated', uncertain:'Relevance uncertain'};
if ($('#regeneration-status')) {
  const evidence = node('div'); evidence.id = 'supporting-evidence';
  $('#receipt-unit-status').after(evidence);
}
const emptyPiece = () => ({location:'', document_type:'', invoice_numbers:[], payee:'', references:[], dates:[], amount_basis:'', brief_description:'', total:'', currency:'', limitations:[]});

function receiptError(error) {
  /* Keep action failures visible without discarding edited fields. */
  $('#receipt-error').textContent = error.message;
  $('#receipt-error').hidden = false;
}

async function receiptAction(task) {
  /* Serialize local actions; the server also checks evidence revisions. */
  if (receiptBusy) return;
  receiptBusy = true; $('#receipt-error').hidden = true;
  try { await task(); } catch (error) { receiptError(error); }
  finally { receiptBusy = false; renderRegeneration(); }
}

async function saveReceiptDecision(path, body, button) {
  /* Keep edits stable until the server confirms an explicit review decision. */
  const label = button.textContent;
  const controls = [...page.root.querySelectorAll('button, input, select, textarea')];
  const disabled = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  button.textContent = 'Saving…'; button.setAttribute('aria-busy', 'true');
  try { return await api(path, body); }
  finally {
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
    button.textContent = label; button.removeAttribute('aria-busy');
  }
}

async function loadReceiptResults() {
  /* Reload saved extraction and allocation state only on explicit refresh. */
  const [session, data] = await Promise.all([api('/api/session'), api('/api/receipts')]);
  token = session.token;
  setReceiptData(data);
}

function setReceiptData(data, selectedKey) {
  /* Retain selected document and transaction while refreshing saved results. */
  const unit = selectedKey ?? ($('#receipt-unit')?.value || new URLSearchParams(page.routeQuery()).get('unit'));
  receiptData = data;
  for (const item of data.units) {
    if (item.regeneration) regenerationJobs[item.document_id] = item.regeneration;
  }
  if ($('#receipt-unit')) {
  selectReceiptUnit(unit || data.units[0]?.key);
  }
}

function selectReceiptUnit(key, force = true) {
  /* Open only the requested document, including assembled multi-page results. */
  const selected = receiptData?.units.find(item => item.key === key) ||
    receiptData?.units.find(item => item.document_id === key?.split(':')[0]);
  const value = key ? selected?.key || '' : $('#receipt-unit').value;
  if (!force && $('#receipt-unit').value === value) return;
  $('#receipt-unit').value = value;
  showReceiptUnit();
}

function receiptField(card, label, key, value, multiline=false) {
  /* Render an editable factual field without filling missing values. */
  const wrapper = node('label', 'setting-field', label);
  const input = node(multiline ? 'textarea' : 'input');
  input.dataset.field = key; input.value = Array.isArray(value) ? value.join('\n') : value;
  wrapper.append(input); card.append(wrapper);
}

function addReceiptPiece(piece=emptyPiece()) {
  /* Let the reviewer correct a model split without changing original images. */
  const card = node('fieldset', 'settings-card');
  card.receiptPiece = structuredClone(piece);
  const unit = receiptData?.units.find(item => item.key === $('#receipt-unit').value);
  if (unit?.assembled) {
    receiptField(card, 'Source unit numbers (one per line; see page labels above)', 'source_units', piece.source_units || [], true);
  }
  card.append(node('legend', '', 'Separate receipt / supporting piece'));
  receiptField(card, 'Location in image or page', 'location', piece.location);
  receiptField(card, 'Piece type', 'document_type', piece.document_type);
  receiptField(card, 'Payee', 'payee', piece.payee || '');
  receiptField(card, 'References (type: value)', 'references', (piece.references || (piece.invoice_numbers || []).map(value => ({type:'invoice', value}))).map(r => `${r.type}: ${r.value}`), true);
  receiptField(card, 'Dates / periods (type: value)', 'dates', (piece.dates || []).map(r => `${r.type}: ${r.value}`), true);
  receiptField(card, 'Short description', 'brief_description', piece.brief_description);
  receiptField(card, 'Printed total', 'total', piece.total);
  receiptField(card, 'Amount basis', 'amount_basis', piece.amount_basis || '');
  receiptField(card, 'Currency', 'currency', piece.currency);
  $('#receipt-pieces').append(card);
}

function showReceiptUnit() {
  /* Show every individual piece beneath its original source reference. */
  const unit = receiptData?.units.find(item => item.key === $('#receipt-unit').value);
  $('#receipt-pieces').replaceChildren();
  $('#receipt-form').hidden = !unit && !$('#document-review-status'); $('#receipt-original').hidden = !unit;
  $('#add-receipt').disabled = !unit || !!unit.trash;
  renderRegeneration();
  if ($('#supporting-evidence')) $('#supporting-evidence').replaceChildren(...(unit?.supporting_evidence || []).map(item =>
    node('p', '', `${item.label}: ${relevanceLabels[item.status] || 'Relevance uncertain'}${item.reason ? ' — ' + item.reason : ''}`)));
  if (!unit) { if (hooks.clearOriginal) hooks.clearOriginal(); $('#receipt-unit-status').textContent = 'No extracted receipt units yet. Run documents, then load the results.'; return; }
  $('#receipt-original').href = `/api/content-file?id=${encodeURIComponent(unit.document_id)}`;
  if ($('#receipt-original').hasAttribute('download')) $('#receipt-original').download = unit.source_path.split(/[\\/]/).pop();
  $('#receipt-unit-status').textContent = unit.accepted ? ($('#document-review-status') ? '' : 'Extraction accepted.') : unit.needs_refresh
    ? 'Older extraction has no separate receipt records. Re-extract or enter pieces after checking the original.'
    : '';
  if (unit.assembled) {
    $('#receipt-unit-status').textContent += ' ' + unit.source_units.map(source => `${source.number}: ${source.label}`).join(' | ');
    if (unit.assembly_pending) $('#receipt-unit-status').textContent = 'Waiting for document receipt assembly. Run documents to continue.';
  }
  if (unit.review_warnings?.length) $('#receipt-unit-status').textContent += ' ' + unit.review_warnings.join(' ');
  $('#receipt-form').querySelector('[type=submit]').disabled = !!unit.assembly_pending;
  $('#receipt-form').querySelector('[type=submit]').hidden = false;
  $('#add-receipt').hidden = false;
  if (unit.trash) {
    $('#receipt-unit-status').textContent = 'Trash — excluded from supporting evidence. Original file preserved.';
    $('#supporting-evidence')?.replaceChildren();
  } else for (const piece of unit.receipts) addReceiptPiece(piece);
  renderRegeneration();
  if (hooks.showOriginal) hooks.showOriginal(unit).catch(receiptError);
}

function renderReviewState() {
  /* Reflect saved review state, local edits and the actual next action. */
  const icon = $('#document-review-status'), button = $('#accept-receipts');
  if (!icon || !button || receiptBusy) return;
  const unit = receiptData?.units.find(item => item.key === $('#receipt-unit').value);
  const index = receiptData?.units.findIndex(item => item.key === unit?.key) ?? -1;
  $('#next-review-document').disabled = index < 0 || index + 1 >= receiptData.units.length;
  const dirty = page.isDirty();
  const job = regenerationJobs[unit?.document_id];
  const pending = unit?.assembly_pending || ['queued', 'running'].includes(job?.status);
  const failed = job?.status === 'failed';
  const state = !unit ? 'empty' : unit.trash ? 'trash' : pending ? 'pending' : failed ? 'failed'
    : dirty ? 'edited' : unit.accepted ? 'accepted' : 'unreviewed';
  const labels = {empty:'No document selected', trash:'Discarded', pending:'Extraction pending',
    failed:'Extraction failed', edited:'Unsaved changes', accepted:'Extraction accepted', unreviewed:'Not reviewed'};
  const symbols = {empty:'—', trash:'−', pending:'…', failed:'!', edited:'✎', accepted:'✓', unreviewed:'○'};
  icon.dataset.state = state;
  icon.textContent = symbols[state];
  icon.title = labels[state];
  icon.setAttribute('aria-label', labels[state]);
  const undo = !!unit?.accepted && !dirty;
  button.textContent = undo ? 'Undo accept' : 'Accept';
  button.title = pending ? 'Waiting for extraction' : failed ? 'Extraction unavailable'
    : unit?.trash ? 'Replace Discard with Accepted' : dirty ? 'Accept current changes' : button.textContent;
  button.classList.toggle('secondary', undo);
  button.classList.toggle('dark', !undo);
  button.disabled = !unit || !!pending || failed;
  $('#discard-document').textContent = unit?.trash ? 'Undo discard' : 'Discard';
  $('#discard-document').classList.toggle('restore-document', !!unit?.trash);

}

function renderRegeneration() {
  /* Update live progress without replacing edits or the original preview. */
  if (receiptBusy) return;
  renderReviewState();
  if (!$('#regeneration-status')) return;
  const unit = receiptData?.units.find(item => item.key === $('#receipt-unit').value);
  const job = regenerationJobs[unit?.document_id];
  const pending = ['queued', 'running'].includes(job?.status);
  if ($('#discard-document')) $('#discard-document').disabled = !unit || pending;
  const messages = {queued:'Queued for background extraction. You can continue browsing.',
    running:'Regenerating in the background. You can continue browsing.',
    completed:'Regeneration complete. Review the new result.', failed:`Regeneration unresolved: ${job?.error || 'Retry to finish.'}`};
  const count = Object.values(regenerationJobs).filter(item => ['queued', 'running'].includes(item.status)).length;
  $('#regeneration-status').textContent = (messages[job?.status] || '') + (count ? ` ${count} document(s) queued or regenerating.` : '');
  $('#regeneration-status').setAttribute('aria-busy', String(pending));
  if (unit && !$('#document-review-status')) $('#receipt-form').querySelector('[type=submit]').disabled = pending || !!unit.assembly_pending || job?.status === 'failed';
}

async function pollRegeneration() {
  /* Load fresh results on completion, preserving any unsaved edits elsewhere. */
  regenerationJobs = (await api('/api/receipts/regeneration')).jobs;
  renderRegeneration();
  const changed = receiptData?.units.some(unit => {
    const job = regenerationJobs[unit.document_id];
    return job?.status === 'completed' && (unit.regeneration?.id !== job.id || unit.regeneration?.status !== 'completed');
  });
  if (changed && !page.isDirty() && !receiptBusy) await loadReceiptResults();
  else if (changed && page.isDirty()) $('#regeneration-status').textContent += ' New results available; reload after saving or discarding edits.';
}

if ($('#regeneration-status')) {
  page.pollVisible(pollRegeneration, 1500);
}

function readReceiptPieces() {
  /* Read the corrected pieces with empty strings and lists preserved. */
  return [...$('#receipt-pieces').children].map(card => {
    const piece = structuredClone(card.receiptPiece || emptyPiece());
    for (const input of card.querySelectorAll('[data-field]')) {
      const key = input.dataset.field;
      if (key === 'references' || key === 'dates') {
        piece[key] = input.value.split('\n').map(value => value.trim()).filter(Boolean).map(value => {
          const split = value.indexOf(':');
          return split < 0 ? {type:'other', value} : {type:value.slice(0, split).trim() || 'other', value:value.slice(split + 1).trim()};
        });
        continue;
      }
      if (key === 'source_units') { piece[key] = input.value.split(/[\s,]+/).filter(Boolean).map(Number); continue; }
      piece[key] = Array.isArray(piece[key]) ? input.value.split('\n').map(value => value.trim()).filter(Boolean) : input.value.trim();
    }
    const assembled = receiptData?.units.find(unit => unit.key === $('#receipt-unit').value)?.assembled;
    if (piece.references) piece.invoice_numbers = piece.references.filter(r => r.type === 'invoice').map(r => r.value);
    delete piece.needs_review;
    if (!assembled) delete piece.source_units;
    return piece;
  });
}

if ($('#receipt-unit')) $('#receipt-unit').onchange = showReceiptUnit;
if ($('#add-receipt')) $('#add-receipt').onclick = () => addReceiptPiece();
if ($('#reload-receipts')) $('#reload-receipts').onclick = () => receiptAction(loadReceiptResults);
if ($('#accept-all-receipts')) $('#accept-all-receipts').onclick = () => receiptAction(async () => {
  /* Accept the loaded batch, carrying unsaved edits through the same validated write. */
  if (!receiptData) return;
  const key = $('#receipt-unit').value;
  const body = {revision:receiptData.revision};
  if (page.isDirty()) body.draft = {key, receipts:readReceiptPieces()};
  const data = await saveReceiptDecision('/api/receipts/accept-all', body, $('#accept-all-receipts'));
  hooks.saved?.();
  setReceiptData(data, key);
  const skipped = data.bulk.skipped.length;
  toast(`${data.bulk.accepted} accepted.${skipped ? ` ${skipped} still need attention.` : ''}`);
  if (skipped) receiptError(new Error(data.bulk.skipped.map(item => {
    const unit = data.units.find(unit => unit.key === item.key);
    return `${unit?.source_path.split('/').pop() || item.key}: ${item.reason}`;
  }).join('\n')));
});
if ($('#receipt-form')) $('#receipt-form').onsubmit = event => {
  event.preventDefault();
  receiptAction(async () => {
    const key = $('#receipt-unit').value;
    const unit = receiptData.units.find(item => item.key === key);
    if (unit.accepted && !page.isDirty()) {
      const data = await saveReceiptDecision('/api/receipts/undo-accept',
        {revision:receiptData.revision, key}, $('#accept-receipts'));
      hooks.saved?.();
      setReceiptData(data, key);
      toast('Acceptance undone. Corrections preserved.');
      return;
    }
    // Discarded entries are hidden, so retain their saved pieces when accepting.
    const body = {revision:receiptData.revision, key, receipts:unit.trash ? unit.receipts : readReceiptPieces()};
    const button = $('#accept-receipts') || $('#receipt-form [type=submit]');
    const data = await saveReceiptDecision('/api/receipts/accept', body, button);
    hooks.saved?.();
    setReceiptData(data, key);
    toast('Extraction accepted.');
  });
};
if ($('#discard-document')) $('#discard-document').onclick = () => receiptAction(async () => {
  /* Toggle discard while leaving direct acceptance available for discarded documents. */
  const key = $('#receipt-unit').value;
  const unit = receiptData.units.find(item => item.key === key);
  const action = unit.trash ? 'restore' : 'trash';
  const data = await saveReceiptDecision('/api/receipts/classify', {
    revision: receiptData.revision, key, action,
  }, $('#discard-document'));
  hooks.saved?.();
  setReceiptData(data, key);
  toast(action === 'trash' ? 'Classified as trash. Original file preserved.' : 'Document restored.');
});
if ($('#run-documents')) $('#run-documents').onclick = () => receiptAction(async () => {
  hooks.setDocumentRequestMessage(hooks.getDocumentState().prepared ? 'Starting document processing...' : 'Preparing document pages...');
  try {
    if (!hooks.getDocumentState().prepared) await api('/api/content/prepare', {});
    hooks.setDocumentRequestMessage('Starting document processing...');
    await api('/api/content/run', {});
    await hooks.refreshExecution();
    await hooks.refreshDocuments();
  } finally { hooks.setDocumentRequestMessage(''); }
});
if ($('#stop-documents')) $('#stop-documents').onclick = async () => {
  /* Stop must bypass the action queue, including an unfinished Start request. */
  hooks.setExecution({stop_requested: true});
  try { hooks.setExecution(await api('/api/content/stop', {})); }
  catch (error) { hooks.setExecution({stop_requested: false}); receiptError(error); }
};
if ($('#receipt-unit')) loadReceiptResults().catch(receiptError);

return {get data() { return receiptData; }, error: receiptError, showUnit: showReceiptUnit,
  selectUnit: selectReceiptUnit, reload: loadReceiptResults, refreshReview: renderReviewState};
}
