import { test, expect, webkit } from '@playwright/test';
import { verifyAuthStartup, tabRequest } from './authStartup.mjs';
import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';

// Real UI and synthetic log2 data; assistant replies and selected failure cases are mocked.
// Native-picker cancellation is simulated explicitly in its boundary test.
const samples = ['A1', 'A2', 'A3', 'A4', 'B1', 'B2', 'B3', 'B4'];
const metadata = 'sample,condition,pair_id\n' + samples.map(s => `${s},${s[0]},${s[1]}`).join('\n');
const sites = ['UPD_seq,PTM_localization,Protein_group,Gene_group,PTM_Collapse_key,' + samples.join(','),
  ...Array.from({ length: 24 }, (_, i) => [
    `SEQ${i}S`, `S${i}`, `P${Math.floor(i / 2)}`, `G${Math.floor(i / 2)}`, `K${i}`,
    ...samples.map((_, j) => (i < 2 && j === 0) ? '' :
      (12 + i * 0.3 + j * 0.12 + ((i * j) % 3) * 0.07 + (j >= 4 ? 1.2 : 0)).toFixed(4)),
  ].join(','))].join('\n');
const signalingGenes = ['TP53', 'AKT1', 'MTOR', 'EGFR', 'ERBB2', 'MAPK1', 'MAPK3', 'MAPK8', 'STAT3', 'JUN', 'FOS', 'MYC'];
const signalingProteins = ['ProteinNames,GeneNames,' + samples.join(','), ...signalingGenes.map((gene, i) =>
  [`P${i}`, gene, ...samples.map((_, j) => 15 + i * .3 + (j % 4) * .1 + (j >= 4 ? (i < 6 ? -2 : 2) : 0))].join(','))].join('\n');

// Existing form labels are adjacent rather than linked to controls. Scope to
// their immediate container instead of using brittle global control indices.
const field = (page, label, tag = 'select') => page.getByLabel(label, { exact: true }).or(
  page.locator('label:not(:has(input, select, textarea))').filter({ hasText: new RegExp(`^\\s*${label}\\s*$`) }).locator('..').locator(tag));
const tab = (page, name) => page.getByRole('button', { name, exact: true });

test('distribution and imputation diagnostics are display-only while imputed CSV remains available', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Distribution').click();
  const qq = page.getByRole('img', { name: 'QQ norm plot', exact: true });
  await expect(qq).toBeVisible();
  await expect.poll(() => qq.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Export notebook', exact: true })).toHaveCount(0);
  await tab(page, 'Imputation').click();
  for (const name of ['Before: With vs Without Missing Values', 'Overall Distribution with Normal Fit', 'After: Non-Imputed vs Imputed Values']) {
    const plot = page.getByRole('img', { name, exact: true });
    await expect(plot).toBeVisible();
    await expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  }
  await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Export notebook', exact: true })).toHaveCount(0);
  await expect(page.getByRole('option', { name: 'PNG', exact: true })).toHaveCount(0);
  await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
  const csv = page.getByRole('button', { name: 'Download Full Imputed CSV', exact: true });
  await expect(csv).toBeEnabled();
  const ready = page.waitForEvent('download');
  await csv.click();
  expect((await ready).suggestedFilename()).toBe('imputed_phospho.csv');
});

test('completeness plots export their rendered notebook and summary calculations', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Completeness').click();
  for (const [name, filename] of [
    ['Missing Value Plot', 'Missing_Value_Plot.zip'],
    ['Missing Value Heatmap', 'Missing_Value_Heatmap.zip'],
  ]) {
    await tab(page, name).click();
    await expect(page.getByRole('img', { name, exact: true })).toBeVisible();
    const button = page.getByRole('button', { name: 'Export notebook', exact: true });
    await expect(button).toBeEnabled();
    const ready = page.waitForEvent('download');
    await button.click();
    const output = await ready;
    expect(output.suggestedFilename()).toBe(filename);
    const plotZip = await readFile(await output.path());
    expect(plotZip.subarray(0, 2).toString()).toBe('PK');
    await tab(page, 'Tables').click();
    const tableButtons = page.getByRole('button', { name: 'Export notebook', exact: true });
    await expect(tableButtons).toHaveCount(3);
    for (const index of [0, 1, 2]) {
      await expect(tableButtons.nth(index)).toBeEnabled();
      const download = page.waitForEvent('download');
      await tableButtons.nth(index).click();
      expect((await readFile(await (await download).path())).equals(plotZip)).toBe(true);
    }
    await page.getByText('Outlier Threshold (%)', { exact: true }).locator('..').locator('input').fill('0');
    await expect(tableButtons.nth(0)).toBeEnabled();
    await tab(page, 'Refresh').click();
    await expect(tableButtons.nth(0)).toBeEnabled();
  }
  // A plot failure must not take the independently useful tables down with it.
  await page.route('**/api/plots/completeness/*/missing-heatmap.png*', route =>
    route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'No heatmap available' }) }));
  await tab(page, 'Refresh').click();
  const unavailable = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(unavailable).toHaveCount(3);
  for (const index of [0, 1, 2]) await expect(unavailable.nth(index)).toBeDisabled();
  await expect(page.getByRole('link', { name: 'Download CSV', exact: true }).first()).toBeVisible();
});

for (const [plot, title, toggle] of [['boxplot', 'Boxplot', 'Toggle Sample n'], ['lineplot', 'Lineplot', 'Toggle ID'], ['heatmap', 'Heatmap', 'Toggle ID']]) {
test(`single ${plot} and summary export the same notebook snapshot`, async ({ page }, testInfo) => {
  await annotated(page);
  await tab(page, 'Single Protein').click();
  await tab(page, plot === 'heatmap' ? 'Phosphosites on Protein Heatmap' : `Protein ${title}`).click();
  if (plot === 'heatmap') await page.getByLabel('Filter *_M1', { exact: true }).uncheck();
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(2);
  const archives = [];
  for (const index of [0, 1]) {
    await expect(buttons.nth(index)).toBeEnabled();
    const pending = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe(`Single_Protein_${title}.zip`);
    archives.push(await readFile(await download.path()));
  }
  expect(archives[0].equals(archives[1])).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`single-${plot}-notebook.png`), fullPage: true });
  const checkbox = page.getByLabel(toggle, { exact: true });
  await checkbox.setChecked(!(await checkbox.isChecked()));
  await expect(buttons.nth(1)).toBeEnabled();
  const pending = page.waitForEvent('download');
  await buttons.nth(1).click();
  expect((await readFile(await (await pending).path())).equals(archives[0])).toBe(false);
  await page.route(`**/api/plots/single-protein/*/${plot}.png*`, route =>
    route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Unavailable plot' }) }));
  await checkbox.setChecked(!(await checkbox.isChecked()));
  await expect(buttons.nth(0)).toBeDisabled();
  await expect(buttons.nth(1)).toBeDisabled();
  await expect(page.getByRole('link', { name: 'Download CSV', exact: true })).toBeVisible();
});
}

for (const [name, title, endpoint] of [['Counts', 'Phosphosite Plot', 'phosphosite-plot'], ['Coverage', 'Phosphosite Coverage Plot', 'coverage'],
  ['Distribution', 'Phosphosite Distribution', 'distribution'], ['STY', 'STY Plot', 'sty']]) {
test(`phosphosite ${name} and table export the same notebook`, async ({ page }, testInfo) => {
  await annotated(page);
  await tab(page, 'Phospho-specific').click();
  await tab(page, title).click();
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(2);
  const archives = [];
  for (const index of [0, 1]) {
    await expect(buttons.nth(index)).toBeEnabled();
    const ready = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await ready;
    expect(download.suggestedFilename()).toBe(`Phosphosite_${name}.zip`);
    archives.push(await readFile(await download.path()));
  }
  expect(archives[0].equals(archives[1])).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`phosphosite-${name}-notebook.png`), fullPage: true });
  const plot = page.getByRole('img', { name: title, exact: true });
  const previousImage = await plot.getAttribute('src');
  await field(page, 'Width (cm)', 'input').fill('17');
  await field(page, 'Width (cm)', 'input').press('Tab');  // number fields commit on leaving the field
  await expect(plot).not.toHaveAttribute('src', previousImage);
  await expect(buttons.nth(1)).toBeEnabled();
  const ready = page.waitForEvent('download');
  await buttons.nth(1).click();
  expect((await readFile(await (await ready).path())).equals(archives[0])).toBe(false);
  await page.route(`**/api/plots/phospho/${endpoint}.png*`, route =>
    route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Unavailable plot' }) }));
  await field(page, 'Width (cm)', 'input').fill('18');
  await field(page, 'Width (cm)', 'input').press('Tab');  // number fields commit on leaving the field
  await expect(buttons.nth(0)).toBeDisabled();
  await expect(buttons.nth(1)).toBeDisabled();
});
}

test('regulation interactive plot and table export the same notebook', async ({ page }, testInfo) => {
  await annotated(page);
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Phosphoprotein Regulation').click();
  await field(page, 'Condition 1').selectOption('A');
  await field(page, 'Condition 2').selectOption('B');
  await field(page, 'P-value Threshold', 'input').fill('0.9');
  // Number fields commit on blur, and the plot re-renders after a debounce.
  // Blur the last field and wait for the render that carries both thresholds;
  // otherwise the first click commits the value, and the plot's export button
  // still hands out the notebook of the previous render.
  const rerendered = page.waitForResponse(r =>
    r.url().includes('/api/plots/phospho/phosprot-regulation.html')
    && /[?&]log2fcThreshold=0(&|$)/.test(r.url()) && /[?&]pValueThreshold=0\.9(&|$)/.test(r.url()));
  await field(page, 'log2 FC Threshold', 'input').fill('0');
  await page.keyboard.press('Tab');
  await rerendered;
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(2);
  await expect(buttons.nth(0)).toBeEnabled();
  await expect(buttons.nth(1)).toBeEnabled();
  const archives = [];
  for (const index of [0, 1]) {
    const pending = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe('Phosphoprotein_Regulation.zip');
    archives.push(await readFile(await download.path()));
  }
  expect(archives[0].equals(archives[1])).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('regulation-notebook.png'), fullPage: true });
});

for (const variant of ['Pearson static', 'Pearson interactive', 'Venn']) {
test(`comparison ${variant} plot and table export the same notebook`, async ({ page }, testInfo) => {
  await annotated(page);
  await tab(page, 'Comparison').click();
  await tab(page, variant === 'Venn' ? 'Venn Diagram' : 'Pearson Correlation').click();
  await field(page, 'Sample 1').selectOption('A1');
  await field(page, 'Sample 2').selectOption('B1');
  if (variant === 'Pearson interactive') await field(page, 'Type').selectOption('Interactive');
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(2);
  const archives = [];
  for (const index of [0, 1]) {
    await expect(buttons.nth(index)).toBeEnabled();
    const pending = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe(`Comparison_${variant === 'Venn' ? 'Venn' : 'Pearson'}.zip`);
    archives.push(await readFile(await download.path()));
  }
  expect(archives[0].equals(archives[1])).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('comparison-notebook.png'), fullPage: true });
  await field(page, 'Sample 2').selectOption('B2');
  await expect(buttons.nth(1)).toBeEnabled();
  const pending = page.waitForEvent('download');
  await buttons.nth(1).click();
  expect((await readFile(await (await pending).path())).equals(archives[0])).toBe(false);
});
}

test('Venn condition sets can require a minimum number of values', async ({ page }) => {
  // Sites K0 and K1 have no value in A1, so they have 3 of 4 values in A.
  await annotated(page);
  await tab(page, 'Comparison').click();
  await tab(page, 'Venn Diagram').click();
  await expect(page.getByLabel('Minimum values per condition', { exact: true })).toHaveCount(0);
  await field(page, 'Mode').selectOption('Condition');
  await field(page, 'Condition 1').selectOption('A');
  await field(page, 'Condition 2').selectOption('B');
  const minimum = page.getByLabel('Minimum values per condition', { exact: true });
  await expect(minimum).toHaveValue('1');
  const totalA = page.getByRole('row').filter({ hasText: 'Total A' });
  await expect(totalA).toContainText('24');
  const table = page.waitForResponse(r => r.url().includes('/venn-table') && r.url().includes('minPresent=4'));
  await minimum.fill('4');
  await minimum.press('Enter');
  await table;
  await expect(totalA).toContainText('22');
});

test('coverage plot and processed table download the same notebook snapshot', async ({ page }) => {
  await annotated(page);
  await tab(page, 'QC Pipeline').click();
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(2);
  await expect(buttons.nth(0)).toBeEnabled();
  await expect(buttons.nth(1)).toBeEnabled();
  const downloads = [];
  for (const index of [0, 1]) {
    const pending = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe('Coverage_Plot.zip');
    downloads.push(await readFile(await download.path()));
  }
  expect(downloads[0].equals(downloads[1])).toBe(true);
  await page.getByLabel('Summary Type', { exact: true }).check();
  await expect(buttons.nth(1)).toBeEnabled();
  await expect(page.getByRole('columnheader', { name: 'Mean', exact: true })).toBeVisible();
  const pending = page.waitForEvent('download');
  await buttons.nth(1).click();
  const summary = await pending;
  expect(summary.suggestedFilename()).toBe('Coverage_Summary.zip');
  expect((await readFile(await summary.path())).equals(downloads[0])).toBe(false);
  for (const [name, filename, mode] of [
    ['Boxplot Intensity', 'Intensity_Boxplot.zip', 'Mean'],
    ['Boxplot Intensity', 'Intensity_Boxplot.zip', 'Single'],
    ['CV Plot', 'Coefficient_of_Variation.zip', null],
  ]) {
    await tab(page, name).click();
    if (mode) await page.getByLabel('Type', { exact: true }).selectOption(mode);
    await expect(buttons.nth(0)).toBeEnabled();
    await expect(buttons.nth(1)).toBeEnabled();
    const pair = [];
    for (const index of [0, 1]) {
      const ready = page.waitForEvent('download');
      await buttons.nth(index).click();
      const output = await ready;
      expect(output.suggestedFilename()).toBe(filename);
      pair.push(await readFile(await output.path()));
    }
    expect(pair[0].equals(pair[1])).toBe(true);
  }
  for (const [name, filename] of [
    ['Histogram Intensity', 'Intensity_Distribution.zip'],
    ['Abundance Plot', 'Abundance_Plot.zip'],
    ['Correlation Plot', 'Sample_Correlation.zip'],
  ]) {
    await tab(page, name).click();
    await expect(buttons).toHaveCount(1);
    await expect(buttons).toBeEnabled();
    const ready = page.waitForEvent('download');
    await buttons.click();
    const output = await ready;
    expect(output.suggestedFilename()).toBe(filename);
    expect((await readFile(await output.path())).subarray(0, 2).toString()).toBe('PK');
  }
  await tab(page, 'Abundance Plot').click();
  await page.route('**/api/plots/qc/*/abundance-interactive.html*', async route => {
    const response = await route.fetch();
    const body = await response.text();
    expect(body).toContain("window.dispatchEvent(new Event('copylot-plot-ready'));");
    await route.fulfill({ response, body: body.replaceAll(
      "window.dispatchEvent(new Event('copylot-plot-ready'));", '') });
  });
  await page.getByLabel('Type', { exact: true }).selectOption('Interactive');
  await expect(page.getByRole('link', { name: 'Open Interactive Plot', exact: true })).toBeVisible();
  const frame = page.frameLocator('iframe[title="Abundance Plot interactive plot"]');
  await expect(frame.locator('.main-svg').first()).toBeVisible();
  await expect(buttons).toBeDisabled();
  await page.evaluate(() => window.postMessage({ type: 'copylot-plot-ready', nonce: 'foreign-frame' }, '*'));
  await expect(buttons).toBeDisabled();
  await frame.locator('body').evaluate(() => window.dispatchEvent(new Event('copylot-plot-ready')));
  await expect(buttons).toBeEnabled();
  await page.unroute('**/api/plots/qc/*/abundance-interactive.html*');
  const interactiveReady = page.waitForEvent('download');
  await buttons.click();
  expect((await interactiveReady).suggestedFilename()).toBe('Interactive_Abundance.zip');
  await page.getByLabel('Condition', { exact: true }).selectOption('B');
  await expect(buttons).toBeEnabled();
  await expect.poll(() => frame.locator('.js-plotly-plot').evaluate(plot => plot.data.length)).toBe(1);
  await tab(page, 'Principal Component Analysis').click();
  for (const dimensions of ['2D', '3D']) {
    await page.getByLabel('Dimensions', { exact: true }).selectOption(dimensions);
    await expect(buttons).toHaveCount(1);
    await expect(buttons).toBeEnabled();
    const ready = page.waitForEvent('download');
    await buttons.click();
    expect((await ready).suggestedFilename()).toBe(`PCA_${dimensions}.zip`);
  }
  await page.getByLabel('Type', { exact: true }).selectOption('Interactive');
  for (const dimensions of ['2D', '3D']) {
    await page.getByLabel('Dimensions', { exact: true }).selectOption(dimensions);
    await expect(buttons).toBeEnabled();
    const pcaFrame = page.frameLocator('iframe[title="PCA Plot interactive plot"]');
    await expect.poll(() => pcaFrame.locator('.js-plotly-plot').evaluate(plot => plot.data[0].type))
      .toBe(dimensions === '3D' ? 'scatter3d' : 'scatter');
    const ready = page.waitForEvent('download');
    await buttons.click();
    expect((await ready).suggestedFilename()).toBe(`Interactive_PCA_${dimensions}.zip`);
  }
});

test('UMAP and t-SNE export the displayed static and interactive embeddings', async ({ page }) => {
  test.setTimeout(180_000);
  await annotated(page);
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Principal Component Analysis').click();
  const button = page.getByRole('button', { name: 'Export notebook', exact: true });
  for (const method of ['UMAP', 't-SNE']) {
    await page.getByLabel('Method', { exact: true }).selectOption(method);
    for (const type of ['Normal', 'Interactive']) {
      await page.getByLabel('Type', { exact: true }).selectOption(type);
      await expect(button).toBeEnabled({ timeout: 60_000 });
      if (type === 'Interactive') {
        const frame = page.frameLocator(`iframe[title="${method} Plot interactive plot"]`);
        await expect.poll(() => frame.locator('.js-plotly-plot').evaluate(plot => plot.layout.xaxis.title.text))
          .toBe(`${method}1`);
      }
      const pending = page.waitForEvent('download');
      await button.click();
      expect((await pending).suggestedFilename()).toBe(`${type === 'Interactive' ? 'Interactive_' : ''}${method}_2D.zip`);
    }
  }
});

for (const interactive of [false, true]) {
  test(`${interactive ? 'interactive' : 'static'} plot recovers from busy responses before enabling notebook export`, async ({ page }) => {
    await annotated(page);
    await tab(page, 'QC Pipeline').click();
    await tab(page, 'Principal Component Analysis').click();
    const button = page.getByRole('button', { name: 'Export notebook', exact: true });
    await expect(button).toBeEnabled();
    let calls = 0;
    const pattern = interactive ? '**/api/plots/qc/*/pca-interactive.html*' : '**/api/plots/qc/*/pca.png*';
    await page.route(pattern, async route => {
      if (++calls <= 2) {
        await route.fulfill({ status: 503, contentType: 'application/json', headers: { 'Retry-After': '1' },
          body: JSON.stringify({ detail: 'Temporary test workload is busy' }) });
      } else await route.continue();
    });
    if (interactive) await page.getByLabel('Type', { exact: true }).selectOption('Interactive');
    else {
      await page.getByLabel('Width (cm)', { exact: true }).fill('21');
      await page.getByLabel('Width (cm)', { exact: true }).press('Tab');
    }
    await expect.poll(() => calls).toBeGreaterThan(0);
    await expect(button).toBeDisabled();
    await expect(button).toBeEnabled();
    expect(calls).toBeGreaterThanOrEqual(3);
    await expect(page.getByText('Temporary test workload is busy', { exact: true })).toHaveCount(0);
    const pending = page.waitForEvent('download');
    await button.click();
    expect((await pending).suggestedFilename()).toBe(`${interactive ? 'Interactive_' : ''}PCA_2D.zip`);
  });
}

