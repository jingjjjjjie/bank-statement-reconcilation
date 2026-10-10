import { createApp } from 'vue';
import App from './App.vue';
import { router } from './router.js';
import './styles/index.css';

// Wait for the initial session and route before mounting controllers.
const app = createApp(App);
app.use(router);
router.isReady().then(() => app.mount('#app')).catch(error => {
  document.querySelector('#app').textContent = `${error.message}. Reload to try again.`;
});
