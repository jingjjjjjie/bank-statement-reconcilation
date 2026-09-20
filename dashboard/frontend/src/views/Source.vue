<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Source.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main class="workspace-picker">
    <section class="picker-heading"><div class="page-title"><h1>Choose your workspace</h1><PageHelp page="Source" /></div></section>
    <section class="workspace-card" aria-label="Workspace selection">
      <div class="workspace-card-top">
        <span class="folder-symbol" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11H3V7Z"/></svg></span>
        <div class="workspace-identity"><h2 id="workspace-name">Choose a folder to begin</h2><p id="workspace-location"></p></div>
        <button id="browse-source" class="button secondary" type="button">Browse folders</button>
      </div>
      <div id="source-error" class="validation" role="alert" hidden></div>
      <div id="selected-source" class="workspace-inputs" role="status" hidden>
        <div class="workspace-input"><span class="input-kind">STATEMENT</span><strong>1 bank statement</strong><span id="statement-name"></span></div>
        <div class="workspace-input"><span class="input-kind">DOCUMENTS</span><strong id="document-count"></strong></div>
      </div>
      <details class="manual-path"><summary>Enter a folder path manually</summary><div class="manual-path-controls"><label for="source-path">Workspace folder</label><input id="source-path" type="text" autocomplete="off" spellcheck="false" placeholder="/uploads/WorkName"><button id="select-source" class="button secondary" type="button">Select workspace</button></div></details>
      <div id="source-action" class="workspace-card-footer" hidden>
        <div><span id="workspace-status" class="workspace-ready">Checking workspace</span><p id="source-preview" aria-live="polite">Checking supporting files...</p></div>
        <button id="prepare-source" class="button secondary" type="button" hidden>Prepare files</button>
        <button id="start-source" class="button dark" type="button" disabled>Proceed</button>
      </div>
      <section id="source-preparation" hidden aria-label="File preparation progress">
        <strong id="preparation-stage" role="status" aria-live="polite"></strong>
        <progress id="preparation-bar" max="100" value="0" aria-labelledby="preparation-stage"></progress>
        <p id="preparation-detail"></p><p id="preparation-warnings" class="validation" hidden></p>
      </section>
    </section>

  </main>
  <dialog id="path-browser" class="path-browser" aria-label="Browse local files">
    <div class="browser-heading"><div><strong>Choose a workspace folder</strong><p id="browser-current">Loading folders…</p></div><button id="browser-close" class="button secondary" type="button">Close</button></div>
    <div id="browser-error" class="validation" role="alert" hidden></div>
    <div id="browser-items" class="browser-items"></div>
    <div class="browser-footer"><button id="browser-use" class="button dark" type="button" hidden>Select this workspace</button></div>
  </dialog>
  </div>
</template>
