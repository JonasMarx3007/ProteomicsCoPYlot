import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// Advanced plot mode shows or hides the appearance panel for the user. It used
// to decide something else as well: with the panel unmounted, its settings were
// not registered as assistant controls, so a styling request first had to turn
// the mode on -- the chat said "Enabled advanced plot options." and the user's
// own switch moved under them (rounds 33-35). The panel is mounted either way
// now, offscreen while the user keeps it closed, and only the user opens it.

async function sourceOf(path) {
  return readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
}

function fakeNode(attributes, parent = null) {
  const node = {
    attributes,
    parentElement: parent,
    hasAttribute: name => name in attributes,
    getAttribute: name => attributes[name] ?? null,
    closest(selector) {
      const [name, value] = selector.replace(/[[\]"]/g, '').split('=');
      for (let current = node; current; current = current.parentElement) {
        if (current.getAttribute(name) === value) return current;
      }
      return null;
    },
  };
  return node;
}

async function hiddenCheck() {
  const text = await sourceOf('lib/assistantControls.ts');
  const code = ts.transpileModule(text.slice(text.indexOf('function assistantHidden'), text.indexOf('function description')),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(`${code}\nreturn assistantHidden;`)();
}

test('the offscreen appearance mount stays readable while ordinary hiding still counts', async () => {
  const assistantHidden = await hiddenCheck();
  const host = (attributes, parent = null) => fakeNode({ 'data-assistant-offscreen': 'true', ...attributes }, parent);
  // The host hides the panel from the user, not from the assistant.
  assert.equal(assistantHidden(fakeNode({}, host({ 'aria-hidden': 'true', inert: '' }))), false);
  // Anything hidden inside the panel is still hidden.
  assert.equal(assistantHidden(fakeNode({ hidden: '' }, host({ 'aria-hidden': 'true' }))), true);
  assert.equal(assistantHidden(fakeNode({}, fakeNode({ 'aria-hidden': 'true' }, host({})))), true);
  // A modal that hides the whole page hides the mount with it.
  assert.equal(assistantHidden(fakeNode({}, host({ 'aria-hidden': 'true' }, fakeNode({ inert: '' })))), true);
  assert.equal(assistantHidden(fakeNode({}, fakeNode({}, fakeNode({ 'aria-hidden': 'true' })))), true);
  assert.equal(assistantHidden(fakeNode({}, fakeNode({}))), false);
});

test('the appearance mount is offscreen and inert rather than unmounted', async () => {
  const fields = await sourceOf('components/AssistantFields.tsx');
  const mount = fields.slice(fields.indexOf('export function AssistantAppearanceMount'), fields.indexOf('export function AssistantInput'));
  assert.match(mount, /if \(visible\) return <>\{children\}<\/>;/);
  assert.match(mount, /data-assistant-offscreen="true"/);
  assert.match(mount, /aria-hidden="true" inert/);
});

test('every advanced panel is mounted whether or not the user opened it', async () => {
  for (const path of ['App.tsx', 'features/qc/QCPipelinePage.tsx', 'features/completeness/CompletenessPage.tsx']) {
    const text = await sourceOf(path);
    const mount = text.indexOf('<AssistantAppearanceMount visible={advancedModeEnabled}>');
    assert.ok(mount > 0, `${path} no longer mounts the appearance panel for the assistant`);
    assert.ok(text.indexOf('<AdvancedPlotOptions', mount) > mount, `${path} does not render the panel inside the mount`);
    assert.doesNotMatch(text, /advancedModeEnabled \? \(\s*<AdvancedPlotOptions/, `${path} unmounts the panel again when advanced mode is off`);
  }
});

test('nothing in the assistant path can turn advanced plot mode on', async () => {
  const run = await sourceOf('lib/runAssistant.ts');
  assert.doesNotMatch(run, /setAdvancedPlotMode/);
  assert.doesNotMatch(await sourceOf('lib/assistantControls.ts'), /advanced_options/);
});
