<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Matching.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main class="matching-main">
    <div class="matching-heading"><div class="heading-left"><a class="back-link" href="/documents">← Documents</a><h1>Final review</h1><span id="matching-workspace" class="subtle"></span></div><a class="button dark" href="/final-report">Final report</a></div>
    <div class="matching-toolbar"><div class="review-tabs"><button id="bank-tab" class="selected" type="button">Transactions</button><button id="document-tab" type="button">Unmatched documents</button></div><div id="matching-counts" class="subtle" aria-live="polite"></div></div>
    <div id="matching-error" class="matching-error" role="alert" hidden></div>
    <section class="matching-layout" id="bank-view">
      <aside class="transaction-panel"><div class="queue-controls"><label for="bank-query">Find a transaction</label><input id="bank-query" type="search" placeholder="Name, amount, reference…"><label for="bank-filter">Decision</label><select id="bank-filter"><option value="all">All decisions</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="denied">Rejected</option></select><label for="confidence-filter">Pairing confidence</label><select id="confidence-filter"><option value="all">All confidence levels</option><option value="high">High confidence</option><option value="low">Low confidence</option><option value="none">No match</option></select><p id="queue-count" class="subtle"></p></div><div id="bank-list" class="bank-list"></div></aside>
      <section class="decision-panel"><div class="decision-scroll"><div id="transaction-detail"></div><div id="review-editor" hidden>
        <div class="section-heading"><h2>Selected support</h2></div>
        <details id="candidate-picker"><summary>Change or add documents</summary><div class="candidate-controls"><label for="candidate-query">Find a supporting document</label><input id="candidate-query" type="search" placeholder="Name, amount or filename…"><label class="check-label"><input type="checkbox" id="all-candidates"> Search all documents</label><button id="restore-suggestion" class="text-button" type="button">Reset to suggestion</button></div></details>
        <div id="candidate-list"></div>
        <div class="selection-summary" id="selection-summary" aria-live="polite"></div>
        <details id="note-details" class="review-note"><summary>Add a note</summary><label for="decision-note">Review note</label><textarea id="decision-note" rows="3" placeholder="Explain differences, identity confirmation or why you denied the suggestion."></textarea><label id="acknowledge-label" class="check-label"><input id="acknowledge" type="checkbox"> I checked the original evidence, any differences, and that these are separate expenses.</label></details>
        <details class="history"><summary>Decision history</summary><div id="decision-history"></div></details>
      </div></div><div class="decision-footer"><div id="footer-summary" class="subtle"></div><div class="decision-actions"><button id="approve-match" class="button dark" type="button" disabled>Approve</button><button id="deny-match" class="button secondary" type="button" disabled>Deny</button><button id="undo-match" class="text-button" type="button" hidden>Undo decision</button></div><p id="save-status" class="subtle" role="status"></p></div></section>
      <section class="evidence-panel"><div class="evidence-heading"><div><h2 id="evidence-title">Select a document</h2></div><a id="evidence-original" target="_blank" rel="noopener" hidden>Open original ↗</a></div><div class="evidence-navigation"><button id="preview-bank" class="button secondary" type="button">Bank statement</button><button id="preview-prev" type="button" aria-label="Previous source page">‹</button><select id="preview-page" aria-label="Source page"></select><button id="preview-next" type="button" aria-label="Next source page">›</button></div><div id="evidence-content" class="evidence-content"><div class="empty-state">Select a transaction to start reviewing.</div></div></section>
    </section>
    <section id="document-view" class="unmatched-panel" hidden><div class="section-heading"><div><h2>Unmatched supporting evidence</h2><p>Unallocated and partially allocated items. Contextual documents have no monetary balance.</p></div><input id="document-query" type="search" aria-label="Search unmatched evidence" placeholder="Find a document or amount…"></div><div class="unmatched-bank-picker"><label>Find a bank transaction<input id="unmatched-bank-query" type="search" placeholder="Name, amount or reference…"></label><label>Match evidence to<select id="unmatched-bank" aria-label="Transaction for unmatched evidence"></select></label></div><div id="unmatched-list"></div></section>
  </main>
  </div>
</template>