test('collapsed phosphoprotein QC plots and tables offer matching notebook exports', async ({ page }) => {
  test.setTimeout(120_000);
  await annotated(page);
  const response = await tabRequest(page).post('/api/annotations/phosprot/aggregate', {
    data: { mode: 'robust_site_median', source: 'non_imputed' },
  });
  expect(response.ok()).toBeTruthy();
  // Refresh available levels after the out-of-band aggregation request.
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Principal Component Analysis').click();
  await field(page, 'Dataset level').selectOption('phosprot');
  const button = page.getByRole('button', { name: 'Export notebook', exact: true });
  for (const type of ['Normal', 'Interactive']) {
    await page.getByLabel('Type', { exact: true }).selectOption(type);
    await expect(button).toBeEnabled();
    const pending = page.waitForEvent('download');
    await button.click();
    expect((await pending).suggestedFilename()).toBe(`${type === 'Interactive' ? 'Interactive_' : ''}PCA_2D.zip`);
  }
  for (const [module, filename, paired] of [
    ['Coverage Plot', 'Coverage_Plot.zip', true],
    ['Boxplot Intensity', 'Intensity_Boxplot.zip', true],
    ['CV Plot', 'Coefficient_of_Variation.zip', true],
    ['Histogram Intensity', 'Intensity_Distribution.zip', false],
    ['Abundance Plot', 'Abundance_Plot.zip', false],
    ['Correlation Plot', 'Sample_Correlation.zip', false],
  ]) {
    await tab(page, module).click();
    await expect(button).toHaveCount(paired ? 2 : 1);
    const archives = [];
    for (let index = 0; index < (paired ? 2 : 1); index++) {
      await expect(button.nth(index)).toBeEnabled();
      const pending = page.waitForEvent('download');
      await button.nth(index).click();
      const download = await pending;
      expect(download.suggestedFilename()).toBe(filename);
      archives.push(await readFile(await download.path()));
    }
    if (paired) expect(archives[0].equals(archives[1])).toBe(true);
  }
  await tab(page, 'Abundance Plot').click();
  await page.getByLabel('Type', { exact: true }).selectOption('Interactive');
  await expect(button).toBeEnabled();
  const pending = page.waitForEvent('download');
  await button.click();
  expect((await pending).suggestedFilename()).toBe('Interactive_Abundance.zip');
});

test('static volcano plot and result table download the same reproducible notebook', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  await tab(page, 'Volcano Plot').click();
  await field(page, 'Condition 2').selectOption('B');
  await field(page, 'Type').selectOption('Normal');
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(2);
  await expect(buttons.nth(0)).toBeEnabled();
  await expect(buttons.nth(1)).toBeEnabled();
  const archives = [];
  for (const index of [0, 1]) {
    const pending = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe('Volcano_Plot.zip');
    archives.push(await readFile(await download.path()));
  }
  expect(archives[0].equals(archives[1])).toBe(true);
  const labels = page.getByLabel('Label top up-regulated', { exact: true });
  await labels.fill('2');
  await labels.press('Enter');
  await expect(buttons.nth(1)).toBeEnabled();
  const pending = page.waitForEvent('download');
  await buttons.nth(1).click();
  expect((await readFile(await (await pending).path())).equals(archives[0])).toBe(false);
  await page.route('**/api/plots/stats/*/volcano.html*', async route => {
    const response = await route.fetch();
    const html = await response.text();
    expect(html).toContain("window.dispatchEvent(new Event('copylot-plot-ready'));");
    await route.fulfill({ response, body: html.replaceAll("window.dispatchEvent(new Event('copylot-plot-ready'));", '') });
  });
  await field(page, 'Type').selectOption('Interactive');
  await expect(buttons).toHaveCount(2);
  await expect(page.getByRole('link', { name: 'Open Plot', exact: true })).toBeVisible();
  const frame = page.frameLocator('iframe[title="Volcano Plot"]');
  await expect(frame.locator('.main-svg').first()).toBeVisible();
  await expect(buttons.nth(0)).toBeDisabled();
  await expect(buttons.nth(1)).toBeDisabled();
  await page.evaluate(() => window.postMessage({ type: 'copylot-plot-ready', nonce: 'wrong-frame' }, '*'));
  await expect(buttons.nth(0)).toBeDisabled();
  await frame.locator('body').evaluate(() => window.dispatchEvent(new Event('copylot-plot-ready')));
  await expect(buttons.nth(0)).toBeEnabled();
  await expect(buttons.nth(1)).toBeEnabled();
  const interactive = [];
  for (const index of [0, 1]) {
    const ready = page.waitForEvent('download');
    await buttons.nth(index).click();
    const download = await ready;
    expect(download.suggestedFilename()).toBe('Interactive_Volcano_Plot.zip');
    interactive.push(await readFile(await download.path()));
  }
  expect(interactive[0].equals(interactive[1])).toBe(true);
});

test('ANOVA plots and their result tables share frozen notebooks', async ({ page }) => {
  test.setTimeout(180_000);
  const threeGroups = 'sample,condition\n' + samples.map((s, i) => `${s},${i < 3 ? 'A' : i < 6 ? 'B' : 'C'}`).join('\n');
  await annotated(page, '2', { meta: threeGroups, expectedRows: 24 });
  await tab(page, 'Statistical Analysis').click();
  await tab(page, 'ANOVA').click();
  await field(page, 'P-value threshold', 'input').fill('1');
  await field(page, 'P-value threshold', 'input').press('Enter');
  await field(page, 'Post-hoc test').selectOption('tukey');
  const buttons = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(buttons).toHaveCount(3);
  async function download(button) {
    await expect(button).toBeEnabled({ timeout: 30_000 });
    const pending = page.waitForEvent('download');
    await button.click();
    const result = await pending;
    return readFile(await result.path());
  }
  const main = await download(buttons.nth(0));
  expect((await download(buttons.nth(1))).equals(main)).toBe(true);
  expect((await download(buttons.nth(2))).equals(main)).toBe(true);
  await field(page, 'Condition 2').selectOption('C');
  const changed = await download(buttons.nth(2));
  expect(changed.equals(main)).toBe(false);
  expect((await download(buttons.nth(0))).equals(changed)).toBe(true);
  await field(page, 'Source').selectOption('anova_cluster');
  await expect(buttons).toHaveCount(3);
  await expect(buttons.nth(1)).toBeEnabled({ timeout: 30_000 });
  await field(page, 'Cluster').selectOption('1');
  await expect(buttons).toHaveCount(5);
  const cluster = await download(buttons.nth(3));
  expect((await download(buttons.nth(4))).equals(cluster)).toBe(true);
  expect((await download(buttons.nth(0))).equals(cluster)).toBe(false);
  await field(page, 'P-value threshold', 'input').fill('0.000000000001');
  await field(page, 'P-value threshold', 'input').press('Enter');
  await expect(page.getByText('No rows passed the selected ANOVA threshold, so no significant-row heatmap or clusters were generated.', { exact: true })).toBeVisible();
  await expect(buttons).toHaveCount(1);
  const noHits = await download(buttons);
  expect(noHits.subarray(0, 2).toString()).toBe('PK');
  await expect(page.getByRole('img', { name: /ANOVA.*Heatmap/ })).toHaveCount(0);
});

test('ORA plot tables and gene lists share reproducible notebook downloads', async ({ page }) => {
  test.setTimeout(180_000);
  await annotated(page, '3', { kind: 'protein', table: signalingProteins });
  await tab(page, 'Statistical Analysis').click();
  await tab(page, 'GO Enrichment (ORA)').click();
  await field(page, 'Condition 2').selectOption('B');
  for (const [label, value] of [['Min term size', '1'], ['Adj p-value cutoff', '1'], ['Top terms', '3']]) {
    await field(page, label, 'input').fill(value);
    await field(page, label, 'input').press('Enter');
  }
  const button = title => page.locator('section').filter({ has: page.getByRole('heading', { name: title, exact: true }) })
    .getByRole('button', { name: 'Export notebook', exact: true });
  async function download(title) {
    const control = button(title);
    await expect(control).toBeEnabled({ timeout: 30_000 });
    const pending = page.waitForEvent('download');
    await control.click();
    return readFile(await (await pending).path());
  }
  for (const direction of ['Upregulated', 'Downregulated']) {
    const plot = await download(`${direction} Terms in A`);
    expect((await download(`${direction} Terms`)).equals(plot)).toBe(true);
    expect((await download(`${direction} Genes`)).equals(plot)).toBe(true);
    if (direction === 'Upregulated') expect((await download('Tested-gene Background')).equals(plot)).toBe(true);
  }
  await field(page, 'Adj p-value cutoff', 'input').fill('0.000000000001');
  await field(page, 'Adj p-value cutoff', 'input').press('Enter');
  await expect(page.getByRole('img', { name: /regulated Terms in A/ })).toHaveCount(0);
  const noTerms = await download('Upregulated Genes');
  expect((await download('Upregulated Terms')).equals(noTerms)).toBe(true);
});

for (const organism of ['human', 'mouse']) {
test(`pathway notebook follows the rendered ${organism} heatmap and disables on plot failure`, async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const table = organism === 'human' ? signalingProteins : signalingProteins.replace(
    /TP53|AKT1|MTOR|EGFR|ERBB2|MAPK1|MAPK3|MAPK8|STAT3|JUN|FOS|MYC/g,
    gene => gene === 'TP53' ? 'Trp53' : gene[0] + gene.slice(1).toLowerCase());
  await annotated(page, '3', { kind: 'protein', table });
  await tab(page, 'Statistical Analysis').click();
  await tab(page, 'Pathway Heatmap').click();
  await field(page, 'Organism').selectOption(organism);
  await field(page, 'Pathway').selectOption('positive regulation of apoptotic process');
  const button = page.getByRole('button', { name: 'Export notebook', exact: true });
  const plot = page.getByRole('img', { name: 'Pathway Heatmap', exact: true });
  await expect(button).toBeEnabled({ timeout: 30_000 });
  async function download() {
    await expect(button).toBeEnabled({ timeout: 30_000 });
    const pending = page.waitForEvent('download');
    await button.click();
    const output = await pending;
    expect(output.suggestedFilename()).toBe('Pathway_Heatmap.zip');
    return readFile(await output.path());
  }
  const original = await download();
  await page.getByLabel('Show collapsed row count (n)', { exact: true }).check();
  await page.getByLabel('Cluster rows', { exact: true }).check();
  await page.getByLabel('Cluster columns', { exact: true }).check();
  const changed = await download();
  expect(changed.equals(original)).toBe(false);
  await expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('pathway-notebook.png'), fullPage: true });
  const pattern = '**/api/plots/stats/*/pathway-heatmap.png*';
  await page.route(pattern, route => route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Test pathway unavailable' }) }));
  await page.getByLabel('Cluster rows', { exact: true }).uncheck();
  await expect(page.getByText('Test pathway unavailable', { exact: true })).toBeVisible();
  await expect(button).toBeDisabled();
  await page.unroute(pattern);
  await page.getByLabel('Cluster rows', { exact: true }).check();
  await expect(button).toBeEnabled({ timeout: 30_000 });
});
}

test('committed number fields show the accepted rounded or clamped value', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  await tab(page, 'Volcano Plot').click();
  await field(page, 'Condition 2').selectOption('B');
  await field(page, 'Type').selectOption('Normal');
  const labels = page.getByLabel('Label top up-regulated', { exact: true });
  const download = page.getByRole('link', { name: 'Download Plot', exact: true });
  await expect(labels).toHaveValue('0');
  for (const [draft, accepted, key] of [
    ['0.4', '0', 'Enter'], ['1.6', '2', 'Tab'], ['2.4', '2', 'Enter'],
    ['-3', '0', 'Tab'], ['-1', '0', 'Enter'], ['1,0', '1', 'Tab'],
    ['invalid', '1', 'Enter'],
  ]) {
    await labels.fill(draft);
    await expect(labels).toHaveValue(draft.replace(',', '.'));
    await labels.press(key);
    await expect(labels).toHaveValue(accepted);
    await expect(download).toHaveAttribute('href', new RegExp(`labelTopUp=${accepted}(?:&|$)`));
  }
  const threshold = page.getByLabel('P-value threshold', { exact: true });
  await threshold.fill('0.01');
  await threshold.press('Enter');
  await expect(threshold).toHaveValue('0.01');
  await expect(download).toHaveAttribute('href', /pValueThreshold=0\.01(?:&|$)/);
});

for (const heatmap of [false, true]) {
  test(`${heatmap ? 'heatmap' : 'standard plot'} safely renders structured errors and recovers`, async ({ page }) => {
    await annotated(page);
    const crashes = [];
    page.on('pageerror', error => crashes.push(error.message));
    if (heatmap) {
      await tab(page, 'Statistical Analysis').click();
      await tab(page, 'ANOVA').click();
    } else {
      await tab(page, 'Single Protein').click();
    }
    const image = page.getByRole('img', { name: heatmap ? 'ANOVA Heatmap' : 'Protein Boxplot', exact: true });
    await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    const pattern = heatmap ? '**/api/plots/stats/*/anova.png*' : '**/api/plots/single-protein/*/boxplot.png*';
    const control = heatmap ? field(page, 'P-value threshold', 'input') : page.getByLabel('Width (cm)', { exact: true });
    const fallback = 'Failed to load the plot image. Check the selected data and plot options.';
    const cases = [
      [JSON.stringify({ detail: 'No matching features' }), 'No matching features'],
      [JSON.stringify({ detail: [{ msg: 'Select a condition', input: 'private-input' }, { msg: 'Invalid width' }] }), 'Select a condition; Invalid width'],
      [JSON.stringify({ detail: { msg: 'Invalid selection' } }), 'Invalid selection'],
      [JSON.stringify({ detail: { unexpected: 'private-input' } }), fallback],
      ['<html>Proxy failure</html>', fallback],
      [JSON.stringify({ detail: '<img src=x onerror="window.errorInjected=true">' }), '<img src=x onerror="window.errorInjected=true">'],
    ];
    let body = '';
    const requests = [];
    await page.route(pattern, route => {
      requests.push(route.request());
      return route.fulfill({ status: 422, contentType: 'application/json', body });
    });
    for (let i = 0; i < cases.length; i++) {
      const [responseBody, message] = cases[i];
      body = responseBody;
      await control.fill(String(heatmap ? .02 + i * .001 : 21 + i));
      await control.press('Tab');
      await expect(page.getByText(message, { exact: true })).toBeVisible();
      await expect(image).toHaveCount(0);
      await expect(page.getByText('private-input', { exact: true })).toHaveCount(0);
    }
    // StrictMode starts and aborts a first effect in development; no completed
    // error response should trigger another request for the same plot.
    const completed = requests.filter(request => !request.failure()).map(request => request.url());
    expect(new Set(completed).size).toBe(completed.length);
    expect(await page.evaluate(() => Boolean(window.errorInjected))).toBe(false);
    await page.unroute(pattern);
    await control.fill(heatmap ? '0.05' : '20');
    await control.press('Tab');
    await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    expect(crashes).toEqual([]);
  });
}

test('plot loader ignores stale responses and malformed notice encoding', async ({ page }) => {
  await page.addInitScript(() => {
    const revoke = URL.revokeObjectURL.bind(URL);
    window.revokedPlotUrls = [];
    URL.revokeObjectURL = url => { window.revokedPlotUrls.push(url); revoke(url); };
  });
  await annotated(page);
  await tab(page, 'Single Protein').click();
  const image = page.getByRole('img', { name: 'Protein Boxplot', exact: true });
  await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  const oldBlob = await image.getAttribute('src');
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route('**/api/plots/single-protein/*/boxplot.png*', async route => {
    const width = new URL(route.request().url()).searchParams.get('widthCm');
    if (width === '21') await delayed;
    await route.fulfill({ status: 200, contentType: 'image/svg+xml',
      headers: { 'X-CoPYlot-Notice': width === '21' ? 'obsolete' : '100% complete' },
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="green"/></svg>' });
  });
  const width = page.getByLabel('Width (cm)', { exact: true });
  const started = page.waitForRequest(request => request.url().includes('/boxplot.png') && new URL(request.url()).searchParams.get('widthCm') === '21');
  await width.fill('21');
  await width.press('Tab');
  await started;
  await width.fill('22');
  await width.press('Tab');
  await expect(page.getByText('100% complete', { exact: true })).toBeVisible();
  release();
  await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.getByText('obsolete', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(url => window.revokedPlotUrls.includes(url), oldBlob)).toBe(true);
  const currentBlob = await image.getAttribute('src');
  await tab(page, 'QC Pipeline').click();
  await expect.poll(() => page.evaluate(url => window.revokedPlotUrls.includes(url), currentBlob)).toBe(true);
});

test('heatmap notice follows the rendered result and disappears on replacement failure', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  const responsePromise = page.waitForResponse(response => response.url().includes('/anova.png') && response.ok());
  await tab(page, 'ANOVA').click();
  const response = await responsePromise;
  const notice = decodeURIComponent(response.headers()['x-copylot-notice']);
  expect(notice).toMatch(/^Heatmap-usable features: \d/);
  await expect(page.getByText(notice, { exact: true })).toBeVisible();
  const image = page.locator('img[alt*="ANOVA"]').first();
  await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.route('**/api/plots/stats/*/anova.png*', route => route.fulfill({
    status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic heatmap refusal' }),
  }));
  await field(page, 'P-value threshold', 'input').fill('0.01');
  await field(page, 'P-value threshold', 'input').press('Tab');
  await expect(page.getByText('Synthetic heatmap refusal', { exact: true })).toBeVisible();
  await expect(page.getByText(notice, { exact: true })).toHaveCount(0);
  await expect(page.locator('img[alt*="ANOVA"]')).toHaveCount(0);
});

test('scientific assistant navigates, selects an entity and applies cumulative plot styling', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; provider answers are synthetic.');
  await annotated(page);
  let calls = 0;
  let selectedProtein;
  let releaseStaleReply;
  await page.route('**/api/chat/assistant', async route => {
    const { view } = route.request().postDataJSON();
    const action = (label, value, type) => {
      const control = view.controls.find(c => c.label.includes(label) && (!type || c.type === type));
      expect(control, `Available controls: ${view.controls.map(c => c.label).join('; ')}`).toBeTruthy();
      return { type: 'set_control', target: control.id, value };
    };
    let actions = [];
    if (calls === 0) actions = [{ type: 'navigate', target: 'singleProtein.boxplot', value: '' }];
    if (calls === 1) {
      const control = view.controls.find(c => c.label === 'Protein / Site');
      expect(control).toBeTruthy();
      selectedProtein = control.options.find(value => value && value !== control.value);
      expect(selectedProtein).toBeTruthy();
      actions = [action('Protein / Site', selectedProtein)];
    }
    // No advanced-options step: the appearance settings are advertised while the
    // user keeps the panel closed, and only the user may open it.
    if (calls === 2) actions = [action('Top', false, 'checkbox'), action('X tick label rotation', '45', 'number')];
    if (calls === 3) actions = [action('Condition colors / A', '#ff0000', 'color'), action('Condition names / A', 'Control', 'text')];
    if (calls === 5) {
      const memory = route.request().postDataJSON().conversationState;
      expect(memory.status).toBe('completed');
      expect(memory.selections).toContainEqual({ label: 'Protein / Site', value: selectedProtein });
      expect(memory.completed.length).toBeGreaterThan(0);
      await new Promise(resolve => { releaseStaleReply = resolve; });
    }
    calls++;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ model: 'synthetic', answer: actions.length ? '' : 'View updated.', actions, evidence: [], revision: 1 }) });
  });
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await page.getByPlaceholder('Ask about this analysis...').fill('Open the protein boxplot, select a protein, remove the top border, rotate labels, change the condition color and rename condition A.');
  await tab(page, 'Send').click();
  await tab(page, 'Confirm and send').click();
  await expect(page.getByText(/View updated\./)).toBeVisible({ timeout: 45000 });
  expect(calls).toBe(5);
  // The advanced panel stayed closed for the user throughout the styling: its
  // settings were reachable only through the offscreen assistant mount.
  await expect(page.locator('[data-assistant-offscreen="true"] [data-assistant-appearance="true"]')).toHaveCount(1);
  expect(await page.evaluate(() => window.sessionStorage.getItem('copylot:advancedPlotMode'))).not.toBe('1');
  await expect(page.getByRole('combobox', { name: 'Protein / Site', exact: true })).toHaveValue(selectedProtein);
  const settings = JSON.parse(new URL(await page.getByRole('link', { name: 'Download Plot', exact: true }).getAttribute('href'), page.url()).searchParams.get('advanced'));
  expect(settings).toMatchObject({ axisLineTop: false, xTickLabelRotation: 45, conditionColors: { A: '#ff0000' }, conditionLabels: { A: 'Control' } });
  const plot = page.locator('main img').first();
  await expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect.poll(() => plot.evaluate(img => img.getBoundingClientRect().top)).toBeLessThan(150);
  await page.getByPlaceholder('Ask about this analysis...').fill('Explain the current plot.');
  await tab(page, 'Send').click();
  await expect.poll(() => typeof releaseStaleReply).toBe('function');
  await tab(page, 'Protein Lineplot').click();
  releaseStaleReply();
  // The reason is written into the conversation itself (2026-10-07), after any completed changes.
  await expect(page.getByText(/(?:No changes applied\.|I stopped here:) The view or analysis changed while I was working\. Please retry\./)).toBeVisible();
});

