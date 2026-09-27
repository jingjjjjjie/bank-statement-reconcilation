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

function renderDocumentTotal() {
  /* Sum editable entries in exact cents, keeping currencies and incomplete values separate. */
  const totals = new Map(); let incomplete = false;
  for (const card of $('#receipt-pieces').children) {
    const value = card.querySelector('[data-field="total"]').value.trim().replaceAll(',', '');
    const currency = card.querySelector('[data-field="currency"]').value || 'Unknown currency';
    if (!/^\d+(\.\d{1,2})?$/.test(value)) { incomplete = true; continue; }
    const [whole, fraction = ''] = value.split('.');
    const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
    totals.set(currency, (totals.get(currency) || 0n) + cents);
  }
  const values = [...totals].map(([currency, cents]) => `${currency} ${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`);
  $('#document-total').textContent = `Document total: ${values.join(' / ') || 'Unavailable'}${incomplete ? ' (incomplete)' : ''}`;
}

function renderPieceNavigation() {
  /* Show every piece as one editable row; retain secondary fields in its disclosure. */
  const cards = [...$('#receipt-pieces').children];
  if (pieceDocument !== selectedUnit) activePiece = 0;
  else if (cards.length > previousPieceCount) activePiece = cards.length - 1;
  pieceDocument = selectedUnit; previousPieceCount = cards.length;
  activePiece = Math.max(0, Math.min(activePiece, cards.length - 1));
  renderDocumentTotal();
  $('#piece-count').textContent = `${cards.length} ${cards.length === 1 ? 'entry' : 'entries'}`;
  $('#remove-piece').title = `Remove piece ${activePiece + 1} from extraction`;
  $('#piece-tabs').hidden = true;
  $('#remove-piece').disabled = !cards.length;
  $('#merge-all-pieces').disabled = cards.length < 2;
  cards.forEach((card, number) => {
    card.hidden = false;
    card.classList.toggle('active-piece', number === activePiece);
    card.querySelector('legend').textContent = `Piece ${number + 1}`;
    if (!card.querySelector('.piece-row')) {
      const row = node('div', 'piece-row'), select = node('button', 'piece-number');
      select.type = 'button'; row.append(select);
      const details = node('details', 'piece-details'), detailFields = node('div', 'piece-detail-fields');
      details.append(node('summary', '', 'Details'));
      for (const key of ['payee', 'payer', 'brief_description', 'total', 'currency', 'document_number']) {
        const field = card.querySelector(`[data-field="${key}"]`);
        if (field) row.append(field.closest('label'));
      }
      const actions = node('div', 'piece-card-actions');
      const showPiece = node('button', 'show-piece', 'Show');
      showPiece.type = 'button'; showPiece.title = 'Show this piece in the original';
      showPiece.onclick = () => {
        const location = card.querySelector('[data-field="amount_location"]')?.value;
        const source = card.querySelector('[data-field="source_units"]')?.value.trim().split(/\s+/)[0];
        showLocation(originalInfo?.kind === 'spreadsheet' && location ? location :
          originalInfo?.labels.length === 1 ? 'page 1' : location || (source ? `page ${source}` : ''));
        $('#original-viewport').scrollIntoView({block:'nearest'});
      };
      const remove = node('button', 'remove-entry', 'Remove');
      remove.type = 'button'; remove.title = 'Remove this entry from extraction';
      remove.onclick = () => removePiece(card);
      actions.append(showPiece, remove); row.append(actions);
      for (const label of [...card.querySelectorAll(':scope > label')]) detailFields.append(label);
      const location = detailFields.querySelector('[data-field="amount_location"]');
      if (location) {
        const show = node('button', 'button secondary', 'Show');
        show.type = 'button'; show.title = 'Show where this amount is in the original';
        show.onclick = () => showLocation(location.value);
        const field = node('div', 'location-field');
        location.replaceWith(field);
        field.append(location, show);
      }
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
    card.querySelector('.show-piece').setAttribute('aria-label', `Show original for piece ${number + 1}`);
    card.querySelector('.remove-entry').setAttribute('aria-label', `Remove piece ${number + 1}`);
  });
}

function removePiece(card) {
  /* Remove only this draft entry and keep keyboard focus on a remaining piece. */
  if (!card) return;
  extractionDirty = true; card.remove(); receipts.refreshReview();
  renderPieceNavigation();
  ($('#receipt-pieces .active-piece .piece-number') || $('#add-receipt')).focus();
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

function showLocation(text) {
  /* Jump the preview to where an amount was read: "page 3", "Sheet1!H7" or "image 1". */
  if (!originalInfo) return;
  for (const row of $('#original-preview').querySelectorAll('.source-highlight')) {
    row.classList.remove('source-highlight'); row.querySelector('th')?.removeAttribute('aria-label');
  }
  const labels = originalInfo.labels, value = (text || '').trim();
  let page = -1, highlight = null;
  const cell = /^(.+)!\$?[A-Z]+\$?(\d+)(?::\$?[A-Z]+\$?(\d+))?$/i.exec(value);
  const number = /(?:page|image)\s*(\d+)/i.exec(value);
  if (cell) {
    const row = Number(cell[2]);
    const sheet = cell[1].replace(/^'(.*)'$/, '$1').replaceAll("''", "'");
    const end = Number(cell[3] || cell[2]);
    if (row < 1 || end < row) { $('#original-status').textContent = 'Invalid source row range'; return; }
    highlight = {start:row, end};
    page = labels.findIndex(label => {
      const range = /^(.*) · rows (\d+)[–-](\d+)$/.exec(label);
      return range && range[1].toLowerCase() === sheet.toLowerCase() && row >= Number(range[2]) && row <= Number(range[3]);
    });
  } else if (number) {
    page = Math.min(Number(number[1]) - 1, labels.length - 1);
  }
  if (page < 0) { $('#original-status').textContent = `Location not found: ${value || 'none recorded'}`; return; }
  $('#original-page').value = String(page);
  renderOriginal(highlight).catch(receipts.error);
}

async function renderOriginal(highlight = null) {
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
    renderOfficePreview(target, data, highlight);
    layoutMedia();
    $('#original-status').textContent = 'Structured document preview. Open the original for exact print formatting.';
    const sourceRow = target.querySelector('.source-highlight');
    if (sourceRow) {
      sourceRow.scrollIntoView({block:'center', inline:'nearest'});
      const last = target.querySelectorAll('.source-highlight');
      const end = last[last.length - 1].dataset.sourceRow;
      $('#original-status').textContent = `${data.sheet} · ${end === String(highlight.start) ? `Row ${end}` : `Rows ${highlight.start}–${end}`} highlighted`;
    }
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
$('#next-review-document').onclick = () => {
  /* Browse independently of acceptance, retaining the unsaved-edit guard. */
  const index = receipts.data.units.findIndex(unit => unit.key === selectedUnit);
  changeDocument(index + 1);
};
$('#remove-piece').onclick = () => {
  /* Remove only the selected extraction piece, never the source file. */
  const card = $('#receipt-pieces').children[activePiece];
  removePiece(card);
};
// Close secondary actions after use; native popover also supports Escape and outside clicks.
$('#extraction-options').onclick = event => {
  if (event.target.closest('button, a')) $('#extraction-options').hidePopover();
};
page.observe(new MutationObserver(renderPieceNavigation), $('#receipt-pieces'), {childList:true});
root.addEventListener('input', event => { if (event.target.closest('#receipt-pieces')) { extractionDirty = true; renderDocumentTotal(); receipts.refreshReview(); } });
root.addEventListener('click', event => { if (event.target.closest('#add-receipt')) { extractionDirty = true; receipts.refreshReview(); } });
root.addEventListener('change', event => {
  if (event.target.id !== 'receipt-unit' || !extractionDirty) return;
  if (!confirm('Discard unsaved extraction changes?')) {
    event.stopImmediatePropagation(); event.target.value = selectedUnit;
  }
}, true);
root.addEventListener('click', event => {
  if (event.target.id === 'reload-receipts' && extractionDirty && !confirm('Discard unsaved extraction changes?')) event.stopImmediatePropagation();
}, true);

const receipts = installReceipts(page, {showOriginal, clearOriginal, changed: () => {extractionDirty = true;}, saved: () => {extractionDirty = false;}});
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
