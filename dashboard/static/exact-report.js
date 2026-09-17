/* Display the deterministic report without offering file-selection actions. */
api('/api/state').then(data => {
  $('#source-files').textContent = data.summary.files;
  $('#duplicate-groups').textContent = data.summary.groups;
  $('#extra-copies').textContent = data.summary.extra_copies;
  $('#unique-documents').textContent = data.summary.unique_documents;
  $('#output-folder').textContent = data.folder;
  $('#report-summary').textContent = data.attention
    ? `${data.attention} groups need attention; output files may have changed.`
    : `${data.summary.copies} files copied into ${data.summary.groups} duplicate groups. No files deleted.`;
  for (const group of data.groups) {
    const section = node('section', 'settings-card');
    section.append(node('h3', '', `${group.id} ? ${group.files.length} copies`),
      node('code', '', `SHA-256: ${group.hash}`));
    const list = node('ul');
    for (const file of group.files) {
      const item = node('li'), link = node('a', '', file.name);
      link.href = `/api/file?id=${encodeURIComponent(file.id)}`;
      link.target = '_blank'; link.rel = 'noopener';
      item.append(link, node('p', '', file.original)); list.append(item);
    }
    section.append(list);
    if (group.errors.length) section.append(node('p', 'validation', group.errors.join(' ')));
    $('#report-groups').append(section);
  }
}).catch(error => {$('#report-summary').textContent = error.message;});
