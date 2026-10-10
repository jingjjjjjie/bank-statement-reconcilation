<script setup>
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { appState } from '../api.js';
import logo from '../assets/upvantage.jpg';
const links = [
  ['/source', 'Workspace'], ['/documents', 'Documents'],
  ['/extraction-review', 'Review Extraction'], ['/bank', 'Bank statement'],
  ['/matching', 'Review Matching'], ['/final-report', 'Export'],
];
// Pair each header destination with its existing workflow status.
const items = computed(() => {
  const steps = appState.steps.filter(step => step.href !== '/review');
  return links.map(([path, label]) => {
    const index = steps.findIndex(step => (step.href === '/' ? '/source' : step.href) === path);
    const status = steps[index];
    return { path, label, step: path !== '/final-report' ? status : null, number: index + 1,
      disabled: status?.available === false || (!status && ['/matching', '/extraction-review'].includes(path)),
      reason: status?.blocked_reason || 'Checking workflow readiness…' };
  });
});
</script>

<template>
  <nav class="app-header" aria-label="Main navigation">
    <div class="app-brand">
      <img class="brand-logo" :src="logo" alt="UPVANTAGE Group">
      <div class="brand-identity"><strong>Accounting Copilot</strong><span>Bank Reconciliation</span></div>
    </div>
    <span v-if="appState.syncing" class="sync-status" role="status">Updating...</span>
    <div class="header-links">
      <component :is="item.disabled ? 'span' : RouterLink" v-for="item in items" :key="item.path" :to="item.disabled ? undefined : item.path" class="header-link" :class="{ disabled: item.disabled }" active-class="active" :role="item.disabled ? 'link' : undefined" :aria-disabled="item.disabled ? 'true' : undefined" :title="item.disabled ? item.reason : undefined" :tabindex="item.disabled ? 0 : undefined">
        <span v-if="item.step" class="header-step" :class="{ complete: item.step.checked }"
          :aria-label="item.step.checked ? 'Complete' : `Step ${item.number}`">
          <svg v-if="item.step.checked" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 8 2.5 2.5L12 5" /></svg>
          <template v-else>{{ item.number }}</template>
        </span>
        <span>{{ item.label }}</span>
      </component>
    </div>
    <RouterLink to="/settings" class="header-settings-icon" active-class="active" aria-label="Settings" title="Settings">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9.5 3-.6 2.2-1.7 1L5 5.6 2.5 10l1.6 1.6v1.8L2.5 15 5 19.4l2.2-.6 1.7 1 .6 2.2h5l.6-2.2 1.7-1 2.2.6 2.5-4.4-1.6-1.6v-1.8L21.5 10 19 5.6l-2.2.6-1.7-1L14.5 3Z"/><circle cx="12" cy="12.5" r="3"/></svg>
    </RouterLink>
  </nav>
</template>

<style scoped>
.app-header { display:flex; align-items:center; gap:20px; height:var(--app-header-height); padding:0 24px; border-bottom:1px solid var(--line); background:white; color:var(--ink); }
.sync-status { font-size:11px; color:var(--muted); white-space:nowrap; }
.app-brand { display:flex; align-items:center; gap:16px; flex-shrink:0; }
.brand-logo { width:148px; height:60px; object-fit:cover; filter:contrast(1.06); }
.brand-identity { display:flex; align-items:center; gap:12px; border-left:1px solid var(--line); padding-left:16px; }
.brand-identity strong { display:block; padding:4px 4px 6px; font-family:'Syne',sans-serif; font-size:17px; font-weight:800; letter-spacing:-.02em; line-height:1.6; white-space:nowrap; background:linear-gradient(90deg,oklch(.52 .18 250),oklch(.55 .18 210)); background-clip:text; -webkit-text-fill-color:transparent; }
.brand-identity span { font-size:11px; font-weight:600; color:var(--muted); white-space:nowrap; }
.header-links { display:flex; align-items:center; align-self:stretch; margin-left:auto; min-width:0; overflow-x:auto; scrollbar-width:thin; scrollbar-color:#bdcddd transparent; }
.header-settings-icon { display:inline-flex; align-items:center; justify-content:center; flex:0 0 36px; width:36px; height:36px; border:1px solid var(--line); border-radius:8px; color:var(--muted); }
.header-settings-icon:hover, .header-settings-icon:focus-visible, .header-settings-icon.active { color:var(--primary); background:var(--blue-light); }
.header-settings-icon:focus-visible { outline:2px solid var(--primary); outline-offset:3px; }
.header-settings-icon svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.header-link { display:inline-flex; flex-shrink:0; align-items:center; gap:7px; height:44px; padding:0 10px; border-bottom:3px solid transparent; color:var(--muted); text-decoration:none; font-size:12px; white-space:nowrap; }
.header-link:hover, .header-link:focus-visible { background:var(--blue-light); color:var(--primary); }
.header-link.active { color:var(--primary); border-bottom-color:var(--primary); font-weight:600; }
.header-link.disabled { color:#748397; opacity:.65; cursor:not-allowed; border-bottom-color:transparent; }
.header-link.disabled:hover { background:transparent; }
.header-step { display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border:1px solid #cbd7e5; border-radius:50%; color:var(--muted); font-size:10px; font-weight:600; }
.header-step.complete { border-color:#cde6d7; background:#edf7f0; color:#28734d; }
.header-link.active .header-step:not(.complete) { color:white; background:var(--primary); border-color:var(--primary); }
.header-step svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
@media (max-width:1100px) {
  .app-header { display:grid; grid-template-columns:minmax(0,1fr) 36px; grid-template-rows:62px 50px; gap:0 12px; padding:0 16px; }
  .app-brand { grid-row:1; grid-column:1; gap:12px; min-width:0; }
  .brand-logo { width:120px; height:50px; }
  .brand-identity { padding-left:12px; align-items:flex-start; flex-direction:column; gap:0; }
  .brand-identity strong { font-size:17px; }
  .header-links { grid-row:2; grid-column:1/-1; width:100%; margin:0; }
  .header-settings-icon { grid-row:1; grid-column:2; }
  .sync-status { display:none; }
}
@media (max-width:450px) { .brand-logo { width:68px; } .app-brand { gap:8px; } .brand-identity { padding-left:8px; } .brand-identity strong { font-size:14px; } }
@media (max-width:380px) { .brand-logo { width:30px; } .brand-identity strong { font-size:13px; } }
</style>
