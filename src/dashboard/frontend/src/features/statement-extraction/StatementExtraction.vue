<script setup>
import { computed, ref } from 'vue';
import { appState } from '../../api.js';
import PageHelp from '../../components/PageHelp.vue';

const file = ref(null), year = ref(new Date().getFullYear()), bank = ref('auto'), company = ref('');
const result = ref(null), busy = ref(false), error = ref(''), search = ref('');
const banks = { auto: 'Auto-detect', ambank: 'AmBank', public_bank: 'Public Bank', maybank: 'Maybank', hong_leong: 'Hong Leong Bank', cimb: 'CIMB', uob: 'UOB' };
const rows = computed(() => (result.value?.statement.transactions || []).filter(row =>
  `${row.narration} ${row.counterparty} ${row.date}`.toLowerCase().includes(search.value.toLowerCase())));

// Format statement amounts consistently with the bank report.
function money(value) { return Number(value).toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

// Clear outdated downloads whenever the extraction inputs change.
function reset() { result.value = null; error.value = ''; search.value = ''; }
function choose(event) { file.value = event.target.files[0] || null; reset(); }
// Upload directly to the isolated endpoint without changing workspace state.
async function extract() {
  reset(); busy.value = true;
  try {
    if (!file.value || file.value.size > 25 * 1024 * 1024) throw Error('Choose a PDF smaller than 25 MB');
    const content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(',')[1]);
      reader.onerror = () => reject(Error('Unable to read this file'));
      reader.readAsDataURL(file.value);
    });
    const response = await fetch('/api/statement-extraction', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Review-Token': appState.session.token },
      body: JSON.stringify({ filename: file.value.name, content, year: year.value, bank: bank.value, company: company.value }),
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Extraction failed');
    result.value = data;
  } catch (failure) { error.value = failure.message; }
  finally { busy.value = false; }
}
// Download the validated output held by this page, then release its object URL.
function download(kind) {
  const bytes = Uint8Array.from(atob(result.value[kind]), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: kind === 'csv' ? 'text/csv' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }));
  const link = document.createElement('a');
  link.href = url; link.download = `bank-transactions.${kind}`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
</script>

<template>
  <main class="standalone-extraction">
    <div class="bank-workspace">
      <section class="page-heading"><div class="page-title"><h1>Bank Statement Extraction</h1><PageHelp page="StatementExtraction" /></div></section>
      <form class="settings-card" @submit.prevent="extract">
        <fieldset :disabled="busy">
          <label class="upload-field">Bank statement PDF
            <input type="file" accept=".pdf,application/pdf" required @change="choose">
            <small>Digital PDF, up to 25 MB</small>
          </label>
          <div class="extraction-fields">
            <label>Bank<select v-model="bank" @change="reset"><option v-for="(name, key) in banks" :key="key" :value="key">{{ name }}</option></select></label>
            <label>Statement year<input v-model.number="year" type="number" min="1900" max="2100" required @input="reset"></label>
            <label>Company name<input v-model="company" maxlength="200" placeholder="Name for the workbook" required @input="reset"></label>
          </div>
          <div class="extract-actions"><span v-if="busy" role="status">Checking layout, balances and totals...</span><button class="button dark" type="submit">{{ busy ? 'Extracting...' : 'Extract' }}</button></div>
        </fieldset>
        <p v-if="error" role="alert" class="validation">{{ error }}</p>
      </form>
      <section v-if="result" aria-label="Extracted transactions" class="extraction-results">
        <div class="result-heading"><div><h2>{{ banks[result.statement.bank] }}</h2><p>{{ result.statement.account }} &middot; {{ result.statement.currency }} &middot; {{ result.statement.transactions.length }} transactions</p></div><div class="download-actions"><button class="button dark" @click="download('xlsx')">Download Excel</button><button class="button secondary" @click="download('csv')">Download CSV</button></div></div>
        <p v-if="result.statement.validation_note" role="alert" class="validation">{{ result.statement.validation_note }}</p>
        <div class="stats bank-stats"><div v-for="(label, key) in { opening_balance: 'Opening balance', total_money_in: 'Money in', total_money_out: 'Money out', closing_balance: 'Closing balance' }" :key="key"><span>{{ label }}</span><strong>{{ money(result.statement[key]) }}</strong></div></div>
        <section class="settings-card">
          <div class="bank-toolbar"><h2>Transactions</h2><input v-model="search" type="search" aria-label="Search transactions" placeholder="Search date, counterparty or narration"></div>
          <div class="bank-table-wrap"><table class="bank-table"><thead><tr><th>Date</th><th>Pay to / from</th><th>Narration</th><th class="amount">Money in</th><th class="amount">Money out</th><th class="amount">Balance</th></tr></thead><tbody><tr v-for="row in rows" :key="row.transaction_id"><td>{{ row.date }}</td><td>{{ row.counterparty || '\u2014' }}</td><td class="narration">{{ row.narration }}</td><td class="amount">{{ money(row.money_in) }}</td><td class="amount">{{ money(row.money_out) }}</td><td class="amount">{{ money(row.balance) }}<small v-if="row.balance_origin === 'calculated'">Calculated</small></td></tr><tr v-if="!rows.length"><td colspan="6" class="empty-result">No transactions match your search.</td></tr></tbody></table></div>
          <p class="bank-row-count">{{ rows.length }} of {{ result.statement.transactions.length }} transactions</p>
        </section>
      </section>
    </div>
  </main>
