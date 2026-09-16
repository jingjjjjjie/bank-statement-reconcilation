/* Pass-two candidate review uses saved model evidence and explicit admin choices. */
const list = $('#candidate-list');
let contentReady = false;

/* A changed decision needs a fresh completion check. */
function resetContentCheck() {
  contentReady = false;
  $('#content-next').hidden = true;
  $('#content-check-note').textContent = '';
}

function paragraphs(items) {
  const box = node('ul', 'content-evidence');
  for (const item of items || []) box.append(node('li', '', item));
  if (!box.children.length) box.append(node('li', '', 'None recorded.'));
  return box;
}

function documentCard(document) {
  const card = node('section', 'content-document');
  card.append(node('h3', '', document.name), node('small', '', document.path));
  const link = node('a', 'button secondary', 'Open original');
  link.href = `/api/content-file?id=${encodeURIComponent(document.id)}`;
  link.target = '_blank'; link.rel = 'noopener'; card.append(link);
  for (let n = 0; n < document.units.length; n++) {
    const unit = document.units[n];
    const details = node('details');
    details.append(node('summary', '', unit.label));
    if (unit.image) {
      const picture = node('img', 'content-preview');
      picture.src = `/api/content-image?id=${encodeURIComponent(document.id)}&unit=${n}`;
      picture.alt = `${document.name}, ${unit.label}`;
      details.append(picture);
    }
    if (unit.text) details.append(node('pre', '', unit.text));
    card.append(details);
  }
  return card;
}

function candidateCard(pair) {
  const card = node('article', 'settings-card content-pair');
  const result = pair.comparison;
  card.append(node('h3', '', `${pair.left.name} / ${pair.right.name}`),
              node('p', '', result ? `${result.classification} · ${result.confidence} confidence` : 'Full comparison pending'));
  card.append(node('p', 'content-reason', `Candidate reason: ${pair.reason}`));
  const documents = node('div', 'content-documents');
  documents.append(documentCard(pair.left), documentCard(pair.right)); card.append(documents);
  if (result) {
    for (const [title, field] of [['Matching evidence', 'evidence'], ['Differences', 'differences'], ['Limitations', 'limitations']]) {
      card.append(node('h4', '', title), paragraphs(result[field]));
    }
    const decision = pair.decision;
    const reason = node('textarea'); reason.placeholder = 'Reason for this decision or undo'; reason.setAttribute('aria-label', 'Decision reason');
    const decisionBar = node('div', 'content-decision-bar');
    decisionBar.append(node('p', 'content-decision', decision ?
      `Admin decision: ${decision.verdict} by ${decision.reviewer}. ${decision.reason}` : 'Admin decision pending.'));
    if (decision) {
      const undo = node('button', 'button secondary', 'Undo decision');
      undo.type = 'button';
      undo.onclick = async () => {
        try {
          await api('/api/content/undo', {pair: pair.pair, reviewer: $('#admin-name').value.trim(),
            reason: reason.value.trim() || 'Uncertain; returned to pending review'});
          resetContentCheck(); toast('Decision undone; candidate is pending again.'); await refresh();
        } catch (error) { toast(error.message); }
      };
      decisionBar.append(undo);
    }
    card.append(decisionBar);
    card.append(reason);
    const actions = node('div', 'content-actions');
    for (const [verdict, label] of [['keep_both', 'Keep both'], ['keep_left', 'Keep left'], ['keep_right', 'Keep right']]) {
      const button = node('button', verdict === 'keep_both' ? 'button secondary' : 'button dark', label);
      button.type = 'button'; button.disabled = verdict !== 'keep_both' && result.classification !== 'same_document';
      button.onclick = async () => {
        try {
          await api('/api/content/decide', {pair: pair.pair, verdict, reviewer: $('#admin-name').value.trim(), reason: reason.value.trim()});
          resetContentCheck(); toast('Admin decision saved.'); await refresh();
        } catch (error) { toast(error.message); }
      };
      actions.append(button);
    }
    card.append(actions);
    if (result.classification === 'same_document') card.append(node('small', '', 'Keep left/right records the approved survivor. Admin cleanup remains separate.'));
  }
  return card;
}

async function refresh() {
  const state = await api('/api/content-review');
  const message = $('#content-message');
  if (!state.exact_ready) {
    resetContentCheck();
    message.textContent = `Finish exact duplicate review first. ${state.exact_problems.length} issue(s) remain.`;
    $('#content-controls').hidden = true; $('#candidate-section').hidden = true; return;
  }
  message.textContent = state.run_error || (state.prepared ? 'Pass one is complete. Review every candidate below.' : 'Pass one is complete. Prepare the remaining documents to begin pass two.');
  $('#content-controls').hidden = false;
  $('#prepare-content').hidden = state.prepared;
  $('#run-content').hidden = !state.prepared || state.running || contentReady;
  $('#check-content').hidden = !state.prepared || state.running;
  $('#content-running').hidden = !state.running;
  $('#content-progress').textContent = state.prepared ?
    `${state.documents} documents · ${state.units_read} units read · ${state.pairs_screened}/${state.pairs_total} pairs screened` : 'No content review prepared yet.';
  $('#candidate-section').hidden = !state.prepared;
  $('#candidate-count').textContent = `(${state.pairs.length})`;
  list.replaceChildren(...state.pairs.map(candidateCard));
  if (state.prepared && !state.pairs.length) list.append(node('p', '', 'No candidate pairs yet. Run a review batch to extract and screen the documents.'));
}

async function action(path) {
  try { await api(path, {}); resetContentCheck(); await refresh(); } catch (error) { toast(error.message); }
}

$('#prepare-content').onclick = () => action('/api/content/prepare');
$('#run-content').onclick = () => action('/api/content/run');
$('#check-content').onclick = async () => {
  const button = $('#check-content'); button.disabled = true;
  try {
    const status = await api('/api/workflow-checks');
    const ready = status.steps[2].checked;
    contentReady = ready;
    $('#content-next').hidden = !ready;
    $('#run-content').hidden = ready;
    $('#content-check-note').textContent = ready ? 'Content review passed its checks.' :
      'Content review is still pending. Complete the remaining candidate decisions and run any unfinished batch.';
  } catch (error) { $('#content-check-note').textContent = error.message; }
  finally { button.disabled = false; }
};
api('/api/session').then(data => { token = data.token; return refresh(); }).catch(error => toast(error.message));
setInterval(() => { if (token) refresh().catch(error => toast(error.message)); }, 5000);
