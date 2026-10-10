<script setup>
import { computed, nextTick, onActivated, onDeactivated, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api, appState, toast } from '../../api.js';
import PageHelp from '../../components/PageHelp.vue';
import Source from './Source.vue';
import './portal.css';

const router = useRouter();
const projects = ref([]), search = ref(''), status = ref('all');
const loading = ref(true), error = ref(''), opening = ref('');
const creating = ref(false), dialog = ref(null), newButton = ref(null);
const visible = computed(() => projects.value.filter(project =>
  (status.value === 'all' || project.status === status.value) &&
  `${project.name} ${project.workspace || ''}`.toLowerCase().includes(search.value.trim().toLowerCase())));

// Refresh saved project metadata whenever this cached screen is opened.
async function load() {
  loading.value = true; error.value = '';
  try { projects.value = (await api('/api/projects')).projects; }
  catch (failure) { error.value = failure.message; }
  finally { loading.value = false; }
}

// Resume directly while retaining the existing activation and unsaved-draft guards.
async function open(project) {
  opening.value = project.id; error.value = '';
  try {
    await api('/api/projects/select', { id: project.id });
    const source = await api('/api/source');
    if (source.active === source.selected?.path) {
      await router.push(appState.resumePath);
    } else {
      const preview = await api('/api/source/preview');
      await api('/api/source/start', { preview: preview.token });
      await router.push('/documents');
    }
  } catch (failure) { error.value = failure.message; }
  finally { opening.value = ''; }
}

// Release this browser's editor lease without changing saved decisions.
async function closeProject() {
  error.value = '';
  try { await api('/api/source/close', {}); await load(); }
  catch (failure) { error.value = failure.message; }
}

// Explain the selected operation before discarding any saved progress or drafts.
async function changeProject(project, action) {
  const reset = action === 'reset';
  const message = reset
    ? `Reset workspace “${project.name}”?\n\nExtraction results, bank transactions and review decisions will be cleared for a fresh run. Previous results and token records will be archived. Original documents and bank statements stay unchanged.`
    : `Delete workspace “${project.name}”?\n\nThis removes it from the app. Its generated results and token records will be archived. Original documents and bank statements stay unchanged. You can add the folder again as a new project.`;
  if (!window.confirm(message + (project.active ? '\n\nUnsaved edits in this workspace will be discarded.' : ''))) return;
  opening.value = project.id; error.value = '';
  try {
    await api(`/api/projects/${action}`, { id: project.id });
    toast(reset ? 'Workspace reset. Resume to start a fresh run.' : 'Workspace deleted. Original files kept.');
    await load();
  } catch (failure) { error.value = failure.message; }
  finally { opening.value = ''; }
}

// Display the server's saved-data timestamp in the user's locale.
function updated(value) {
  return value ? new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : 'Unavailable';
}
// Keep workspace setup in a native modal with keyboard focus and Escape handling.
async function newProject() {
  creating.value = true;
  await nextTick();
  dialog.value.showModal();
}
// Dispose the picker and return focus to its trigger after cancellation.
function closed() {
  creating.value = false;
  newButton.value?.focus();
}
onActivated(load);
onDeactivated(() => { dialog.value?.close(); creating.value = false; });
</script>

<template>
  <main class="portal-main">
    <div class="portal-heading">
      <div class="page-title"><h1>Bank Statement Reconciliation</h1><PageHelp v-if="!creating" page="Projects" /></div>
      <button ref="newButton" type="button" class="button dark" @click="newProject">New project</button>
    </div>
    <div class="project-toolbar">
      <label>Search projects<input v-model="search" type="search" placeholder="Name or folder" /></label>
      <label>Status<select v-model="status" aria-label="Status"><option value="all">All projects</option><option value="ongoing">Ongoing</option><option value="needs_attention">Needs attention</option></select></label>
      <span role="status">{{ loading ? 'Loading projects…' : `${visible.length} projects` }}</span>
      <button type="button" class="button secondary" :disabled="loading || !!opening" @click="load">Refresh</button>
    </div>
    <div v-if="error" class="validation" role="alert">{{ error }}</div>
    <section v-if="visible.length" class="project-list" aria-label="Saved projects" :aria-busy="loading">
      <article v-for="project in visible" :key="project.id" class="project-row">
        <div class="project-identity">
          <div class="project-title"><h2>{{ project.name }}</h2><span v-if="project.active" class="project-active">Active workspace</span><span v-else-if="project.in_use" class="project-active">Project in use</span></div>
          <p class="project-path">{{ project.workspace || 'Project record unavailable' }}</p>
          <p v-if="project.statement" class="project-path">{{ project.statement }}</p>
          <p v-if="project.error" class="project-warning">{{ project.error }}</p>
        </div>
        <div class="project-meta"><span class="project-status" :class="project.status">{{ project.status === 'ongoing' ? 'Ongoing' : 'Needs attention' }}</span><span>{{ project.documents == null ? 'File count unavailable' : `${project.documents} supporting files` }}</span><span>Updated {{ updated(project.updated) }}</span></div>
        <div class="project-actions">
          <button v-if="project.active" type="button" class="button secondary" :disabled="!!opening" @click="closeProject">Close project</button>
          <button type="button" class="button secondary" :aria-label="`Resume ${project.name}`" :disabled="!!opening || !project.workspace || project.in_use" @click="open(project)">{{ project.in_use ? 'Project in use' : opening === project.id ? 'Working…' : 'Resume' }}</button>
          <button type="button" class="button secondary" :aria-label="`Reset workspace ${project.name}`" :disabled="!!opening || !project.workspace || project.in_use" @click="changeProject(project, 'reset')">Reset workspace</button>
          <button type="button" class="button secondary project-delete" :aria-label="`Delete workspace ${project.name}`" :disabled="!!opening || project.in_use" @click="changeProject(project, 'delete')">Delete workspace</button>
        </div>
      </article>
    </section>
    <div v-else-if="!loading && !error" class="portal-empty">
      <h2>{{ projects.length ? 'No matching projects' : 'No projects yet' }}</h2>
      <p>{{ projects.length ? 'Change your search or status filter.' : 'Select New project to choose your workspace folder.' }}</p>
    </div>
    <dialog ref="dialog" class="project-dialog" aria-label="New project" @close="closed">
      <div class="project-dialog-close"><button type="button" class="button secondary" @click="dialog.close()">Close</button></div>
      <Source v-if="creating" new-project />
    </dialog>
  </main>
</template>