test('a local OpenAI-compatible server lists its models through the app and needs no cloud consent', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode.');
  // A stand-in for llama.cpp's server: OpenAI-compatible /v1, no Ollama /api.
  const { createServer } = await import('node:http');
  const standIn = createServer((request, response) => {
    const send = (status, body) => { response.writeHead(status, { 'Content-Type': 'application/json' }); response.end(JSON.stringify(body)); };
    if (request.url === '/v1/models') send(200, { object: 'list', data: [{ id: 'glm5', object: 'model', owned_by: 'llamacpp' }] });
    else send(404, { error: { code: 404, message: 'File Not Found' } });
  });
  await new Promise(resolve => standIn.listen(0, '127.0.0.1', resolve));
  const address = `http://127.0.0.1:${standIn.address().port}/v1`;
  try {
    await annotated(page);
    let sent;
    await page.route('**/api/chat/assistant', async route => {
      sent = route.request().postDataJSON();
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ model: 'glm5', answer: 'Answered locally.', actions: [], evidence: [], revision: 1 }) });
    });
    await tab(page, 'Open chatbot sidebar').click();
    await tab(page, 'Toggle AI settings').click();
    await page.getByLabel('Select chatbot provider').selectOption('openai_compatible');
    await page.getByLabel('Local AI server address').fill(address);
    await page.getByLabel('Local AI server address').press('Enter');
    await expect(page.getByLabel('Select chatbot model')).toHaveValue('glm5');
    await page.getByPlaceholder('Ask about this analysis...').fill('Explain the current plot.');
    await tab(page, 'Send').click();
    await expect(page.getByText('Answered locally.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Confirm and send' })).toHaveCount(0);
    expect(sent).toMatchObject({ provider: 'openai_compatible', model: 'glm5', localServerUrl: address });
  } finally {
    standIn.close();
  }
});

test('scientific assistant explains the updated view after a mixed request', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; all assistant responses are scripted.');
  await annotated(page);
  const requests = [];
  await page.route('**/api/chat/assistant', async route => {
    const payload = route.request().postDataJSON();
    requests.push(payload);
    const step = requests.length;
    expect(step).toBeLessThanOrEqual(3);
    if (step > 1) expect(payload.view.module).toBe('singleProtein.boxplot');
    if (step === 3) {
      expect(payload.answerOnly).toBe(true);
      expect(payload.receipts).toHaveLength(1);
      expect(payload.receipts[0]).toMatch(/^Opened /);
      expect(payload.view.mode).toEqual(requests[1].view.mode);
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
      model: 'scripted-no-inference', revision: 1,
      explainAfterChanges: step === 1,
      actions: step === 1 ? [{ type: 'navigate', target: 'singleProtein.boxplot' }] : [],
      answer: step === 3 ? 'This scripted explanation refers to the updated protein boxplot.' : '',
      evidence: step === 3 ? [{ tool: 'Simulation', status: 'available', text: 'Scripted transport fixture, not a model evaluation.' }] : [],
    }) });
  });
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await page.getByPlaceholder('Ask about this analysis...').fill('Open the protein boxplot and explain it.');
  await tab(page, 'Send').click();
  await tab(page, 'Confirm and send').click();
  await expect(page.getByText(/This scripted explanation refers to the updated protein boxplot\./)).toBeVisible({ timeout: 45000 });
  expect(requests).toHaveLength(3);
  expect(requests.map(request => request.answerOnly)).toEqual([false, false, true]);
  const plot = page.locator('main img').first();
  await expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
});

test('volcano lists the rows it could not test and offers them for download', async ({ page }) => {
  // Two sites keep a single value in A: the t-test cannot use them.
  const untestable = ['UPD_seq,PTM_localization,Protein_group,Gene_group,PTM_Collapse_key,' + samples.join(','),
    ...Array.from({ length: 24 }, (_, i) => [
      `SEQ${i}S`, `S${i}`, `P${Math.floor(i / 2)}`, `G${Math.floor(i / 2)}`, `K${i}`,
      ...samples.map((_, j) => (i < 2 && j >= 1 && j <= 3) ? '' :
        (12 + i * 0.3 + j * 0.12 + ((i * j) % 3) * 0.07 + (j >= 4 ? 1.2 : 0)).toFixed(4)),
    ].join(','))].join('\n');
  await annotated(page, '1', { table: untestable, expectedRows: 24 });
  await tab(page, 'Statistical Analysis').click();
  await tab(page, 'Volcano Plot').click();
  await field(page, 'Condition 2').selectOption('B');
  await expect(page.getByText('2 of 24 rows were not tested: fewer than 2 values in a compared condition.')).toBeVisible();
  const plotSection = page.locator('section').filter({ has: page.getByRole('link', { name: 'Open Plot', exact: true }) });
  const notice = page.getByText('2 of 24 rows were not tested: fewer than 2 values in a compared condition.');
  await expect.poll(async () => {
    const plotBox = await plotSection.boundingBox();
    const noticeBox = await notice.boundingBox();
    return Boolean(plotBox && noticeBox && noticeBox.y >= plotBox.y + plotBox.height);
  }).toBe(true);
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Rows not tested', exact: true }) });
  await expect(section).toBeVisible();
  await expect(section.getByText('fewer than 2 values in A').first()).toBeVisible();
  const pending = page.waitForEvent('download');
  await section.getByRole('link', { name: 'Download CSV', exact: true }).click();
  const download = await pending;
  expect(download.suggestedFilename()).toMatch(/_not_tested\.csv$/);
  const csv = (await readFile(await download.path())).toString('utf8');
  expect(csv.split('\n')[0]).toContain('n_A');
  expect(csv).toContain('K0');
  expect(csv).toContain('K1');
  expect(csv).not.toContain('K2,');
});

test('scientific assistant can set multiline volcano highlight terms', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; assistant responses are scripted.');
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  const highlight = page.getByLabel('Highlight terms', { exact: true });
  await expect(highlight).toBeVisible();
  let calls = 0;
  page.on('dialog', dialog => { throw new Error(`Unexpected scientific approval: ${dialog.message()}`); });
  await page.route('**/api/chat/assistant', async route => {
    const { view } = route.request().postDataJSON();
    const control = view.controls.find(item => item.label === 'Highlight terms');
    expect(control).toMatchObject({ type: 'text', permission: 'view' });
    if (calls) expect(control.value).toBe('G1\nG2');
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
      model: 'scripted', revision: 1, evidence: [],
      actions: calls++ === 0 ? [{ type: 'set_control', target: control.id, value: 'G1\nG2' }] : [],
      answer: calls === 1 ? '' : 'Highlight selection updated.',
    }) });
  });
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await page.getByPlaceholder('Ask about this analysis...').fill('Highlight terms G1 and G2.');
  await tab(page, 'Send').click();
  await tab(page, 'Confirm and send').click();
  await expect(page.getByText('Highlight selection updated.', { exact: false })).toBeVisible({ timeout: 45000 });
  await expect(highlight).toHaveValue('G1\nG2');
  expect(calls).toBe(2);
});

test('assistant changes are logged and the last one can be undone', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; assistant responses are scripted.');
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  const highlight = page.getByLabel('Highlight terms', { exact: true });
  await expect(highlight).toHaveValue('');
  let calls = 0;
  await page.route('**/api/chat/assistant', async route => {
    const { view } = route.request().postDataJSON();
    const control = view.controls.find(item => item.label === 'Highlight terms');
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
      model: 'scripted', revision: 1, evidence: [],
      actions: calls++ === 0 ? [{ type: 'set_control', target: control.id, value: 'G1' }] : [],
      answer: calls === 1 ? '' : 'Highlight selection updated.',
    }) });
  });
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await page.getByPlaceholder('Ask about this analysis...').fill('Highlight G1.');
  await tab(page, 'Send').click();
  await tab(page, 'Confirm and send').click();
  await expect(page.getByText('Highlight selection updated.', { exact: false })).toBeVisible({ timeout: 45000 });
  await expect(highlight).toHaveValue('G1');

  const log = page.locator('details').filter({ hasText: 'Changes made by the assistant (1)' });
  await log.locator('summary').click();
  await expect(log.getByRole('list', { name: 'Assistant changes' })).toContainText('Highlight terms: empty → G1');

  // Changed by hand since: undo refuses and keeps the entry.
  await highlight.fill('G2');
  await highlight.press('Tab');
  await log.getByRole('button', { name: 'Undo last change', exact: true }).click();
  await expect(log.getByRole('status')).toContainText('has been changed since the assistant set it');
  await expect(highlight).toHaveValue('G2');

  // Back to what the assistant set: undo restores the earlier value and clears the entry.
  await highlight.fill('G1');
  await highlight.press('Tab');
  await log.getByRole('button', { name: 'Undo last change', exact: true }).click();
  await expect(highlight).toHaveValue('');
  await expect(page.getByText('Changes made by the assistant (0)')).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Set Highlight terms back to ""' })).toBeVisible();
});

for (const destination of ['stats.simulation', 'data.distribution', 'phospho.ksea', 'analysis.canvas']) {
  test(`scientific assistant receives current context for ${destination}`, { tag: '@ai' }, async ({ page }) => {
    test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; assistant responses are scripted.');
    await annotated(page);
    let calls = 0;
    await page.route('**/api/chat/assistant', async route => {
      const { view } = route.request().postDataJSON();
      if (calls) {
        expect(view.module).toBe(destination);
        const mode = view.mode;
        expect(mode.kind).toBe('phospho');
        if (destination === 'analysis.canvas') expect(Array.isArray(mode.tiles)).toBe(true);
        if (destination === 'data.distribution') expect(mode.randomSeed).toBe(187);
        if (destination === 'phospho.ksea') expect(mode.source).toBe('volcano');
        if (destination === 'stats.simulation') expect(mode.status === 'incomplete_parameters' || mode.source === 'volcano').toBe(true);
      }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        model: 'scripted', revision: 1, evidence: [],
        actions: calls++ === 0 ? [{ type: 'navigate', target: destination }] : [],
        answer: calls === 1 ? '' : 'Current context captured.',
      }) });
    });
    await tab(page, 'Open chatbot sidebar').click();
    await tab(page, 'Toggle AI settings').click();
    await page.getByLabel('Select chatbot provider').selectOption('openai');
    await page.getByPlaceholder('Ask about this analysis...').fill(`Open ${destination}.`);
    await tab(page, 'Send').click();
    await tab(page, 'Confirm and send').click();
    await expect(page.getByText('Current context captured.', { exact: false })).toBeVisible({ timeout: 45000 });
    expect(calls).toBe(2);
  });
}

async function askForRealEvidence(page) {
  const firstRequest = await tab(page, 'Open chatbot sidebar').isVisible();
  if (firstRequest) {
    await tab(page, 'Open chatbot sidebar').click();
    await tab(page, 'Toggle AI settings').click();
    await page.getByLabel('Select chatbot provider').selectOption('openai');
  }
  await page.getByPlaceholder('Ask about this analysis...').fill('Explain the current plot.');
  const pending = page.waitForResponse(r => r.url().endsWith('/api/chat/assistant'));
  await tab(page, 'Send').click();
  const confirmation = tab(page, 'Confirm and send');
  if (firstRequest) await confirmation.click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const payload = await response.json();
  expect(payload.model).toBe('scripted-no-inference');
  return { request: response.request().postDataJSON(), ...payload };
}

test('end-to-end evidence reads uploaded KSEA values and preserves rendered settings', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the isolated scripted provider.');
  const annotation = await annotated(page);
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  for (const label of ['Serine/Threonine Result File', 'Tyrosine/Non-canonical Result File']) {
    await page.getByLabel(label).setInputFiles({ name: 'synthetic.csv', mimeType: 'text/csv',
      buffer: Buffer.from('Kinase,Frequency Factor,Adjusted p-value\nAKT1,4,0.02\n') });
  }
  const rendered = page.waitForResponse(r => r.url().endsWith('/api/plots/phospho/ksea-volcano.html'));
  await tab(page, 'Generate Kinase Library Volcano').click();
  const token = (await rendered).headers()['x-copylot-evidence'];
  expect(token).toMatch(/^[A-Za-z0-9_-]+$/);
  const first = await askForRealEvidence(page);
  expect(first.request.view.mode).toMatchObject({ externalPlotPresent: true, externalEvidenceToken: token });
  expect(first.evidence).toHaveLength(1);
  expect(first.evidence[0].text).toContain('log2ff=2');
  expect(first.evidence[0].text).toContain('adj_pval=0.02');
  expect(first.evidence[0].text).toContain('result_group=S/T');
  expect(first.evidence[0].text).toContain('result_group=Y');
  await field(page, 'Kinase Library Volcano P-value Threshold', 'input').fill('0.01');
  await field(page, 'Kinase Library Volcano P-value Threshold', 'input').blur();
  const unchanged = await askForRealEvidence(page);
  expect(unchanged.evidence).toEqual(first.evidence);
  const rerendered = page.waitForResponse(r => r.url().endsWith('/api/plots/phospho/ksea-volcano.html'));
  await tab(page, 'Generate Kinase Library Volcano').click();
  await rerendered;
  const updated = await askForRealEvidence(page);
  expect(updated.evidence[0].text).toContain('threshold=0.01');
  expect(updated.evidence[0].text).toContain('Not significant');
  const regenerated = await tabRequest(page).post('/api/annotations/generate', { data: annotation.sent });
  expect(regenerated.ok(), await regenerated.text()).toBeTruthy();
  const stale = await askForRealEvidence(page);
  expect(stale.evidence).toHaveLength(1);
  expect(stale.evidence[0].status).toBe('unavailable');
});

