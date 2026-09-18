<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/ExtractionReview.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main>
<header class="review-header"><div class="review-title"><a href="/documents" aria-label="Back to document status">← Documents</a><span class="header-divider"></span><h1>Step 2 · Review results</h1></div><div class="document-choice"><label for="receipt-unit">DOCUMENT / PAGE</label><select id="receipt-unit" aria-label="Document / page"></select></div><div class="document-navigation"><button id="previous-document" type="button" aria-label="Previous document">←</button><span id="document-position">0 / 0</span><button id="next-document" type="button" aria-label="Next document">→</button></div><div class="review-header-actions"><span id="review-progress" class="review-progress"></span><button id="reload-receipts" class="button secondary" type="button" title="Load latest saved results">Reload</button></div></header>
<div class="regeneration-controls"><span id="regeneration-status" role="status" aria-live="polite"></span></div>
<div class="extraction-layout">
<section class="extraction-original" aria-label="Original document"><div id="original-viewport"><div id="original-preview"></div></div><div class="viewer-footer"><label>Page / sheet <select id="original-page"></select></label><label>Zoom <select id="original-zoom"><option value="1">Fit page</option><option value="1.5">150%</option><option value="2">200%</option><option value="3">300%</option></select></label><a id="receipt-original" class="original-link" target="_blank" rel="noopener">Open file ↗</a><span id="original-status" role="status"></span></div></section>
<section class="extraction-editor" id="receipt-review-panel"><div class="piece-bar"><span id="piece-count" class="piece-count">0 pieces</span><div id="piece-tabs" class="piece-tabs" aria-label="Receipt pieces"></div><div class="piece-actions"><button id="split-piece" type="button" aria-label="Split receipt">Split</button><button id="remove-piece" type="button" aria-label="Remove this piece from extraction">Remove</button></div></div><p id="receipt-error" class="validation" role="alert" hidden></p><p id="receipt-unit-status" role="status"></p>
<form id="receipt-form"><div id="receipt-pieces"></div><div class="editor-footer"><button id="add-receipt" class="button secondary" type="button">+ Add piece</button><button id="accept-receipts" class="button dark" type="submit">Accept &amp; next →</button></div></form>
</section></div></main>
  </div>
</template>
