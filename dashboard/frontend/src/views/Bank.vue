<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Bank.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <section class="page-heading"><div><div class="page-title"><h1>AmBank transactions</h1><PageHelp page="Bank" /></div><p id="bank-note">Loading the extracted bank statement…</p></div><a id="workbook" class="button dark" href="/api/bank-workbook" download="answer_statement_bank_only.xlsx" hidden>Download bank-only workbook</a></section>
    <div id="bank-error" class="validation" role="alert" hidden></div>
    <section id="bank-extraction" class="settings-card" hidden>
      <h2>Extract bank statement</h2><p id="statement-source"></p>
      <label class="setting-field"><strong>Statement year</strong><input id="bank-year" type="number" min="1900" max="2100" step="1" required placeholder="Enter year"></label>

      <button id="prepare-bank" class="button dark" type="button">Extract bank statement</button>
      <p id="bank-result" role="status"></p>
    </section>
    <section id="bank-content" hidden>
      <section class="stats bank-stats"><div><span>Transactions</span><strong id="bank-count"></strong><small id="bank-account"></small></div><div><span>Opening balance</span><strong id="bank-opening"></strong></div><div><span>Money in / out</span><strong id="bank-flow"></strong></div><div><span>Closing balance</span><strong id="bank-closing"></strong><small id="bank-checks"></small></div></section>
      <div class="stage-actions"><button id="check-bank" class="button secondary" type="button">Check bank extraction</button><p id="bank-step-note" role="status"></p></div>
      <section class="settings-card"><h2>Export styled Excel</h2><div class="bank-export-fields"><label>Company name<input id="export-company" type="text" autocomplete="organization" placeholder="Company Sdn. Bhd."></label></div><button id="export-button" class="button dark" type="button">Export Excel</button><p id="export-error" class="validation" role="alert" hidden></p></section>
      <section class="settings-card"><div class="bank-toolbar"><div><h2>Statement rows</h2><p id="match-note"></p></div><input id="bank-search" type="search" placeholder="Search date, payee, reference, or amount" aria-label="Search bank transactions"></div><div class="bank-table-wrap"><table class="bank-table"><thead><tr><th>Date</th><th>Pay to / from</th><th>Money in</th><th>Money out</th><th>Balance</th><th>Match</th></tr></thead><tbody id="bank-rows"></tbody></table></div><p id="row-count" class="bank-row-count"></p></section>
    </section>
  </main>
  </div>
</template>