test('end-to-end evidence follows canvas contrast and p-value changes', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the isolated scripted provider.');
  await annotated(page);
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  await canvas.locator('select').first().selectOption('volcano');
  await tab(page, '+ Add Plot').click();
  await canvas.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await canvas.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  const first = await askForRealEvidence(page);
  const tile = first.evidence.find(e => e.tool.includes(': volcano'));
  await expect(canvas.locator('svg').getByText('-log10(BH-adjusted p-value)', { exact: true })).toBeVisible();
  expect(tile.status).not.toBe('unavailable');
  expect(tile.text).toContain('p_metric=BH-adjusted');
  expect(tile.text).toContain('log2FC=');
  await canvas.getByRole('combobox', { name: 'P-value mode', exact: true }).selectOption('uncorrected');
  await canvas.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('B');
  await canvas.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('A');
  const changed = await askForRealEvidence(page);
  const settings = changed.request.view.mode.tileEvidence.find(t => t.type === 'volcano').settings;
  expect(settings).toMatchObject({ condition1: 'B', condition2: 'A', useUncorrected: true });
  const rawTile = changed.evidence.find(e => e.tool.includes(': volcano'));
  await expect(canvas.locator('svg').getByText('-log10(p-value)', { exact: true })).toBeVisible();
  expect(rawTile.text).toContain('p_metric=raw');
  expect(rawTile.text).not.toEqual(tile.text);
  const actualResponse = await tabRequest(page).post('/api/analysis/volcano/data', { data: settings });
  expect(actualResponse.ok(), await actualResponse.text()).toBeTruthy();
  const actual = await actualResponse.json();
  expect(rawTile.text).toContain(`totalRows=${actual.totalRows}`);
  expect(rawTile.text).toContain(`log2FC=${actual.points[0].log2FC}`);
  expect(rawTile.text).toContain(`negLog10P=${actual.points[0].negLog10P}`);
  for (const type of ['proteinBoxplot', 'proteinLineplot', 'oraList']) {
    await canvas.locator('select').first().selectOption(type);
    await tab(page, '+ Add Plot').click();
  }
  for (const control of await canvas.getByRole('combobox', { name: 'Protein source', exact: true }).all()) {
    await control.selectOption('manual');
  }
  await canvas.getByRole('textbox', { name: 'Protein or gene', exact: true }).fill('K1');
  await canvas.getByRole('textbox', { name: 'Proteins or genes (comma, space, or newline)', exact: true }).fill('K1 K2');
  const mixed = await askForRealEvidence(page);
  const specs = mixed.request.view.mode.tileEvidence;
  expect(specs.find(t => t.type === 'proteinBoxplot').settings).toMatchObject({ protein: 'K1', conditions: ['B', 'A'] });
  expect(specs.find(t => t.type === 'proteinLineplot').settings).toMatchObject({ proteins: ['K1', 'K2'], conditions: ['B', 'A'] });
  for (const type of ['proteinBoxplot', 'proteinLineplot']) {
    expect(mixed.evidence.find(e => e.tool.endsWith(type)).status).not.toBe('unavailable');
  }
  expect(mixed.evidence.find(e => e.tool.endsWith('oraList')).status).toBe('unavailable');
  await canvas.locator('select').first().selectOption('volcano');
  await tab(page, '+ Add Plot').click();
  await canvas.getByRole('combobox', { name: 'Condition 1', exact: true }).last().selectOption('A');
  await canvas.getByRole('combobox', { name: 'Condition 2', exact: true }).last().selectOption('B');
  await canvas.getByRole('combobox', { name: 'P-value mode', exact: true }).last().selectOption('corrected');
  const multiple = await askForRealEvidence(page);
  const independent = multiple.request.view.mode.tileEvidence.filter(tile => tile.type === 'volcano');
  expect(independent[0].settings).toMatchObject({ condition1: 'B', condition2: 'A', useUncorrected: true });
  expect(independent[1].settings).toMatchObject({ condition1: 'A', condition2: 'B', useUncorrected: false });
  const unrelatedRequests = [];
  const observe = request => {
    if (request.url().endsWith('/api/analysis/volcano/data') && request.postDataJSON().condition1 === 'B') unrelatedRequests.push(request);
  };
  page.on('request', observe);
  for (const metric of ['uncorrected', 'corrected']) {
    const updated = page.waitForResponse(response => response.url().endsWith('/api/analysis/volcano/data') && response.request().postDataJSON().condition1 === 'A');
    await canvas.getByRole('combobox', { name: 'P-value mode', exact: true }).last().selectOption(metric);
    expect((await updated).ok()).toBeTruthy();
  }
  page.off('request', observe);
  expect(unrelatedRequests).toHaveLength(0);
  const volcanoTiles = multiple.evidence.filter(e => e.tool.endsWith(': volcano'));
  expect(volcanoTiles).toHaveLength(2);
  for (const item of volcanoTiles) {
    const contrast = item.text.match(/volcano_contrast\|([^\n]+)/)[1];
    const tileNumber = item.tool.match(/canvas tile (\d+)/)[1];
    const paragraph = multiple.answer.split('\n\n').find(text => text.startsWith(`Tile ${tileNumber} (volcano):`));
    expect(paragraph).toBeTruthy();
    expect(paragraph).toContain(`log2 fold change is ${contrast.replace(' - ', ' minus ')}`);
    const metric = item.text.includes('for_significance=pval') ? 'raw' : 'BH-adjusted';
    expect(paragraph).toContain(`The y-axis is the negative log10 of the ${metric} p-value`);
  }
  await canvas.locator(`[data-assistant-tile="${independent[1].id}"] svg circle`).first().click();
  await expect(page.getByRole('combobox', { name: 'Linked plot source', exact: true })).toHaveValue(independent[1].id);
  await page.getByRole('combobox', { name: 'Linked plot source', exact: true }).selectOption(independent[0].id);
  await page.getByRole('combobox', { name: 'Linked plot source', exact: true }).selectOption(independent[1].id);
  const linked = await askForRealEvidence(page);
  expect(linked.request.view.mode.tileEvidence.find(tile => tile.type === 'proteinBoxplot').settings.conditions).toEqual(['A', 'B']);
  const styledTile = canvas.locator(`[data-assistant-tile="${independent[1].id}"]`);
  const statisticalRequests = [];
  const observeStyle = request => { if (request.url().endsWith('/api/analysis/volcano/data')) statisticalRequests.push(request); };
  page.on('request', observeStyle);
  await styledTile.getByText('Plot styling', { exact: true }).click();
  await styledTile.locator('summary').filter({ has: page.getByText('Title', { exact: true }) }).click();
  await styledTile.getByPlaceholder('Overwrite plot title', { exact: true }).fill('A & B <test>');
  await styledTile.locator('summary').filter({ has: page.getByText('Volcano points', { exact: true }) }).click();
  await styledTile.getByText('All classes', { exact: true }).locator('..').getByLabel('Size', { exact: true }).fill('8');
  await expect(styledTile.locator('svg')).toContainText('A & B <test>');
  await expect(styledTile.locator('svg circle title').first()).toContainText('-log10(BH-adjusted p-value)');
  const pointAttributes = await styledTile.locator('svg circle').evaluateAll(points => points.map(point =>
    ['cx', 'cy', 'r', 'fill', 'stroke'].map(key => point.getAttribute(key))));
  const pendingDownload = page.waitForEvent('download');
  await styledTile.getByRole('button', { name: 'Download SVG', exact: true }).click();
  const svgDownload = await pendingDownload;
  expect(svgDownload.suggestedFilename()).toBe(`canvas_${independent[1].id}_volcano.svg`);
  const svgText = await readFile(await svgDownload.path(), 'utf8');
  const exportedSvg = await page.evaluate(text => {
    const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
    return {
      error: !!doc.querySelector('parsererror'), text: doc.documentElement.textContent,
      points: [...doc.querySelectorAll('circle')].map(point => ['cx', 'cy', 'r', 'fill', 'stroke'].map(key => point.getAttribute(key))),
      unsafe: !!doc.querySelector('script, test, [data-selection-overlay]'),
    };
  }, svgText);
  expect(exportedSvg.error).toBe(false);
  expect(exportedSvg.unsafe).toBe(false);
  expect(exportedSvg.text).toContain('A & B <test>');
  expect(exportedSvg.text).toContain('-log10(BH-adjusted p-value)');
  expect(exportedSvg.points).toEqual(pointAttributes);
  expect(statisticalRequests).toHaveLength(0);
  page.off('request', observeStyle);
  await styledTile.getByText('Plot styling', { exact: true }).click();
  await page.getByRole('button', { name: 'Close chatbot sidebar', exact: true }).click();
  await styledTile.screenshot({ path: test.info().outputPath('canvas-volcano-desktop.png') });
  await page.setViewportSize({ width: 760, height: 900 });
  await page.getByRole('button', { name: 'Close sidebar', exact: true }).click();
  await styledTile.screenshot({ path: test.info().outputPath('canvas-volcano-narrow.png') });
  await expect(styledTile.getByRole('button', { name: 'Download SVG', exact: true })).toBeVisible();
  expect(await styledTile.locator('svg').evaluate(svg => svg.getBoundingClientRect().width <= svg.parentElement.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole('button', { name: 'Open sidebar', exact: true }).click();
  await page.getByRole('button', { name: 'Open chatbot sidebar', exact: true }).click();
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Analysis').click();
  await expect(styledTile.locator('svg')).toContainText('A & B <test>');
  await expect(canvas.locator(`[data-assistant-tile="${independent[0].id}"] svg`)).not.toContainText('A & B <test>');
  await expect(page.getByRole('combobox', { name: 'Linked plot source', exact: true })).toHaveValue(independent[1].id);
  const restored = await askForRealEvidence(page);
  expect(restored.request.view.mode.tileEvidence.filter(tile => tile.type === 'volcano')).toEqual(independent);
  await canvas.locator(`[data-assistant-tile="${independent[1].id}"]`).getByRole('button', { name: 'Remove', exact: true }).click();
  const remaining = await askForRealEvidence(page);
  expect(remaining.request.view.mode.tileEvidence.find(tile => tile.type === 'proteinBoxplot').settings.conditions).toEqual(['B', 'A']);
});

test('end-to-end evidence preserves canvas data sources and matches dedicated tables', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the isolated scripted provider.');
  await annotated(page);
  await tab(page, 'Imputation').click();
  await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  for (const type of ['volcano', 'proteinBoxplot', 'proteinLineplot']) {
    await canvas.locator('select').first().selectOption(type);
    await tab(page, '+ Add Plot').click();
  }
  const volcano = canvas.locator('[data-assistant-group="Tile 1: volcano"]');
  await volcano.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await volcano.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  const pending = page.waitForResponse(response => response.url().endsWith('/api/analysis/volcano/data') && response.request().postDataJSON().dataSource === 'imputed');
  await volcano.getByRole('combobox', { name: 'Data source', exact: true }).selectOption('imputed');
  expect((await pending).ok()).toBeTruthy();
  for (const [index, type, tabName] of [[2, 'proteinBoxplot', 'boxplot'], [3, 'proteinLineplot', 'lineplot']]) {
    const tile = canvas.locator(`[data-assistant-group="Tile ${index}: ${type}"]`);
    await tile.getByRole('combobox', { name: 'Protein source', exact: true }).selectOption('manual');
    await tile.getByRole('textbox').fill('K0');
    for (const source of ['data', 'filtered', 'imputed']) {
      await tile.getByRole('combobox', { name: 'Data source', exact: true }).selectOption(source);
      const img = tile.locator('img');
      await expect(img).toHaveAttribute('src', new RegExp(`dataSource=${source}`));
      await expect.poll(() => img.evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
      expect(new URL(await img.getAttribute('src'), page.url()).pathname.endsWith(`/api/plots/single-protein/phospho/${tabName}.png`)).toBe(true);
      // The tables behind the assistant's tile evidence are compared with the
      // dedicated ones in test_visualization_data_sources.py
      // (test_canvas_single_protein_tables_match_dedicated_defaults); the
      // /api/analysis/*-table routes this used to call were removed on 2026-10-02.
    }
  }
  for (const [index, type] of [[2, 'proteinBoxplot'], [3, 'proteinLineplot']]) {
    const tile = canvas.locator(`[data-assistant-group="Tile ${index}: ${type}"]`);
    await tile.getByText('Plot styling', { exact: true }).click();
    await tile.locator('summary').filter({ has: page.getByText('Title', { exact: true }) }).click();
    await tile.getByPlaceholder('Overwrite plot title', { exact: true }).fill(`Styled ${type}`);
    await expect.poll(async () => JSON.parse(new URL(await tile.locator('img').getAttribute('src'), page.url()).searchParams.get('advanced')).titleElement.text).toBe(`Styled ${type}`);
    await expect.poll(() => tile.locator('img').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    for (const [format, mime] of [['png', 'image/png'], ['jpg', 'image/jpeg'], ['webp', 'image/webp'], ['pdf', 'application/pdf']]) {
      await tile.getByRole('combobox', { name: 'Export format', exact: true }).selectOption(format);
      const href = await tile.getByRole('link', { name: 'Download Plot', exact: true }).getAttribute('href');
      const displayed = new URL(await tile.locator('img').getAttribute('src'), page.url());
      const exported = new URL(href, page.url());
      exported.searchParams.delete('downloadFormat');
      expect(exported.toString()).toBe(displayed.toString());
      const download = await page.request.get(href);
      expect(download.ok()).toBeTruthy();
      expect(download.headers()['content-type']).toContain(mime);
    }
    await tile.getByText('Plot styling', { exact: true }).click();
    await tile.screenshot({ path: test.info().outputPath(`canvas-${type}.png`) });
  }
  const evidence = await askForRealEvidence(page);
  const specs = evidence.request.view.mode.tileEvidence;
  expect(specs.every(tile => tile.settings.dataSource === 'imputed')).toBeTruthy();
  expect(evidence.evidence.filter(item => item.tool.startsWith('canvas tile')).every(item => item.status !== 'unavailable')).toBeTruthy();
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Analysis').click();
  for (const select of await canvas.getByRole('combobox', { name: 'Data source', exact: true }).all()) {
    await expect(select).toHaveValue('imputed');
  }
  for (const type of ['proteinBoxplot', 'proteinLineplot']) {
    const tile = canvas.locator(`[data-assistant-group$=": ${type}"]`);
    const advanced = JSON.parse(new URL(await tile.locator('img').getAttribute('src'), page.url()).searchParams.get('advanced'));
    expect(advanced.titleElement.text).toBe(`Styled ${type}`);
  }
});

for (const kind of ['protein', 'phospho']) test(`end-to-end evidence feature focus resolves ${kind} and preserves scope and existing tiles`, { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the isolated scripted provider.');
  const feature = kind === 'protein' ? 'P0' : 'K0';
  const level = kind === 'protein' ? 'protein' : 'phosphosite';
  const table = kind === 'protein' ? ['ProteinNames,GeneNames,' + samples.join(','),
    ...sites.split('\n').slice(1).map((row, index) => `P${index},G${index},${row.split(',').slice(5).join(',')}`)].join('\n') : sites;
  await annotated(page, '3', { table, kind });
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  await canvas.getByRole('combobox', { name: 'New tile type', exact: true }).selectOption('oraList');
  await tab(page, '+ Add Plot').click();
  const originalId = await canvas.locator('[data-assistant-tile]').first().getAttribute('data-assistant-tile');
  await page.getByPlaceholder('Paste genes separated by comma, space, or newline').fill('KEEP');
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  async function focus(message, confirm = false) {
    await page.getByPlaceholder('Ask about this analysis...').fill(message);
    const response = page.waitForResponse(r => r.url().endsWith('/api/chat/assistant'));
    await tab(page, 'Send').click();
    if (confirm) await tab(page, 'Confirm and send').click();
    const result = await response;
    expect(result.ok(), await result.text()).toBeTruthy();
    return result.json();
  }
  const result = await focus(`Focus canvas on ${level} ${feature}`, true);
  expect(result.actions[0].type).toBe('focus_canvas');
  await expect(canvas.locator('[data-assistant-tile]')).toHaveCount(4);
  const volcano = canvas.locator('[data-assistant-group="Tile 2: volcano"]');
  await expect(volcano.locator('svg circle[stroke="#334155"]')).toHaveCount(1);
  const box = canvas.locator('[data-assistant-group="Tile 3: proteinBoxplot"]');
  await expect(box.getByRole('textbox', { name: 'Protein or gene', exact: true })).toHaveValue(feature);
  await expect(box.locator('img')).toBeVisible();
  await expect(box.locator('img')).toHaveAttribute('src', /identifier=workflow/);
  const ids = await canvas.locator('[data-assistant-tile]').evaluateAll(nodes => nodes.map(node => node.dataset.assistantTile));
  await focus(`Focus canvas on ${level} ${feature}`);
  await expect(canvas.locator('[data-assistant-tile]')).toHaveCount(4);
  expect(await canvas.locator('[data-assistant-tile]').evaluateAll(nodes => nodes.map(node => node.dataset.assistantTile))).toEqual(ids);
  const unavailable = await focus(kind === 'phospho' ? 'Focus canvas on protein P0' : 'Focus canvas on phosphosite K0');
  expect(unavailable.needsClarification).toBe(true);
  expect(unavailable.actions).toEqual([]);
  await expect(canvas.locator('[data-assistant-tile]').first()).toHaveAttribute('data-assistant-tile', originalId);
  await expect(page.getByPlaceholder('Paste genes separated by comma, space, or newline')).toHaveValue('KEEP');
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Analysis').click();
  await expect(volcano.locator('svg circle[stroke="#334155"]')).toHaveCount(1);
  await expect(box.locator('img')).toBeVisible();
  if (kind === 'phospho') {
    await focus('Focus canvas on all phosphosites on protein P0');
    await expect(canvas.locator('[data-assistant-tile]')).toHaveCount(8);
    await expect(canvas.locator('[data-assistant-group="Tile 5: volcano"] svg circle[stroke="#334155"]')).toHaveCount(2);
    await expect(canvas.locator('[data-assistant-group="Tile 7: proteinBoxplot"] input').first()).toHaveValue('K1');
    await expect(canvas.locator('[data-assistant-group="Tile 8: proteinLineplot"] textarea')).toHaveValue('K0\nK1');
  }
});

test('large canvas preserves selected points and avoids requests during layout changes', async ({ page }) => {
  test.setTimeout(120000);
  const count = 5000;
  const table = [sites.split('\n')[0], ...Array.from({ length: count }, (_, i) => [
    `SEQ${i}S`, `S${i}`, `P${i}`, `G${i}`, `K${i}`,
    ...samples.map((_, j) => (12 + (i % 100) * .03 + (j % 4) * .12 + ((i * j) % 3) * .07 + (j >= 4 ? 2 : 0)).toFixed(4)),
  ].join(','))].join('\n');
  await annotated(page, '3', { table });
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  for (let i = 0; i < 2; i++) {
    await canvas.getByRole('combobox', { name: 'New tile type', exact: true }).selectOption('volcano');
    await tab(page, '+ Add Plot').click();
    const tile = canvas.locator('[data-assistant-tile]').last();
    await tile.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
    await tile.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
    await expect(tile.locator('svg circle')).toHaveCount(count);
  }
  const id = await canvas.locator('[data-assistant-tile]').first().getAttribute('data-assistant-tile');
  const tile = canvas.locator(`[data-assistant-tile="${id}"]`);
  // B is higher in this fixture; the displayed contrast is A minus B.
  await tile.getByRole('button', { name: 'Add all downregulated to list', exact: true }).click();
  await tile.getByRole('button', { name: 'Multi-select mode: Off', exact: true }).click();
  await tile.getByRole('button', { name: 'Select list in plot', exact: true }).click();
  await expect(tile.locator('svg circle[stroke="#334155"]')).toHaveCount(count);
  const firstPoint = await tile.locator('svg circle').first().elementHandle();
  const lastPoint = await tile.locator('svg circle').last().elementHandle();
  const requests = [];
  const observe = request => { if (/\/api\/(analysis|plots)\//.test(request.url())) requests.push(request.url()); };
  page.on('request', observe);
  const start = performance.now();
  for (let i = 0; i < 3; i++) {
    await tile.getByRole('button', { name: 'Collapse tile', exact: true }).click();
    await tile.getByRole('button', { name: 'Move tile down', exact: true }).click();
    await tile.getByRole('button', { name: 'Expand tile', exact: true }).click();
    await tile.getByRole('button', { name: 'Move tile up', exact: true }).click();
  }
  const elapsed = performance.now() - start;
  expect(requests).toEqual([]);
  page.off('request', observe);
  await expect(tile.locator('svg circle[stroke="#334155"]')).toHaveCount(count);
  expect(await firstPoint.evaluate(node => node.isConnected)).toBe(true);
  expect(await lastPoint.evaluate(node => node.isConnected)).toBe(true);
  await expect(page.getByRole('combobox', { name: 'Linked plot source', exact: true })).toHaveValue(id);
  await test.info().attach('large-canvas-layout', { body: JSON.stringify({ pointsPerTile: count, tiles: 2, selected: count, layoutActions: 12, elapsedMs: Math.round(elapsed), requests: requests.length }), contentType: 'application/json' });
  console.info(`Large canvas: ${count} selected points, 12 layout actions in ${Math.round(elapsed)} ms, ${requests.length} plot requests.`);
});

test('canvas plot loading hides old results and failed renders can be retried', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  await canvas.getByRole('combobox', { name: 'New tile type', exact: true }).selectOption('volcano');
  await tab(page, '+ Add Plot').click();
  const volcano = canvas.locator('[data-assistant-tile]').first();
  await volcano.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await volcano.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  await expect(volcano.locator('svg circle').first()).toBeVisible();
  let releaseVolcano;
  const volcanoGate = new Promise(resolve => { releaseVolcano = resolve; });
  const volcanoRoute = '**/api/analysis/volcano/data';
  await page.route(volcanoRoute, async route => {
    await volcanoGate;
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Temporary plot failure' }) });
  });
  await volcano.getByRole('combobox', { name: 'P-value mode', exact: true }).selectOption('uncorrected');
  await expect(volcano.getByRole('status')).toHaveText('Loading plot…');
  await expect(volcano.locator('svg')).toHaveCount(0);
  releaseVolcano();
  await expect(volcano.getByRole('alert')).toContainText('Temporary plot failure');
  await page.unroute(volcanoRoute);
  await volcano.getByRole('button', { name: 'Retry plot', exact: true }).click();
  await expect(volcano.locator('svg circle').first()).toBeVisible();
  await expect(volcano.locator('svg')).toContainText('-log10(p-value)');

  for (const [type, name] of [['proteinBoxplot', 'boxplot'], ['proteinLineplot', 'lineplot']]) {
    await canvas.getByRole('combobox', { name: 'New tile type', exact: true }).selectOption(type);
    await tab(page, '+ Add Plot').click();
    const tile = canvas.locator('[data-assistant-tile]').last();
    await tile.getByRole('combobox', { name: 'Protein source', exact: true }).selectOption('manual');
    await tile.getByRole('textbox').fill('K0');
    await expect(tile.locator('img')).toBeVisible();
    let releaseImage;
    const imageGate = new Promise(resolve => { releaseImage = resolve; });
    const imageRoute = `**/${name}.png?*`;
    await page.route(imageRoute, async route => {
      await imageGate;
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
    });
    await tile.getByRole('textbox').fill('K1');
    await expect(tile.getByRole('status')).toHaveText('Loading plot…');
    await expect(tile.locator('img')).toHaveAttribute('aria-busy', 'true');
    await expect(tile.locator('img')).toBeHidden();
    await expect(tile.getByRole('link', { name: 'Download Plot', exact: true })).toHaveCount(0);
    releaseImage();
    await expect(tile.getByRole('alert')).toContainText('Could not render');
    await expect(tile.locator('img')).toHaveAttribute('aria-busy', 'false');
    await page.unroute(imageRoute);
    await tile.getByRole('button', { name: 'Retry plot', exact: true }).click();
    await expect(tile.locator('img')).toBeVisible();
    await expect(tile.locator('img')).toHaveAttribute('src', /_retry=1/);
    await expect(tile.locator('img')).toHaveAttribute('aria-busy', 'false');
    await expect(tile.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', await tile.locator('img').getAttribute('src'));
  }
});

test('a canvas lineplot names the proteins it could not find', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  await canvas.getByRole('combobox', { name: 'New tile type', exact: true }).selectOption('proteinLineplot');
  await tab(page, '+ Add Plot').click();
  const tile = canvas.locator('[data-assistant-tile]').last();
  await tile.getByRole('combobox', { name: 'Protein source', exact: true }).selectOption('manual');
  await tile.getByRole('textbox').fill('K0 NOT_A_PROTEIN');
  await expect(tile.locator('img')).toBeVisible();
  await expect(tile.getByText('Not found in this dataset, so not plotted: NOT_A_PROTEIN.', { exact: true })).toBeVisible();
  await tile.getByRole('textbox').fill('K0');
  await expect(tile.getByText('Not found in this dataset', { exact: false })).toHaveCount(0);
});

test('canvas layout preserves automatic linking, order and collapsed state', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  for (let index = 0; index < 2; index++) {
    await canvas.getByRole('combobox', { name: 'New tile type', exact: true }).selectOption('volcano');
    await tab(page, '+ Add Plot').click();
    const tile = canvas.locator('[data-assistant-tile]').nth(index);
    await tile.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption(index ? 'B' : 'A');
    await tile.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption(index ? 'A' : 'B');
    await expect(tile.locator('svg circle').first()).toBeVisible();
  }
  const ids = await canvas.locator('[data-assistant-tile]').evaluateAll(nodes => nodes.map(node => node.dataset.assistantTile));
  const first = canvas.locator(`[data-assistant-tile="${ids[0]}"]`);
  const second = canvas.locator(`[data-assistant-tile="${ids[1]}"]`);
  const linked = page.getByRole('combobox', { name: 'Linked plot source', exact: true });
  await expect(linked).toHaveValue(ids[0]);
  await expect(first.getByRole('button', { name: 'Move tile up', exact: true })).toBeDisabled();
  await expect(second.getByRole('button', { name: 'Move tile down', exact: true })).toBeDisabled();
  const requests = [];
  const observe = request => { if (request.url().endsWith('/api/analysis/volcano/data')) requests.push(request); };
  page.on('request', observe);
  await first.getByRole('button', { name: 'Collapse tile', exact: true }).click();
  await expect(first.locator('svg')).toBeHidden();
  await second.getByRole('button', { name: 'Move tile up', exact: true }).click();
  await expect(canvas.locator('[data-assistant-tile]').first()).toHaveAttribute('data-assistant-tile', ids[1]);
  await expect(linked).toHaveValue(ids[0]);
  await expect(first.getByRole('button', { name: 'Expand tile', exact: true })).toHaveAttribute('aria-expanded', 'false');
  expect(requests).toHaveLength(0);
  page.off('request', observe);
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Analysis').click();
  await expect(canvas.locator('[data-assistant-tile]').first()).toHaveAttribute('data-assistant-tile', ids[1]);
  await expect(linked).toHaveValue(ids[0]);
  await expect(first.locator('svg')).toBeHidden();
  await first.getByRole('button', { name: 'Expand tile', exact: true }).click();
  await expect(first.locator('svg circle').first()).toBeVisible();
  await expect(first.getByRole('combobox', { name: 'Condition 1', exact: true })).toHaveValue('A');
  await canvas.screenshot({ path: test.info().outputPath('canvas-layout-controls.png') });
});

test('end-to-end evidence follows completed ORA results and clearing', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the isolated scripted provider.');
  await annotated(page);
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  await canvas.locator('select').first().selectOption('oraList');
  await tab(page, '+ Add Plot').click();
  await page.getByPlaceholder('Paste genes separated by comma, space, or newline').fill('AKT1 EGFR MAPK1 MAPK3');
  await canvas.getByRole('combobox', { name: 'Background', exact: true }).selectOption('global');
  await field(canvas, 'Adj p-value cutoff', 'input').fill('1');
  let runs = 0;
  page.on('request', request => { if (request.url().endsWith('/api/stats/ora/list/run')) runs++; });
  const completed = page.waitForResponse(r => r.url().endsWith('/api/stats/ora/list/run'));
  await tab(page, 'Run ORA').click();
  const response = await completed;
  expect(response.ok(), await response.text()).toBeTruthy();
  const actual = await response.json();
  expect(actual.terms.length).toBeGreaterThan(0);
  expect(actual.evidenceToken).toMatch(/^[A-Za-z0-9_-]+$/);
  const first = await askForRealEvidence(page);
  const tile = first.evidence.find(e => e.tool.endsWith('oraList'));
  expect(tile.status).not.toBe('unavailable');
  expect(tile.text).toContain(`termId=${actual.terms[0].termId}`);
  expect(Number(tile.text.match(/\|adjPValue=([^|\n]+)/)[1])).toBe(actual.terms[0].adjPValue);
  expect(first.request.view.mode.tileEvidence[0].token).toBe(actual.evidenceToken);
  const exportLink = page.getByRole('link', { name: 'Download Terms CSV', exact: true });
  const originalExport = await exportLink.getAttribute('href');
  await page.getByPlaceholder('Paste genes separated by comma, space, or newline').fill('TP53');
  await field(canvas, 'Adj p-value cutoff', 'input').fill('0.5');
  await field(canvas, 'Min term size', 'input').fill('10');
  await field(canvas, 'Max term size', 'input').fill('400');
  await field(canvas, 'Top terms', 'input').fill('5');
  await expect(exportLink).toHaveAttribute('href', originalExport);
  await canvas.getByRole('button', { name: 'Collapse tile', exact: true }).click();
  await expect(exportLink).toBeHidden();
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Analysis').click();
  await expect(canvas.getByRole('button', { name: 'Expand tile', exact: true })).toBeVisible();
  await canvas.getByRole('button', { name: 'Expand tile', exact: true }).click();
  await expect(page.getByPlaceholder('Paste genes separated by comma, space, or newline')).toHaveValue('TP53');
  await expect(field(canvas, 'Adj p-value cutoff', 'input')).toHaveValue('0.5');
  await expect(field(canvas, 'Min term size', 'input')).toHaveValue('10');
  await expect(field(canvas, 'Max term size', 'input')).toHaveValue('400');
  await expect(field(canvas, 'Top terms', 'input')).toHaveValue('5');
  await expect(exportLink).toHaveAttribute('href', originalExport);
  const edited = await askForRealEvidence(page);
  expect(edited.evidence).toEqual(first.evidence);
  expect(runs).toBe(1);
  const rerun = page.waitForResponse(r => r.url().endsWith('/api/stats/ora/list/run'));
  await tab(page, 'Run ORA').click();
  const rerunResponse = await rerun;
  expect(rerunResponse.ok(), await rerunResponse.text()).toBeTruthy();
  const updatedResult = await rerunResponse.json();
  const updated = await askForRealEvidence(page);
  expect(updated.request.view.mode.tileEvidence[0].token).toBe(updatedResult.evidenceToken);
  expect(updatedResult.evidenceToken).not.toBe(actual.evidenceToken);
  expect(updated.evidence.find(e => e.tool.endsWith('oraList')).text).toContain('querySize=1');
  expect(runs).toBe(2);
  await tab(page, 'Clear Result').click();
  const cleared = await askForRealEvidence(page);
  expect(cleared.evidence.find(e => e.tool.endsWith('oraList')).status).toBe('unavailable');
  expect(cleared.request.view.mode.tileEvidence[0].token).toBe('');
  expect(runs).toBe(2);
  await tab(page, 'QC Pipeline').click();
  await tab(page, 'Analysis').click();
  await expect(exportLink).toHaveCount(0);
  const stillCleared = await askForRealEvidence(page);
  expect(stillCleared.evidence.find(e => e.tool.endsWith('oraList')).status).toBe('unavailable');
  expect(runs).toBe(2);
  let release;
  let entered;
  const held = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  await page.route('**/api/stats/ora/list/run', async route => {
    entered();
    await held;
    await route.fulfill({ json: actual });
  });
  await tab(page, 'Run ORA').click();
  await started;
  await tab(page, 'Clear Result').click();
  release();
  await expect(tab(page, 'Run ORA')).toBeEnabled();
  const afterCancelled = await askForRealEvidence(page);
  expect(afterCancelled.evidence.find(e => e.tool.endsWith('oraList')).status).toBe('unavailable');
  await expect(exportLink).toHaveCount(0);
});

test('end-to-end evidence follows control volcano contrasts and removal', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the isolated scripted provider.');
  const names = ['A', 'B', 'C', 'D'].flatMap(group => [1, 2, 3, 4].map(n => `${group}${n}`));
  const table = ['UPD_seq,PTM_localization,Protein_group,Gene_group,PTM_Collapse_key,' + names.join(','),
    ...Array.from({ length: 24 }, (_, i) => [`SEQ${i}S`, `S${i}`, `P${i}`, `G${i}`, `K${i}`,
      ...names.map((_, j) => (12 + i * .3 + Math.floor(j / 4) * .7 + (j % 4) * .11 + (i * j % 3) * .04).toFixed(4))].join(','))].join('\n');
  const meta = 'sample,condition,pair_id\n' + names.map(s => `${s},${s[0]},${s[1]}`).join('\n');
  await annotated(page, '3', { table, meta });
  await tab(page, 'Analysis').click();
  const canvas = page.getByRole('heading', { name: 'Analysis Canvas', exact: true }).locator('..').locator('..');
  await canvas.locator('select').first().selectOption('volcanoControl');
  await tab(page, '+ Add Plot').click();
  for (const [label, value] of [['Condition 1', 'A'], ['Condition 2', 'B'], ['Condition 1 Control', 'C'], ['Condition 2 Control', 'D']]) {
    await canvas.getByRole('combobox', { name: label, exact: true }).selectOption(value);
  }
  for (const raw of [false, true]) {
    if (raw) {
      await canvas.getByRole('combobox', { name: 'P-value mode', exact: true }).selectOption('uncorrected');
      await canvas.getByRole('combobox', { name: 'Condition 1 Control', exact: true }).selectOption('D');
      await canvas.getByRole('combobox', { name: 'Condition 2 Control', exact: true }).selectOption('C');
    }
    const result = await askForRealEvidence(page);
    const settings = result.request.view.mode.tileEvidence[0].settings;
    expect(settings).toMatchObject({ source: 'volcano_control', useUncorrected: raw,
      condition1: 'A', condition2: 'B', condition1Control: raw ? 'D' : 'C', condition2Control: raw ? 'C' : 'D' });
    const response = await tabRequest(page).post('/api/analysis/volcano/data', { data: settings });
    expect(response.ok(), await response.text()).toBeTruthy();
    const actual = await response.json();
    expect(actual.points.length).toBeGreaterThan(0);
    const tile = result.evidence.find(e => e.tool.endsWith('volcanoControl'));
    expect(tile.status).not.toBe('unavailable');
    expect(tile.text).toContain(`p_metric=${raw ? 'raw' : 'BH-adjusted'}`);
    expect(Number(tile.text.match(/\|log2FC=([^|\n]+)/)[1])).toBe(actual.points[0].log2FC);
    expect(Number(tile.text.match(/\|negLog10P=([^|\n]+)/)[1])).toBe(actual.points[0].negLog10P);
  }
  await canvas.getByRole('button', { name: 'Remove', exact: true }).click();
  const removed = await askForRealEvidence(page);
  expect(removed.request.view.mode.tileEvidence).toEqual([]);
  expect(removed.evidence.some(e => e.tool.includes('volcanoControl'))).toBe(false);
});

