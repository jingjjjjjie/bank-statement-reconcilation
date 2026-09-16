/* Show saved progress for every prepared content-review document. */
let documentState = {prepared: false, documents: []};

function renderDocuments() {
  /* Filter the current saved snapshot without changing workflow state. */
  const rows = documentState.documents;
  const search = $('#document-search').value.trim().toLowerCase();
  const filter = $('#document-filter').value;
  const visible = rows.filter(item => (filter === 'all' || item.status === filter) &&
    `${item.name} ${item.path}`.toLowerCase().includes(search));
  $('#document-total').textContent = rows.length;
  $('#document-extracted').textContent = rows.filter(item => item.units_read === item.units_total).length;
  $('#document-admin').textContent = rows.filter(item => item.status === 'Admin review').length;
  $('#document-complete').textContent = rows.filter(item => item.status === 'Complete').length;
  $('#document-summary').textContent = documentState.prepared ?
    `${visible.length} of ${rows.length} documents shown. Progress updates automatically.` :
    'Prepare the content review to see document progress.';
  const body = $('#document-rows'); body.replaceChildren();
  for (const item of visible) {
    const tr = node('tr'), title = node('td');
    title.append(node('strong', '', item.name), node('small', '', item.path));
    const status = node('span', `document-status ${item.status.toLowerCase().replaceAll(' ', '-')}`, item.status);
    const review = item.candidates ? `${item.decisions}/${item.candidates} decisions · ${item.comparisons}/${item.candidates} compared` : 'No candidates yet';
    const open = node('a', '', 'Open file');
    open.href = `/api/content-file?id=${encodeURIComponent(item.id)}`;
    open.target = '_blank'; open.rel = 'noopener';
    const file = node('td'); file.append(open);
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
}

$('#document-search').oninput = renderDocuments;
$('#document-filter').onchange = renderDocuments;
refreshDocuments().catch(error => toast(error.message));
setInterval(() => refreshDocuments().catch(error => toast(error.message)), 5000);
