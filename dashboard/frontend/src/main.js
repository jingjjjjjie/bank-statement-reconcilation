import { createApp } from 'vue';
import App from './App.vue';
import { router } from './router.js';
import './styles/style.css';
import './styles/documents.css';
import './styles/extraction-review.css';
import './styles/matching.css';
import './styles/application.css';

// Wait for the initial session and route before mounting controllers.
const app = createApp(App);
app.use(router);
router.isReady().then(() => app.mount('#app')).catch(error => {
  document.querySelector('#app').textContent = `${error.message}. Reload to try again.`;
});
