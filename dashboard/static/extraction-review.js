/* Keep original evidence visible independently of editable extraction fields. */
let originalUnit, originalInfo, originalRequest = 0, extractionDirty = false, selectedUnit = '';
let activePiece = 0, pieceDocument = '', previousPieceCount = 0;
let mediaZoom = 1, mediaDrag = null;
const mediaViewport = $('#original-viewport'), mediaPreview = $('#original-preview');
const mediaStage = node('div', 'original-stage');
mediaPreview.before(mediaStage); mediaStage.append(mediaPreview);
mediaViewport.title = 'Scroll to zoom · Drag to pan · Double-click to fit';

function layoutMedia() {
  /* Scale a fixed document layout instead of stretching or reflowing its container. */
  const bounds = mediaViewport.getBoundingClientRect();
  mediaPreview.style.width = `${bounds.width}px`;
  mediaPreview.style.height = mediaPreview.querySelector('img') ? `${bounds.height}px` : 'auto';
  mediaPreview.style.transform = `scale(${mediaZoom})`;
  mediaStage.style.width = `${bounds.width * mediaZoom}px`;
  mediaStage.style.height = `${Math.max(bounds.height, mediaPreview.scrollHeight) * mediaZoom}px`;
  mediaViewport.dataset.zoomed = String(mediaZoom > 1);
}

function zoomMedia(value, clientX, clientY) {
  /* Keep the same document point under the pointer while changing magnification. */
  const bounds = mediaViewport.getBoundingClientRect();
  const x = clientX === undefined ? mediaViewport.clientWidth / 2 : clientX - bounds.left;
  const y = clientY === undefined ? mediaViewport.clientHeight / 2 : clientY - bounds.top;
  const documentX = (mediaViewport.scrollLeft + x) / mediaZoom;
  const documentY = (mediaViewport.scrollTop + y) / mediaZoom;
  mediaZoom = Math.min(5, Math.max(1, value));
  layoutMedia();
  mediaViewport.scrollLeft = documentX * mediaZoom - x;
  mediaViewport.scrollTop = documentY * mediaZoom - y;
  const select = $('#original-zoom');
  select.querySelector('[data-custom-zoom]')?.remove();
  const exact = [...select.options].find(option => Number(option.value) === mediaZoom);
  if (!exact) {
    const option = new Option(`${Math.round(mediaZoom * 100)}%`, String(mediaZoom));
    option.dataset.customZoom = 'true'; select.add(option);
  }
  select.value = String(mediaZoom);
}

function resetMedia() {
  /* Fit new pages and documents without carrying over an old pan position. */
  zoomMedia(1);
  mediaViewport.scrollLeft = mediaViewport.scrollTop = 0;
}

mediaViewport.addEventListener('wheel', event => {
  if (!mediaPreview.children.length) return;
  event.preventDefault();
  const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? mediaViewport.clientHeight : 1;
  const delta = Math.max(-300, Math.min(300, event.deltaY * units));
  zoomMedia(mediaZoom * Math.exp(-delta * 0.002), event.clientX, event.clientY);
}, {passive:false});
mediaViewport.addEventListener('pointerdown', event => {
  if (event.button !== 0 || event.pointerType !== 'mouse' || mediaZoom === 1) return;
  event.preventDefault();
  mediaDrag = {x:event.clientX, y:event.clientY, left:mediaViewport.scrollLeft, top:mediaViewport.scrollTop};
  mediaViewport.setPointerCapture(event.pointerId);
  mediaViewport.classList.add('panning');
});
mediaViewport.addEventListener('pointermove', event => {
  if (!mediaDrag) return;
  mediaViewport.scrollLeft = mediaDrag.left + mediaDrag.x - event.clientX;
  mediaViewport.scrollTop = mediaDrag.top + mediaDrag.y - event.clientY;
});
mediaViewport.addEventListener('lostpointercapture', () => {
  mediaDrag = null; mediaViewport.classList.remove('panning');
});
mediaViewport.addEventListener('dblclick', resetMedia);
new ResizeObserver(layoutMedia).observe(mediaViewport);

