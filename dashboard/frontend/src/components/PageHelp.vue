<script setup>
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue';
import { pageHelp } from '../pageHelp.js';

const props = defineProps({ page: { type: String, required: true } });
const help = computed(() => pageHelp[props.page]);
const button = ref(null), panel = ref(null), open = ref(false), position = ref({});
const id = computed(() => `page-help-${props.page}`);
let timer;

// Clamp the help panel to the viewport, including narrow screens and long help.
async function show() {
  clearTimeout(timer);
  open.value = true;
  await nextTick();
  if (!panel.value || !button.value) return;
  const anchor = button.value.getBoundingClientRect();
  const width = panel.value.offsetWidth;
  position.value = {
    left: `${Math.max(12, Math.min(anchor.left, window.innerWidth - width - 12))}px`,
    top: `${Math.max(12, Math.min(anchor.bottom + 8, window.innerHeight - panel.value.offsetHeight - 12))}px`,
  };
}
// A short delay lets the pointer cross from the circle into the help panel.
function leave() { clearTimeout(timer); timer = setTimeout(close, 180); }
function close() { clearTimeout(timer); open.value = false; }
// Dismiss mouse-opened help even when the button does not have keyboard focus.
function dismiss(event) {
  if (event.key === 'Escape' || (event.type === 'pointerdown' &&
      !button.value?.contains(event.target) && !panel.value?.contains(event.target))) close();
}
onMounted(() => { document.addEventListener('keydown', dismiss); document.addEventListener('pointerdown', dismiss); });
onDeactivated(close);
onBeforeUnmount(() => {
  close(); document.removeEventListener('keydown', dismiss); document.removeEventListener('pointerdown', dismiss);
});
</script>

<template>
  <span class="page-help" @keydown.esc.stop="close">
    <button ref="button" class="page-help-button" type="button" aria-label="How to use this page"
      :aria-describedby="open ? id : undefined" :aria-expanded="open"
      @mouseenter="show" @mouseleave="leave" @focus="show" @blur="leave" @click="show">
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M9.25 8.75a2.75 2.75 0 0 1 5.5 0c0 2-2.75 2.1-2.75 4.25" />
        <circle cx="12" cy="17" r="1" />
      </svg>
    </button>
    <span v-show="open" :id="id" ref="panel" class="page-help-panel" role="tooltip" :style="position"
      @mouseenter="show" @mouseleave="leave">
      <strong>{{ help[0] }}</strong>
      <span v-for="line in help[1]" :key="line">{{ line }}</span>
    </span>
  </span>
</template>

<style scoped>
:global(.page-title) { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
:global(.page-title h1) { margin-bottom: 0; }
.page-help { display: inline-flex; flex: 0 0 auto; font-size: 14px; font-weight: 400; letter-spacing: normal; text-transform: none; }
.page-help-button {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; min-width: 32px; padding: 0;
  border: 1px solid transparent; border-radius: 50%;
  background: #e9eee8; color: #526b5b; cursor: help;
  transition: background-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
}
.page-help-button svg { width: 20px; height: 20px; overflow: visible; }
.page-help-button path { fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.page-help-button circle { fill: currentColor; }
.page-help-button:hover, .page-help-button[aria-expanded="true"] {
  background: #294b3a; color: #fff; box-shadow: 0 2px 7px #294b3a18;
}
.page-help-button:focus-visible { outline: 2px solid #52765f; outline-offset: 4px; }
.page-help-panel { position: fixed; z-index: 10000; display: flex; flex-direction: column; gap: 10px; box-sizing: border-box; width: min(390px, calc(100vw - 24px)); max-height: calc(100dvh - 24px); overflow-y: auto; padding: 18px; border: 1px solid #e1e7df; border-radius: 16px; background: #fff; color: #263c30; box-shadow: 0 12px 36px #18352414, 0 2px 6px #18352408; font: 400 14px/1.5 system-ui, sans-serif; text-align: left; white-space: normal; }
.page-help-panel strong { font-weight: 650; }
@media (prefers-reduced-motion: reduce) { .page-help-button { transition: none; } }
@media print { .page-help { display: none; } }
</style>
