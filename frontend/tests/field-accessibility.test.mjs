import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';

const MODULES = ['features/stats/VolcanoPanel', 'features/stats/PathwayHeatmapPanel', 'features/completeness/CompletenessPage',
  'features/data/ColorsPage', 'components/SelectField', 'features/data/IdTranslatorPage',
  'features/data/ImputationPage', 'features/peptide/PeptideLevelPage', 'components/QcFields'];

// A label is announced with its control when it either points at one by id, or
// wraps one. Both are correct; a label that does neither is a caption, and a
// screen reader reads the field beside it as unnamed.
//
// This used to require every listed module to define its own reusable
// `<label ...>{label}</label>` field component, which stopped being true as
// pages moved onto the shared fields in `components/QcFields` and
// `components/PlotFields`. The rule below is the one that was actually meant.
function unlabelledControls(source) {
  const offenders = [];
  const pattern = /<label\b([^>]*)>([\s\S]*?)<\/label>/g;
  for (const match of source.matchAll(pattern)) {
    const [, attributes, body] = match;
    if (/htmlFor=/.test(attributes)) continue;
    if (/<(?:input|select|textarea|Assistant\w+)\b/.test(body)) continue;
    const line = source.slice(0, match.index).split('\n').length;
    offenders.push(`${line}: ${body.trim().slice(0, 40)}`);
  }
  return offenders;
}

for (const module of MODULES) {
  test(`${module} labels name the control they sit with`, async () => {
    const source = await readFile(new URL(`../src/${module}.tsx`, import.meta.url), 'utf8');
    assert.match(source, /<label\b/, `${module} has no labels at all; is it still the right module to check?`);
    assert.deepEqual(unlabelledControls(source), [],
      `${module} has labels that neither reference nor wrap a control`);
  });

  test(`${module} reusable fields link their label by id`, async () => {
    const source = await readFile(new URL(`../src/${module}.tsx`, import.meta.url), 'utf8');
    const labels = [...source.matchAll(/<label\b([^>]*)>\{label\}<\/label>/g)];
    if (labels.length === 0) return; // the page uses the shared fields instead
    for (const label of labels) assert.match(label[1], /htmlFor=\{fieldId\}/);
    assert.match(source, /const fieldId = useId\(\)/);
    assert.match(source, /<(?:select|input|textarea|Assistant(?:Select|Input|Textarea)) id=\{fieldId\}/);
  });
}

test('the rule recognises both correct forms and rejects a bare caption', () => {
  assert.deepEqual(unlabelledControls('<label htmlFor={a}>Name</label>'), []);
  assert.deepEqual(unlabelledControls('<label className="x"><input type="checkbox" />Show</label>'), []);
  assert.deepEqual(unlabelledControls('<label className="x"><AssistantSelect /></label>'), []);
  assert.equal(unlabelledControls('<label className="x">Dataset level</label>').length, 1);
});

test('shared advanced styling and volcano multiline controls stay assistant-aware', async () => {
  const advanced = await readFile(new URL('../src/components/plots/AdvancedPlotOptions.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(advanced, /<(?:input|select|textarea)\b/);
  const volcano = await readFile(new URL('../src/features/stats/VolcanoPanel.tsx', import.meta.url), 'utf8');
  assert.match(volcano, /<AssistantTextarea id=\{fieldId\} data-assistant-permission="view"/);
  const statsDir = new URL('../src/features/stats/', import.meta.url);
  for (const name of await readdir(statsDir)) {
    assert.doesNotMatch(await readFile(new URL(name, statsDir), 'utf8'), /<textarea\b/, name);
  }
});
