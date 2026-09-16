/* Folder selection is read-only until the user starts a review. */
let sourceState = {};
function showSource(data) {
  sourceState = {...sourceState, ...data};
  $('#active-source').textContent = sourceState.active || 'No active review';
  const selected = sourceState.selected;
  $('#selected-source').hidden = !selected;
  $('#source-action').hidden = !selected;
  if (selected) {
    $('#source-path').value = selected.path;
    $('#selected-source').textContent = `${selected.path} · ${selected.files.toLocaleString()} files`;
  }
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

$('#browse-source').onclick = () => sourceAction(async () => {
  $('#browse-source').disabled = true;
  try {
    const result = await api('/api/source/pick', {});
    if (!result.cancelled) showSource({selected: result.selected});
  } finally {$('#browse-source').disabled = false;}
});
$('#select-source').onclick = () => sourceAction(async () => {
  const result = await api('/api/source/select', {path: $('#source-path').value});
  showSource({selected: result.selected});
});
$('#browse-bank').onclick = () => sourceAction(async () => {
  $('#browse-bank').disabled = true;
  try {
    const result = await api('/api/source/bank-pick', {});
    if (!result.cancelled) showSource({bank: result.bank});
  } finally {$('#browse-bank').disabled = false;}
});
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
    await api('/api/source/start', {});
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
