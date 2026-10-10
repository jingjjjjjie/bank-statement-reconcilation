import { node } from '../dom.js';
import { renderOfficePreview } from '../office.js';

// Scope screen state and handlers to this cached Vue view.
export default function initialize(page) {
const { root, $, api, toast, pollVisible, navigate, routeQuery } = page;
let token;
/* Display the saved bank extraction; supporting-document matches remain pending. */
const money = value => new Intl.NumberFormat('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(Number(value || 0));
let transactions = [];
function renderRows() {
  const query = $('#bank-search').value.trim().toLowerCase();
  const matches = transactions.filter(row => [row.date, row.counterparty, row.narration, row.money_in, row.money_out, row.balance, row.matching_status].some(value => String(value).toLowerCase().includes(query)));
  const body = $('#bank-rows'); body.replaceChildren();
  for (const row of matches) {
    const tr = node('tr');
    const party = node('td'); party.append(node('strong', '', row.counterparty || 'Unidentified'), node('small', '', `Page ${row.page} · ${row.counterparty_role || 'unknown role'}`));
    const details = node('details'); details.append(node('summary', '', 'Bank narration'), node('pre', '', row.narration)); party.append(details);
    for (const value of [row.date, party, row.money_in === '0.00' ? '—' : money(row.money_in), row.money_out === '0.00' ? '—' : money(row.money_out), money(row.balance), row.matching_status || 'pending']) {
      tr.append(value instanceof Node ? value : node('td', '', value));
    }
    body.append(tr);
  }
  $('#row-count').textContent = `${matches.length} of ${transactions.length} transactions shown`;
}
async function loadBank() {
  try {
    const data = await api('/api/bank-statement');
    $('#bank-extraction').hidden = true;
    if (!data.available) {
      $('#bank-note').textContent = 'No prepared bank statement was found.';
      $('#bank-note').hidden = false;
      const source = await api('/api/source');
      const ready = source.bank && source.selected && source.active === source.selected.path;
      $('#bank-extraction').hidden = !ready;
      if (ready) $('#statement-source').textContent = source.bank.path;
      return;
    }
    transactions = data.transactions;
    $('#bank-note').hidden = true;
    $('#bank-count').textContent = data.count;
    $('#bank-account').textContent = `Account ${data.account} · ${data.currency}`;
    $('#bank-opening').textContent = money(data.opening_balance);
    $('#bank-flow').textContent = `${money(data.total_money_in)} / ${money(data.total_money_out)}`;
    $('#bank-closing').textContent = money(data.closing_balance);
    $('#bank-checks').textContent = data.balance_checks === 'passed' ? 'Bank balance checks passed' : 'Bank balance checks need review';
    $('#match-note').textContent = `${data.matched} of ${data.count} transactions matched to supporting documents`;
    $('#workbook').hidden = !data.workbook_available;
    $('#bank-content').hidden = false;
    renderRows();
  } catch (error) { $('#bank-error').textContent = error.message; $('#bank-error').hidden = false; }
}
let matchingReady = false, matchingStarting = false;
async function loadMatchingReadiness() {
  /* Show whether the current bank and extracted pieces are ready for matching. */
  try {
    const data = await api('/api/matching');
    matchingReady = !!data.live_pieces;
    $('#load-final-matching').disabled = matchingReady;
    $('#generate-matches').disabled = !matchingReady;
    if (matchingReady) await matchingProgress(); else renderMatchingProgress({});
    $('#final-matching-ready').textContent = data.live_pieces
      ? 'Progress is saved automatically. Review the matches on Review Matching.' : 'Load the current bank statement and extracted pieces for final matching.';
  } catch (error) {
    $('#final-matching-ready').textContent = 'Prepare the bank statement and supporting documents before loading.';
  }
}
$('#load-final-matching').onclick = async () => {
  /* Activate the existing migration without starting model calls or approving matches. */
  const button = $('#load-final-matching');
  button.disabled = true;
  $('#final-matching-ready').textContent = 'Loading current data...';
  try {
    await api('/api/matching-pieces', {});
    await loadMatchingReadiness();
  } catch (error) {
    button.disabled = false;
    $('#final-matching-ready').textContent = error.message;
  }
};
function renderMatchingProgress(state) {
  /* Display real processed counts; failures and stopped work never imply successful completion. */
  const total = state.total || 0, completed = state.completed || 0;
  const running = !!state.running, stopping = !!state.stop_requested;
  const complete = !running && total > 0 && completed >= total && !state.failed && !state.error && !state.outdated;
  const percent = total ? Math.min(100, Math.floor(completed / total * 100)) : 0;
  const panel = $('#matching-progress'), bar = $('#matching-progress-bar');
  panel.hidden = false;
  panel.dataset.running = String(running);
  panel.dataset.error = String(!!state.error);
  panel.setAttribute('aria-busy', String(running));
  $('#generate-matches').disabled = running || !matchingReady;
  $('#generate-matches').hidden = false;
  $('#stop-matches').hidden = !running;
  $('#stop-matches').disabled = !running || stopping || matchingStarting;
  $('#stop-matches').textContent = stopping && running ? 'Stopping...' : 'Stop';
  $('#generate-matches').textContent = matchingStarting ? 'Starting...' : running ? (stopping ? 'Stopping...' : 'Matching...')
    : !state.outdated && !complete && total && (completed < total || state.failed || state.error || state.stop_requested) ? 'Resume matching' : 'Generate matches';
  $('#matching-run-status').textContent = running
    ? stopping ? 'Stopping…' : matchingStarting ? 'Starting matching…' : 'Generating matches'
    : state.outdated ? 'Matches need updating' : complete ? 'Matching complete' : state.error || state.failed ? 'Finished with errors' : !total ? 'Ready to match' : 'Stopped';
  $('#matching-progress-count').textContent = total ? `${completed} / ${total} processed (${percent}%)` : '';
  if (matchingStarting || !total) bar.removeAttribute('value');
  else bar.value = percent;
  const track = $('#matching-progress-track');
  track.dataset.busy = String(matchingStarting);
  track.dataset.running = String(running && !stopping);
  track.querySelector('.progress-fill').style.transform = `scaleX(${percent / 100})`;
  $('#matching-progress-detail').textContent = [
    running ? (stopping ? 'Waiting for active processes to exit' : state.phase || 'Matching transactions') : '',
    state.elapsed_seconds != null ? `${state.elapsed_seconds}s elapsed` : '',
    running && state.active_processes ? `${state.active_processes} active` : '',
    state.failed ? `${state.failed} failed` : '',
    state.error && !state.failed ? state.error : '',
  ].filter(Boolean).join(' · ');
}
async function matchingProgress() {
  /* Keep start, stop and progress together on the Bank statement page. */
  if (!matchingReady || matchingStarting) return;
  const state = await api('/api/matching-run');
  if (!matchingStarting) renderMatchingProgress(state);
}
$('#generate-matches').onclick = async () => {
  if (matchingStarting || !matchingReady) return;
  matchingStarting = true;
  renderMatchingProgress({running:true});
  try {
    const state = await api('/api/matching-run', {});
    matchingStarting = false;
    renderMatchingProgress(state);
    await matchingProgress();
  } catch (e) {
    matchingStarting = false;
    renderMatchingProgress({error:e.message});
    $('#final-matching-ready').textContent = e.message;
  }
};
$('#stop-matches').onclick = async () => {
  $('#stop-matches').disabled = true;
  $('#matching-run-status').textContent = 'Stopping…';
  try { renderMatchingProgress(await api('/api/matching-stop', {})); }
  catch (e) { $('#stop-matches').disabled = false; $('#final-matching-ready').textContent = e.message; }
};
page.pollVisible(matchingProgress, 2000);
loadMatchingReadiness();

$('#bank-search').addEventListener('input', renderRows);
$('#prepare-bank').onclick = async () => {
  const button = $('#prepare-bank');
  const yearField = $('#bank-year');
  const year = Number(yearField.value);
  if (!yearField.value.trim() || !Number.isInteger(year) || year < 1900 || year > 2100) {
    $('#bank-error').textContent = 'Enter the statement year (1900–2100).';
    $('#bank-error').hidden = false;
    yearField.focus();
    return;
  }
  button.disabled = true;
  const label = button.textContent;
  button.textContent = 'Extracting...';
  $('#bank-error').hidden = true;
  try {
    token = (await api('/api/session')).token;
    await api('/api/source/bank-prepare', {year});
    await loadBank();
  } catch (error) {
    $('#bank-error').textContent = error.message;
    $('#bank-error').hidden = false;
  } finally { button.disabled = false; button.textContent = label; }
};
loadBank();


page.onRefresh(async () => { await loadBank(); await loadMatchingReadiness(); }, ['/api/source/bank-prepare', '/api/matching-pieces', '/api/receipts/']);
}
