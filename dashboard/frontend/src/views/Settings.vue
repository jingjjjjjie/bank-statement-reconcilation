<script setup>
import PageHelp from '../components/PageHelp.vue';
import { ref } from 'vue';
import { usePage } from '../page.js';
import initialize from '../controllers/Settings.js';

const root = ref(null);
usePage(root, initialize);
</script>

<template>
  <div ref="root" class="page-view">
<main class="settings-page">
    <section class="page-heading"><div><div class="page-title"><h1>Review settings</h1><PageHelp page="Settings" /></div></div></section>
    <div id="settings-error" class="validation" role="alert" hidden></div>
    <section class="settings-card codex-account"><div class="section-title"><div><h2>Codex account <span id="codex-version" class="codex-version"></span></h2></div>
        <span id="codex-detail" class="codex-detail"></span></div>
      <p class="codex-state"><span id="codex-dot" class="status-dot busy" aria-hidden="true"></span><strong id="codex-status" role="status" aria-live="polite">Checking Codex…</strong></p>
      <div class="codex-actions"><button type="button" class="button secondary" id="codex-check">Check now</button><button type="button" class="button secondary" id="codex-update">Check for updates</button><button type="button" class="button secondary" id="codex-login-start">Log in with ChatGPT</button><button type="button" class="button secondary" id="codex-login-cancel" hidden>Cancel</button></div>
      <ol id="codex-login" class="codex-login" hidden><li>Open <a id="codex-login-url" target="_blank" rel="noopener noreferrer"></a></li><li>Enter <code id="codex-login-code" class="codex-code"></code> (expires in 15 minutes)</li></ol>
      <pre id="codex-output" class="codex-output" hidden></pre>
    </section>
    <form id="settings-form">
      <fieldset id="settings-fields" disabled>
        <section class="settings-card"><div class="section-title"><div><h2>Documents</h2></div></div>
          <div class="settings-grid">
            <label class="setting-field"><strong>PDF processing</strong><select id="pdf-mode"><option value="vision">Vision: every page</option><option value="text_only">Legacy: extractor only</option><option value="auto">Legacy: vision for sparse pages only</option></select></label>
            <label class="setting-field"><strong>PDF pages per call</strong><input id="pdf-whole-document-max-pages" type="number" min="1" max="40" required aria-describedby="pdf-whole-document-help"><span id="pdf-whole-document-help">Short PDFs: one call. Longer PDFs: groups up to this size, then whole-document assembly.</span></label>
            <label class="setting-switch"><span><strong>Allow picture processing</strong></span><input id="pictures-enabled" type="checkbox" role="switch"></label>
          </div>
        </section>
        <section class="settings-card"><div class="section-title"><div><h2>Codex</h2></div></div>
          <label class="setting-switch codex-master"><span><strong>Enable Codex reasoning and vision</strong></span><input id="codex-enabled" type="checkbox" role="switch"></label>

          <div id="stage-settings"></div>
        </section>
        <section class="settings-card"><div class="section-title"><div><h2>Request limit per run</h2></div></div>

          <div class="budget-grid">
            <label class="setting-field"><strong>Maximum new Codex requests</strong><input id="max-calls" type="number" min="1" max="1000" required aria-describedby="call-example"></label>
            <div class="call-example"><p id="call-example" aria-live="polite">Loading saved limit…</p></div>
          </div>
          <label class="setting-field"><strong>Codex requests in parallel</strong><input id="max-parallel" type="number" min="1" max="8" required></label>


        </section>
        <section class="settings-card"><div class="section-title"><div><h2>Workspace token usage</h2></div></div>
          <div id="token-usage" aria-live="polite">Loading usage…</div>
          <pre id="token-breakdown"></pre>

        </section>
      </fieldset>
      <div id="settings-refresh" class="validation" hidden>Prepared inputs need refreshing before the next content review. Previous metadata and decisions are archived.<code class="block-code">.tools\python\python.exe vision_workflow.py prepare --refresh</code></div>
      <div class="settings-savebar"><div><strong id="save-state" role="status" aria-live="polite">Loading settings…</strong></div><div><button type="button" class="button secondary" id="discard-settings" disabled>Discard changes</button><button type="submit" class="button dark" id="save-settings" disabled>Save settings</button></div></div>
    </form>

  </main>
  </div>
</template>
