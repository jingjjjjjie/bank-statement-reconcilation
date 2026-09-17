/* Keep original evidence visible independently of editable extraction fields. */
let originalUnit, originalInfo, originalRequest = 0, extractionDirty = false, selectedUnit = '';

function clearOriginal() {
  /* Clear stale evidence when no extraction is selected. */
  originalRequest++;
  originalUnit = originalInfo = null;
  $('#original-preview').replaceChildren();
  $('#original-page').replaceChildren();
  $('#original-status').textContent = 'No extracted documents available yet.';
}

async function showOriginal(unit) {
  /* Select the matching source page and ignore superseded requests. */
  const request = ++originalRequest;
  selectedUnit = unit.key; extractionDirty = false;
  originalUnit = unit;
  originalInfo = null;
  $('#original-page').replaceChildren();
  $('#original-name').textContent = unit.source_path.split(/[\\/]/).pop();
  $('#original-status').textContent = 'Loading original…';
  $('#original-preview').replaceChildren();
  const info = await api(`/api/extraction-preview?id=${encodeURIComponent(unit.document_id)}`);
  if (request !== originalRequest) return;
  originalInfo = info;
  $('#original-page').replaceChildren(...info.labels.map((label, page) => new Option(label, page)));
  const number = /^(?:page|image) (\d+)/i.exec(unit.label);
  if (number) $('#original-page').value = String(Math.min(Number(number[1]) - 1, info.pages - 1));
  if (info.kind === 'spreadsheet') {
    const match = /^sheet (.*?) \(/i.exec(unit.label);
    const page = info.labels.findIndex(label => match && label.startsWith(match[1] + ' '));
    if (page >= 0) $('#original-page').value = String(page);
  }
  const embedded = info.labels.findIndex(label => label.startsWith('Embedded image: ') && unit.label.startsWith(label.slice(16)));
  if (embedded >= 0) $('#original-page').value = String(embedded);
  await renderOriginal();
}

async function renderOriginal() {
  /* Render Office structure, original images, or explicit fallback text safely. */
  if (!originalInfo || !originalUnit) return;
  const request = ++originalRequest, info = originalInfo, unit = originalUnit;
  const target = $('#original-preview'), page = Number($('#original-page').value || 0);
  target.replaceChildren();
  $('#original-status').textContent = 'Loading preview…';
  const office = ['word', 'spreadsheet'].includes(info.kind);
  if (office && page < info.office_pages) {
    const data = await api(`/api/office-view?content_id=${encodeURIComponent(unit.document_id)}&page=${page}`);
    if (request !== originalRequest) return;
    renderOfficePreview(target, data);
    $('#original-status').textContent = 'Structured document preview. Open the original for exact print formatting.';
  } else if (office || ['image', 'pdf'].includes(info.kind)) {
    const picture = node('img');
    picture.alt = `${$('#original-name').textContent}, ${info.labels[page]}`;
    picture.onload = () => { if (request === originalRequest) $('#original-status').textContent = info.labels[page]; };
    picture.onerror = () => { if (request === originalRequest) $('#original-status').textContent = 'Preview could not load. Open the original document.'; };
    picture.src = `/api/extraction-preview-image?id=${encodeURIComponent(unit.document_id)}&page=${page}`;
    target.append(picture);
  } else {
    if (info.kind === 'text') target.append(node('pre', '', info.text));
    $('#original-status').textContent = info.message || 'Original document text';
  }
}

$('#original-page').onchange = () => renderOriginal().catch(receiptError);
$('#original-zoom').onchange = event => { $('#original-preview').style.width = `${Number(event.target.value) * 100}%`; };
document.addEventListener('input', event => { if (event.target.closest('#receipt-pieces')) extractionDirty = true; });
document.addEventListener('click', event => { if (event.target.closest('#receipt-pieces button, #add-receipt')) extractionDirty = true; });
document.addEventListener('change', event => {
  if (event.target.id !== 'receipt-unit' || !extractionDirty) return;
  if (!confirm('Discard unsaved extraction changes?')) {
    event.stopImmediatePropagation(); event.target.value = selectedUnit;
  }
}, true);
document.addEventListener('click', event => {
  if (event.target.id === 'reload-receipts' && extractionDirty && !confirm('Discard unsaved extraction changes?')) event.stopImmediatePropagation();
}, true);
window.addEventListener('beforeunload', event => { if (extractionDirty) { event.preventDefault(); event.returnValue = ''; } });
