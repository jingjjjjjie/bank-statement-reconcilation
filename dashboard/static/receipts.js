/* Keep receipt pieces separate until a reviewer explicitly allocates them. */
let receiptData = null, receiptBusy = false;
const emptyPiece = () => ({location:'', document_type:'', invoice_numbers:[], brief_description:'', total:'', currency:'', limitations:[]});

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
  finally { receiptBusy = false; }
}

async function loadReceiptResults() {
  /* Reload saved extraction and allocation state only on explicit refresh. */
  const [session, data] = await Promise.all([api('/api/session'), api('/api/receipts')]);
  token = session.token;
  setReceiptData(data);
}

function setReceiptData(data) {
  /* Retain selected document and transaction while refreshing saved results. */
  const unit = $('#receipt-unit')?.value || new URLSearchParams(location.search).get('unit');
  receiptData = data;
  if ($('#receipt-unit')) {
  $('#receipt-unit').replaceChildren(...data.units.map(item => new Option(
    `${item.source_path.split(/[\\/]/).pop()} / ${item.label}`, item.key)));
  const selected = data.units.find(item => item.key === unit) || data.units.find(item => item.document_id === unit?.split(':')[0]);
  if (selected) $('#receipt-unit').value = selected.key;
  showReceiptUnit();
  }
  if ($('#receipt-bank')) { renderReceiptBanks(); renderSavedMatches(); }
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
    const label = node('label', '', ' Boundaries need review');
    const flag = node('input'); flag.type = 'checkbox'; flag.dataset.boundaryReview = 'true';
    flag.checked = piece.needs_review !== false; label.prepend(flag); card.append(label);
  }
  card.append(node('legend', '', 'Separate receipt / supporting piece'));
  receiptField(card, 'Location in image or page', 'location', piece.location);
  receiptField(card, 'Document type', 'document_type', piece.document_type);
  receiptField(card, 'Invoice numbers (one per line)', 'invoice_numbers', piece.invoice_numbers, true);
  receiptField(card, 'Short description', 'brief_description', piece.brief_description);
  receiptField(card, 'Printed total', 'total', piece.total);
  receiptField(card, 'Currency (for example MYR)', 'currency', piece.currency);
  receiptField(card, 'Limitations (one per line)', 'limitations', piece.limitations, true);
  card.splitPiece = () => {
    const pieces = readReceiptPieces(), position = [...$('#receipt-pieces').children].indexOf(card);
    const original = pieces[position];
    pieces.splice(position, 1, {...original, total:'', needs_review:true}, {...emptyPiece(), source_units:original.source_units, needs_review:true});
    $('#receipt-pieces').replaceChildren(); pieces.forEach(addReceiptPiece);
    $('#receipt-unit-status').textContent = 'Set the source locations and printed totals for both pieces, then resolve the boundary flags.';
  };
  $('#receipt-pieces').append(card);
}

function showReceiptUnit() {
  /* Show every individual piece beneath its original source reference. */
  const unit = receiptData?.units.find(item => item.key === $('#receipt-unit').value);
  $('#receipt-pieces').replaceChildren();
  $('#receipt-form').hidden = !unit; $('#receipt-original').hidden = !unit;
  if (!unit) { if (typeof clearOriginal === 'function') clearOriginal(); $('#receipt-unit-status').textContent = 'No extracted receipt units yet. Run documents, then load the results.'; return; }
  $('#receipt-original').href = `/api/content-file?id=${encodeURIComponent(unit.document_id)}`;
  $('#receipt-unit-status').textContent = unit.accepted ? 'Extraction accepted.' : unit.needs_refresh
    ? 'Older extraction has no separate receipt records. Re-extract or enter pieces after checking the original.'
    : '';
  if (unit.assembled) {
    $('#receipt-unit-status').textContent += ' ' + unit.source_units.map(source => `${source.number}: ${source.label}`).join(' | ');
    if (unit.assembly_pending) $('#receipt-unit-status').textContent = 'Waiting for document receipt assembly. Run documents to continue.';
    else if (unit.limitations?.length) $('#receipt-unit-status').textContent += ' Limitations: ' + unit.limitations.join('; ');
  }
  $('#receipt-form').querySelector('[type=submit]').disabled = !!unit.assembly_pending;
  for (const piece of unit.receipts) addReceiptPiece(piece);
  if (typeof showOriginal === 'function') showOriginal(unit).catch(receiptError);
}

