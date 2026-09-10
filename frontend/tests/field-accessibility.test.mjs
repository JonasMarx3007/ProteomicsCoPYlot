import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

for (const module of ['features/stats/StatisticalAnalysisPage', 'features/completeness/CompletenessPage',
  'features/data/ColorsPage', 'components/SelectField', 'features/data/IdTranslatorPage',
  'features/data/ImputationPage', 'features/peptide/PeptideLevelPage', 'components/QcFields']) {
  test(`${module} reusable field labels have unique linked controls`, async () => {
    const source = await readFile(new URL(`../src/${module}.tsx`, import.meta.url), 'utf8');
    const labels = [...source.matchAll(/<label\b([^>]*)>\{label\}<\/label>/g)];
    assert.ok(labels.length > 0);
    for (const label of labels) assert.match(label[1], /htmlFor=\{fieldId\}/);
    assert.match(source, /const fieldId = useId\(\)/);
    assert.match(source, /<(?:select|input|textarea) id=\{fieldId\}/);
  });
}
