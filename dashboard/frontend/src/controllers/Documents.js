import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';
import { installReceipts } from '../receipts.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, showDevelopmentMode, navigate, routeQuery } = page;
let token;
/* Show saved progress for every prepared content-review document. */
let documentState = {prepared: false, documents: []};
let documentRequestMessage = "";

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
  $('#document-extracted').textContent = rows.filter(item => item.units_read === item.units_total).length;
  $('#document-admin').textContent = rows.filter(item => item.status === 'Admin review').length;
  $('#document-complete').textContent = rows.filter(item => item.status === 'Complete').length;
  $('#document-summary').textContent = documentState.prepared ?
    `${visible.length} of ${rows.length} documents shown. ${hidden} approved duplicates hidden. Progress updates automatically.` :
    'Prepare the content review to see document progress.';
  const body = $('#document-rows'); body.replaceChildren();
  for (const item of visible) {
    const tr = node('tr'), title = node('td');
    title.append(node('strong', '', item.name), node('small', '', item.path));
    if (item.approved_duplicate) title.append(node('small', '', 'Approved duplicate'));
    const status = node('span', `document-status ${item.status.toLowerCase().replaceAll(' ', '-')}`, item.status);
    const review = item.candidates ? `${item.decisions}/${item.candidates} decisions · ${item.comparisons}/${item.candidates} compared` : 'No candidates yet';
    const open = node('a', '', 'Open file');
    open.href = `/api/content-file?id=${encodeURIComponent(item.id)}`;
    open.target = '_blank'; open.rel = 'noopener';
    const file = node('td'); file.append(open);
    const extraction = node('a', '', 'Review extraction');
    extraction.href = `/extraction-review?unit=${encodeURIComponent(item.id + ':0')}`;
    file.append(node('br'), extraction);
    tr.append(title, node('td'), node('td', '', `${item.units_read}/${item.units_total} units`),
      node('td', '', `${item.pairs_screened}/${item.pairs_total} pairs`), node('td', '', review), file);
    tr.children[1].append(status);
    body.append(tr);
  }
  $('#document-empty').hidden = !!visible.length;
  $('#document-empty').textContent = documentState.prepared ? 'No documents match this filter.' : 'No content review has been prepared yet.';
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
    {name:'Screening possible duplicates', done:sum('pairs_screened') / 2, total:sum('pairs_total') / 2, unit:'pairs'},
    {name:'Comparing candidates', done:sum('comparisons') / 2, total:sum('candidates') / 2, unit:'comparisons'},
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
  $('#document-run-status').textContent = documentRequestMessage || documentState.run_error ||
    (documentState.running ? 'Progress is saved automatically. Parallel and request limits follow Settings.' :
      'Run resumes remaining work within your request limit. Load latest receipt results to review completed extraction.');
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
