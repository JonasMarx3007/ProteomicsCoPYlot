import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// Code-shape rules that used to be regular expressions in Python tests. Each
// message says what went wrong the last time the shape appeared.
const SIZE_KEY = '/^(widthCm|heightCm|dpi)$/'
const SIZE_RULES = [
  {
    selector: `Property[key.name=${SIZE_KEY}] > CallExpression[callee.object.name='Math']`,
    message:
      'Plot sizes are clamped by SizeRow and lib/plotLimits.ts alone; a clamp here is a second set of limits (one page once refused a 3 cm figure the backend draws).',
  },
  {
    selector: `CallExpression[callee.name='Number'] MemberExpression[object.name=/^persisted/][property.name=${SIZE_KEY}]`,
    message:
      'Restore a saved size with restorePlotDimensionCm/restorePlotDpi: Number(null) is 0, a 0 cm figure.',
  },
  {
    selector: "JSXAttribute[name.name='label'][value.value=/^(Width \\(cm\\)|Height \\(cm\\)|DPI)$/]",
    message: 'Size a plot with SizeRow from components/PlotFields; a page-local copy once showed DPI before width.',
  },
  {
    selector: "FunctionDeclaration[id.name='SizeRow'], VariableDeclarator[id.name='SizeRow']",
    message: 'SizeRow lives in components/PlotFields.tsx alone; import it from there (or QcFields, which re-exports it).',
  },
]

// Code-shape rules that replaced regular expressions over the frontend source
// in the node --test files and the Python tests. Behaviour is tested in
// tests/unit and tests/component; these hold the shapes a test cannot see.
const GLOBAL_RULES = [
  {
    // tests/unit/plot-image-failure.test.tsx
    selector: "FunctionDeclaration[id.name='handleImageError'], VariableDeclarator[id.name='handleImageError']",
    message: 'Render a plot through components/PlotImage; every private image-error handler left a broken <img> above the explanation.',
  },
  {
    // tests/unit/plot-image-failure.test.tsx
    selector: "JSXOpeningElement[name.name='img'] > JSXAttribute[name.name='src'] Identifier[name=/^(plotView|url|heatmapUrl|plotUrl)$/]",
    message: 'A plot image is rendered by components/PlotImage, which replaces a refused figure with its explanation instead of a broken image.',
  },
  {
    // tests/unit/statisticalTests.test.ts
    selector: "ArrayExpression:has(Literal[value='unpaired']):has(Literal[value='paired']):not(:has(Literal[value='unpaired_welch']))",
    message: 'Offer statistical tests from lib/statisticalTests; a page-local ["unpaired", "paired"] once hid Welch\'s test.',
  },
  {
    // tests/unit/qc-dbscan-factor.test.tsx; the backend half is tests/unit/qc/test_dbscan_eps_is_relative.py
    selector: "Identifier[name=/^dbscan_?[eE]ps$/], Literal[value=/^dbscan_?[eE]ps$/]",
    message: 'DBSCAN takes dbscanEpsFactor, a fraction of the median sample distance; an absolute radius labelled every sample "Noise".',
  },
  {
    // tests/unit/provider-default-models.test.tsx
    selector: "Literal[value=/^(claude|gemini|gpt)-[0-9a-z.-]+$/]",
    message: 'The default cloud models come from the backend (/api/chat/provider-defaults); a browser copy pre-filled models that had been shut down.',
  },
]

const FRAME_RULES = [
  {
    // tests/unit/plot-frame-security.test.tsx
    selector: "JSXOpeningElement[name.name='iframe']:not(:has(JSXAttribute[name.name='sandbox'][value.value='allow-scripts allow-downloads']))",
    message: 'A frame showing generated plot HTML is sandboxed with exactly sandbox="allow-scripts allow-downloads" (never allow-same-origin).',
  },
]