test('scientific assistant verifies typed canvas additions and stops', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.COPYLOT_BROWSER_ASSISTANT_STUB !== '1', 'Requires the local scripted provider.');
  await annotated(page);
  await tab(page, 'Analysis').click();
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  let calls = 0;
  page.on('request', request => { if (request.url().endsWith('/api/chat/assistant')) calls++; });
  const cases = [['proteinBoxplot', 'protein boxplot'], ['proteinLineplot', 'protein lineplot'],
    ['volcano', 'volcano'], ['volcanoControl', 'control volcano'], ['oraList', 'ORA']];
  let previous = [];
  for (const [index, [type, name]] of cases.entries()) {
    await page.getByPlaceholder('Ask about this analysis...').fill(`Add two ${name} tiles to this canvas.`);
    await tab(page, 'Send').click();
    if (!index) await tab(page, 'Confirm and send').click();
    await expect(page.getByText(/Added 2 .* tiles\. Existing plots were kept\./).last()).toBeVisible({ timeout: 45000 });
    await expect(page.locator(`[data-assistant-tile-type="${type}"]`)).toHaveCount(2);
    await expect(page.locator('[data-assistant-tile]')).toHaveCount((index + 1) * 2);
    const current = await page.locator('[data-assistant-tile]').evaluateAll(elements => elements.map(el => el.getAttribute('data-assistant-tile')));
    expect(previous.every(id => current.includes(id))).toBe(true);
    previous = current;
    expect(calls).toBe(index + 1);
  }
});

for (const remove of [false, true]) {
  test(`scientific assistant adds a canvas tile and ${remove ? 'removes it after approval' : 'preserves it after refusal'}`, { tag: '@ai' }, async ({ page }) => {
    test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; replies are scripted.');
    await annotated(page);
    await tab(page, 'Analysis').click();
    let calls = 0;
    // Image loading adds the export controls. Force it to overlap the final
    // planner turn so the assistant must wait for the complete canvas view.
    await page.route('**/api/plots/single-protein/*/boxplot.png*', async route => {
      await new Promise(resolve => setTimeout(resolve, 1200));
      await route.continue();
    });
    await page.route('**/api/chat/assistant', async route => {
      const { view } = route.request().postDataJSON();
      expect(view.controls.some(c => /Run ORA|Upload|Generate Annotation/.test(c.label))).toBe(false);
      const find = label => {
        const control = view.controls.find(c => c.label.endsWith(label));
        expect(control, view.controls.map(c => c.label).join('; ')).toBeTruthy();
        return control.id;
      };
      const actions = calls === 0 ? [{ type: 'set_control', target: find('New tile type'), value: 'proteinBoxplot' }]
        : calls === 1 ? [{ type: 'activate_control', target: find('+ Add Plot') }]
        : calls === 2 ? [{ type: 'set_control', target: find('Protein source'), value: 'manual' }]
        : calls === 3 ? [{ type: 'set_control', target: find('Protein or gene'), value: 'K1' }]
        : calls === 5 ? [{ type: 'activate_control', target: find('Remove') }] : [];
      if (calls === 4) await expect(page.getByRole('img', { name: 'analysis boxplot', exact: true })).toBeVisible();
      calls++;
      await route.fulfill({ json: { model: 'scripted', revision: 1, actions, evidence: [], answer: actions.length ? '' : 'Canvas updated.' } });
    });
    await tab(page, 'Open chatbot sidebar').click();
    await tab(page, 'Toggle AI settings').click();
    await page.getByLabel('Select chatbot provider').selectOption('openai');
    await page.getByPlaceholder('Ask about this analysis...').fill('Add a protein boxplot tile for K1.');
    await tab(page, 'Send').click();
    await tab(page, 'Confirm and send').click();
    await expect(page.getByText(/Canvas updated\./)).toBeVisible({ timeout: 45000 });
    await expect(page.locator('[data-assistant-tile]')).toHaveCount(1);
    await expect(page.getByRole('textbox', { name: 'Protein or gene', exact: true })).toHaveValue('K1');
    page.once('dialog', async dialog => { expect(dialog.message()).toContain('Remove this canvas tile'); if (remove) await dialog.accept(); else await dialog.dismiss(); });
    await page.getByPlaceholder('Ask about this analysis...').fill('Remove the boxplot tile.');
    await tab(page, 'Send').click();
    if (remove) await expect(page.locator('[data-assistant-tile]')).toHaveCount(0);
    else await expect(page.getByText(/Tile removal was declined/)).toBeVisible();
    await expect(page.locator('[data-assistant-tile]')).toHaveCount(remove ? 0 : 1);
  });
}

test('scientific assistant offers ambiguous feature candidates without selecting', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; replies are scripted.');
  await annotated(page);
  await tab(page, 'Single Protein').click();
  const selection = page.getByRole('combobox', { name: 'Protein / Site', exact: true });
  const initial = await selection.inputValue();
  let calls = 0;
  await page.route('**/api/chat/assistant', async route => {
    calls++;
    const { view } = route.request().postDataJSON();
    const control = view.controls.find(item => item.label === 'Protein / Site');
    await route.fulfill({ json: { model: 'scripted', revision: 1, evidence: [], answer: '',
      actions: [{ type: 'search_options', target: control.id, value: 'K' }] } });
  });
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await page.getByPlaceholder('Ask about this analysis...').fill('Show the site matching K.');
  await tab(page, 'Send').click();
  await tab(page, 'Confirm and send').click();
  await expect(page.getByText(/Which uploaded identifier do you mean/)).toBeVisible();
  await expect(page.getByText(/No feature was selected by this search/)).toBeVisible();
  await expect(selection).toHaveValue(initial);
  expect(calls).toBe(1);
});

for (const repeatSearch of [false, true]) {
test(`scientific assistant ${repeatSearch ? 'stops repeated searches without changing selection' : 'searches beyond the advertised entity options without selecting first'}`, { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; replies are scripted.');
  const table = [sites.split('\n')[0], ...Array.from({ length: 80 }, (_, i) =>
    [`SEQ${i}S`, `S${i}`, `P${i}`, `G${i}`, `K${i}`, ...samples.map((_, j) => 12 + i * .1 + j * .12)].join(','))].join('\n');
  await annotated(page, '3', { table });
  await tab(page, 'Single Protein').click();
  let calls = 0;
  let initial;
  await page.route('**/api/chat/assistant', async route => {
    const { view } = route.request().postDataJSON();
    const control = view.controls.find(c => c.label === 'Protein / Site');
    expect(control.optionCount).toBeGreaterThan(40);
    if (calls === 0) { initial = control.value; expect(control.options).not.toContain('K79'); }
    if (calls === 1) { expect(control.value).toBe(initial); expect(control.optionQuery).toBe('K79'); expect(control.options).toEqual(['K79']); expect(control.optionMatchCount).toBe(1); }
    if (calls === 2) expect(control.value).toBe('K79');
    const actions = calls === 0 || repeatSearch ? [{ type: 'search_options', target: control.id, value: 'K79' }]
      : calls === 1 ? [{ type: 'set_control', target: control.id, value: 'K79' }] : [];
    calls++;
    await route.fulfill({ json: { model: 'scripted', revision: 1, actions, evidence: [], answer: actions.length ? '' : 'Entity selected.' } });
  });
  await tab(page, 'Open chatbot sidebar').click();
  await tab(page, 'Toggle AI settings').click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await page.getByPlaceholder('Ask about this analysis...').fill('Find the last site and select it.');
  await tab(page, 'Send').click();
  await tab(page, 'Confirm and send').click();
  await expect(page.getByText(repeatSearch ? /choose an exact identifier or narrow the search/ : /Entity selected\./)).toBeVisible({ timeout: 45000 });
  await expect(page.getByRole('combobox', { name: 'Protein / Site', exact: true })).toHaveValue(repeatSearch ? initial : 'K79');
  expect(calls).toBe(repeatSearch ? 2 : 3);
});
}

for (const approved of [false, true]) {
  test(`scientific assistant ${approved ? 'applies approved' : 'preserves declined'} methodological changes`, { tag: '@ai' }, async ({ page }) => {
    test.skip(process.env.VITE_AI_ENABLED !== '1', 'Requires AI mode; provider answers are synthetic.');
    await annotated(page);
    await tab(page, 'Statistical Analysis').click();
    await expect(field(page, 'Test type')).toHaveValue('unpaired');
    const annotation = await (await tabRequest(page).get('/api/annotations/current/phospho')).json();
    let calls = 0;
    let confirmations = 0;
    page.on('dialog', async dialog => {
      confirmations++;
      expect(dialog.type()).toBe('confirm');
      expect(dialog.message()).toContain('Test type: "unpaired" → "unpaired_welch"');
      if (approved) await dialog.accept();
      else await dialog.dismiss();
    });
    await page.route('**/api/chat/assistant', async route => {
      const { view } = route.request().postDataJSON();
      const control = view.controls.find(c => c.label === 'Test type');
      expect(control?.permission).toBe('confirm');
      const actions = calls++ === 0 ? [{ type: 'set_control', target: control.id, value: 'unpaired_welch' }] : [];
      await route.fulfill({ json: { model: 'synthetic', answer: actions.length ? '' : 'Method updated.', actions, evidence: [], revision: 1 } });
    });
    await tab(page, 'Open chatbot sidebar').click();
    await tab(page, 'Toggle AI settings').click();
    await page.getByLabel('Select chatbot provider').selectOption('openai');
    await page.getByPlaceholder('Ask about this analysis...').fill('Use the Welch test.');
    await tab(page, 'Send').click();
    await tab(page, 'Confirm and send').click();
    await expect(page.getByText(approved ? /Method updated\./ : /Requested changes were declined\./)).toBeVisible();
    expect(confirmations).toBe(1);
    expect(calls).toBe(approved ? 2 : 1);
    await expect(field(page, 'Test type')).toHaveValue(approved ? 'unpaired_welch' : 'unpaired');
    expect(await (await tabRequest(page).get('/api/annotations/current/phospho')).json()).toEqual(annotation);
  });
}

