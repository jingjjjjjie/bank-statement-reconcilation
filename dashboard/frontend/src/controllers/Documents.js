import { node } from '../dom.js';
import { installReceipts } from '../receipts.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { $, api, toast, pollVisible } = page;
/* Show saved progress for every prepared content-review document. */
let documentState = {prepared: false, documents: []};
let documentRequestMessage = "";
let executionRevision = 0;

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
  $('#document-empty').textContent = documentState.prepared ? 'No documents match this filter.' : 'Click Extract documents to get started.';
}

async function refreshDocuments() {
  /* Poll the checkpointed review while retaining search and filter choices. */
  const revision = executionRevision;
  const snapshot = await api('/api/document-status');
  documentState = revision === executionRevision ? snapshot : {...snapshot, ...executionFields()};
  renderDocuments();
  renderDocumentProgress();
}

function setDocumentRequestMessage(message) {
  /* Show immediate feedback while preparing, starting, or stopping a batch. */
  documentRequestMessage = message;
  renderDocumentProgress();
}

function executionFields() {
  /* Keep a slow document snapshot from overwriting a newer stop acknowledgement. */
  return Object.fromEntries(['running', 'stop_requested', 'active_processes', 'execution_status', 'run_error', 'phase', 'elapsed_seconds']
    .map(key => [key, documentState[key]]));
}

function setExecution(state) {
  /* Apply lightweight execution updates independently of document scans. */
  executionRevision++;
  Object.assign(documentState, state);
  renderDocumentProgress();
}

async function refreshExecution() {
  /* Keep Stop responsive while a full document snapshot is still loading. */
  const revision = executionRevision;
  const state = await api('/api/content/execution');
  if (revision === executionRevision) setExecution(state);
}

function renderDocumentProgress() {
  /* Count saved pages and assemblies together so progress never resets by stage. */
  const rows = documentState.documents;
  const sum = field => rows.reduce((total, row) => total + (row[field] || 0), 0);
  const done = sum('units_read') + sum('assembly_done');
  const total = sum('units_total') + sum('assembly_total');
  const extracted = rows.filter(row => row.extracted).length;
  const processed = rows.filter(row => row.units_total > 0 && row.units_read === row.units_total &&
    row.assembly_done === row.assembly_total).length;
  const stopping = documentState.stop_requested && documentState.running;
  const bar = $('#document-progress-bar');
  const busy = !!documentRequestMessage;
  const preparing = busy && !documentState.prepared;
  $('#run-documents').textContent = documentState.running ? (stopping ? 'Stopping...' : 'Extracting...') :
    preparing ? 'Preparing...' : busy ? 'Starting...' : extracted || done ? 'Resume extraction' : 'Extract documents';
  $('#run-documents').disabled = busy || !!documentState.running || (!!rows.length && extracted === rows.length);
  $('#stop-documents').disabled = !documentState.running || !!documentState.stop_requested;
  $('#stop-documents').textContent = stopping ? 'Stopping...' : 'Stop';
  bar.value = total ? Math.floor(done / total * 100) : 0;
  const percent = bar.value;
  if (preparing) bar.removeAttribute('value');
  $('#document-progress-stage').textContent = preparing ? 'Preparing documents...' : rows.length
    ? `${processed} / ${rows.length} documents processed` : 'Ready to extract';
  $('#document-progress-count').textContent = preparing || !total ? '' : `${done} / ${total} steps (${percent}%)`;
  const track = $('#document-progress-track');
  track.dataset.busy = String(preparing);
  track.dataset.running = String(!!documentState.running && !stopping);
  track.querySelector('.progress-fill').style.transform = `scaleX(${percent / 100})`;
  $('#document-run-status').textContent = documentState.execution_status === 'stop_failed'
    ? documentState.run_error : stopping
    ? `Stopping - waiting for ${documentState.active_processes || 0} active processes to exit.`
    : (!documentState.running && documentRequestMessage) || documentState.run_error ||
      (documentState.running ? `${documentState.phase || 'Extracting supporting documents'} - ${documentState.active_processes || 0} active processes - ${documentState.elapsed_seconds || 0}s elapsed` :
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
pollVisible(refreshDocuments, 2000);
pollVisible(refreshExecution, 500);

installReceipts(page, {getDocumentState: () => documentState, setDocumentRequestMessage, refreshDocuments, setExecution, refreshExecution});


page.onRefresh(refreshDocuments, ['/api/receipts/', '/api/content/']);
}