function readReceiptPieces() {
  /* Read the corrected pieces with empty strings and lists preserved. */
  return [...$('#receipt-pieces').children].map(card => {
    const piece = structuredClone(card.receiptPiece || emptyPiece());
    for (const input of card.querySelectorAll('[data-field]')) {
      const key = input.dataset.field;
      if (key === 'source_units') { piece[key] = input.value.split(/[\s,]+/).filter(Boolean).map(Number); continue; }
      piece[key] = Array.isArray(piece[key]) ? input.value.split('\n').map(value => value.trim()).filter(Boolean) : input.value.trim();
    }
    const flag = card.querySelector('[data-boundary-review]');
    if (flag) piece.needs_review = flag.checked;
    else { delete piece.source_units; delete piece.needs_review; }
    return piece;
  });
}

function renderReceiptBanks() {
  /* Search bank facts while preserving the selected transaction when possible. */
  const selected = $('#receipt-bank').value, query = $('#receipt-bank-search').value.toLowerCase();
  const banks = receiptData.transactions.filter(bank =>
    `${bank.date} ${bank.amount} ${bank.counterparty} ${bank.narration}`.toLowerCase().includes(query));
  $('#receipt-bank').replaceChildren(...banks.map(bank => new Option(
    `${bank.date} / ${bank.direction} / ${bank.currency} ${bank.amount} / ${bank.counterparty || bank.narration}`, bank.transaction_id)));
  if (banks.some(bank => bank.transaction_id === selected)) $('#receipt-bank').value = selected;
  showReceiptBank();
}

function showReceiptBank() {
  /* Offer independently approved pieces with their remaining allocation amounts. */
  const bank = receiptData?.transactions.find(item => item.transaction_id === $('#receipt-bank').value);
  $('#receipt-allocations').replaceChildren(); $('#receipt-proposal').replaceChildren();
  $('#receipt-match-form').hidden = !bank;
  $('#receipt-bank-detail').textContent = bank ? `${bank.currency} ${bank.amount} / ${bank.narration}` : 'Extract the bank statement to create matches.';
  if (!bank) return;
  const available = receiptData.receipts.filter(item => item.accepted && item.currency === bank.currency && Number(item.remaining_amount) > 0);
  for (const receipt of available) {
    const row = node('div', 'settings-card'); row.dataset.receiptId = receipt.receipt_id;
    const label = node('label'), checkbox = node('input'); checkbox.type = 'checkbox';
    label.append(checkbox, document.createTextNode(` ${receipt.brief_description || 'Supporting piece'} / ${receipt.location || 'Location unspecified'} / ${receipt.currency} ${receipt.total}`));
    const allocation = node('input'); allocation.value = receipt.remaining_amount; allocation.inputMode = 'decimal';
    allocation.setAttribute('aria-label', `Allocate amount for ${receipt.brief_description || receipt.receipt_id}`);
    const source = node('a', '', 'Open original'); source.href = `/api/content-file?id=${encodeURIComponent(receipt.document_id)}`;
    source.target = '_blank'; source.rel = 'noopener';
    row.append(label, node('p', '', `Already allocated: ${receipt.allocated_amount}. Remaining: ${receipt.remaining_amount}.`), allocation, source);
    $('#receipt-allocations').append(row);
  }
  if (!available.length) $('#receipt-allocations').append(node('p', '', 'No accepted receipts with available amounts in this currency. Review missing fields above.'));
  const existing = receiptData.matches.find(match => match.bank_transaction_id === bank.transaction_id);
  if (existing) $('#receipt-proposal').append(matchCard(existing));
}