test('static retention-time notebooks follow the rendered method and recover after failure', async ({ page }, testInfo) => {
  test.setTimeout(120000);
  await page.goto('/');
  await page.getByLabel('Dataset type', { exact: true }).selectOption('peptide');
  const csv = 'File.Name,Stripped.Sequence,Predicted.RT,RT\n' +
    Array.from({ length: 100 }, (_, i) => `run1,PEP${i},${10 + i / 3},${11 + i / 3 + Math.sin(i)}`).join('\n');
  await page.locator('input[type=file]').setInputFiles({
    name: 'retention.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/peptide-file'));
  await tab(page, 'Upload').last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await page.evaluate(() => sessionStorage.setItem('pcopylot.ui.peptide.level.v1', JSON.stringify({ rt: { bins: 20 } })));
  await tab(page, 'Peptide Level').click();
  await tab(page, 'RT Plot').click();
  const button = page.getByRole('button', { name: 'Export notebook', exact: true });
  const archives = [];
  for (const method of ['Hexbin Plot', 'Density Plot', 'Scatter Plot']) {
    await field(page, 'Mode').selectOption(method);
    await expect(button).toBeEnabled({ timeout: 60000 });
    const ready = page.waitForEvent('download');
    await button.click();
    const result = await ready;
    expect(result.suggestedFilename()).toBe('Peptide_Retention_Time.zip');
    archives.push(await readFile(await result.path()));
  }
  expect(archives[0].equals(archives[1])).toBe(false);
  expect(archives[1].equals(archives[2])).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('retention-notebook.png'), fullPage: true });
  await page.route('**/api/plots/peptide/rt.png*', route => route.fulfill({
    status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Test RT unavailable' }),
  }));
  await page.getByLabel('Add Line', { exact: true }).check();
  await expect(page.getByText('Test RT unavailable', { exact: false })).toBeVisible();
  await expect(button).toBeDisabled();
  await page.unroute('**/api/plots/peptide/rt.png*');
  await page.getByLabel('Add Line', { exact: true }).uncheck();
  await expect(button).toBeEnabled();
  await field(page, 'Type').selectOption('Interactive');
  await expect(button).toBeEnabled();
  await expect(page.getByRole('link', { name: 'Open Interactive Plot', exact: true })).toBeVisible();
  const interactiveReady = page.waitForEvent('download');
  await button.click();
  expect((await interactiveReady).suggestedFilename()).toBe('Interactive_Peptide_Retention_Time.zip');
  await expect(page.frameLocator('iframe[title="Retention Time Plot interactive"]').locator('.js-plotly-plot')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('interactive-retention-notebook.png'), fullPage: true });
  await page.route('**/api/plots/peptide/rt-interactive.html*', route => route.fulfill({
    status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Test interactive RT unavailable' }),
  }));
  await page.getByLabel('Add Line', { exact: true }).check();
  await expect(page.getByText('Test interactive RT unavailable', { exact: false })).toBeVisible();
  await expect(button).toBeDisabled();
  await page.unroute('**/api/plots/peptide/rt-interactive.html*');
  await page.getByLabel('Add Line', { exact: true }).uncheck();
  await expect(button).toBeEnabled();
});

test('peptide modification and missed-cleavage notebooks follow rendered settings and recover from failure', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Dataset type', { exact: true }).selectOption('peptide');
  const csv = 'File.Name,Modified.Sequence,Stripped.Sequence,Precursor.Quantity\n' +
    'r1,AC(UniMod:4)M(UniMod:35),AKPAK,10\nr1,(UniMod:1)PEPTIDE,PEPTIDE,0\n' +
    'r2,AC(UniMod:4)M(UniMod:35),AKPAK,20\nr2,(UniMod:1)PEPTIDE,PEPTIDE,30\n';
  await page.locator('input[type=file]').setInputFiles({
    name: 'modifications.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/peptide-file'));
  await tab(page, 'Upload').last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await tab(page, 'Annotation').click();
  await page.getByLabel('Dataset level', { exact: true }).selectOption('peptide');
  await page.getByLabel('Condition name', { exact: true }).fill('A');
  await page.getByLabel('Peptide file names', { exact: true }).selectOption(['r1', 'r2']);
  const annotation = page.waitForResponse(r => r.url().endsWith('/api/peptide/metadata/generate'));
  await tab(page, 'Generate Peptide Annotation').click();
  expect((await annotation).ok()).toBeTruthy();
  await tab(page, 'Peptide Level').click();
  await tab(page, 'Modification Plot').click();
  const button = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(button).toBeEnabled();
  const ready = page.waitForEvent('download');
  await button.click();
  const first = await ready;
  expect(first.suggestedFilename()).toBe('Peptide_Modifications.zip');
  const firstZip = await readFile(await first.path());
  await page.getByLabel('Toggle IDs', { exact: true }).check();
  await expect(button).toBeEnabled();
  const changed = page.waitForEvent('download');
  await button.click();
  expect((await readFile(await (await changed).path())).equals(firstZip)).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('modification-notebook.png'), fullPage: true });
  await page.route('**/api/plots/peptide/modification.png*', route => route.fulfill({ status: 400,
    contentType: 'application/json', body: JSON.stringify({ detail: 'Test modification unavailable' }) }));
  await page.getByLabel('Toggle IDs', { exact: true }).uncheck();
  await expect(page.getByText('Test modification unavailable', { exact: false })).toBeVisible();
  await expect(button).toBeDisabled();
  await page.unroute('**/api/plots/peptide/modification.png*');
  await page.getByLabel('Toggle IDs', { exact: true }).check();
  await expect(button).toBeEnabled();
  await tab(page, 'Missed Cleavage Plot').click();
  const cleavageZips = [];
  for (const protease of ['trypsin', 'trypsin_lysc']) {
    await field(page, 'Cleavage Rule').selectOption(protease);
    await expect(button).toBeEnabled();
    const ready = page.waitForEvent('download');
    await button.click();
    const result = await ready;
    expect(result.suggestedFilename()).toBe('Peptide_Missed_Cleavages.zip');
    cleavageZips.push(await readFile(await result.path()));
  }
  expect(cleavageZips[0].equals(cleavageZips[1])).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('missed-cleavage-notebook.png'), fullPage: true });
  await page.route('**/api/plots/peptide/missed-cleavage.png*', route => route.fulfill({ status: 400,
    contentType: 'application/json', body: JSON.stringify({ detail: 'Test cleavage unavailable' }) }));
  await page.getByLabel('Toggle Text', { exact: true }).uncheck();
  await expect(page.getByText('Test cleavage unavailable', { exact: false })).toBeVisible();
  await expect(button).toBeDisabled();
  await page.unroute('**/api/plots/peptide/missed-cleavage.png*');
  await page.getByLabel('Toggle Text', { exact: true }).check();
  await expect(button).toBeEnabled();
});

test('sequence coverage TXT and notebook share the captured result', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Dataset type', { exact: true }).selectOption('peptide');
  await page.locator('input[type=file]').setInputFiles({ name: 'sequence.csv', mimeType: 'text/csv',
    buffer: Buffer.from('File.Name,ProteinNames,Stripped.Sequence\nr1,P53_HUMAN,MEEPQSDPSV\nr1,P53_HUMAN,EPPLSQETF\nr1,P53_HUMAN,NOTAMATCH\n') });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/peptide-file'));
  await tab(page, 'Upload').last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await tab(page, 'Peptide Level').click();
  await tab(page, 'Sequence Coverage').click();
  const button = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(button).toBeEnabled();
  await expect(page.getByRole('link', { name: 'Download TXT', exact: true })).toBeVisible();
  const ready = page.waitForEvent('download');
  await button.click();
  const first = await ready;
  expect(first.suggestedFilename()).toBe('Peptide_Sequence_Coverage.zip');
  const bytes = await readFile(await first.path());
  await page.getByLabel('Chunk Size', { exact: true }).fill('30');
  await page.getByLabel('Chunk Size', { exact: true }).press('Tab');
  await expect(button).toBeEnabled();
  const changed = page.waitForEvent('download');
  await button.click();
  expect((await readFile(await (await changed).path())).equals(bytes)).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('sequence-notebook.png'), fullPage: true });
  await page.route('**/api/peptide/sequence-coverage*', route => route.fulfill({ status: 400,
    contentType: 'application/json', body: JSON.stringify({ detail: 'Test sequence unavailable' }) }));
  await page.getByLabel('Chunk Size', { exact: true }).fill('40');
  await page.getByLabel('Chunk Size', { exact: true }).press('Tab');
  await expect(page.getByText('Test sequence unavailable', { exact: false })).toBeVisible();
  await expect(button).toHaveCount(0);
  await page.unroute('**/api/peptide/sequence-coverage*');
  await page.getByLabel('Chunk Size', { exact: true }).fill('30');
  await page.getByLabel('Chunk Size', { exact: true }).press('Tab');
  await expect(button).toBeEnabled();
});

test('peptide upload offers peptide and precursor coverage and missing-value plots', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Dataset type', { exact: true }).selectOption('peptide');
  const csv = 'File.Name,Stripped.Sequence,Precursor.Id,Precursor.Quantity\n' +
    'r1,PEPA,PEPA_2,10\nr1,PEPA,PEPA_3,20\nr1,PEPB,PEPB_2,0\n' +
    'r2,PEPA,PEPA_2,0\nr2,PEPA,PEPA_3,30\nr2,PEPB,PEPB_2,5\n';
  await page.locator('input[type=file]').setInputFiles({
    name: 'synthetic-peptides.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/peptide-file'));
  await tab(page, 'Upload').last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await tab(page, 'Annotation').click();
  await page.getByLabel('Dataset level', { exact: true }).selectOption('peptide');
  await page.getByLabel('Condition name', { exact: true }).fill('A');
  await page.getByLabel('Peptide file names', { exact: true }).selectOption(['r1', 'r2']);
  const annotation = page.waitForResponse(r => r.url().endsWith('/api/peptide/metadata/generate'));
  await tab(page, 'Generate Peptide Annotation').click();
  expect((await annotation).ok()).toBeTruthy();

  for (const [section, path] of [['QC Pipeline', 'qc'], ['Completeness', 'completeness']]) {
    await tab(page, section).click();
    for (const level of ['peptide', 'precursor']) {
      await field(page, 'Dataset level').selectOption(level);
      const plot = page.locator('main img').first();
      await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', new RegExp(`/api/plots/${path}/${level}/`));
      await expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
      {
        const button = page.getByRole('button', { name: 'Export notebook', exact: true });
        await expect(button).toBeEnabled();
        const pending = page.waitForEvent('download');
        await button.click();
        expect((await pending).suggestedFilename()).toBe(`${level === 'peptide' ? 'Peptide' : 'Precursor'}_${section === 'QC Pipeline' ? 'Coverage' : 'Missing_Values'}.zip`);
      }
    }
  }
});

test('tool startup waits for logout before checking authentication', async ({ page }) => {
  await verifyAuthStartup(page, '/api/tool/auth');
  await expect(page.getByRole('navigation', { name: 'Module views' }).getByRole('button', { name: 'Upload', exact: true })).toBeVisible();
});

