<script setup>
import { useRoute } from 'vue-router';
import { appState } from '../api.js';
const route = useRoute();
</script>

<template>
  <nav id="workflow-progress" class="workflow-progress" aria-label="Workflow progress">
    <RouterLink v-for="(step, index) in appState.steps" :key="step.name" :to="step.href || '/complete'"
      class="workflow-step" :class="{ done: step.checked, pending: !step.checked, current: step.href === route.path }"
      :aria-current="step.href === route.path ? 'step' : undefined">
      <span class="workflow-step-number">{{ step.checked ? '✓' : index + 1 }}</span><span>{{ step.name }}</span>
    </RouterLink>
  </nav>
</template>
