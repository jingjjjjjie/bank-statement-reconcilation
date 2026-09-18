import { node } from '../dom.js';
import { installReceipts } from '../receipts.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { $, api, toast, pollVisible } = page;
/* Show saved progress for every prepared content-review document. */
let documentState = {prepared: false, documents: []};
let documentRequestMessage = "";
let progressStage;

function renderDocuments() {
  /* Filter the current saved snapshot without changing workflow state. */
  const rows = documentState.documents;
  const search = $('#document-search').value.trim().toLowerCase();
  const filter = $('#document-filter').value;
  const hideDuplicates = $('#hide-duplicates').checked;
  const hidden = hideDuplicates ? rows.filter(item => item.approved_duplicate).length : 0;
  const visible = rows.filter(item => (!hideDuplicates || !item.approved_duplicate) && (filter === 'all' || item.status === filter) &&
    `${item.name} ${item.path}`.toLowerCase().includes(search));
  $('#document-total').textContent = rows.length;
  $('#document-admin').textContent = rows.filter(item => item.status === 'Needs review').length;
  $('#document-complete').textContent = rows.filter(item => item.status === 'Complete').length;
  $('#document-summary').textContent = documentState.prepared ?
    `${visible.length} of ${rows.length} documents${hidden ? ` · ${hidden} duplicates hidden` : ''}` :
    'Run documents to prepare your files.';
  const body = $('#document-rows'); body.replaceChildren();
  for (const item of visible) {
    const tr = node('tr'), title = node('td');
    title.append(node('strong', '', item.name));
    title.title = item.path;
    if (item.approved_duplicate) title.append(node('small', '', 'Approved duplicate'));
    const status = node('span', `document-status ${item.status.toLowerCase().replaceAll(' ', '-')}`, item.status);
    const open = node('a', '', 'Open file');
    open.href = `/api/content-file?id=${encodeURIComponent(item.id)}`;
    open.target = '_blank'; open.rel = 'noopener';
    const file = node('td', 'document-actions');
    const extraction = node('a', 'receipt-review-link', 'Review results');
    extraction.href = `/extraction-review?unit=${encodeURIComponent(item.id + ':0')}`;
    file.append(extraction, open);
    tr.append(title, node('td'), file);
    tr.children[1].append(status);
    body.append(tr);
  }
  $('#document-empty').hidden = !!visible.length;
  $('#document-empty').textContent = documentState.prepared ? 'No documents match this filter.' : 'Click Run all documents to get started.';
}

async function refreshDocuments() {
  /* Poll the checkpointed review while retaining search and filter choices. */
  documentState = await api('/api/document-status');
  renderDocuments();
  renderDocumentProgress();
}

function setDocumentRequestMessage(message) {
  /* Show immediate feedback while preparing, starting, or stopping a batch. */
  documentRequestMessage = message;
  renderDocumentProgress();
}

function renderDocumentProgress() {
  /* Report measured progress for the current stage, never an estimated timer. */
  const rows = documentState.documents;
  const sum = field => rows.reduce((total, row) => total + row[field], 0);
  const stages = [
    {name:'Extracting documents', done:sum('units_read'), total:sum('units_total'), unit:'units'},
    {name:'Assembling receipts', done:sum('assembly_done'), total:sum('assembly_total'), unit:'documents'},
  ];
  const stage = stages.find(item => item.done < item.total);
  const bar = $('#document-progress-bar');
  const busy = !!documentRequestMessage;
  $('#run-documents').disabled = busy || !!documentState.running;
  $('#stop-documents').disabled = busy || !documentState.running || !!documentState.stop_requested;
  if (busy || (documentState.running && !stage)) {
    bar.removeAttribute('value');
    $('#document-progress-stage').textContent = documentRequestMessage || 'Finishing batch';
    $('#document-progress-count').textContent = 'Please wait';
  } else if (stage) {
    const percent = Math.floor(stage.done / stage.total * 100);
    bar.value = percent;
    const prefix = documentState.stop_requested && documentState.running ? 'Stopping: ' : documentState.running ? '' : 'Paused: ';
    $('#document-progress-stage').textContent = prefix + stage.name;
    $('#document-progress-count').textContent = `${stage.done} / ${stage.total} ${stage.unit} (${percent}%)`;
  } else {
    bar.value = documentState.prepared && rows.length ? 100 : 0;
    const attention = rows.filter(row => row.status === 'Needs attention').length;
    $('#document-progress-stage').textContent = !documentState.prepared ? 'Not started' : !rows.length ? 'No documents to process' : attention ? 'Processing finished with items needing attention' : 'Processing finished - review results';
    $('#document-progress-count').textContent = attention ? `${attention} documents need attention` : rows.length ? `${rows.length} documents` : '';
  }
  // Ease measured updates; reset stage changes without a backwards sweep.
  const track = $('#document-progress-track'), fill = track.querySelector('.progress-fill');
  const nextStage = stage?.name || 'idle';
  const indeterminate = !bar.hasAttribute('value');
  track.dataset.busy = String(indeterminate);
  track.dataset.running = String(!!documentState.running && !documentState.stop_requested);
  if (!indeterminate) {
    const reset = progressStage === undefined || (stage && progressStage !== nextStage);
    if (reset) fill.style.transition = 'none';
    fill.style.transform = `scaleX(${bar.value / 100})`;
    if (reset) { void fill.offsetWidth; fill.style.transition = ''; }
    progressStage = nextStage;
  }
  $('#document-run-status').textContent = documentRequestMessage || documentState.run_error ||
    (documentState.running ? 'You can leave this page; extraction continues and progress is saved.' :
      'Open Review results beside a document to check its extraction.');
}

function rememberFilters() {
  /* Keep this browser's document view when navigating away or reloading. */
  try {
    localStorage.setItem('document-status-filters', JSON.stringify({
      search: $('#document-search').value, status: $('#document-filter').value,
      hideDuplicates: $('#hide-duplicates').checked,
    }));
  } catch { /* Storage restrictions must not prevent filtering. */ }
  renderDocuments();
}

/* Restore preferences only; document progress always comes from saved review state. */
try {
  const filters = JSON.parse(localStorage.getItem('document-status-filters') || '{}');
  $('#hide-duplicates').checked = filters?.hideDuplicates === true;
  if (typeof filters?.search === 'string') $('#document-search').value = filters.search;
  if ([...$('#document-filter').options].some(option => option.value === filters?.status)) {
    $('#document-filter').value = filters.status;
  }
} catch { /* Ignore unavailable storage or invalid old preferences. */ }
$('#hide-duplicates').onchange = rememberFilters;
$('#document-search').oninput = rememberFilters;
$('#document-filter').onchange = rememberFilters;
refreshDocuments().catch(error => toast(error.message));
pollVisible(refreshDocuments, 5000);

installReceipts(page, {getDocumentState: () => documentState, setDocumentRequestMessage, refreshDocuments});


page.onRefresh(refreshDocuments);
}
