import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// `peptide_rt_interactive_html` takes add_line, header, sampling_seed and the
// figure size. It always draws a scatter and never bins, so Mode and Bins do
// nothing while Type is Interactive -- a control that silently changes nothing
// is worse than no control. These tests read the page's own JSX rather than a
// copy of the rule, so removing the gate fails here.

const PAGE = 'features/peptide/PeptideLevelPage.tsx';

async function sourceOf(path) {
  return readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
}

function parse(path, text) {
  return ts.createSourceFile(path, text, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
}

// Every JSX element in the page, indexed by the literal `label="..."` it carries.
async function fieldsByLabel(path) {
  const text = await sourceOf(path);
  const file = parse(path, text);
  const found = new Map();
  const visit = (node) => {
    if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
      const attributes = new Map();
      for (const attribute of node.attributes.properties) {
        if (!ts.isJsxAttribute(attribute)) continue;
        attributes.set(attribute.name.getText(), attribute.initializer);
      }
      const label = attributes.get('label');
      if (label && ts.isStringLiteral(label)) {
        const list = found.get(label.text) ?? [];
        list.push({ tag: node.tagName.getText(), attributes });
        found.set(label.text, list);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

// The text of a `disabled={...}` attribute, or null when the field has none.
function disabledExpression(field) {
  const value = field.attributes.get('disabled');
  if (!value) return null;
  if (ts.isJsxExpression(value) && value.expression) return value.expression.getText();
  return value.getText();
}

test('the RT plot greys out Mode and Bins while Type is Interactive', async () => {
  const fields = await fieldsByLabel(PAGE);

  for (const label of ['Mode', 'Bins']) {
    const matches = fields.get(label) ?? [];
    assert.equal(matches.length, 1, `expected exactly one ${label} field on the peptide page`);
    assert.equal(
      disabledExpression(matches[0]),
      'rtInteractive',
      `${label} is offered while the interactive renderer ignores it`
    );
  }
});

test('the controls the interactive renderer does read stay enabled', async () => {
  const fields = await fieldsByLabel(PAGE);
  // Type chooses the renderer; Random Seed is the interactive plot's own
  // down-sampling seed; the size row and Add Line reach both renderers.
  for (const label of ['Type', 'Random Seed']) {
    const matches = fields.get(label) ?? [];
    assert.equal(matches.length, 1, `expected exactly one ${label} field`);
    assert.equal(disabledExpression(matches[0]), null, `${label} must stay usable`);
  }
});

test('rtInteractive is exactly "Type is Interactive"', async () => {
  const text = await sourceOf(PAGE);
  assert.match(
    text,
    /const rtInteractive = String\(rt\.type\)\.trim\(\)\.toLowerCase\(\) === "interactive";/,
    'the flag the gate reads is no longer the renderer switch'
  );
  // The same flag picks the endpoint, so the gate and the renderer cannot disagree.
  assert.match(text, /rtInteractive \? "\/api\/plots\/peptide\/rt-interactive\.html"/);
});

test('both fields can actually be disabled', async () => {
  // A `disabled` prop that the component ignores would leave the control live.
  // The dropdown is the shared component now; the number field is still local.
  for (const [component, path] of [['SelectField', 'components/SelectField.tsx'],
                                   ['CommittedNumberField', PAGE]]) {
    const text = await sourceOf(path);
    const start = text.search(new RegExp(`(?:export default )?function ${component}\\(`));
    assert.ok(start > 0, `${component} is no longer declared in ${path}`);
    const body = text.slice(start, text.indexOf('\n}\n', start));
    assert.match(body, /disabled = false,/, `${component} does not accept a disabled prop`);
    assert.match(body, /disabled=\{disabled\}/, `${component} never passes disabled to its input`);
  }
});

test('neither renderer was changed to honour the greyed-out controls', async () => {
  // The gate is a UI change only: Mode and Bins still reach the static plot.
  const text = await sourceOf(PAGE);
  assert.match(text, /method: rt\.method,/);
  assert.match(text, /bins: rt\.bins,/);
});
