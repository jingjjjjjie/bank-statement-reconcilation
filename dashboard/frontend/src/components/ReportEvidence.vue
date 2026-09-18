<script setup>
import { ref, watch, nextTick } from 'vue';
import { api } from '../api.js';
import { renderOfficePreview } from '../office.js';
const props = defineProps(['kind', 'id', 'title', 'preferred']);
const info = ref(null), page = ref(0), zoom = ref(100), error = ref(''), loading = ref(false), office = ref(null);
let serial = 0;
// Encode only server-resolved evidence IDs; never accept arbitrary source paths.
function url(endpoint, includePage = false) {
  return `/api/matching-${endpoint}?${new URLSearchParams({kind: props.kind, id: props.id, ...(includePage ? {page: page.value} : {})})}`;
}
// Discard responses for a document that is no longer selected.
async function load() {
  const request = ++serial;
  info.value = null; error.value = ''; zoom.value = 100; loading.value = true;
  try {
    const result = await api(url('preview'));
    if (request !== serial) return;
    page.value = Math.max(0, Math.min(props.preferred || 0, result.pages - 1));
    info.value = result;
  } catch (e) { if (request === serial) error.value = e.message; }
  finally { if (request === serial) loading.value = false; }
}
watch(() => [props.kind, props.id], load, {immediate: true});
// Reuse the existing safe Office renderer for spreadsheets and Word originals.
watch([info, page], async () => {
  if (!info.value || !['word', 'spreadsheet'].includes(info.value.kind) || page.value >= info.value.office_pages) return;
  const request = serial, requestedPage = page.value;
  error.value = '';
  await nextTick();
  office.value?.replaceChildren();
  try {
    const data = await api(url('office', true));
    if (request === serial && requestedPage === page.value && office.value) renderOfficePreview(office.value, data);
  } catch (e) { if (request === serial && requestedPage === page.value) error.value = e.message; }
});
</script>

<template>
  <section class="report-evidence" :aria-label="title">
    <header><h3>{{ title }}</h3><a v-if="info" :href="url('file')" download>Download original</a></header>
    <div v-if="info" class="preview-tools">
      <label>Page <select v-model.number="page" :aria-label="`${title} page`"><option v-for="(label, index) in info.labels" :value="index" :key="index">{{ label }}</option></select></label>
      <label>Zoom <select v-model.number="zoom" :aria-label="`${title} zoom`"><option v-for="value in [100, 125, 150, 200]" :key="value" :value="value">{{ value }}%</option></select></label>
    </div>
    <div class="report-preview">
      <p v-if="loading" role="status">Loading original evidence…</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <div v-if="info && !error" :style="{width: `${zoom}%`}">
        <pre v-if="info.kind === 'text'">{{ info.text }}</pre>
        <p v-else-if="info.kind === 'unsupported'">{{ info.message }}</p>
        <div v-else-if="['word', 'spreadsheet'].includes(info.kind) && page < info.office_pages" ref="office"></div>
        <img v-else :key="url('image', true)" :src="url('image', true)" :alt="`${title} — ${info.labels[page]}`" @error="error = 'Preview unavailable. Download the original to inspect it.'">
      </div>
    </div>
  </section>
</template>
