import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// Every plot offered as a static/interactive pair follows one rule
// (`src/lib/plotRenderType.ts`):
//   static      -> width, height and DPI, plus the PNG/JPG/WEBP/SVG/PDF export;
//   interactive -> neither; Plotly's camera button and "Open ... Plot" in a new
//                  window, and the static figure's size is not sent to it.
// These tests read the pages' own JSX, so dropping a gate fails here.

const PAIRS = [
  { page: 'features/stats/VolcanoPanel.tsx', name: 'volcano', width: 'widthCm', within: 'VolcanoPanel' },
  { page: 'features/qc/QCPipelinePage.tsx', name: 'QC PCA', width: 'pca.widthCm' },
  { page: 'features/qc/QCPipelinePage.tsx', name: 'QC abundance', width: 'abundance.widthCm' },
  { page: 'features/comparison/ComparisonPipelinePage.tsx', name: 'Pearson', width: 'pearson.widthCm' },
  { page: 'features/peptide/PeptideLevelPage.tsx', name: 'peptide RT', width: 'rt.widthCm' },
];

const STATIC_ONLY = /Interactive|interactive|"Normal"/;

async function parsed(path) {
  const text = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
  return { text, file: ts.createSourceFile(path, text, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX) };
}

function enclosingFunctionName(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isFunctionDeclaration(current)) return current.name?.getText() ?? null;
  }
  return null;
}

function sizeRowsWithWidth(file, width, within) {
  const found = [];
  const visit = (node) => {
    if (within && ts.isJsxSelfClosingElement(node) && enclosingFunctionName(node) !== within) {
      ts.forEachChild(node, visit);
      return;
    }
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText() === 'SizeRow') {
      for (const attribute of node.attributes.properties) {
        if (!ts.isJsxAttribute(attribute) || attribute.name.getText() !== 'widthCm') continue;
        const value = attribute.initializer;
        if (value && ts.isJsxExpression(value) && value.expression?.getText() === width) found.push(node);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

// The condition the element is rendered under: the nearest ternary or `&&`.
function renderCondition(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isConditionalExpression(current)) return current.condition.getText();
    if (ts.isBinaryExpression(current) && current.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      return current.left.getText();
    }
    if (ts.isFunctionLike(current)) break;
  }
  return null;
}

for (const pair of PAIRS) {
  test(`${pair.name}: the size row is shown for the static plot only`, async () => {
    const { file } = await parsed(pair.page);
    const rows = sizeRowsWithWidth(file, pair.width, pair.within);
    assert.equal(rows.length, 1, `expected one size row for ${pair.name}`);
    const condition = renderCondition(rows[0]);
    assert.ok(condition && STATIC_ONLY.test(condition), `${pair.name} size row is not gated on the render type (${condition})`);
  });
}

test('the interactive plots are not sent the static figure size', async () => {
  for (const page of new Set(PAIRS.map((pair) => pair.page).filter((page) => !page.includes('stats/')))) {
    const { text } = await parsed(page);
    assert.match(text, /withoutStaticSize\(/, `${page} sends the static size to its interactive plot`);
  }
  // The volcano adds the size only inside its static branch.
  const { text } = await parsed('features/stats/VolcanoPanel.tsx');
  assert.match(text, /isStatic \? \{ labelTopUp, labelTopDown, widthCm, heightCm, dpi \}/);
});

test('the static volcano has an export control', async () => {
  const { file } = await parsed('features/stats/VolcanoPanel.tsx');
  let ok = false;
  const visit = (node) => {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText() === 'ImageSection') {
      const attrs = node.attributes.properties.filter(ts.isJsxAttribute);
      const title = attrs.find((a) => a.name.getText() === 'title')?.initializer?.getText();
      if (title === '"Volcano Plot"' && attrs.some((a) => a.name.getText() === 'download')) ok = true;
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  assert.ok(ok, 'the static volcano ImageSection has no download prop');
});
