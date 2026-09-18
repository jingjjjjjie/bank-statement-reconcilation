<script setup>
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Source.js';
import WorkflowProgress from '../components/WorkflowProgress.vue';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main class="workspace-picker">
    <header><span class="picker-kicker">YOUR REVIEW WORKSPACE</span><a class="header-settings" href="/content-review">Return to review &rarr;</a></header>
    <WorkflowProgress />
    <section class="picker-heading"><span class="picker-step">01 / GET STARTED</span><h1>Choose your workspace</h1><p>One folder. Your statement and supporting documents, together.</p></section>
    <section class="workspace-card" aria-label="Workspace selection">
      <div class="workspace-card-top">
        <span class="folder-symbol" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11H3V7Z"/></svg></span>
        <div class="workspace-identity"><span class="picker-label">SELECTED WORKSPACE</span><h2 id="workspace-name">Choose a folder to begin</h2><p id="workspace-location">Select a workspace from your upload folder.</p></div>
        <button id="browse-source" class="button secondary" type="button">Browse folders</button>
      </div>
      <div id="source-error" class="validation" role="alert" hidden></div>
      <div id="selected-source" class="workspace-inputs" role="status" hidden>
        <div class="workspace-input"><span class="input-kind">STATEMENT</span><strong>1 bank statement</strong><span id="statement-name"></span><span class="input-found">Detected in statement/</span></div>
        <div class="workspace-input"><span class="input-kind">DOCUMENTS</span><strong id="document-count"></strong><span>Receipts, invoices and other supporting files</span><span class="input-found">Detected in documents/</span></div>
      </div>
      <details class="manual-path"><summary>Enter a folder path manually</summary><div class="manual-path-controls"><label for="source-path">Workspace folder</label><input id="source-path" type="text" autocomplete="off" spellcheck="false" placeholder="/uploads/WorkName"><button id="select-source" class="button secondary" type="button">Select workspace</button></div></details>
      <div id="source-action" class="workspace-card-footer" hidden>
        <div><span id="workspace-status" class="workspace-ready">Checking workspace</span><p id="source-preview" aria-live="polite">Checking supporting files...</p></div>
        <button id="start-source" class="button dark" type="button" disabled>Proceed</button>
      </div>
    </section>
    <details class="workspace-format"><summary>How should my workspace be organized?</summary><div><pre>WorkName/
  statement/   One bank-statement PDF
  documents/   All supporting files</pre><p>Select WorkName itself. We find both inputs automatically. Duplicate reports are generated automatically when you proceed.</p></div></details>
  </main>
  <dialog id="path-browser" class="path-browser" aria-label="Browse local files">
    <div class="browser-heading"><div><strong>Choose a workspace folder</strong><p id="browser-current">Loading folders…</p></div><button id="browser-close" class="button secondary" type="button">Close</button></div>
    <div id="browser-error" class="validation" role="alert" hidden></div>
    <div id="browser-items" class="browser-items"></div>
    <div class="browser-footer"><button id="browser-use" class="button dark" type="button" hidden>Select this workspace</button></div>
  </dialog>
  </div>
</template>