test('accessible workflow labels, modal focus and responsive navigation', async ({ page }, info) => {
  await annotated(page);
  await expect(page.getByLabel('Dataset level', { exact: true })).toHaveValue('phospho');
  await expect(page.getByLabel('Minimum valid values', { exact: true })).toHaveValue('3');
  await page.getByText('Minimum valid values', { exact: true }).click();
  await expect(page.getByLabel('Minimum valid values', { exact: true })).toBeFocused();
  await expect(page.getByText('Manual Condition Mapping', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Condition name', { exact: true })).not.toBeVisible();
  await page.screenshot({ path: info.outputPath('annotation-desktop.png'), fullPage: true });
  await tab(page, 'Statistical Analysis').click();
  await expect(page.getByLabel('Test type', { exact: true })).toBeVisible();
  const manual = tab(page, 'Manual');
  await manual.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const expectFullWindowManual = async () => {
    const viewport = page.viewportSize();
    await expect.poll(() => dialog.boundingBox()).toEqual({ x: 0, y: 0, width: viewport.width, height: viewport.height });
    expect(await dialog.evaluate(el => el.scrollHeight <= el.clientHeight)).toBe(true);
  };
  await expectFullWindowManual();
  await page.setViewportSize({ width: 390, height: 844 });
  await expectFullWindowManual();
  await page.setViewportSize({ width: 1280, height: 720 });
  await expectFullWindowManual();
  expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  await dialog.getByRole('button', { name: 'Close', exact: true }).focus();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('link', { name: 'Download', exact: true })).toBeFocused();
  await dialog.getByRole('button', { name: 'Close', exact: true }).focus();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(manual).toBeFocused();
  await page.getByRole('button', { name: 'Close sidebar', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Analysis modules' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Skip to analysis content' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  await page.screenshot({ path: info.outputPath('statistics-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator('main').evaluate(el => el.getBoundingClientRect().left)).toBeLessThan(20);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.screenshot({ path: info.outputPath('statistics-narrow.png'), fullPage: true });
});

test('HTML report preview and download preserve the generated document', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Summary').click();
  await tab(page, 'Report').click();
  const title = 'Report <check> & preserved';
  await page.getByLabel('Report Title', { exact: true }).fill(title);
  await page.getByLabel('Author', { exact: true }).fill('Author <safe>');
  const generated = page.waitForResponse(r => r.url().endsWith('/api/summary/report') && r.request().method() === 'POST', { timeout: 60000 });
  await tab(page, 'Generate HTML Report').click();
  const response = await generated;
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  const preview = page.locator('iframe[title="Summary Report"]');
  await expect(preview).toHaveAttribute('srcdoc', result.html);
  await expect(preview).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
  const frame = preview.contentFrame();
  await expect(frame.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(frame.getByRole('heading', { name: /PCA Plot$/ })).toBeVisible();
  await expect.poll(() => frame.locator('img').first().evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download HTML Report', exact: true }).click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toBe(result.fileName);
  expect(await readFile(await file.path(), 'utf8')).toBe(result.html);
});

for (const section of ['QC Pipeline', 'Completeness']) {
  test(`${section} retains linked numeric controls and plot updates`, async ({ page }) => {
    await annotated(page);
    await tab(page, section).click();
    const plot = page.locator('main img').first();
    const plotReady = () => expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(plot).toBeVisible();
    await plotReady();
    const width = page.getByLabel('Width (cm)', { exact: true });
    await page.getByText('Width (cm)', { exact: true }).click();
    await expect(width).toBeFocused();
    await width.fill('14,5');
    await width.press('Tab');
    await expect(width).toHaveValue('14.5');
    await plotReady();
    await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', /widthCm=14\.5(?:&|$)/);
    await width.fill('invalid');
    await width.press('Enter');
    await expect(width).toHaveValue('14.5');
    const dpi = page.getByLabel('DPI', { exact: true });
    await dpi.fill('10');
    await dpi.press('Tab');
    await expect(dpi).toHaveValue('72');
    await plotReady();
    await expect(page.getByLabel('Toggle Header', { exact: true })).toHaveCount(0);
    await page.getByLabel('Toggle Text', { exact: true }).check();
    await plotReady();
    await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', /text=true(?:&|$)/);
    await page.getByLabel('Toggle Text', { exact: true }).uncheck();
    await plotReady();
    await expect(page.getByLabel('Toggle Text', { exact: true })).not.toBeChecked();
    await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', /text=false(?:&|$)/);
    if (section === 'QC Pipeline') {
      await tab(page, 'Boxplot Intensity').click();
      await page.getByLabel('Type', { exact: true }).selectOption('Single');
      await expect(page.getByLabel('Type', { exact: true })).toHaveValue('Single');
      await plotReady();
    }
  });
}

test('volcano groups related controls and places dimensions below highlights', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  await field(page, 'Condition 2').selectOption('B');
  const type = page.getByLabel('Type', { exact: true });
  await type.selectOption('Normal');
  const bounds = async label => {
    const control = page.getByLabel(label, { exact: true });
    await expect(control).toBeVisible();
    return control.boundingBox();
  };
  const typeBox = await bounds('Type');
  const labelBox = await bounds('Label column');
  const testBox = await bounds('Test type');
  const pBox = await bounds('P-value threshold');
  const fcBox = await bounds('log2 FC threshold');
  expect(Math.abs(typeBox.y - labelBox.y)).toBeLessThan(2);
  expect(Math.abs(testBox.y - pBox.y)).toBeLessThan(2);
  expect(Math.abs(testBox.y - fcBox.y)).toBeLessThan(2);
  expect(testBox.y).toBeGreaterThan(typeBox.y + typeBox.height);
  const highlightBox = await bounds('Highlight terms');
  const widthBox = await bounds('Width (cm)');
  expect(widthBox.y).toBeGreaterThan(highlightBox.y + highlightBox.height);
  const image = page.getByRole('img', { name: 'Volcano Plot', exact: true });
  await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await page.screenshot({ path: info.outputPath('volcano-layout.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await type.selectOption('Interactive');
  await expect(page.getByLabel('Width (cm)', { exact: true })).toHaveCount(0);
});

test('shared plot controls preserve numeric editing, bounds, toggles and multiple selection', async ({ page }, info) => {
  await annotated(page);
  await expect(page.locator('#active-dataset-package')).toHaveCount(0);
  await expect(page.locator('#active-metadata-profile')).toHaveCount(0);
  await expect(page.getByText(/No normalization was applied/)).toHaveCount(0);
  await expect(page.getByText('Metadata Source', { exact: true })).toHaveCount(0);
  await tab(page, 'Single Protein').click();
  await expect(page.getByRole('table').getByRole('cell', { name: 'A', exact: true })).toBeVisible();
  let tableRequests = 0;
  const plotReady = () => expect.poll(() => page.getByRole('img', { name: 'Protein Boxplot', exact: true })
    .evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await plotReady();
  const sampleN = page.getByLabel('Toggle Sample n', { exact: true });
  await expect(sampleN).toBeChecked();
  await sampleN.uncheck();
  await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', /sampleN=false/);
  await plotReady();
  await tab(page, 'Analysis').click();
  await expect(page.getByRole('heading', { name: 'Analysis Pipeline', exact: true })).toHaveCount(0);
  await tab(page, 'Single Protein').click();
  await expect(sampleN).not.toBeChecked();
  await sampleN.check();
  await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', /sampleN=true/);
  await plotReady();
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/boxplot-table')) tableRequests++;
  });
  const width = page.getByLabel('Width (cm)', { exact: true });
  await expect(width).toBeVisible();
  await width.fill('12,5');
  await width.press('Tab');
  await expect(width).toHaveValue('12.5');
  await plotReady();
  await width.fill('invalid');
  await width.press('Tab');
  await expect(width).toHaveValue('12.5');
  const dpi = page.getByLabel('DPI', { exact: true });
  await dpi.fill('10');
  await dpi.press('Enter');
  await expect(dpi).toHaveValue('72');
  await plotReady();
  expect(tableRequests).toBe(0);
  const conditions = page.getByRole('listbox', { name: /^Conditions\b/ });
  await conditions.selectOption(['A', 'B']);
  await expect(conditions).toHaveValues(['A', 'B']);
  await conditions.selectOption(['B']);
  await expect(conditions).toHaveValues(['B']);
  await expect(page.getByRole('table').getByRole('cell', { name: 'B', exact: true })).toBeVisible();
  await expect(page.getByRole('table').getByRole('cell', { name: 'A', exact: true })).toHaveCount(0);
  await plotReady();
  const requestsBeforeDots = tableRequests;
  await expect(page.getByLabel('Toggle Legend', { exact: true })).toHaveCount(0);
  const dots = page.getByLabel('Toggle Dots', { exact: true });
  await dots.uncheck();
  await expect(dots).not.toBeChecked();
  await plotReady();
  await dots.check();
  await expect(dots).toBeChecked();
  await plotReady();
  expect(tableRequests).toBe(requestsBeforeDots);
  const plotDownload = page.getByRole('link', { name: 'Download Plot', exact: true });
  await expect.poll(async () => {
    const url = new URL(await plotDownload.getAttribute('href'), page.url());
    return JSON.parse(url.searchParams.get('conditions'));
  }).toEqual(['B']);
  const downloaded = page.waitForEvent('download');
  await plotDownload.click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe('single_protein_boxplot_phospho.png');
  await download.saveAs(info.outputPath('single-protein-export.png'));
  const bytes = await readFile(await download.path());
  expect(bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  expect(bytes.readUInt32BE(16)).toBe(Math.round(12.5 / 2.54 * 72));
  await expect(page.getByRole('table').getByRole('cell', { name: 'B', exact: true })).toBeVisible();
  await expect(page.getByRole('table').getByRole('cell', { name: 'A', exact: true })).toHaveCount(0);
});

for (const [panel, endpoint, setting, value, parameter] of [
  ['ANOVA', 'anova', 'P-value threshold', '0.01', 'pValueThreshold'],
  ['Replicate & Variance Projection', 'simulation', 'Variance × factor', '2', 'varianceMultiplier'],
  ['Replicate & Variance Projection', 'simulation', 'Replicates per group (0 = observed, 2-100 fixed)', '8', 'sampleSizeOverride'],
]) {
  test(`${panel} hides old results until the changed request completes: ${setting}`, async ({ page }) => {
    await annotated(page);
    await tab(page, 'Statistical Analysis').click();
    await tab(page, panel).click();
    if (panel === 'Replicate & Variance Projection') {
      await field(page, 'Condition 1').selectOption('A');
      await field(page, 'Condition 2').selectOption('B');
    }
    await expect(page.getByText('Rows', { exact: true })).toBeVisible();
    let pending;
    await page.route(`**/api/stats/${endpoint}/run`, async route => {
      if (route.request().postDataJSON()[parameter] === Number(value)) pending = route;
      else await route.continue();
    });
    await field(page, setting, 'input').fill(value);
    await field(page, setting, 'input').press('Tab');
    await expect.poll(() => Boolean(pending)).toBe(true);
    await expect(page.getByText('Rows', { exact: true })).toHaveCount(0);
    const response = await pending.fetch();
    expect(response.ok()).toBeTruthy();
    await pending.fulfill({ response });
    await expect(page.getByText('Rows', { exact: true })).toBeVisible();
  });
}

for (const change of ['settings', 'revision']) {
  test(`ORA cluster choices wait for matching ANOVA ${change}`, async ({ page }) => {
    await annotated(page, '3', { table: sites.replace(/,,/g, ',12,') });
    const aggregate = await tabRequest(page).post('/api/annotations/phosprot/aggregate', {
      data: { mode: 'mean', source: 'non_imputed' },
    });
    expect(aggregate.ok()).toBeTruthy();
    await tab(page, 'Statistical Analysis').click();
    await tab(page, 'GO Enrichment (ORA)').click();
    await field(page, 'Analysis source').selectOption('anova');
    const clusters = page.getByRole('combobox', { name: 'Protein cluster', exact: true });
    await expect.poll(() => clusters.locator('option').count()).toBeGreaterThan(1);
    let pending;
    await page.route('**/api/stats/anova/run', route => { pending = route; });
    if (change === 'settings') {
      await field(page, 'Clusters', 'input').fill('3');
      await field(page, 'Clusters', 'input').press('Tab');
    } else {
      await page.evaluate(async () => {
        const { updateAnnotationPairing } = await import('/src/lib/api.ts');
        await updateAnnotationPairing({ kind: 'phospho', condition1: 'A', condition2: 'B',
          pairs: [1, 2, 3, 4].map(i => ({ condition1Sample: `A${i}`, condition2Sample: `B${i}` })) });
      });
    }
    await expect(clusters.locator('option')).toHaveCount(1);
    await expect.poll(() => Boolean(pending)).toBe(true);
    const response = await pending.fetch();
    expect(response.ok()).toBeTruthy();
    await pending.fulfill({ response });
    await expect.poll(() => clusters.locator('option').count()).toBeGreaterThan(1);
  });
}

for (const consumer of ['volcano', 'ksea', 'ora', 'analysis']) {
  test(`saved valid-to-valid pairing refreshes ${consumer} results`, async ({ page }) => {
    await annotated(page);
    if (consumer === 'ora') {
      const aggregate = await tabRequest(page).post('/api/annotations/phosprot/aggregate', {
        data: { mode: 'mean', source: 'non_imputed' },
      });
      expect(aggregate.ok()).toBeTruthy();
    }
    let calls = 0;
    let hold = false;
    let pending;
    const endpoint = consumer === 'ksea' ? '**/api/plots/phospho/ksea-table?*'
      : consumer === 'ora' ? '**/api/stats/ora/run'
      : consumer === 'analysis' ? '**/api/analysis/volcano/data' : '**/api/stats/volcano/run';
    await page.route(endpoint, async route => {
      calls++;
      if (hold) pending = route;
      else if (consumer === 'ksea') await route.fulfill({ json: { rows: [{ comparison: 'before' }] } });
      else await route.continue();
    });
    await tab(page, consumer === 'ksea' ? 'Phospho-specific'
      : consumer === 'analysis' ? 'Analysis' : 'Statistical Analysis').click();
    if (consumer === 'ksea') await tab(page, 'Kinase Library').click();
    if (consumer === 'ora') await tab(page, 'GO Enrichment (ORA)').click();
    if (consumer === 'analysis') await tab(page, '+ Add Plot').click();
    await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
    await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
    await page.getByRole('combobox', { name: consumer === 'ksea' ? 'Test Type' : 'Test type', exact: true }).selectOption('paired');
    const output = consumer === 'ksea'
      ? page.getByRole('link', { name: 'Download Kinase Library Table (TSV)' })
      : consumer === 'ora' ? page.getByRole('heading', { name: 'Downregulated Genes', exact: true })
      : consumer === 'analysis' ? page.getByText(/^Total rows:/)
      : page.getByText('Result Table', { exact: true });
    await expect(output).toBeVisible();
    const before = calls;
    await page.getByLabel('Sample paired with A1', { exact: true }).selectOption('');
    await page.getByLabel('Sample paired with A2', { exact: true }).selectOption('B1');
    await page.getByLabel('Sample paired with A1', { exact: true }).selectOption('B2');
    hold = true;
    const saved = page.waitForResponse(r => r.url().endsWith('/api/annotations/pairing'));
    await page.getByRole('button', { name: 'Save pairing', exact: true }).click();
    expect((await saved).ok()).toBeTruthy();
    await expect.poll(() => calls).toBeGreaterThan(before);
    await expect(output).toHaveCount(0);
    await expect.poll(() => Boolean(pending)).toBe(true);
    if (consumer === 'ksea') await pending.fulfill({ json: { rows: [{ comparison: 'after' }] } });
    else await pending.fulfill({ response: await pending.fetch() });
    await expect(output).toBeVisible();
  });
}

test('KSEA Data produces a real export with full sequence context', async ({ page }, testInfo) => {
  const validSites = sites.replace(/SEQ\d+S/g, 'AAAAAAAs*AAAAAAA');
  await annotated(page, '3', { table: validSites });
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  const download = page.getByRole('link', { name: 'Download Kinase Library Table (TSV)' });
  await expect(page.getByRole('combobox', { name: 'Data Source', exact: true })).toHaveValue('filtered');
  await expect(download).toBeVisible();
  const href = await download.getAttribute('href');
  const exported = decodeURIComponent(href.split(',').slice(1).join(','));
  expect(exported).toContain('UPD_seq');
  expect(exported).toContain('AAAAAAASAAAAAAA');
  expect(exported.trim().split('\n')).toHaveLength(25);
  const notebook = page.getByRole('button', { name: 'Export notebook', exact: true });
  await expect(notebook).toHaveCount(1);
  await expect(notebook).toBeEnabled();
  const ready = page.waitForEvent('download');
  await notebook.click();
  const archive = await ready;
  expect(archive.suggestedFilename()).toBe('Kinase_Library_Input_Table.zip');
  expect((await readFile(await archive.path())).subarray(0, 2).toString()).toBe('PK');
  await page.screenshot({ path: testInfo.outputPath('ksea-table-notebook.png'), fullPage: true });
  await tab(page, 'Data').click();
  await tab(page, 'Imputation').click();
  await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  const imputedResponse = page.waitForResponse(r => r.url().includes('/api/plots/phospho/ksea-table?') &&
    new URL(r.url()).searchParams.get('dataSource') === 'imputed');
  await page.getByRole('combobox', { name: 'Data Source', exact: true }).selectOption('imputed');
  expect((await imputedResponse).ok()).toBeTruthy();
  await expect(download).toBeVisible();
  await tab(page, 'Data').click();
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  await expect(page.getByRole('combobox', { name: 'Data Source', exact: true })).toHaveValue('imputed');
  await expect(download).toBeVisible();
});

test('KSEA refuses incomplete data-source options instead of selecting unfiltered data', async ({ page }) => {
  await annotated(page);
  await page.route('**/api/plots/phospho/options', async route => {
    const response = await route.fetch();
    const body = await response.json();
    delete body.availableDataSources;
    delete body.defaultDataSource;
    await route.fulfill({ response, json: body });
  });
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  await expect(page.getByText('Invalid phospho data-source options. Reload the app and try again.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download Kinase Library Table (TSV)' })).toHaveCount(0);
});

test('KSEA export stays bound to the completed selection during debounce and loading', async ({ page }) => {
  await annotated(page);
  let pending;
  await page.route('**/api/plots/phospho/ksea-table?*', async route => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('condition1') === 'B') {
      pending = route;
    } else {
      await route.fulfill({ json: { rows: [{ comparison: 'A_vs_B', value: 1 }] } });
    }
  });
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  const link = page.getByRole('link', { name: 'Download Kinase Library Table (TSV)' });
  await expect(link).toHaveAttribute('download', 'KinaseLibrary_A_vs_B.tsv');
  await expect(link).toHaveAttribute('href', /A_vs_B/);
  await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('B');
  await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('A');
  await expect(link).toHaveCount(0);
  await expect.poll(() => Boolean(pending)).toBe(true);
  await expect(link).toHaveCount(0);
  await pending.fulfill({ json: { rows: [{ comparison: 'B_vs_A', value: 2 }] } });
  await expect(link).toHaveAttribute('download', 'KinaseLibrary_B_vs_A.tsv');
  const downloadEvent = page.waitForEvent('download');
  await link.click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('KinaseLibrary_B_vs_A.tsv');
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const contents = Buffer.concat(chunks).toString('utf8');
  expect(contents).toContain('B_vs_A');
  expect(contents).not.toContain('A_vs_B');
});

test('uploaded hostile kinase labels stay inert and interactive plots cannot access the app', async ({ page }) => {
  const attack = "</script><script>window.injected=1</script><img src=x onerror='window.injected=2'>";
  const table = `Kinase,Log2(Frequency Factor),Adjusted p-value\n${attack},2,0.01\nAKT1,-2,0.02\n`;
  const rawTable = `Gene Name,Frequency Factor,Adjusted p value\n${attack},4,0.01\nAKT1,0.25,0.02\n`;
  await annotated(page);
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'Kinase Library').click();
  await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  for (const label of ['Serine/Threonine Result File', 'Tyrosine/Non-canonical Result File']) {
    await page.getByLabel(label).setInputFiles({ name: 'synthetic.csv', mimeType: 'text/csv',
      buffer: Buffer.from(label === 'Serine/Threonine Result File' ? table : rawTable) });
  }
  await page.getByLabel('Annotate Hits', { exact: true }).check();
  const rendered = page.waitForResponse(r => r.url().endsWith('/api/plots/phospho/ksea-volcano.html'));
  await tab(page, 'Generate Kinase Library Volcano').click();
  const response = await rendered;
  expect(response.ok(), await response.text()).toBeTruthy();
  expect(response.headers()['content-security-policy']).toContain('sandbox allow-scripts allow-downloads');
  expect(response.headers()['x-copylot-evidence']).toMatch(/^[A-Za-z0-9_-]+$/);
  expect(response.headers()['content-security-policy']).toContain("connect-src 'none'");
  const iframe = page.locator('iframe[title="Kinase Library Volcano"]');
  await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
  const frame = iframe.contentFrame();
  await expect(frame.locator('.main-svg').first()).toBeVisible();
  const plot = frame.locator('.js-plotly-plot');
  expect(await plot.evaluate(element => element.calcdata.flatMap((trace, index) =>
    element._fullData[index].mode === 'markers' ? trace.map(point => point.x) : [])
    .sort((a, b) => a - b))).toEqual([-2, -2, 2, 2]);
  const result = await plot.evaluate(async (element) => {
    window.Plotly.Fx.hover(element, [{ curveNumber: 0, pointNumber: 0 }]);
    await window.Plotly.relayout(element, { 'xaxis.range': [-5, 5] });
    let parentBlocked = false;
    let storageBlocked = false;
    try { void parent.document.body; } catch { parentBlocked = true; }
    try { void localStorage.length; } catch { storageBlocked = true; }
    return { parentBlocked, storageBlocked, injected: window.injected ?? null,
      range: element.layout.xaxis.range, points: element.calcdata.reduce((n, trace, index) =>
        n + (element._fullData[index].mode === 'markers' ? trace.length : 0), 0) };
  });
  expect(result).toEqual({ parentBlocked: true, storageBlocked: true, injected: null, range: [-5, 5], points: 4 });
  await expect(frame.locator('[onerror], img[src=x]')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected ?? null)).toBeNull();
  const download = page.waitForEvent('download');
  await plot.evaluate(element => window.Plotly.downloadImage(element, { format: 'svg', filename: 'security-regression' }));
  expect((await download).suggestedFilename()).toBe('security-regression.svg');
});

test('real browser file stream abort preserves previous bytes and success replaces them', async ({ page, browserName, baseURL }) => {
  test.skip(browserName === 'webkit' && process.platform === 'win32',
    'Windows Playwright WebKit OPFS returns empty files even for raw writes; real download/restore is tested separately.');
  // WebKit private contexts reject OPFS access; use a disposable persistent profile.
  const context = browserName === 'webkit' ? await webkit.launchPersistentContext('', { baseURL }) : null;
  try {
    if (context) page = await context.newPage();
    await page.goto('/');
    const result = await page.evaluate(async () => {
      const { saveRestoreStateBlob } = await import('/src/lib/saveStateFile.ts');
      const root = await navigator.storage.getDirectory();
      const handle = await root.getFileHandle('save-regression.copylotstate', { create: true });
      try {
        await saveRestoreStateBlob({ blob: new Blob(['previous']), existingHandle: handle });
        const interruptedHandle = {
          name: handle.name,
          async createWritable() {
            const stream = await handle.createWritable();
            return {
              async write(blob) { await stream.write(blob); throw new Error('Injected write failure'); },
              close: () => stream.close(),
              abort: () => stream.abort(),
            };
          },
        };
        let error;
        try {
          await saveRestoreStateBlob({ blob: new Blob(['incomplete']), existingHandle: interruptedHandle });
        } catch (failure) { error = failure.message; }
        const afterFailure = await (await handle.getFile()).text();
        await saveRestoreStateBlob({ blob: new Blob(['replacement']), existingHandle: handle });
        return { error, afterFailure, afterSuccess: await (await handle.getFile()).text() };
      } finally {
        await root.removeEntry('save-regression.copylotstate');
      }
    });
    expect(result).toEqual({ error: 'Injected write failure', afterFailure: 'previous', afterSuccess: 'replacement' });
  } finally { await context?.close(); }
});

test('cancelled native save and open dialogs never report success or clear unsaved state', async ({ page }) => {
  await page.addInitScript(() => {
    window.showSaveFilePicker = async () => { throw new DOMException('Cancelled', 'AbortError'); };
    window.showOpenFilePicker = async () => { throw new DOMException('Cancelled', 'AbortError'); };
  });
  await annotated(page);
  const before = await (await tabRequest(page).get('/api/annotations/current/phospho')).json();
  await tab(page, 'Restore').click();
  for (const name of ['Save State...', 'Save State As...', 'Save Portable State...']) {
    await tab(page, name).click();
    await expect(tab(page, name)).toBeEnabled();
    await expect(page.getByText(/Save state written|Portable save state written|Current save target:/)).toHaveCount(0);
  }
  await tab(page, 'Open Save File...').click();
  await expect(tab(page, 'Open Save File...')).toBeEnabled();
  await expect(tab(page, 'Restore').last()).toBeDisabled();
  expect(await (await tabRequest(page).get('/api/annotations/current/phospho')).json()).toEqual(before);
  const leaving = page.waitForEvent('dialog');
  await page.close({ runBeforeUnload: true });
  const warning = await leaving;
  expect(warning.type()).toBe('beforeunload');
  await warning.dismiss();
  expect(page.isClosed()).toBe(false);
  await expect(tab(page, 'Save State...')).toBeVisible();
});

test('portable save restores through required replacement upload without changing numeric data', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'showSaveFilePicker', { value: undefined, configurable: true });
    Object.defineProperty(window, 'showOpenFilePicker', { value: undefined, configurable: true });
  });
  await annotated(page);
  const expected = await (await tabRequest(page).get('/api/annotations/current/phospho')).json();
  await tab(page, 'Restore').click();
  const downloaded = page.waitForEvent('download');
  page.once('dialog', dialog => dialog.accept());
  await tab(page, 'Save Portable State...').click();
  const download = await downloaded;
  const bytes = await readFile(await download.path());
  const payload = JSON.parse(gunzipSync(bytes).toString('utf8'));
  expect(payload.portable).toBe(true);
  for (const pkg of payload.backend.packages) {
    for (const dataset of Object.values(pkg.datasets).filter(Boolean)) expect(dataset.path).toBeNull();
  }
  await expect(page.getByText('Portable save state written without local dataset paths.', { exact: true })).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(field(page, 'Dataset type')).toBeVisible();
  await tab(page, 'Restore').click();
  await page.locator('input[type=file]').setInputFiles({ name: 'portable.copylotstate', mimeType: 'application/octet-stream', buffer: bytes });
  const missingResponse = page.waitForResponse(r => r.url().endsWith('/api/restore/import'));
  await tab(page, 'Restore').last().click();
  const missing = await missingResponse;
  expect(missing.status()).toBe(409);
  const missingBody = await missing.json();
  expect(missingBody.ok).toBe(false);
  expect(missingBody.missingFiles).toHaveLength(1);
  expect((await tabRequest(page).get('/api/annotations/current/phospho')).status()).toBe(404);
  await expect(tab(page, 'Restore').last()).toBeDisabled();
  const replacements = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Missing Files' }) });
  await replacements.locator('input[type=file]').setInputFiles({ name: 'synthetic-sites.csv', mimeType: 'text/csv', buffer: Buffer.from(sites) });
  const restored = await actionResponse(page, '/api/restore/import', () => tab(page, 'Restore').last().click());
  expect(restored.body.ok).toBe(true);
  await expect(page.getByText(/Restore complete\./)).toBeVisible();
  const actual = await (await tabRequest(page).get('/api/annotations/current/phospho')).json();
  delete actual.warnings;
  delete expected.warnings;
  expectRoundTrip(actual, expected);
});
async function actionResponse(page, path, action) {
  const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(path) && r.request().method() === 'POST');
  await action();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const request = response.request();
  const sent = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : undefined;
  return { body: await response.json(), sent };
}

async function annotated(page, minimum = '3', { fresh = true, table = sites, meta = metadata, kind = 'phospho', expectedRows } = {}) {
  if (fresh) await page.goto('/');
  await field(page, 'Dataset type').selectOption(kind);
  await page.locator('input[type=file]').setInputFiles({ name: 'synthetic-sites.csv', mimeType: 'text/csv', buffer: Buffer.from(table) });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload') && r.request().method() === 'POST');
  await tab(page, 'Upload').last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await tab(page, 'Annotation').click();
  await field(page, 'Dataset level').selectOption(kind);
  await field(page, 'Metadata file', 'input').setInputFiles({ name: 'synthetic-meta.csv', mimeType: 'text/csv', buffer: Buffer.from(meta) });
  const metadataResponse = page.waitForResponse(r => r.url().endsWith('/api/annotations/metadata/upload') && r.request().method() === 'POST');
  await tab(page, 'Upload Metadata').click();
  expect((await metadataResponse).ok()).toBeTruthy();
  await page.getByLabel('Dataset is already log2 transformed').check();
  await field(page, 'Minimum valid values', 'input').fill(minimum);
  await field(page, 'Normalization').selectOption('none');
  const result = await actionResponse(page, '/api/annotations/generate', () => tab(page, 'Generate Annotation').click());
  expect(result.sent.kind).toBe(kind);
  expect(result.sent.filter.minPresent).toBe(Number(minimum));
  expect(result.sent.isLog2Transformed).toBe(true);
  expect(result.body.filteredRows).toBe(expectedRows ?? (minimum === '3' ? table.trim().split('\n').length - 1 : minimum === '4' ? 22 : 0));
  return result;
}

