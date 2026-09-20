<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/ExtractionReview.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
    <main>
      <header class="review-header">
        <div class="review-title"><div class="page-title"><h1>Review results</h1><PageHelp page="ExtractionReview" /></div></div>
        <div class="review-header-actions"><span id="review-progress" class="review-progress"></span><button id="accept-all-receipts" class="button secondary" type="button" title="Accept all ready extraction results">Accept all</button><button id="reload-receipts" class="button secondary" type="button" title="Load latest saved results">Reload</button></div>
      </header>
      <div class="document-bar">
        <div class="document-choice"><span id="current-document-name"></span><input id="receipt-unit" type="hidden"></div>
        <div class="document-navigation"><button id="previous-document" type="button" aria-label="Previous 10 documents">&larr;</button><div id="document-buttons" aria-label="Choose document"></div><button id="next-document" type="button" aria-label="Next 10 documents">&rarr;</button></div>
      </div>
      <div class="regeneration-controls"><span id="regeneration-status" role="status" aria-live="polite"></span></div>
      <div class="extraction-layout">
        <section class="extraction-original" aria-label="Original document">
          <div class="original-heading"><h2>Original document</h2><a id="receipt-original" class="original-link" download>Download original</a></div>
          <div id="original-viewport"><div id="original-preview"></div></div>
          <div class="viewer-footer"><label>Page / sheet <select id="original-page"></select></label><label>Zoom <select id="original-zoom"><option value="1">Fit page</option><option value="1.5">150%</option><option value="2">200%</option><option value="3">300%</option></select></label><span id="original-status" role="status"></span></div>
        </section>
        <section class="extraction-editor" id="receipt-review-panel" aria-label="Extracted pieces">
          <div class="piece-bar"><div class="piece-heading"><h2>Extracted pieces</h2><span id="piece-count" class="piece-count">0 pieces</span></div><button id="add-receipt" class="button secondary" type="button">+ Add piece</button><div id="piece-tabs" class="piece-tabs" hidden></div></div>
          <div class="piece-search"><input id="piece-query" type="search" aria-label="Search pieces" placeholder="Search all pieces by payee, reference or amount"><div id="piece-search-results"></div></div>
          <div class="piece-selection"><span id="selected-piece" role="status" aria-live="polite">No piece selected</span><div class="piece-actions" aria-label="Selected piece actions"><button id="merge-piece" type="button">Merge next</button><button id="remove-piece" type="button" aria-label="Remove this piece from extraction">Remove</button></div></div>
          <p id="receipt-error" class="validation" role="alert" hidden></p><p id="receipt-unit-status" role="status"></p>
          <form id="receipt-form"><div id="receipt-pieces"></div><div class="editor-footer"><button id="discard-document" class="button discard-document" type="button">Discard document</button><button id="accept-receipts" class="button dark" type="submit">Accept &amp; next &rarr;</button></div></form>
        </section>
      </div>
    </main>
  </div>
</template>