function matchCard(match) {
  /* Present Python-calculated totals and require a separate acceptance click. */
  const card = node('section', 'settings-card');
  card.append(node('h3', '', `${match.currency} ${match.bank_amount} bank transaction`));
  for (const item of match.supporting_items) card.append(node('p', '', `${item.brief_description || item.receipt_id} / ${item.location} / ${match.currency} ${item.allocated_amount}`));
  card.append(node('p', '', `Supporting total: ${match.currency} ${match.supporting_total}`),
    node('p', match.difference !== '0' && Number(match.difference) !== 0 ? 'validation' : '', `Difference: ${match.currency} ${match.difference}`),
    node('p', '', `${match.review_status}${match.stale ? ' / Evidence changed: undo and review again.' : ''}`));
  if (match.reason) card.append(node('p', '', `Notes: ${match.reason}`));
  const actions = match.review_status === 'accepted' ? [['undo','Undo match']] : match.review_status === 'pending'
    ? [...(match.stale ? [] : [['accept','Accept match']]), ['reject','Reject proposal']] : [];
  for (const [action,label] of actions) {
    const button = node('button', 'button secondary', label); button.type = 'button';
    button.onclick = () => receiptAction(async () => setReceiptData(await api('/api/receipts/match', {
      revision:receiptData.revision, bank_transaction_id:match.bank_transaction_id, action,
      reviewer:$('#receipt-reviewer').value, reason:$('#receipt-match-reason').value,
    })));
    card.append(button);
  }
  return card;
}

function renderSavedMatches() {
  /* Show persistent combined and separate matches, including rejected history heads. */
  $('#receipt-saved-matches').replaceChildren(...receiptData.matches.map(matchCard));
}

if ($('#receipt-unit')) $('#receipt-unit').onchange = showReceiptUnit;
if ($('#add-receipt')) $('#add-receipt').onclick = () => addReceiptPiece();
if ($('#receipt-bank-search')) $('#receipt-bank-search').oninput = renderReceiptBanks;
if ($('#receipt-bank')) $('#receipt-bank').onchange = showReceiptBank;
$('#reload-receipts').onclick = () => receiptAction(loadReceiptResults);
if ($('#receipt-form')) $('#receipt-form').onsubmit = event => {
  event.preventDefault();
  receiptAction(async () => {
    const key = $('#receipt-unit').value;
    const data = await api('/api/receipts/accept', {
      revision:receiptData.revision, key, receipts:readReceiptPieces(),
    });
    extractionDirty = false;
    setReceiptData(data);
    const next = data.units.find(item => !item.accepted && item.key !== key);
    if (next) { $('#receipt-unit').value = next.key; showReceiptUnit(); }
    toast(next ? 'Extraction accepted. Next item opened.' : 'Extraction accepted. All available items reviewed.');
  });
};
if ($('#receipt-match-form')) $('#receipt-match-form').onsubmit = event => {
  event.preventDefault();
  receiptAction(async () => {
    const selected = [...$('#receipt-allocations').querySelectorAll('[data-receipt-id]')]
      .filter(row => row.querySelector('[type=checkbox]').checked)
      .map(row => ({receipt_id:row.dataset.receiptId, allocated_amount:row.querySelector('input:not([type=checkbox])').value}));
    setReceiptData(await api('/api/receipts/match', {revision:receiptData.revision,
      bank_transaction_id:$('#receipt-bank').value, action:'propose', supporting_items:selected,
      reviewer:$('#receipt-reviewer').value, reason:$('#receipt-match-reason').value}));
  });
};
if ($('#run-documents')) $('#run-documents').onclick = () => receiptAction(async () => {
  setDocumentRequestMessage(documentState.prepared ? 'Starting document processing...' : 'Preparing document pages...');
  try {
    if (!documentState.prepared) await api('/api/content/prepare', {});
    setDocumentRequestMessage('Starting document processing...');
    await api('/api/content/run', {});
    await refreshDocuments();
  } finally { setDocumentRequestMessage(''); }
});
if ($('#stop-documents')) $('#stop-documents').onclick = () => receiptAction(async () => {
  setDocumentRequestMessage('Stopping document processing...');
  try { await api('/api/content/stop', {}); await refreshDocuments(); }
  finally { setDocumentRequestMessage(''); }
});
loadReceiptResults().catch(receiptError);
