import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// The plot appearance panel shows a card only where the renderer reads it.
// Which cards a page offers is decided by its `activeAdvancedVisibleControls`
// memo, so these tests lift that memo out of the page source, run it, and check
// what it answers for the plots whose renderers were read. A card that comes
// back -- on a plot that still ignores it -- fails here.

async function sourceOf(path) {
  return readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
}

function parse(path, text) {
  return ts.createSourceFile(path, text, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
}

function findDeclaration(file, name) {
  let found = null;
  const visit = (node) => {
    if (!found && ts.isVariableDeclaration(node) && node.name.getText() === name) found = node;
    if (!found) ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

// The memo body, compiled into a plain function of the page state it reads, so
// the test asks the real decision rather than a copy of it.
async function visibleControlsFunction(path, parameters) {
  const text = await sourceOf(path);
  const declaration = findDeclaration(parse(path, text), 'activeAdvancedVisibleControls');
  assert.ok(declaration, `${path} no longer declares activeAdvancedVisibleControls`);
  const call = declaration.initializer;
  assert.ok(call && ts.isCallExpression(call), `${path} no longer builds the controls with useMemo`);
  const body = call.arguments[0].body.getText();
  assert.match(body, /^\{/, `${path} memo is not a block body any more`);
  const compiled = ts.transpileModule(`function visibleControls(${parameters}) ${body}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(`${compiled}\nreturn visibleControls;`)();
}

// Every object passed as `visibleControls={{...}}` in a page, evaluated.
async function inlineVisibleControls(path) {
  const text = await sourceOf(path);
  const file = parse(path, text);
  const sets = [];
  const visit = (node) => {
    if (
      ts.isJsxAttribute(node) &&
      node.name.getText() === 'visibleControls' &&
      node.initializer &&
      ts.isJsxExpression(node.initializer) &&
      node.initializer.expression &&
      ts.isObjectLiteralExpression(node.initializer.expression)
    ) {
      const literal = node.initializer.expression.getText();
      const compiled = ts.transpileModule(`const value = ${literal};`, {
        compilerOptions: { target: ts.ScriptTarget.ES2022 },
      }).outputText;
      sets.push(new Function('boxplot', `${compiled}\nreturn value;`)(false));
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return sets;
}

test('the shared panel keeps the dot colour behind its own flag', async () => {
  const panel = await sourceOf('components/plots/AdvancedPlotOptions.tsx');
  assert.match(panel, /markerColor\?: boolean;/);
  assert.match(panel, /const showMarkerColor = visibleControls\.markerColor !== false;/);
  // The field is inside the Points card, so it is gated where it is drawn.
  const points = panel.slice(panel.indexOf('{showMarkerStyle ?'), panel.indexOf('{showVolcanoMarkers ?'));
  assert.match(points, /\{showMarkerColor \?[\s\S]*?Dot colour[\s\S]*?\) : null\}/);
});

test('App shows a card only where the renderer behind that plot key reads it', async () => {
  const controls = await visibleControlsFunction('App.tsx', 'activeAdvancedPlotKey, contextModes = {}');
  const at = (key, modes = {}) => controls(key, modes);

  // phospho_coverage_png prints no number on any bar, in either mode.
  assert.notEqual(at('phospho:coverage').valueLabels, true);
  // Its class colours are read, so the card it does have stays.
  assert.equal(at('phospho:coverage').phosphoClassColors, true);

  // peptide_modification_plot draws grouped bars and no text; the missed
  // cleavage plot beside it does write on its bars, and keeps the card.
  assert.notEqual(at('peptide:modification').valueLabels, true);
  assert.equal(at('peptide:missedCleavage').valueLabels, true);

  // phospho_sty_png gives S, T and Y a fixed colour each.
  assert.notEqual(at('phospho:sty').barColor, true);
  // The two bar plots that do read barColor keep it.
  assert.equal(at('phospho:phosphositePlot').barColor, true);
  assert.equal(at('phospho:distribution').barColor, true);

  // Neither phosphoprotein regulation renderer draws a threshold line, and both
  // colour their points through a colour scale.
  assert.notEqual(at('phospho:phosprotRegulation').referenceLineColor, true);
  assert.equal(at('phospho:phosprotRegulation').markerStyle, true);
  assert.equal(at('phospho:phosprotRegulation').markerColor, false);
  // KSEA, which used to share that case, draws both threshold lines.
  assert.equal(at('phospho:ksea').referenceLineColor, true);
  assert.equal(at('phospho:ksea').markerColor, false);

  // Both Pearson renderers draw the fit line (the PNG since 2026-09-25), so
  // the card shows for either type.
  const pearson = (type) => ({ comparison: { kind: 'protein', type } });
  assert.equal(at('comparison:pearson', pearson('Normal')).referenceLineColor, true);
  assert.equal(at('comparison:pearson', pearson('Interactive')).referenceLineColor, true);
  // Its points are drawn without a plot-chosen colour, so the dot colour stays.
  assert.equal(at('comparison:pearson', pearson('Interactive')).markerStyle, true);
  assert.notEqual(at('comparison:pearson', pearson('Interactive')).markerColor, false);

  // The cluster heatmaps label their rows only while "Show feature names" is on,
  // and the Row labels card follows it. This read the context mode as a
  // substring of its JSON before; it is a boolean now.
  assert.equal(at('stats:anova', { 'stats:anova': { showRowLabels: true } }).rowLabels, true);
  assert.equal(at('stats:anova', { 'stats:anova': { showRowLabels: false } }).rowLabels, false);
  assert.equal(at('stats:anova').rowLabels, false);

  // single_protein_lineplot_plot draws a fixed circle marker and labels its x
  // axis from the annotation.
  assert.notEqual(at('singleProtein:lineplot').markerStyle, true);
  assert.equal(at('singleProtein:lineplot').conditionLabels, false);
  // The boxplot on the same page does read both, and keeps them.
  assert.equal(at('singleProtein:boxplot').boxplotPoints, true);
  assert.notEqual(at('singleProtein:boxplot').conditionLabels, false);

  // The two scatter plots whose dot colour does reach their points.
  assert.notEqual(at('data:distribution').markerColor, false);
  assert.notEqual(at('peptide:rtPlot').markerColor, false);
});

test('QC hides the dot colour where the condition palette decides it', async () => {
  const controls = await visibleControlsFunction(
    'features/qc/QCPipelinePage.tsx',
    'activeTab, coverage = {}, hist = {}, box = {}, cv = {}, pca = {}, abundance = {}'
  );
  const pca = controls('pca');
  assert.equal(pca.markerStyle, true);
  assert.equal(pca.markerColor, false);
  const clustered = controls('pca', {}, {}, {}, {}, { colorBy: 'Cluster', clusterMethod: 'kmeans' });
  assert.equal(clustered.markerColor, false);

  const abundance = controls('abundance');
  assert.equal(abundance.markerStyle, true);
  assert.equal(abundance.markerColor, false);

  // The jittered dots over the coverage summary bars take no plot colour, so
  // theirs stays offered.
  const summary = controls('coverage', { summary: true });
  assert.equal(summary.markerStyle, true);
  assert.notEqual(summary.markerColor, false);
});

test('Completeness offers the missing-value plot the bar colour and label size it reads', async () => {
  const controls = await visibleControlsFunction('features/completeness/CompletenessPage.tsx', 'activeTab');
  const missing = controls('missingPlot');
  assert.equal(missing.barColor, true);
  assert.equal(missing.valueLabels, true);
  // The heatmap beside it draws neither.
  const heatmap = controls('heatmap');
  assert.notEqual(heatmap.barColor, true);
  assert.notEqual(heatmap.valueLabels, true);
});

test('the browser-drawn volcano tile offers no font it cannot apply', async () => {
  const sets = await inlineVisibleControls('features/analysis/AnalysisPage.tsx');
  const tile = sets.find((set) => set.volcanoMarkers === true);
  assert.ok(tile, 'the canvas volcano tile no longer declares its own visible controls');
  assert.equal(tile.fontControls, false);

  // The tile is typeset in one face set on the <svg> element and reads no font
  // key, which is why the card is gone.
  const page = await sourceOf('features/analysis/AnalysisPage.tsx');
  assert.match(page, /fontFamily="Arial, sans-serif"/);
  assert.doesNotMatch(page, /(?:title|axisLabel|tick|legend|valueLabel)FontFamily/);

  // The server-rendered canvas plots keep theirs: those figures are drawn by
  // matplotlib, which does read the font.
  const image = sets.find((set) => set.volcanoMarkers !== true);
  assert.ok(image, 'the canvas image plots no longer declare their own visible controls');
  assert.notEqual(image.fontControls, false);
});
