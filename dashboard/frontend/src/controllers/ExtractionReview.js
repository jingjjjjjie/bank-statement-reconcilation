import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';
import { installReceipts } from '../receipts.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
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
page.observe(new ResizeObserver(layoutMedia), mediaViewport);

function renderPieceNavigation() {
  /* Show every piece as one editable row; retain secondary fields in its disclosure. */
  const cards = [...$('#receipt-pieces').children];
  if (pieceDocument !== selectedUnit) activePiece = 0;
  else if (cards.length > previousPieceCount) activePiece = cards.length - 1;
  pieceDocument = selectedUnit; previousPieceCount = cards.length;
  activePiece = Math.max(0, Math.min(activePiece, cards.length - 1));
  $('#piece-count').textContent = `${cards.length} ${cards.length === 1 ? 'entry' : 'entries'}`;
  $('#remove-piece').title = `Remove piece ${activePiece + 1} from extraction`;
  $('#piece-tabs').hidden = true;
  $('#remove-piece').disabled = !cards.length;
  cards.forEach((card, number) => {
    card.hidden = false;
    card.classList.toggle('active-piece', number === activePiece);
    card.querySelector('legend').textContent = `Piece ${number + 1}`;
    if (!card.querySelector('.piece-row')) {
      const row = node('div', 'piece-row'), select = node('button', 'piece-number');
      select.type = 'button'; row.append(select);
      const details = node('details', 'piece-details'), detailFields = node('div', 'piece-detail-fields');
      details.append(node('summary', '', 'Details'));
      for (const key of ['payee', 'brief_description', 'total', 'currency']) {
        const field = card.querySelector(`[data-field="${key}"]`);
        if (field) {
          const label = field.closest('label');
          label.firstChild.textContent = {payee:'Payee', brief_description:'Description', total:'Amount', currency:'Currency'}[key];
          row.append(label);
        }
      }
      for (const label of [...card.querySelectorAll(':scope > label')]) detailFields.append(label);
      details.append(detailFields);
      card.append(row, details);
      card.addEventListener('focusin', () => {
        const index = [...$('#receipt-pieces').children].indexOf(card);
        if (index !== activePiece) { activePiece = index; renderPieceNavigation(); }
      });
    }
    const select = card.querySelector('.piece-number');
    select.textContent = String(number + 1);
    select.setAttribute('aria-label', `Select piece ${number + 1}`);
    select.setAttribute('aria-pressed', String(number === activePiece));
    select.onclick = () => { activePiece = number; renderPieceNavigation(); };
  });
}

function updateReviewNavigation() {
  /* Show ten numbered documents with accepted and current states kept separate. */
  const units = receipts.data?.units || [], count = units.length;
  const index = units.findIndex(unit => unit.key === $('#receipt-unit').value);
  const start = Math.floor(Math.max(0, index) / 10) * 10;
  const current = units[index];
  const name = current ? current.source_path.split(/[\\/]/).pop() : 'No document selected';
  $('#current-document-name').textContent = name;
  $('#current-document-name').title = current ? `${name} / ${current.label}` : '';
  $('#previous-document').disabled = start === 0;
  $('#next-document').disabled = start + 10 >= count;
  $('#document-buttons').replaceChildren(...units.slice(start, start + 10).map((unit, offset) => {
    const number = start + offset + 1;
    const button = node('button', unit.trash ? 'trash' : unit.accepted ? 'reviewed' : '', String(number));
    button.type = 'button';
    button.setAttribute('aria-label', `Document ${number}${unit.trash ? ', trash' : unit.accepted ? ', reviewed' : ', not reviewed'}`);
    if (unit.key === current?.key) button.setAttribute('aria-current', 'true');
    button.title = unit.source_path.split(/[\\/]/).pop();
    button.onclick = () => changeDocument(start + offset);
    return button;
  }));
  const accepted = units.filter(unit => unit.accepted || unit.trash).length;
  $('#review-progress').textContent = `${accepted} of ${count} reviewed`;
}

function changeDocument(index) {
  /* Reuse the selection event so unsaved-change protection applies to navigation. */
  const select = $('#receipt-unit');
  const unit = receipts.data?.units[index];
  if (!unit) return;
  select.value = unit.key;
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
  receipts.refreshReview();
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
    const data = await api(`/api/extraction-office?id=${encodeURIComponent(unit.document_id)}&page=${page}`);
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

$('#original-page').onchange = () => renderOriginal().catch(receipts.error);
$('#original-zoom').onchange = event => {
  zoomMedia(Number(event.target.value));
};
$('#previous-document').onclick = () => {
  const index = receipts.data.units.findIndex(unit => unit.key === selectedUnit);
  changeDocument(Math.max(0, Math.floor(index / 10) * 10 - 10));
};
$('#next-document').onclick = () => {
  const index = receipts.data.units.findIndex(unit => unit.key === selectedUnit);
  changeDocument(Math.floor(index / 10) * 10 + 10);
};
$('#remove-piece').onclick = () => {
  /* Remove only the selected extraction piece, never the source file. */
  const card = $('#receipt-pieces').children[activePiece];
  if (card) { extractionDirty = true; card.remove(); receipts.refreshReview(); }
};
page.observe(new MutationObserver(renderPieceNavigation), $('#receipt-pieces'), {childList:true});
root.addEventListener('input', event => { if (event.target.closest('#receipt-pieces')) { extractionDirty = true; receipts.refreshReview(); } });
root.addEventListener('click', event => { if (event.target.closest('#receipt-pieces button:not(.piece-number), #add-receipt')) { extractionDirty = true; receipts.refreshReview(); } });
root.addEventListener('change', event => {
  if (event.target.id !== 'receipt-unit' || !extractionDirty) return;
  if (!confirm('Discard unsaved extraction changes?')) {
    event.stopImmediatePropagation(); event.target.value = selectedUnit;
  }
}, true);
root.addEventListener('click', event => {
  if (event.target.id === 'reload-receipts' && extractionDirty && !confirm('Discard unsaved extraction changes?')) event.stopImmediatePropagation();
}, true);

const receipts = installReceipts(page, {showOriginal, clearOriginal, saved: () => {extractionDirty = false;}});
page.dirty(() => extractionDirty);
page.onRefresh(() => receipts.reload(), ['/api/receipts/', '/api/content/']);
page.onQuery(() => {
  const key = new URLSearchParams(routeQuery()).get('unit');
  if (key && $('#receipt-unit').value !== key) {
    const target = receipts.data?.units.find(unit => unit.key === key || unit.document_id === key.split(':')[0]);
    if (target?.key === $('#receipt-unit').value) return;
    if (extractionDirty && !confirm('Discard unsaved results and open this document?')) return;
    receipts.selectUnit(key, false);
  }
});

}
