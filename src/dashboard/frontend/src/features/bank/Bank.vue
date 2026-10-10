<script setup>
import PageHelp from '../../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../../page.js';
import initialize from './Bank.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
    <div class="bank-workspace">
    <section class="page-heading"><div><div class="page-title"><h1>Bank Statement Extraction</h1><PageHelp page="Bank" /></div><p id="bank-note">Loading the extracted bank statement…</p></div><a id="workbook" class="button dark" href="/api/bank-workbook" download="answer_statement_bank_only.xlsx" hidden>Download bank-only workbook</a></section>
    <div id="bank-error" class="validation" role="alert" hidden></div>
    <section id="bank-extraction" class="settings-card" hidden>
      <h2>Extract bank statement</h2><p id="statement-source"></p>
      <label class="setting-field"><strong>Statement year</strong><input id="bank-year" type="number" min="1900" max="2100" step="1" required placeholder="Enter year"></label>

      <button id="prepare-bank" class="button dark" type="button">Extract bank statement</button>
      <p id="bank-result" role="status"></p>
    </section>
    <section class="settings-card documents-page" aria-label="Final matching">
      <div class="processing-toolbar"><h2>Final matching</h2>
      <div class="stage-actions"><button id="load-final-matching" class="button secondary" type="button">Load for final matching</button><button id="generate-matches" type="button" class="button dark" disabled>Generate matches</button><button id="stop-matches" type="button" class="button secondary" disabled>Stop</button></div></div>
      <p id="final-matching-ready" role="status"></p>
    <section id="matching-progress" class="document-progress" aria-label="Matching progress">
      <div class="matching-progress-label"><strong id="matching-run-status" role="status" aria-live="polite"></strong><span id="matching-progress-count"></span></div>
      <progress id="matching-progress-bar" max="100" value="0" aria-labelledby="matching-run-status" aria-describedby="matching-progress-count"></progress>
      <div id="matching-progress-track" class="progress-track" aria-hidden="true"><span class="progress-fill"></span><span class="progress-activity"></span></div>
      <p id="matching-progress-detail" role="status"></p>
    </section>
    </section>
    <section id="bank-content" hidden>
      <section class="stats bank-stats"><div><span>Transactions</span><strong id="bank-count"></strong><small id="bank-account"></small></div><div><span>Opening balance</span><strong id="bank-opening"></strong></div><div><span>Money in / out</span><strong id="bank-flow"></strong></div><div><span>Closing balance</span><strong id="bank-closing"></strong><small id="bank-checks"></small></div></section>
      <section class="settings-card"><div class="bank-toolbar"><div><h2>Statement rows</h2><p id="match-note"></p></div><input id="bank-search" type="search" placeholder="Search date, payee, reference, or amount" aria-label="Search bank transactions"></div><div class="bank-table-wrap"><table class="bank-table"><thead><tr><th>Date</th><th>Pay to / from</th><th>Money in</th><th>Money out</th><th>Balance</th><th>Match</th></tr></thead><tbody id="bank-rows"></tbody></table></div><p id="row-count" class="bank-row-count"></p></section>
    </section>
    </div>
  </main>
  </div>
</template>