const FIELD_RULES = {
  // tests/unit/field-accessibility.test.tsx: every field in the advanced panel
  // registers with the assistant, so none is a raw form element.
  advancedPanel: [{
    selector: "JSXOpeningElement[name.name=/^(input|select|textarea)$/]",
    message: 'Use AssistantInput/AssistantSelect/AssistantTextarea in the advanced panel, so the assistant can read and set the field.',
  }],
  stats: [{
    selector: "JSXOpeningElement[name.name='textarea']",
    message: 'Use AssistantTextarea in the statistics panels, so the assistant can read and set the field.',
  }],
  // Every label in src: it either points at its control (htmlFor) or wraps it.
  labels: [{
    selector: "JSXElement[openingElement.name.name='label']:not(:has(JSXAttribute[name.name='htmlFor'])):not(:has(JSXOpeningElement[name.name=/^(input|select|textarea|Assistant(Input|Select|Textarea)|NumberInput)$/]))",
    message: 'A label names its control by htmlFor or by wrapping it; a bare caption leaves the field unnamed to a screen reader.',
  }],
}

const ASSISTANT_RULES = [
  {
    // tests/unit/assistant-appearance-mount.test.tsx
    selector: "Identifier[name='setAdvancedPlotMode'], Literal[value='advanced_options']",
    message: "Advanced plot mode is the user's switch; the assistant styles a plot through the offscreen panel and never turns the mode on.",
  },
]

const CANVAS_RULES = [
  {
    // tests/unit/plot-control-visibility.test.tsx: the browser-drawn volcano tile
    // is typeset in one face on its <svg>, which is why it offers no font card.
    selector: "Identifier[name=/^(title|axisLabel|tick|legend|valueLabel)FontFamily$/]",
    message: 'The canvas volcano tile offers no font card (fontControls: false); reading a font key here needs that card back.',
  },
]

const NAVIGATION_RULES = [
  {
    // tests/unit/assistant-plot-catalogue.test.ts
    selector: "VariableDeclarator[id.name=/^(data|qc|completeness|stats|peptide|singleProtein|phospho|comparison|external|summary)Tabs$/] > ArrayExpression",
    message: "A section's tabs live in lib/navigationTabs.ts, where the assistant's plot catalogue is checked against them.",
  },
]

const restricted = (...lists) => ['error', ...lists.flat()]

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      'no-empty': ['error', { allowEmptyCatch: true }],
      'react-hooks/set-state-in-effect': 'warn',
      'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES),
    },
  },
  // Later blocks replace the rule for the files they name, so each repeats the
  // lists of the blocks before it that also apply to those files. Every label
  // in the application names its control (FIELD_RULES.labels).
  {
    files: ['src/**/*.tsx'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, FIELD_RULES.labels) },
  },
  {
    files: ['src/features/**/*.tsx', 'src/components/InteractivePlot.tsx'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, FIELD_RULES.labels, FRAME_RULES) },
  },
  {
    files: ['src/features/stats/*.tsx'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, FIELD_RULES.labels, FRAME_RULES, FIELD_RULES.stats) },
  },
  {
    files: ['src/components/plots/AdvancedPlotOptions.tsx'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, FIELD_RULES.labels, FIELD_RULES.advancedPanel) },
  },
  {
    files: ['src/features/analysis/AnalysisPage.tsx'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, FIELD_RULES.labels, FRAME_RULES, CANVAS_RULES) },
  },
  {
    files: ['src/App.tsx'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, FIELD_RULES.labels, NAVIGATION_RULES) },
  },
  {
    files: ['src/lib/runAssistant.ts', 'src/lib/assistantControls.ts'],
    rules: { 'no-restricted-syntax': restricted(SIZE_RULES, GLOBAL_RULES, ASSISTANT_RULES) },
  },
  {
    // The one implementation of the size row.
    files: ['src/components/PlotFields.tsx'],
    rules: { 'no-restricted-syntax': restricted(GLOBAL_RULES, FIELD_RULES.labels) },
  },
])