for (const source of ['non_imputed', 'imputed']) {
  test(`phosphosite upload to collapse and statistics: ${source}`, async ({ page }) => {
    await annotated(page);
    if (source === 'imputed') {
      await tab(page, 'Imputation').click();
      await expect(field(page, 'Dataset level')).toHaveValue('phospho');
      const result = await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
      expect(result.sent.kind).toBe('phospho');
      expect(result.sent.sampleWise).toBe(true);
      await expect(page.getByLabel('Sample-wise imputation')).toBeChecked();
      await tab(page, 'Annotation').click();
    }
    await field(page, 'Source data').selectOption(source);
    const aggregate = await actionResponse(page, '/api/annotations/phosprot/aggregate', () => tab(page, 'Aggregate to Phosphoprotein').click());
    expect(aggregate.sent).toMatchObject({ source, mode: 'robust_site_median' });
    // Download the actual result: the imputed path must preserve a value at A1
    // without inflating its original observation count.
    const csv = await tabRequest(page).get('/api/annotations/current/phosprot/source/download');
    expect(csv.ok()).toBeTruthy();
    const lines = (await csv.text()).trim().split(/\r?\n/).map(line => line.split(','));
    const headers = lines[0];
    const row = lines.slice(1).find(values => values[headers.indexOf('Phosphoprotein')] === 'P0');
    expect(row).toBeTruthy();
    expect(Number(row[headers.indexOf('site_observed__A1')])).toBe(0);
    expect(row[headers.indexOf('A1')] === '').toBe(source === 'non_imputed');
    await tab(page, 'Imputation').click();
    await expect(field(page, 'Dataset level').locator('option[value=phosprot]')).toHaveCount(0);
    await expect(page.getByText('Phosphoproteins cannot be imputed directly.', { exact: false })).toBeVisible();
    const statsResponse = page.waitForResponse(r => {
      if (!r.url().endsWith('/api/stats/volcano/run')) return false;
      const payload = r.request().postDataJSON();
      return payload?.kind === 'phosprot' && payload.testType === 'unpaired_welch';
    });
    await tab(page, 'Statistical Analysis').click();
    await field(page, 'Dataset level').selectOption('phosprot');
    await field(page, 'Condition 1').selectOption('A');
    await field(page, 'Condition 2').selectOption('B');
    await field(page, 'Test type').selectOption('unpaired_welch');
    const response = await statsResponse;
    expect(response.ok(), await response.text()).toBeTruthy();
    expect((await response.json()).totalRows).toBe(12);
    expect(response.request().postDataJSON()).toMatchObject({ condition1: 'A', condition2: 'B', dataSource: 'filtered' });
    await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  });
}

test('empty filtering preserves a selected source and requires an explicit unfiltered choice', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Statistical Analysis').click();
  const source = page.getByRole('combobox', { name: 'Data Source', exact: true });
  await expect(source).toHaveValue('filtered');
  await field(page, 'Condition 1').selectOption('A');
  await field(page, 'Condition 2').selectOption('B');
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  await tab(page, 'Data').click();
  await tab(page, 'Annotation').click();
  // The page reloads the stored annotation, and its settings, when the dataset
  // snapshot arrives; typing before that settles was overwritten by it.
  await page.waitForLoadState('networkidle');
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  await field(page, 'Minimum valid values', 'input').fill('5');
  const annotation = await actionResponse(page, '/api/annotations/generate', () => tab(page, 'Generate Annotation').click());
  expect(annotation.sent.filter.minPresent).toBe(5);
  expect(annotation.body.filteredRows).toBe(0);
  const requests = [];
  page.on('request', request => {
    if (request.url().endsWith('/api/stats/volcano/run')) requests.push(request.postDataJSON());
  });
  await tab(page, 'Statistical Analysis').click();
  await expect(source).toHaveValue('filtered');
  await expect(page.getByText(/No features passed the selected filter/)).toBeVisible();
  await expect(page.getByText('Result Table', { exact: true })).toHaveCount(0);
  expect(requests.length).toBeGreaterThan(0);
  expect(requests.every(request => request.dataSource === 'filtered')).toBe(true);
  await source.selectOption('data');
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  expect(requests.at(-1).dataSource).toBe('data');
});

test('empty filtering stays empty and aggregation displays the API rejection', async ({ page }) => {
  await annotated(page, '5');
  const pending = page.waitForResponse(r => r.url().endsWith('/api/annotations/phosprot/aggregate') && r.request().method() === 'POST');
  await tab(page, 'Aggregate to Phosphoprotein').click();
  expect((await pending).status()).toBe(400);
  await expect(page.getByText(/No features passed/)).toBeVisible();
});

test('cancelled leave preserves analysis; confirmed reload starts a new one', async ({ page }) => {
  await annotated(page);
  const dialogEvent = page.waitForEvent('dialog');
  await page.close({ runBeforeUnload: true });
  const dialog = await dialogEvent;
  expect(dialog.type()).toBe('beforeunload');
  await dialog.dismiss();
  expect(page.isClosed()).toBe(false);
  await expect(tab(page, 'Generate Annotation')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(field(page, 'Dataset type')).toBeVisible();
  await tab(page, 'Annotation').click();
  await expect(field(page, 'Dataset level')).toBeDisabled();
});

async function analysisSnapshot(page) {
  const snapshot = {};
  // Read-only export also exposes the full stored imputed matrix and collapse
  // provenance, which the annotation-preview endpoint does not return.
  const exported = await tabRequest(page).post('/api/restore/export', { data: { uiState: {} } });
  expect(exported.ok()).toBeTruthy();
  const state = JSON.parse(gunzipSync(await exported.body()).toString('utf8'));
  snapshot.storedAnnotations = state.backend.packages.flatMap(pkg => pkg.annotations.map(annotation => ({
    kind: annotation.kind, imputedFrame: annotation.imputedFrame,
    phosprotAggregation: annotation.phosprotAggregation,
  })));
  for (const kind of ['phospho', 'phosprot']) {
    const annotation = await tabRequest(page).get(`/api/annotations/current/${kind}`);
    expect(annotation.ok()).toBeTruthy();
    snapshot[kind] = await annotation.json();
    // Restore recomputes annotation notices (e.g. "using uploaded metadata")
    // instead of persisting the last operation's prose. Compare analysis state.
    delete snapshot[kind].warnings;
    const csv = await tabRequest(page).get(`/api/annotations/current/${kind}/filtered/download`);
    expect(csv.ok()).toBeTruthy();
    // This synthetic fixture has no quoted delimiters. Keep headers, identities
    // and empty cells exact; parse numeric cells for round-trip tolerance.
    snapshot[`${kind}Csv`] = (await csv.text()).trim().split(/\r?\n/).map(line =>
      line.split(',').map(cell => cell !== '' && Number.isFinite(Number(cell)) ? Number(cell) : cell));
  }
  return snapshot;
}

function expectRoundTrip(actual, expected) {
  if (typeof expected === 'number') {
    expect(typeof actual).toBe('number');
    expect(Math.abs(actual - expected)).toBeLessThanOrEqual(1e-12 + 1e-12 * Math.abs(expected));
  } else if (expected !== null && typeof expected === 'object') {
    expect(actual).not.toBeNull();
    expect(Array.isArray(actual)).toBe(Array.isArray(expected));
    expect(Object.keys(actual).sort()).toEqual(Object.keys(expected).sort());
    for (const key of Object.keys(expected)) expectRoundTrip(actual[key], expected[key]);
  } else {
    expect(actual).toEqual(expected);
  }
}

const alternateMetadata = metadata.replace(/,A,/g, ',X,').replace(/,B,/g, ',Y,');

async function showManager(page, name) {
  const show = tab(page, `Show ${name} Manager`);
  if (await show.count()) await show.click();
}

async function verifyScopeStatistics(page, first, second, rows) {
  const pending = page.waitForResponse(r => {
    if (!r.url().endsWith('/api/stats/volcano/run')) return false;
    const p = r.request().postDataJSON();
    return p?.condition1 === second && p.condition2 === first && p.testType === 'unpaired_welch';
  });
  await tab(page, 'Statistical Analysis').click();
  await expect(field(page, 'Dataset level')).toHaveValue('phospho');
  await expect(field(page, 'Condition 1').locator('option')).toHaveText([first, second]);
  await field(page, 'Condition 1').selectOption(second);
  await field(page, 'Condition 2').selectOption(first);
  await field(page, 'Test type').selectOption('unpaired_welch');
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  expect(result.totalRows).toBe(rows);
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  await tab(page, 'Data').click();
  return result;
}

async function holdNextResponse(page, path) {
  let release;
  let captured;
  const gate = new Promise(resolve => { release = resolve; });
  const ready = new Promise(resolve => { captured = resolve; });
  let held = false;
  await page.route(`**${path}`, async route => {
    if (held) return route.continue();
    const response = await route.fetch(); // Real old-scope response, unchanged.
    const payload = await response.json();
    // A background request from the current profile may arrive first. Hold
    // only the distinguishable old-profile response this scenario targets.
    if (held || payload.filter?.minPresent !== 3) return route.fulfill({ response });
    held = true;
    captured(payload);
    await gate;
    await route.fulfill({ response });
  });
  return { ready, async release() {
    const received = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(path));
    release();
    await received;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.unroute(`**${path}`);
  } };
}

test('package switching keeps same-filename datasets and statistics separate', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Upload').click();
  await showManager(page, 'Dataset');
  const originalPackage = await field(page, 'Selected dataset').inputValue();
  await field(page, 'New dataset', 'input').fill('Second');
  await actionResponse(page, '/api/datasets/packages/create', () => tab(page, 'Create').click());
  // Deliberately reuse filenames: scope cannot be inferred from filename alone.
  await annotated(page, '4', { fresh: false, meta: alternateMetadata,
    table: sites.replace(/SEQ/g, 'ALTSEQ').replace(/,K(\d+)/g, ',ALT$1') });
  const second = await verifyScopeStatistics(page, 'X', 'Y', 22);
  expect(second.rows.every(row => String(row.PTM_Collapse_key).startsWith('ALT'))).toBe(true);
  await tab(page, 'Upload').click();
  await showManager(page, 'Dataset');
  await field(page, 'Selected dataset').selectOption(originalPackage);
  await tab(page, 'Annotation').click();
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  const first = await verifyScopeStatistics(page, 'A', 'B', 24);
  expect(first.rows.every(row => String(row.PTM_Collapse_key).startsWith('K'))).toBe(true);
  await tab(page, 'Upload').click();
  await showManager(page, 'Dataset');
  await field(page, 'Selected dataset').selectOption('Second');
  await tab(page, 'Annotation').click();
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  const delayed = await holdNextResponse(page, '/api/annotations/current/phospho');
  try {
    await tab(page, 'Upload').click();
    await showManager(page, 'Dataset');
    await field(page, 'Selected dataset').selectOption(originalPackage);
    await tab(page, 'Annotation').click();
    expect((await delayed.ready).filter.minPresent).toBe(3);
    await tab(page, 'Upload').click();
    await showManager(page, 'Dataset');
    await field(page, 'Selected dataset').selectOption('Second');
    await tab(page, 'Annotation').click();
    await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  } finally {
    await delayed.release();
  }
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  await verifyScopeStatistics(page, 'X', 'Y', 22);
});

test('metadata switching ignores a delayed previous-profile annotation', async ({ page }) => {
  await annotated(page);
  await showManager(page, 'Annotation');
  const originalProfile = await field(page, 'Selected metadata').inputValue();
  await field(page, 'New metadata profile', 'input').fill('Alternative');
  await actionResponse(page, '/api/datasets/metadata/profiles/create', () => tab(page, 'Create').click());
  await expect(field(page, 'Selected metadata')).toHaveValue('Alternative');
  await expect(field(page, 'Selected metadata')).toBeEnabled();
  await field(page, 'Metadata file', 'input').setInputFiles({ name: 'alternate.csv', mimeType: 'text/csv', buffer: Buffer.from(alternateMetadata) });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/annotations/metadata/upload') && r.request().method() === 'POST');
  await tab(page, 'Upload Metadata').click();
  expect((await uploaded).ok()).toBeTruthy();
  await field(page, 'Minimum valid values', 'input').fill('4');
  await actionResponse(page, '/api/annotations/generate', () => tab(page, 'Generate Annotation').click());
  const alternativeProfile = await field(page, 'Selected metadata').inputValue();
  expect(alternativeProfile).not.toBe(originalProfile);
  await verifyScopeStatistics(page, 'X', 'Y', 22);
  await tab(page, 'Annotation').click();
  await showManager(page, 'Annotation');
  const delayed = await holdNextResponse(page, '/api/annotations/current/phospho');
  try {
    await field(page, 'Selected metadata').selectOption(originalProfile);
    expect((await delayed.ready).filter.minPresent).toBe(3);
    // Switch again while the old annotation is still in flight.
    await field(page, 'Selected metadata').selectOption(alternativeProfile);
    await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  } finally {
    await delayed.release();
  }
  await expect(field(page, 'Selected metadata')).toHaveValue(alternativeProfile);
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  await verifyScopeStatistics(page, 'X', 'Y', 22);
  await tab(page, 'Annotation').click();
  await showManager(page, 'Annotation');
  await field(page, 'Selected metadata').selectOption(originalProfile);
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  await verifyScopeStatistics(page, 'A', 'B', 24);
});

test('save download and UI restore preserve analysis and settings; invalid restore is non-destructive', async ({ page }) => {
  // Exercise the supported browser download/upload path, not an OS picker stub.
  await page.addInitScript(() => {
    Object.defineProperty(window, 'showSaveFilePicker', { value: undefined, configurable: true });
    Object.defineProperty(window, 'showOpenFilePicker', { value: undefined, configurable: true });
  });
  await annotated(page);
  await tab(page, 'Imputation').click();
  await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
  await tab(page, 'Annotation').click();
  await field(page, 'Source data').selectOption('imputed');
  await field(page, 'Aggregation mode').selectOption('mean');
  await actionResponse(page, '/api/annotations/phosprot/aggregate', () => tab(page, 'Aggregate to Phosphoprotein').click());
  await tab(page, 'Statistical Analysis').click();
  await field(page, 'Dataset level').selectOption('phosprot');
  await field(page, 'Condition 1').selectOption('B');
  await field(page, 'Condition 2').selectOption('A');
  const matchesSettings = r => {
    if (!r.url().endsWith('/api/stats/volcano/run')) return false;
    const p = r.request().postDataJSON();
    return p?.kind === 'phosprot' && p.testType === 'unpaired_welch' && p.condition1 === 'B' && p.condition2 === 'A';
  };
  const originalStats = page.waitForResponse(matchesSettings);
  await field(page, 'Test type').selectOption('unpaired_welch');
  const originalResponse = await originalStats;
  expect(originalResponse.ok()).toBeTruthy();
  const expectedStats = await originalResponse.json();
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  const expected = await analysisSnapshot(page);
  await tab(page, 'Data').click();
  await tab(page, 'Restore').click();
  const downloaded = page.waitForEvent('download');
  const confirmation = page.waitForEvent('dialog');
  await tab(page, 'Save State As...').click();
  const dialog = await confirmation;
  expect(dialog.type()).toBe('confirm');
  expect(dialog.message()).toContain('finished downloading');
  await dialog.accept();
  const download = await downloaded;
  const bytes = await readFile(await download.path());
  await expect(page.getByText('Save state written to the selected file.', { exact: true })).toBeVisible();
  expect(bytes.length).toBeGreaterThan(100);

  // A fresh load must actually empty the backend before import is attempted.
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(field(page, 'Dataset type')).toBeVisible();
  expect((await tabRequest(page).get('/api/annotations/current/phosprot')).status()).toBe(404);
  await tab(page, 'Restore').click();
  await page.locator('input[type=file]').setInputFiles({ name: download.suggestedFilename(), mimeType: 'application/octet-stream', buffer: bytes });
  const imported = page.waitForResponse(r => r.url().endsWith('/api/restore/import'));
  await tab(page, 'Restore').last().click();
  const restore = await imported;
  expect(restore.ok(), await restore.text()).toBeTruthy();
  expect((await restore.json()).ok).toBe(true);
  await expect(page.getByText(/Restore complete\./)).toBeVisible();
  expectRoundTrip(await analysisSnapshot(page), expected);

  const restoredStats = page.waitForResponse(matchesSettings);
  await tab(page, 'Statistical Analysis').click();
  await expect(field(page, 'Dataset level')).toHaveValue('phosprot');
  await expect(field(page, 'Condition 1')).toHaveValue('B');
  await expect(field(page, 'Condition 2')).toHaveValue('A');
  await expect(field(page, 'Test type')).toHaveValue('unpaired_welch');
  expectRoundTrip(await (await restoredStats).json(), expectedStats);
  await tab(page, 'Data').click();
  await tab(page, 'Annotation').click();
  await field(page, 'Dataset level').selectOption('phospho');
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  await expect(field(page, 'Normalization')).toHaveValue('none');
  await expect(field(page, 'Source data').locator('option[value=imputed]')).toHaveCount(1);

  await tab(page, 'Restore').click();
  const beforeRejectedRestore = await analysisSnapshot(page);
  await page.locator('input[type=file]').setInputFiles({ name: 'broken.copylotstate', mimeType: 'application/octet-stream', buffer: Buffer.from('not a save state') });
  const rejected = page.waitForResponse(r => r.url().endsWith('/api/restore/import'));
  await tab(page, 'Restore').last().click();
  const rejection = await rejected;
  expect(rejection.status()).toBe(400);
  const error = await rejection.json();
  await expect(page.getByText(error.detail, { exact: true })).toBeVisible();
  expect(await analysisSnapshot(page)).toEqual(beforeRejectedRestore);
  await tab(page, 'Statistical Analysis').click();
  await expect(field(page, 'Test type')).toHaveValue('unpaired_welch');
  await expect(field(page, 'Condition 1')).toHaveValue('B');
});

test('one localization probability cutoff narrows every phosphosite view and the collapse', async ({ page }) => {
  // Numeric probabilities 0/24 .. 23/24, so a cutoff of 0.50 keeps sites K12..K23.
  const table = sites.split('\n').map((line, index) => {
    if (index === 0) return line;
    const cells = line.split(',');
    cells[1] = ((index - 1) / 24).toFixed(4);
    return cells.join(',');
  }).join('\n');
  await annotated(page, '3', { table });
  const overview = async () => (await (await tabRequest(page).get('/api/plots/phospho/phosphosite-plot-table')).json())
    .rows.find(row => row.Term === 'Phosphosites').Count;
  expect(await overview()).toBe(24);

  await tab(page, 'Phospho-specific').click();
  const cutoff = page.getByLabel('Localization probability cutoff', { exact: true });
  await expect(cutoff).toHaveValue('0.00');
  await expect(page.getByLabel('Cutoff', { exact: true })).toHaveCount(0);
  const plot = page.getByRole('img', { name: 'Phosphosite Plot', exact: true });
  await expect(plot).toBeVisible();
  const before = await plot.getAttribute('src');
  const saved = page.waitForResponse(r => r.url().endsWith('/api/data-tools/phospho-localization-cutoff') && r.request().method() === 'POST');
  // The figure on screen is redrawn, not only the data behind it.
  const redrawn = page.waitForResponse(r => r.url().includes('/api/plots/phospho/phosphosite-plot.png'));
  await cutoff.fill('0.5');
  await cutoff.press('Enter');
  expect((await saved).ok()).toBeTruthy();
  expect((await redrawn).ok()).toBeTruthy();
  await expect(cutoff).toHaveValue('0.50');
  await expect.poll(() => plot.getAttribute('src')).not.toBe(before);
  expect(await overview()).toBe(12);

  // The same value, not a copy, appears wherever phospho is the dataset level.
  await tab(page, 'QC Pipeline').click();
  const qcCutoff = page.getByLabel('Localization probability cutoff', { exact: true });
  await expect(qcCutoff).toHaveValue('0.50');
  const qcRedrawn = page.waitForResponse(r => r.url().includes('/api/plots/qc/phospho/coverage.png'));
  await qcCutoff.fill('0.25');
  await qcCutoff.press('Enter');
  expect((await qcRedrawn).ok()).toBeTruthy();
  expect(await overview()).toBe(18);
  await qcCutoff.fill('0.5');
  await qcCutoff.press('Enter');
  await expect.poll(overview).toBe(12);
  await tab(page, 'Statistical Analysis').click();
  await expect(page.getByLabel('Localization probability cutoff', { exact: true }).first()).toHaveValue('0.50');

  // The collapse starts from the shared value and records the one it used.
  await tab(page, 'Data').click();
  await tab(page, 'Annotation').click();
  await expect(page.getByLabel('Site localization probability cutoff', { exact: true })).toHaveValue('0.50');
  const aggregate = await actionResponse(page, '/api/annotations/phosprot/aggregate', () => tab(page, 'Aggregate to Phosphoprotein').click());
  expect(aggregate.sent.localizationCutoff).toBe(0.5);
});
