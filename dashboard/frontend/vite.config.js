import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Produce local, content-hashed assets served by the Python process.
export default defineConfig({
  plugins: [vue()],
  build: { target: 'es2022' },
  css: { postcss: { plugins: [{
    postcssPlugin: 'scope-review-styles',
    Once(root) {
      // Keep cached evidence screens' styles from changing unrelated pages.
      const name = root.source.input.file.replaceAll('\\', '/').split('/').pop();
      const scope = { 'matching.css': '.matching-app', 'extraction-review.css': '.extraction-workspace',
        'documents.css': '.documents-page' }[name];
      if (!scope) return;
      root.walkRules(rule => {
        if (rule.parent.type === 'atrule' && rule.parent.name.includes('keyframes')) return;
        rule.selectors = rule.selectors.map(selector => selector.includes(scope) ? selector : `${scope} ${selector}`);
      });
    },
  }] } },
});