</template>

<style scoped>
.standalone-extraction { max-width:1320px; margin:0 auto; padding:24px; }
fieldset { border:0; margin:0; padding:0; min-width:0; }
label { display:flex; flex-direction:column; gap:8px; font-size:12px; font-weight:600; color:var(--ink); min-width:0; }
input, select { box-sizing:border-box; width:100%; min-width:0; height:42px; padding:10px 12px; border:1px solid var(--line); border-radius:7px; background:white; color:var(--ink); font:inherit; font-size:14px; }
input:focus-visible, select:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
.upload-field { padding:18px; border:1px dashed #bccfe3; border-radius:8px; background:var(--paper); }
input[type=file] { height:auto; padding:0; border:0; background:transparent; }
input[type=file]::file-selector-button { padding:9px 14px; margin-right:12px; border:1px solid var(--line); border-radius:6px; background:white; color:var(--primary); font:inherit; cursor:pointer; }
small { display:block; color:var(--muted); font-size:11px; font-weight:400; }
.extraction-fields { display:grid; grid-template-columns:1fr 160px 1.5fr; gap:18px; margin-top:20px; }
.extract-actions { display:flex; justify-content:flex-end; align-items:center; gap:16px; margin-top:20px; }
.extract-actions span { color:var(--muted); font-size:12px; }
.extract-actions .button { min-width:140px; }
.extraction-results { border-top:1px solid var(--line); }
.result-heading { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:20px 24px 0; }
.result-heading h2 { font-size:16px; margin:0 0 6px; }
.result-heading p { font-size:12px; color:var(--muted); margin:0; }
.download-actions { display:flex; gap:8px; flex-wrap:wrap; }
.extraction-results > .validation { margin:16px 24px; }
.bank-toolbar { gap:16px; }
.bank-toolbar h2 { margin:0; }
.bank-toolbar input { width:340px; max-width:100%; }
.bank-table-wrap { overflow:auto; }
.bank-table td { vertical-align:top; }
.bank-table .amount { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.narration { white-space:pre-wrap; min-width:220px; max-width:420px; color:var(--muted); font-size:12px; }
.empty-result { text-align:center; padding:28px; color:var(--muted); }
@media(max-width:700px) {
  .standalone-extraction { padding:16px; }
  .extraction-fields { grid-template-columns:1fr; gap:14px; }
  .result-heading { align-items:flex-start; flex-direction:column; }
  .bank-toolbar { align-items:stretch; flex-direction:column; }
  .bank-toolbar input { width:100%; }
  .download-actions { width:100%; }
  .download-actions .button { flex:1; }
}
</style>
