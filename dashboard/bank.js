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
    if (!data.available) { $('#bank-note').textContent = 'No prepared bank statement was found.'; $('#bank-source-link').hidden = false; return; }
    transactions = data.transactions;
    $('#bank-note').textContent = 'Extracted bank data for review. Supporting-document matching is still pending.';
    $('#bank-count').textContent = data.count;
    $('#bank-account').textContent = `Account ${data.account} · ${data.currency}`;
    $('#bank-opening').textContent = money(data.opening_balance);
    $('#bank-flow').textContent = `${money(data.total_money_in)} / ${money(data.total_money_out)}`;
    $('#bank-closing').textContent = money(data.closing_balance);
    $('#bank-checks').textContent = data.balance_checks === 'passed' ? 'Bank balance checks passed' : 'Bank balance checks need review';
    $('#match-note').textContent = `${data.matched} of ${data.count} transactions matched to supporting documents`;
    $('#workbook').hidden = !data.workbook_available;
    try {
      const defaults = await api('/api/bank-export-defaults');
      $('#export-company').value = defaults.company;
      $('#export-template').value = defaults.template;
    } catch (error) { $('#export-error').textContent = error.message; $('#export-error').hidden = false; }
    $('#bank-content').hidden = false;
    renderRows();
  } catch (error) { $('#bank-error').textContent = error.message; $('#bank-error').hidden = false; }
}
async function exportWorkbook() {
  const button = $('#export-button');
  $('#export-error').hidden = true;
  button.disabled = true;
  try {
    token = (await api('/api/session')).token;
    const response = await fetch('/api/bank-export', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Review-Token': token},
      body: JSON.stringify({company: $('#export-company').value, template: $('#export-template').value})});
    if (!response.ok) throw Error((await response.json()).error || 'Export failed');
    const url = URL.createObjectURL(await response.blob());
    const link = node('a'); link.href = url; link.download = 'answer_statement_bank_only.xlsx';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    $('#export-error').textContent = error.message;
    $('#export-error').hidden = false;
  } finally { button.disabled = false; }
}
$('#bank-search').addEventListener('input', renderRows);
$('#check-bank').onclick = async () => {
  const button = $('#check-bank'); button.disabled = true;
  try {
    const status = await api('/api/workflow-checks');
    const bank = status.steps[3];
    const pending = status.steps.slice(1, 3).filter(step => !step.checked).map(step => step.name.toLowerCase());
    $('#bank-next').hidden = !bank.next;
    $('#bank-step-note').textContent = !bank.checked ? 'Bank balance checks need review.' :
      bank.next ? 'Bank extraction passed. Continue to the completion checks.' :
      `Bank extraction passed. Finish ${pending.join(' and ')} before continuing.`;
  } catch (error) { $('#bank-step-note').textContent = error.message; }
  finally { button.disabled = false; }
};
$('#export-button').addEventListener('click', exportWorkbook);
loadBank();
