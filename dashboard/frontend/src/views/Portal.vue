<script setup>
import '../styles/portal.css';
</script>

<template>
  <main class="portal-main tool-directory">
    <div class="portal-heading">
      <h1>Accounting and Finance</h1>
    </div>
    <div class="portal-grid">
      <RouterLink to="/projects" class="portal-card">
        <span class="portal-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h6m-6 5 2 2 4-4"/>
          </svg>
        </span>
        <h2>Bank Statement Reconciliation</h2>
        <p>Reconcile bank statements with supporting documents.</p>
      </RouterLink>
    </div>
  </main>
</template>
