<script setup>
import clockIcon from '../../assets/icons/clock.svg?raw';
import './portal.css';
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
        <h2>Bank Statement<br>Reconciliation</h2>
        <p>Reconcile bank statements with supporting documents.</p>
      </RouterLink>
      <RouterLink to="/statement-extraction" class="portal-card">
        <span class="portal-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5M13 3l5 5M13 3v5h5v4M8 8h2M8 12h5M8 16h2M17 14v7m-3-3 3 3 3-3" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
        <h2>Bank Statement<br>Extraction</h2>
        <p>Extract bank transactions and download Excel or CSV.</p>
      </RouterLink>
    </div>
    <section class="directory-section" aria-labelledby="others-heading">
      <div class="portal-heading"><h2 id="others-heading">Others</h2></div>
      <div class="portal-grid">
        <article class="upcoming-card">
          <span class="portal-icon" aria-hidden="true" v-html="clockIcon"></span>
          <h3>Coming soon</h3>
          <p>More functionalities coming soon.</p>
        </article>
      </div>
    </section>
  </main>
</template>
