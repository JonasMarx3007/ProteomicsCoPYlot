import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// The ORA figures are the page's only two plots that a reader compares with each
// other, and the thing they need most is width: a term label is a sentence, not
// a word. These tests hold the page to that -- the two figures stacked rather
// than in two columns, each with its own export control, and a size row wired to
// the request -- because all three are one `className` or one forgotten prop
// away from silently going back to how they were.

const PAGE = new URL('../src/features/stats/OraPanel.tsx', import.meta.url);

async function pageSource() {
  return readFile(PAGE, 'utf8');
}

// The block between the ORA summary and the gene lists, which is where the two
// direction figures live.
function oraFigureBlock(source) {
  const start = source.indexOf('{result.upGenes.length > 0 && result.upTerms.length > 0');
  assert.ok(start > 0, 'the ORA page no longer renders an upregulated figure');
  const end = source.indexOf('<GeneListSection title="Upregulated Genes"', start);
  assert.ok(end > start, 'the ORA page no longer renders the upregulated gene list');
  return source.slice(start, end);
}

test('the two ORA figures are stacked, not placed side by side', async () => {
  const source = await pageSource();
  const block = oraFigureBlock(source);
  const container = source.slice(source.lastIndexOf('<div', source.indexOf(block)), source.indexOf(block));
  assert.doesNotMatch(
    container,
    /grid-cols-2/,
    'the up and down figures are back in two columns; half a window is not wide enough for a GO term'
  );
  assert.match(container, /space-y-/, 'the figures are no longer laid out one above the other');
});

test('each ORA figure carries its own download control', async () => {
  const block = oraFigureBlock(await pageSource());
  const downloads = block.match(/download=\{\{/g) ?? [];
  assert.equal(downloads.length, 2, 'both the up and the down figure must be downloadable');
  assert.match(block, /filename: upPlotFilename/);
  assert.match(block, /filename: downPlotFilename/);
});

test('the ORA figure titles name the first condition and not the second', async () => {
  const block = oraFigureBlock(await pageSource());
  for (const heading of block.match(/title=\{[^}]*\}/g) ?? []) {
    assert.doesNotMatch(
      heading,
      /condition2/,
      `"${heading}" states the comparison from both sides; the direction belongs to condition 1 alone`
    );
  }
  assert.match(block, /Upregulated Terms in \$\{condition1\}/);
  assert.match(block, /Downregulated Terms in \$\{condition1\}/);
});

test('the ORA request carries the size the page asks for', async () => {
  const source = await pageSource();
  const start = source.indexOf('const commonPlotParams = {');
  assert.ok(start > 0, 'the ORA page no longer builds its plot parameters in one place');
  const params = source.slice(start, source.indexOf('};', start));
  for (const key of ['widthCm', 'heightCm', 'dpi']) {
    assert.match(params, new RegExp(`\\b${key}\\b`), `the ORA plot request drops ${key}`);
  }
  assert.match(source, /<SizeRow/, 'the ORA page no longer offers a size row');
});

test('the ORA size is remembered with the rest of the panel', async () => {
  const source = await pageSource();
  const start = source.indexOf('writePersistedUiState("stats.ora.v1"');
  assert.ok(start > 0, 'the ORA page no longer persists its state');
  const persisted = source.slice(start, source.indexOf('});', start));
  for (const key of ['widthCm', 'heightCm', 'dpi', 'downloadFormat']) {
    assert.match(persisted, new RegExp(`\\b${key},`), `${key} is not remembered between visits`);
  }
});
