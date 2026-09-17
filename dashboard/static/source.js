/* Folder selection is read-only until the user starts a review. */
let sourceState = {};
let previewToken = null;
async function loadPreview() {
  previewToken = null;
  $('#start-source').disabled = true;
  $('#source-preview').textContent = 'Checking exact duplicates…';
  try {
    const preview = await api('/api/source/preview');
    previewToken = preview.token;
    $('#source-preview').textContent = `${preview.files} source file${preview.files === 1 ? '' : 's'} · ${preview.groups} exact duplicate group${preview.groups === 1 ? '' : 's'} · ${preview.copies_to_move} copies would move into duplicated/.`;
    $('#start-source').disabled = false;
  } catch (error) {
    $('#source-preview').textContent = error.message;
  }
}
function showSource(data) {
  sourceState = {...sourceState, ...data};
  $('#active-source-name').textContent = sourceState.active ?
    sourceState.active.split(/[\\/]/).filter(Boolean).pop() : 'No active review';
  $('#active-source').textContent = sourceState.active || '';
  $('#active-source-details').hidden = !sourceState.active;
  $('#source-next').hidden = !sourceState.active;
  const selected = sourceState.selected;
  $('#selected-source').hidden = !selected;
  $('#source-action').hidden = !selected;
  if (selected) {
    $('#source-path').value = selected.path;
    $('#selected-source').textContent = `${selected.path} · ${selected.files.toLocaleString()} files`;
  }
  if (Object.hasOwn(data, 'selected') && selected) loadPreview();
  const bank = sourceState.bank;
  $('#selected-bank').hidden = !bank;
  $('#bank-action').hidden = !bank;
  if (bank) {
    $('#bank-path').value = bank.path;
    $('#selected-bank').textContent = `${bank.path} · ${(bank.bytes / 1024 / 1024).toFixed(2)} MB`;
  }
}

/* Keep errors visible without changing the active review. */
async function sourceAction(action) {
  $('#source-error').hidden = true;
  try {
    await action();
  } catch (error) {
    $('#source-error').textContent = error.message;
    $('#source-error').hidden = false;
  }
}

let browserKind = 'folder';
let browserPath = null;
async function browse(path) {
  const items = $('#browser-items');
  items.replaceChildren();
  $('#browser-error').hidden = true;
  $('#browser-current').textContent = 'Loading folders…';
  try {
    const query = new URLSearchParams({kind: browserKind});
    if (path) query.set('path', path);
    const data = await api('/api/source/browse?' + query);
    browserPath = data.path;
    $('#browser-current').textContent = data.path || 'Computer';
    $('#browser-use').hidden = browserKind !== 'folder' || !data.path;
    const addItem = (label, target, action) => {
      const button = node('button', 'browser-item', label);
      button.type = 'button'; button.onclick = () => action(target); items.append(button);
    };
    if (data.path) addItem('↖ Up one level', data.parent, browse);
    for (const folder of data.folders) addItem('📁 ' + (folder.split(/[\\/]/).filter(Boolean).pop() || folder), folder, browse);
    for (const file of data.files) addItem('📄 ' + file.split(/[\\/]/).pop(), file, async selected => {
      await sourceAction(async () => {
        const result = await api('/api/source/bank-select', {path: selected});
        showSource({bank: result.bank}); $('#path-browser').close();
      });
    });
    if (!data.folders.length && !data.files.length) items.append(node('p', '', 'No folders or PDF files here.'));
  } catch (error) {
    $('#browser-error').textContent = error.message;
    $('#browser-error').hidden = false;
  }
}
function openBrowser(kind) {
  browserKind = kind;
  $('#path-browser').showModal();
  browse(sourceState.active || sourceState.selected?.path || null);
}
$('#browse-source').onclick = () => openBrowser('folder');
$('#browser-close').onclick = () => $('#path-browser').close();
$('#browser-use').onclick = () => sourceAction(async () => {
  const result = await api('/api/source/select', {path: browserPath});
  showSource({selected: result.selected}); $('#path-browser').close();
});
$('#select-source').onclick = () => sourceAction(async () => {
  const result = await api('/api/source/select', {path: $('#source-path').value});
  showSource({selected: result.selected});
});
$('#browse-bank').onclick = () => openBrowser('bank');
$('#select-bank').onclick = () => sourceAction(async () => {
  const result = await api('/api/source/bank-select', {path: $('#bank-path').value});
  showSource({bank: result.bank});
});
$('#prepare-bank').onclick = () => sourceAction(async () => {
  $('#prepare-bank').disabled = true;
  try {
    const result = await api('/api/source/bank-prepare', {year: Number($('#bank-year').value)});
    $('#bank-result').textContent = result.existing ? 'Existing bank master confirmed.' : `Bank master created: ${result.path}`;
  } finally {$('#prepare-bank').disabled = false;}
});
$('#start-source').onclick = () => sourceAction(async () => {
  $('#start-source').disabled = true;
  try {
    await api('/api/source/start', {preview: previewToken});
    location.assign('/');
  } finally {$('#start-source').disabled = false;}
});
Promise.all([api('/api/session'), api('/api/source')]).then(([session, source]) => {
  token = session.token;
  showSource(source);
}).catch(error => {
  $('#source-error').textContent = error.message;
  $('#source-error').hidden = false;
});
