"""Run the actual page lifecycle against delayed settings responses without a browser."""

import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node is required for frontend lifecycle checks')
class PageDraftTests(unittest.TestCase):
    def test_settings_edit_survives_pending_refresh_then_reloads_when_clean(self):
        """A late refresh cannot erase edits, while clean refreshes and saves still apply."""
        script = r"""
const fs = require('node:fs');
const assert = require('node:assert/strict');
const callbacks = {}, pages = new Set(), pending = [], applied = [], errors = [];
let revision = 0, dirty = false, draft = 'saved', page;
const onMounted = fn => callbacks.mount = fn;
const onActivated = fn => callbacks.activate = fn;
const onDeactivated = fn => callbacks.deactivate = fn;
const onBeforeUnmount = fn => callbacks.unmount = fn;
const onBeforeRouteUpdate = () => {};
const watch = () => {};
const useRoute = () => ({query:{}}), useRouter = () => ({push(){}});
const appState = {session:{review_id:'fixture'}, changes:0};
const revisionFor = () => revision;
const toast = error => errors.push(error);
const document = {addEventListener(){}, removeEventListener(){}};
const api = (path, body) => new Promise(resolve => pending.push({path, body, resolve}));
const source = fs.readFileSync(process.argv[1], 'utf8').replace(/^import .*;\r?\n/gm, '').replace('export function usePage', 'function usePage');
const createPage = eval(source + '\nusePage;');
const element = {addEventListener(){}, querySelector(){}, querySelectorAll(){return [];}};
createPage({value:element}, controller => {
  page = controller;
  page.dirty(() => dirty);
  page.onLive(['/api/config']);
  page.onRefresh(async () => {
    const result = await page.api('/api/config');
    draft = result.value;
    dirty = false;
    applied.push(result.value);
  }, ['/api/config']);
});
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); };
(async () => {
  callbacks.mount();
  revision++;
  callbacks.activate();
  assert.equal(pending.length, 1);
  dirty = true; draft = 'unsaved correction';
  pending.shift().resolve({value:'old saved value'});
  await settle();
  assert.equal(draft, 'unsaved correction');
  assert.equal(dirty, true);
  assert.deepEqual(applied, []);
  assert.deepEqual(errors, []);

  dirty = false;
  page.liveUpdate('/api/config');
  assert.equal(pending.length, 1);
  pending.shift().resolve({value:'fresh saved value'});
  await settle();
  assert.equal(draft, 'fresh saved value');
  assert.deepEqual(applied, ['fresh saved value']);

  dirty = true;
  const save = page.api('/api/config', {config:{max_calls:7}});
  pending.shift().resolve({value:'accepted save'});
  assert.deepEqual(await save, {value:'accepted save'});
  callbacks.unmount();
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        source = Path(__file__).resolve().parents[3] / 'src/dashboard/frontend/src/page.js'
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
