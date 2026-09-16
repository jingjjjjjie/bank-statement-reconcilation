/* Settings page: changes are explicit and never start document processing. */
let savedSettings, dirty = false;
const stages = [
  ['pdf', 'PDF reading', 'Uses the PDF processing option above: extracted text, vision fallback, or full vision.'],
  ['images', 'JPG / image reading', 'Vision only for now, including PNG and other supported images. No separate OCR step. Picture processing must be on.'],
  ['excel', 'Excel reading', 'Python extracts cells, formulas and cached values from XLSX files. This model reads that text and any allowed embedded pictures.'],
  ['word', 'Word reading', 'Reads extracted DOCX text and any allowed embedded pictures.'],
  ['comparison', 'Document comparison', 'Screens summaries and compares candidate originals across all file types, including PDF against JPG. May use vision when originals contain pictures.']
];
function callExample() {
  const n = Number($('#max-calls').value);
  $('#call-example').textContent = Number.isInteger(n) && n >= 1 && n <= 500
    ? `Up to ${n} new request${n === 1 ? '' : 's'} in this run. If more work remains, pause before request ${n + 1}. Run again to continue with up to ${n} more.`
    : 'Enter a whole number from 1 to 500.';
}
function updateReasoning(stage, selected = 'default') {
  const model = savedSettings.models.find(m => m.id === $(`#${stage}-model`).value);
  const levels = model?.reasoning || [];
  const input = $(`#${stage}-reasoning`);
  input.replaceChildren(new Option('Model default', 'default'), ...levels.map(r => new Option(r[0].toUpperCase() + r.slice(1), r)));
  input.value = levels.includes(selected) ? selected : 'default';
  input.disabled = !model;
}
function renderStages(data) {
  $('#stage-settings').replaceChildren();
  for (const [stage, title, description] of stages) {
    const section = document.createElement('section');
    section.className = 'stage-setting';
    // Only fixed stage identifiers enter markup; catalog labels use Option text.
    section.innerHTML = `<h3>${title}</h3><p>${description}</p><div class="settings-grid"><label class="setting-field"><strong>Model</strong><select id="${stage}-model" aria-label="${title} model"></select></label><label class="setting-field"><strong>Reasoning effort</strong><select id="${stage}-reasoning" aria-label="${title} reasoning"></select></label></div>`;
    $('#stage-settings').append(section);
    const choice = data.config.stages?.[stage] || data.config;
    const select = $(`#${stage}-model`);
    select.replaceChildren(new Option('Codex default', ''), ...data.models.map(m => new Option(m.name, m.id)));
    select.value = choice.model;
    updateReasoning(stage, choice.reasoning);
    select.onchange = () => {updateReasoning(stage); markDirty();};
  }
}
function showSettings(data) {
  savedSettings = data;
  $('#pdf-mode').value = data.config.pdf_mode;
  $('#pictures-enabled').checked = data.config.pictures_enabled;
  $('#codex-enabled').checked = data.config.codex_enabled;
  $('#max-calls').value = data.config.max_calls;
  renderStages(data);
  $('#settings-refresh').hidden = !data.requires_refresh;
  $('#settings-fields').disabled = false;
  $('#settings-error').hidden = true;
  dirty = false;
  $('#save-state').textContent = 'All settings saved';
  $('#save-settings').disabled = $('#discard-settings').disabled = true;
  callExample();
}
function markDirty() {
  dirty = true;
  $('#save-state').textContent = 'Unsaved changes';
  $('#save-settings').disabled = $('#discard-settings').disabled = false;
  callExample();
}
$('#settings-form').oninput = markDirty;
$('#discard-settings').onclick = () => showSettings(savedSettings);
window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});

/* Preserve backend validation and stale-tab protection when saving. */
$('#settings-form').onsubmit = async event => {
  event.preventDefault();
  if (!savedSettings || !token) return;
  $('#settings-fields').disabled = true;
  $('#save-settings').disabled = $('#discard-settings').disabled = true;
  try {
    const choices = Object.fromEntries(stages.map(([stage]) => [stage, {model: $(`#${stage}-model`).value, reasoning: $(`#${stage}-reasoning`).value}]));
    const config = {...savedSettings.config, pdf_mode: $('#pdf-mode').value, pictures_enabled: $('#pictures-enabled').checked, codex_enabled: $('#codex-enabled').checked, max_calls: Number($('#max-calls').value), stages: choices};
    showSettings(await api('/api/config', {config, revision: savedSettings.revision}));
    toast('Settings saved. No review was started.');
  } catch (error) {
    $('#settings-error').hidden = false; $('#settings-error').textContent = error.message;
    $('#settings-fields').disabled = false; markDirty();
  }
};
Promise.all([api('/api/session'), api('/api/config')]).then(([session, config]) => {token = session.token; showSettings(config);}).catch(error => {$('#settings-error').hidden = false; $('#settings-error').textContent = error.message; $('#save-state').textContent = 'Unable to load settings';});