function renderPieceNavigation() {
  /* Edit one piece at a time while preserving every piece in the submitted form. */
  const cards = [...$('#receipt-pieces').children];
  if (pieceDocument !== selectedUnit) activePiece = 0;
  else if (cards.length > previousPieceCount) activePiece = cards.length - 1;
  pieceDocument = selectedUnit; previousPieceCount = cards.length;
  activePiece = Math.max(0, Math.min(activePiece, cards.length - 1));
  $('#piece-count').textContent = `${cards.length} ${cards.length === 1 ? 'piece' : 'pieces'}`;
  $('#piece-tabs').hidden = cards.length < 2;
  $('#split-piece').disabled = $('#remove-piece').disabled = !cards.length;
  $('#piece-tabs').replaceChildren(...cards.map((card, number) => {
    card.hidden = number !== activePiece;
    card.querySelector('legend').textContent = `Piece ${number + 1} details`;
    const button = node('button', '', `Piece ${number + 1}`);
    button.type = 'button'; button.setAttribute('aria-pressed', String(number === activePiece));
    button.onclick = () => { activePiece = number; renderPieceNavigation(); $('#receipt-pieces').scrollTop = 0; };
    return button;
  }));
}

function updateReviewNavigation() {
  /* Show real review progress and bound previous/next navigation. */
  const select = $('#receipt-unit'), count = select.options.length;
  $('#document-position').textContent = count ? `${select.selectedIndex + 1} / ${count}` : '0 / 0';
  $('#previous-document').disabled = select.selectedIndex <= 0;
  $('#next-document').disabled = select.selectedIndex >= count - 1;
  const accepted = receiptData?.units.filter(unit => unit.accepted).length || 0;
  $('#review-progress').textContent = `${accepted} of ${count} reviewed`;
}

function changeDocument(offset) {
  /* Reuse the selection event so unsaved-change protection applies to navigation. */
  const select = $('#receipt-unit');
  select.selectedIndex += offset;
  select.dispatchEvent(new Event('change', {bubbles:true}));
}

function clearOriginal() {
  /* Clear stale evidence when no extraction is selected. */
  originalRequest++;
  originalUnit = originalInfo = null;
  $('#original-preview').replaceChildren();
  $('#original-page').replaceChildren();
  $('#original-status').textContent = 'No extracted documents available yet.';
  updateReviewNavigation();
}

async function showOriginal(unit) {
  /* Select the matching source page and ignore superseded requests. */
  const request = ++originalRequest;
  selectedUnit = unit.key; extractionDirty = false;
  updateReviewNavigation();
  originalUnit = unit;
  originalInfo = null;
  $('#original-page').replaceChildren();
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
  resetMedia();
  $('#original-status').textContent = 'Loading preview…';
  const office = ['word', 'spreadsheet'].includes(info.kind);
  if (office && page < info.office_pages) {
    const data = await api(`/api/office-view?content_id=${encodeURIComponent(unit.document_id)}&page=${page}`);
    if (request !== originalRequest) return;
    renderOfficePreview(target, data);
    layoutMedia();
    $('#original-status').textContent = 'Structured document preview. Open the original for exact print formatting.';
  } else if (office || ['image', 'pdf'].includes(info.kind)) {
    const picture = node('img');
    picture.alt = `${unit.source_path.split(/[\\/]/).pop()}, ${info.labels[page]}`;
    picture.draggable = false;
    picture.onload = () => { if (request === originalRequest) { layoutMedia(); $('#original-status').textContent = info.labels[page]; } };
    picture.onerror = () => { if (request === originalRequest) $('#original-status').textContent = 'Preview could not load. Open the original document.'; };
    picture.src = `/api/extraction-preview-image?id=${encodeURIComponent(unit.document_id)}&page=${page}`;
    target.append(picture);
  } else {
    if (info.kind === 'text') target.append(node('pre', '', info.text));
    $('#original-status').textContent = info.message || 'Original document text';
    layoutMedia();
  }
}

$('#original-page').onchange = () => renderOriginal().catch(receiptError);
$('#original-zoom').onchange = event => {
  zoomMedia(Number(event.target.value));
};
$('#previous-document').onclick = () => changeDocument(-1);
$('#next-document').onclick = () => changeDocument(1);
$('#split-piece').onclick = () => {
  /* Apply the split to the selected piece, retaining all other edits. */
  const card = $('#receipt-pieces').children[activePiece];
  if (card) { extractionDirty = true; card.splitPiece(); }
};
$('#remove-piece').onclick = () => {
  /* Remove only the selected extraction piece, never the source file. */
  const card = $('#receipt-pieces').children[activePiece];
  if (card) { extractionDirty = true; card.remove(); }
};
new MutationObserver(renderPieceNavigation).observe($('#receipt-pieces'), {childList:true});
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
