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
    <section class="settings-card"><label class="setting-switch"><span><strong>Development / testing mode</strong></span><input id="development-mode" type="checkbox" role="switch" disabled></label><p id="development-mode-status" role="status">Loading mode?</p></section>
    <form id="settings-form">
      <fieldset id="settings-fields" disabled>
        <section class="settings-card"><div class="section-title"><div><h2>Documents</h2></div></div>
          <div class="settings-grid">
            <label class="setting-field"><strong>PDF processing</strong><select id="pdf-mode"><option value="vision">Vision: every page</option><option value="hybrid" data-development-tools hidden>Text + checked vision fallback (testing)</option><option value="compare" data-development-tools hidden>Compare text and vision (testing)</option><option value="text_only">Legacy: extractor only</option><option value="auto">Legacy: vision for sparse pages only</option></select></label>
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
      <div class="settings-savebar"><div><strong id="save-state" role="status" aria-live="polite">Loading settings…</strong></div><div><button type="button" class="button secondary" id="use-defaults" data-development-tools hidden disabled>Use testing defaults</button><button type="button" class="button secondary" id="discard-settings" disabled>Discard changes</button><button type="submit" class="button dark" id="save-settings" disabled>Save settings</button></div></div>
    </form>
    <section class="settings-card" data-development-tools hidden><h2>Development cache</h2>
      <p id="development-status" role="status">Loading remembered decisions…</p>
      <label class="setting-field"><strong>Your name for replayed content decisions</strong><input id="development-reviewer" autocomplete="name" placeholder="Admin name"></label>
      <div class="content-actions"><button class="button secondary" id="remember-decisions" type="button">Remember current decisions</button><button class="button secondary" id="apply-decisions" type="button">Apply remembered decisions</button></div>
    </section>

  </main>
  </div>
</template>
