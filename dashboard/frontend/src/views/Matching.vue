<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Matching.js';

const root = ref(null);
usePage(root, initialize);
const split = ref(50), resizing = ref(false);
try {
  const saved = Number(localStorage.getItem('matching-review-width'));
  if (saved >= 35 && saved <= 65) split.value = saved;
} catch { /* Storage restrictions leave the default equal split available. */ }

// Keep this display preference separate from transaction drafts and review decisions.
function setSplit(value) {
  split.value = Math.max(35, Math.min(65, Math.round(value)));
  try { localStorage.setItem('matching-review-width', String(split.value)); } catch { /* Resizing still works without storage. */ }
}
function moveSplit(event) {
  // Pointer capture keeps dragging reliable when the pointer leaves the handle.
  if (!resizing.value) return;
  const bounds = event.currentTarget.parentElement.getBoundingClientRect();
  setSplit((event.clientX - bounds.left) / bounds.width * 100);
}
function startSplit(event) {
  // Use a single captured pointer without registering document-wide listeners.
  if (event.button !== 0) return;
  event.currentTarget.setPointerCapture(event.pointerId);
  resizing.value = true;
}
function keySplit(event) {
  // Arrow keys adjust the split; Home and double-click restore equal panels.
  if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return;
  event.preventDefault();
  setSplit(event.key === 'Home' ? 50 : split.value + (event.key === 'ArrowLeft' ? -2 : 2));
}
</script>

<template>
  <div ref="root" class="page-view">
<main class="matching-main">
    <section aria-label="Review controls">
      <div class="queue-controls">
        <div class="page-title"><h1>Review Matching</h1><PageHelp page="Matching" /></div>

        <button type="button" class="button secondary" popovertarget="matching-options" aria-label="Review options">Options</button>
        <div id="matching-options" popover>
          <div class="review-tabs"><button id="bank-tab" class="selected" type="button">Transactions</button><button id="document-tab" type="button">Unmatched pieces</button></div>

        </div>
        <div id="transaction-toolbar" class="confidence-controls">
        <label class="sr-only" for="bank-filter">Decision</label><select id="bank-filter"><option value="all">All decisions</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="denied">Rejected</option></select>
        <label class="sr-only" for="confidence-filter">Pairing confidence</label><select id="confidence-filter"><option value="all">All confidence levels</option><option value="high">High confidence</option><option value="low">Low confidence</option><option value="none">No match</option></select>
        <span id="queue-count" class="subtle" role="status"></span>
        <div class="transaction-navigation"><button id="previous-transactions" type="button" aria-label="Previous ten transactions">&larr;</button><div id="transaction-pages" role="group" aria-label="Transaction pages"></div><button id="next-transactions" type="button" aria-label="Next ten transactions">&rarr;</button></div>
        </div>
      </div>
    </section>
    <p id="matching-load-note" class="warning" hidden>Load the current data for final matching on the Bank statement page first.</p>
    <p id="matching-outdated" class="warning" hidden>Saved proposals are outdated. Results remain visible; recheck current evidence or generate matches again.</p>
    <div id="matching-error" class="matching-error" role="alert" hidden></div>
    <p id="filtered-empty" class="empty-state" role="status" hidden>No transactions match these filters.</p>
    <section class="matching-layout" id="bank-view" :class="{'is-resizing': resizing}" :style="{'--review-width': `${split}fr`, '--evidence-width': `${100 - split}fr`}">
      <section class="decision-panel" aria-label="Candidate review"><div class="decision-scroll"><div id="transaction-detail"></div><div id="review-editor" hidden>
        <section id="selected-tray" class="candidate-tray" aria-labelledby="selected-heading">
          <div class="section-heading"><h2 id="selected-heading">Selected</h2><span id="selected-count" class="subtle" aria-live="polite"></span></div>
          <div id="selected-candidates"></div>
        </section>
        <section id="support-group" class="candidate-tray" aria-labelledby="support-heading">
          <div class="section-heading"><div class="candidate-heading"><h2 id="support-heading">Available candidates</h2><span id="candidate-count" class="subtle" role="status"></span></div><button id="toggle-candidate-search" class="text-button" type="button" aria-expanded="false" aria-controls="candidate-search">Search</button><span id="support-status" class="sr-only" aria-live="polite"></span></div>
          <div id="candidate-search" class="candidate-controls" hidden><label class="sr-only" for="candidate-query">Search all supporting pieces</label><input id="candidate-query" type="search" placeholder="Search all pieces"><button id="restore-suggestion" class="text-button" type="button">Reset to suggestion</button></div>
          <div id="candidate-list" tabindex="0" role="region" aria-label="Supporting candidate results"></div>
        </section>
        <div class="selection-summary" id="selection-summary" aria-live="polite"></div>
      </div></div></section>
      <div class="matching-divider" role="separator" aria-label="Resize review and evidence panels" aria-orientation="vertical" :aria-valuenow="split" aria-valuemin="35" aria-valuemax="65" tabindex="0" title="Drag to resize; double-click to reset" @pointerdown="startSplit" @pointermove="moveSplit" @pointerup="resizing = false" @pointercancel="resizing = false" @lostpointercapture="resizing = false" @keydown="keySplit" @dblclick="setSplit(50)"></div>
      <section class="evidence-panel" aria-label="Original evidence">
        <div class="evidence-heading"><label class="sr-only" for="preview-source">Displayed evidence</label><select id="preview-source" aria-label="Displayed evidence"></select><span id="evidence-title" class="sr-only">Select a document</span><button id="preview-bank" class="button secondary" type="button">Bank statement</button></div>
        <div id="evidence-content" class="evidence-content"><div class="empty-state">Select a transaction to start reviewing.</div></div>
        <div class="evidence-navigation"><button id="preview-prev" type="button" aria-label="Previous source page" disabled>&lsaquo;</button><label class="sr-only" for="preview-page">Source page</label><select id="preview-page" aria-label="Source page"></select><button id="preview-next" type="button" aria-label="Next source page" disabled>&rsaquo;</button><label for="preview-zoom">Zoom</label><select id="preview-zoom"><option value="1">Fit width</option><option value="1.5">150%</option><option value="2">200%</option><option value="3">300%</option></select><a id="evidence-original" target="_blank" rel="noopener" hidden>Open original ↗</a></div>
        <div class="decision-footer"><div class="decision-actions"><button id="approve-match" class="button dark" type="button" disabled>Confirm &amp; next</button><button id="deny-match" class="button secondary" type="button" disabled>Reject suggestion</button><button id="undo-match" class="text-button" type="button" hidden>Undo decision</button><button id="next-review-transaction" class="button secondary" type="button" disabled>Next &rarr;</button></div><p id="save-status" class="subtle" role="status"></p></div>
      </section>
    </section>
    <section id="document-view" class="unmatched-panel" hidden><div class="section-heading"><div><h2>Unmatched supporting evidence</h2></div><input id="document-query" type="search" aria-label="Search unmatched evidence" placeholder="Find a piece, payee or amount…"></div><div class="unmatched-bank-picker"><label>Find a bank transaction<input id="unmatched-bank-query" type="search" placeholder="Name, amount or reference…"></label><label>Match evidence to<select id="unmatched-bank" aria-label="Transaction for unmatched evidence"></select></label></div><div id="unmatched-list"></div></section>
  </main>
  </div>
</template>
