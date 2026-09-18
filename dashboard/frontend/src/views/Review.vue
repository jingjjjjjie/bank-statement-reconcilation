<script setup>
import { defineAsyncComponent } from 'vue';
import { appState } from '../api.js';
const ExactReport = defineAsyncComponent(() => import('./ExactReport.vue'));
const ExactReview = defineAsyncComponent(() => import('./ExactReview.vue'));
</script>

<template>
  <component :is="appState.session.mode === 'exact_report' ? ExactReport : ExactReview" />
</template>
