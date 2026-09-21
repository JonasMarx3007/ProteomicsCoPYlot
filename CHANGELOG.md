# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Because this is scientific software, "breaking" here includes changes that alter
the **numbers or labels** a released version produced, not only changes to an
API signature. Those are listed first in every release.

## [Unreleased]

### Changed (breaking)

- **Fold-change orientation is now `condition1 − condition2`.** The first
  selected condition is always the minuend, so a positive `log2FC` means higher
  in the condition named first, and the volcano title, the axis label and the
  number finally agree. Previously the computation was
  `condition2 − condition1` while the title read `condition1 vs condition2`.
  This **inverts the sign of every fold change** and swaps Upregulated ↔
  Downregulated relative to any result produced before this change. Magnitudes,
  p-values, adjusted p-values and counts of significant features are unchanged.
  Reports, restore states and published viewer datasets produced earlier will
  disagree in direction with ones produced now. Applies to the backend, the
  Python package and the R package alike.
- **`"data"` now means the annotated, unfiltered matrix everywhere.** It used to
  mean the filtered matrix through one resolver and the unfiltered one through
  another, so the same request returned 11,580 rows on the statistics path and
  11,916 on the visualization path with nothing in the response to say which.
  The request vocabulary is exactly `data | filtered | imputed`, defined once in
  `app.schemas.annotation`, and resolved by a single function
  (`functions.select_matrix`). `analysis_data_source`,
  `_visualization_data_source`, `resolve_data_source_choice` and
  `DATA_SOURCE_CHOICES` were removed rather than deprecated.
- **A named data source no longer falls back.** Requesting a matrix that does
  not exist raises instead of quietly substituting the next one down, because a
  substituted matrix produces real numbers under the wrong label.
- **Coverage totals count features quantified in at least one sample**, not
  matrix rows. The two differ for features that are identified with no quantity
  surviving anywhere (21 such rows in the shipped phosphosite file, 1 in the
  phosphoprotein file). The total is now the union of the bars and agrees with
  the missing-value plot; an `Identified, not quantified` row states the
  difference rather than hiding it.

### Changed

- **The advanced plot panel opens on Ctrl/Cmd + Shift + E**, not Shift + A.
  Chrome answers Ctrl+Shift+A with its own tab search, so the page never saw the
  key and the shortcut appeared to do nothing. The guard test now refuses `KeyA`
  outright.
- **The feature-scaling selector names the scaling.** It offered "Method default
  (centred)", "Centred only" and "Unit variance" — and for PCA the first two are
  the same scaling under two names, while for UMAP and t-SNE the duplicate pair
  is the first and the third. It now offers "Centred" and "Unit variance", and
  switching method moves the selection to that method's default (PCA centred,
  UMAP and t-SNE unit variance) rather than leaving the new method on the old
  method's convention. `auto` is still accepted by the API and by saved states;
  it is simply not a third choice, because it is not a third scaling.
- **The enrichment organism is a request parameter**, offered as a selector with
  one entry (Human). It used to be a constant stamped onto every result, so the
  result reported an organism nobody had chosen. An organism with no bundled
  database is now refused rather than quietly answered with the human one —
  every number would be real and the species wrong.
- **An empty phosphoprotein-regulation result is a figure, not an error.** With
  thresholds nothing passes, the static plot drew "no phosphosites pass the
  selected significance and fold-change thresholds" while the interactive one
  raised, which the route turned into a 400 — so the same question, asked with
  the Type selector one notch over, came back as an error with no way to tell a
  strict threshold from a broken plot. Both now answer with the same sentence,
  from the same constant.
- **Imputation only happens when you press the button.** The Imputation page
  shows what the chosen parameters *would* do -- the plots refresh as you change
  them -- but nothing is written until you run it, and the table you get back is
  the imputation you last ran, not the preview you are looking at. Before, every
  settings change ran the real imputation and replaced the session's imputed
  matrix, so a matrix could be built from parameters nobody had committed to,
  and the table underneath showed one thing while the stored data held another.
  The applied run is stated on the page (method, parameters, row count), and the
  download takes the applied settings rather than the current ones.
- **Ctrl/Cmd + S does nothing in a published viewer.** It exports the whole
  session, which a viewer has no business taking with it and which
  `POST /api/restore/export` now refuses anyway, so a collaborator pressing it
  used to get a key that silently failed. The advanced-panel shortcut works in
  the viewer on purpose: the advanced panel is how a collaborator makes
  a publication-ready figure out of a project somebody published for them.

### Added

- **SVG as a download format for every rendered figure.** The format now reaches
  matplotlib before it draws, as PDF already did, so the file is a real vector
  rather than a raster with an `.svg` name: an artist marked for rasterization is
  un-rasterized first, and the response is served as `image/svg+xml`. JPG and
  WEBP are still produced by re-encoding the rendered PNG; SVG never is, and the
  converter refuses it rather than wrapping pixels in an `<image>` tag. The
  interactive Plotly plots are unaffected — they are served as HTML and have no
  download-format selector, so their in-browser toolbar still saves PNG.
- **A warning under the CV plot when phosphoprotein values are ratios.** A
  `robust_site_median` collapse centres every phosphosite on its own
  across-sample median, so the stored values are ratios rather than abundances
  and their coefficient of variation is not comparable with the protein-level or
  phosphosite-level numbers. The QC options endpoint reports the collapse
  (`centredPhosprotValues`), and the CV tab shows a red box under the figure for
  that one combination. The plot is still drawn, and nothing is written into the
  image.
- **A font control for every text in a figure.** One selector sets the face for
  the whole plot — title, axis labels, tick labels, legend, and the numbers and
  annotations drawn on the marks — and five more override it for any of those on
  its own, the same way a dot size can be set for all points or one condition.
  The list is what journals ask for: Helvetica/Arial, Times New Roman, Courier,
  and the two DejaVu faces. The image now installs the Liberation family, whose
  metrics are identical to the first three, so a figure drawn in
  "Helvetica / Arial" measures the same as one typeset in Arial; the build fails
  if a face the panel offers is not installed, because a missing family is not an
  error at render time — matplotlib substitutes silently and returns a perfectly
  good picture in the wrong typeface.
- **Reference lines can be switched off, restyled and resized.** The card that
  offered one colour picker for the coverage plot now carries show/hide, colour,
  dash style and width, and it reaches every line drawn over data rather than
  from it: both coverage plots, the volcano thresholds (static, interactive,
  phospho and KSEA), the Q-Q fit, the retention-time identity line, the Pearson
  regression fit, and the imputation normal-fit and draw-area guides. Each keeps
  its own appearance until something is changed.

- **The volcano can be drawn for print.** A Type selector beside the other
  volcano options, matching the one the QC plots have always had. Interactive is
  the default, because that panel is for exploring and the hover text is how you
  find out which point you are looking at; Normal renders the same numbers as a
  figure for a paper — two spines, no gridlines, a muted palette, thin grey
  threshold lines and the legend outside the plotting area. Optionally it labels
  the top N up- and down-regulated hits: each label is measured after it is
  drawn and moved until it misses every label already placed, with a leader line
  when it ends up far from its point, and dropped rather than drawn on top of
  another. Nothing is labelled unless asked, because a volcano of 8,000 features
  has no readable set of labels that can be chosen for you.
- **A report renders each volcano the way it was added.** The mode rides on the
  entry rather than on the report, so one report can hold an interactive
  comparison for screen reading and a static one for the figure. A static
  volcano is also about a tenth of the size: 0.5 MB against 5.4 MB.
- **Dot size, opacity and outline moved into the advanced plot settings**, and
  now exist for every plot that draws points rather than only PCA and the
  correlation scatter. Where a figure draws more than one kind of point, each
  gets its own control: the volcano's up-regulated, down-regulated and
  non-significant classes are sized, faded and coloured separately, and the
  single-protein boxplot's jittered data points are separate from the outlier
  fliers beside them.
- **Marker shape and colour, and per-condition overrides for both.** Every plot
  that draws points now offers a shape (ten of them, the same set in matplotlib
  and plotly) and a colour alongside the size, opacity and outline. Above them
  sits a general row and below it one row per condition: setting the general
  size to 20 sets every group to 20, and a single group can then be given a
  triangle, or a different size, on its own. Picking a new general value clears
  the per-group overrides again, so the general row is always a way back rather
  than a setting that quietly no longer applies. The volcano gets the same
  general row above its three significance classes.
- **The advanced plot settings are organised by the thing they change.** One
  card per plot element — Title, X axis, Y axis, Legend, Frame and grid,
  Background, Points, Bars, Value labels, Colour scale — in the same order on
  every plot, with the general elements first and the plot-specific ones after,
  so the panel is recognisable before you have read it. Every card is collapsed
  until you open it, because the freedom to set everything is only usable if you
  are not shown everything at once. A plot is offered only the cards that mean
  something for it. Controls that change the same element sit together: an axis
  card holds its label text, size, weight, style and colour beside its tick size,
  rotation and colour, rather than scattering them down a single flat list.
- **The canvas volcano tiles use the same advanced settings as the page plots.**
  The canvas had its own five-field styling panel — two colours, a radius and an
  opacity — while the identical figure on the statistics page had thirty
  settings. It now renders the shared panel, so a canvas volcano gets the same
  title, axis, legend and per-class point controls as any other. Canvases saved
  with the old panel are migrated: the stored radius becomes a diameter, which is
  what every other size in the tool means.
- **A keyboard shortcut for the advanced plot options.** Ctrl/Cmd + Shift + E
  toggles the styling panel from anywhere, the same switch as Settings > Plot
  Options. Both shortcuts now match on the physical key rather than the letter
  the layout produces, so they work on a QWERTZ or AZERTY keyboard, and
  Ctrl+Shift+S is given back to the browser: the handler ignored Shift, so it
  was swallowing the browser's own screenshot or save-as.
- **A checkbox on the pathway heatmap for the collapsed-row count.** The
  `GENE (n=3)` suffix is now off by default — on a pathway of forty genes it was
  forty parentheticals down the side of the figure, and most of them read 1.
- A data-source selector on PCA, the statistics modules, ORA and the
  single-protein plots, offering only the matrices that exist and defaulting to
  the most processed one available (imputed > filtered > data). The backend
  decides the ladder, so two pages cannot disagree.
- Imputation is stated explicitly at the top of a report, next to filtering, and
  before any plot whose input it changed (PCA and the volcanoes).
- **A report PCA block states how much of the matrix reached the projection**:
  "7,981 of 8,806 features (90.6%) were complete across every sample and entered
  the projection; the remaining 825 were dropped because a projection cannot use
  a feature with a missing value." A PCA is complete-case, so on an unimputed
  matrix the figure is drawn from a subset the report had never quantified. The
  count comes from the same summary the panel shows, and the sentence is omitted
  rather than guessed when the level or the source does not exist.
- **A pairwise panel under the ANOVA post-hoc test**, laid out like the volcano's
  condition pickers. Choosing two conditions computes only that comparison:
  every pair costs one studentized-range integral per significant feature, and
  on a project with 1,477 significant features three pairs took 25 s. The number
  is unchanged by the selection — Tukey's `q` takes `k` from the whole design and
  the MSE is pooled across every condition — and a test asserts the same pair
  computed alone and computed with the others is identical, to the bit.
- **A Normalization card on the viewer's annotation view**, shown only when a
  normalization was applied and naming the method. "Normalization: None" is a
  card that says nothing, and its absence is the same statement with less to
  read.
- Ruff, mypy and coverage configuration in `pyproject.toml`, and a
  `.pre-commit-config.yaml`, so the Python side can be checked locally the way
  the frontend already was in CI.
- `CONTRIBUTING.md` and `SECURITY.md`.

### Removed

- **The grey line under every input in the advanced plot panel.** Sixteen of
  them, mostly repeating a number the field already shows when it is empty —
  `Reference: 6` under a box whose value is 6 until you change it. The three
  that said something the label did not (that 0 draws no outline, that a size
  applies to the static plot only, that a dot size is in points) now say it in
  the label, where it is read rather than skimmed past.

- **The ORA Provenance card**, and with it the GO database SHA-256 and the
  correction-scope paragraph. The organism, the correction method and the number
  of terms in the search space are still stated, in the summary row beside the
  result where the rest of the run's parameters already were. The same two
  fields are gone from the exported ORA rows, where they repeated identically on
  every line, and from the canvas ORA tile.
- **The two standing amber boxes on the Restore page.** Five buttons with two
  paragraphs of prose in front of them. The amber boxes that remain there are
  conditional — Missing Files, and the warnings a restore actually returned.
- **The grey note under the simulation's sample-size override**, folded into the
  label: "Sample size override (0 = observed, 2-100 fixed)".
- **The score-explanation box in the phosphoprotein-regulation options.**
- The data-source selector on QC and on the comparison pipeline (correlation
  heatmap, Pearson, Venn). QC describes the data as loaded, so it reads the
  annotated matrix on whatever scale each statistic is defined on. PCA is the
  single exception, because it cannot use incomplete features.
- **Advanced plot controls that changed nothing.** The panel offered value
  labels, bar controls and a colour scale on plots whose renderers never read
  them, so turning them on did nothing and said nothing. Each plot is now
  offered only the cards its renderer acts on, and a test holds the two lists
  against each other so a control cannot outlive the code behind it.

### Fixed

- **The interactive volcano ignored the reference-line colour** that its static
  twin honoured, so the same comparison had black thresholds in one renderer and
  the chosen colour in the other. The retention-time identity line had the same
  split, drawn as `red` by one renderer and `#ef4444` by the other. Both read
  the same setting now.
- **A bold title changed its typeface** in the interactive plots: bold and italic
  were faked by swapping the font family to Arial Black or Arial Italic, which
  restyled the text and would have overridden any face chosen for it. Plotly's
  own weight and style are used instead.
- **Setting a legend text size dropped the legend text colour** in the
  interactive plots, because the size replaced the whole font object rather than
  adding to it.

- **One condition without a confidence ellipse no longer costs the whole PCA
  figure.** The ellipse is fitted with Khachiyan's algorithm, which needs the
  group's points to span the plane. A condition whose replicates land on a line,
  or two samples at the same coordinates, makes the scatter matrix singular and
  the solver raises -- and the guard at every call site counted points rather
  than checking rank, so the request returned a 500 and the user saw no plot at
  all. That group's ellipse is now skipped, everything else is drawn, and the
  omission is named in the notice *under* the plot, never in the figure: a
  collapsed ellipse is refused the same way, because one drawn as a line reads
  as a confidence region of zero area rather than as the absence of one. The
  backend, the Python package and the R package all skip the same groups; the
  packages warn instead, having no notice to write to.
- **The rank-abundance plot added a pseudocount the axis did not mention.** It
  plotted `log10(mean + 1)` under a label reading `log10 <workflow> Intensity`.
  On ordinary MS intensities the pseudocount is invisible in the middle of the
  range and grows at the bottom of it: up to 0.10 log10 too high on the shipped
  protein matrix and 0.27 on the phosphoprotein one, a factor of 1.9 on exactly
  the part of the curve the plot exists to show. On a `robust_site_median`
  phosphoprotein matrix -- the default aggregation, whose values are ratios
  centred on 1 -- it is not an edge case: every point moved by about 0.30 and the
  curve's range compressed from 0.73 to 0.44 log10 units, under an axis that
  named the raw ratio. Now log10 of the value, in the backend, the Python package
  and the R package alike; a non-positive mean has no logarithm and is dropped
  rather than shifted into range.
- **The canvas volcano named its x-axis backwards.** `log2FC` is
  `condition1 - condition2` everywhere in the tool and the backend labels the
  axis accordingly, but the Analysis canvas drew `log2 Fold Change (condition2 vs
  condition1)` on its own SVG -- the opposite reading, in a form that does not say
  which way the difference was taken. The same reversal was in the control-volcano
  axis, the linked-plot picker and the assistant's confirmation sentence. The
  points, the counts and the generated list names were always right; only the
  axis lied.
- **A saved canvas volcano came back on a different matrix.** The restore
  collapsed a saved `filtered` to `data`, so a volcano restored from a save file
  silently ran on the unfiltered matrix -- a different row count, a different BH
  denominator, therefore different adjusted p-values and different counts -- while
  the selector agreed with the value it had just been changed to. The boxplot and
  lineplot tiles beside it had always restored correctly.
- **The single-protein boxplot and lineplot labelled centred ratios as
  intensity, and imputed values as measured.** Both hardcoded `log2 intensity`
  while the heatmap colourbar on the same page asked whether the phosphoprotein
  matrix was centred, so one page called the same numbers two different things.
  The boxplot title also read "Measured ... values" on the imputed matrix, where
  some of those points are draws from a down-shifted normal, and the exported
  figure carries no data-source selector to say otherwise.
- **The ANOVA post-hoc panel never showed its result.** The panel caches one
  result under a key describing the request, and the key was written out as a
  second object literal that had drifted: the request carried the post-hoc pair
  and the key did not. With Tukey selected, the stored key could never equal the
  key being compared, so the panel showed "Running the ANOVA and the Tukey HSD
  post-hoc... it can take a minute" indefinitely over a response that had already
  arrived. The key is derived from the request now.
- **Stale tables beside fresh plots.** Plot bodies have always said `no-store`;
  the JSON tables carrying the same numbers said nothing at all, and the
  frontend's own cache-buster was not bumped by the seven calls that replace a
  matrix -- including re-filtering and re-imputation. Both halves closed.
- **Three copies of one function, drifted.** The advanced plot settings were
  compacted for the URL by three near-identical functions. Each omission is
  silent in the same way: the panel stores the setting, the URL never carries it,
  and the plot renders as though it had never been set. `App.tsx` was dropping the
  legacy flat text keys a save file still carries, and the Completeness page was
  dropping the legend, box, colour-scale and condition keys. Now one function.
- **`True` and `1` shared a cache entry.** The cache key kept booleans and
  integers as themselves, and Python holds `True == 1` with equal hashes. The
  advanced plot settings arrive as untyped JSON, where `{"x": true}` and
  `{"x": 1}` render differently, so the second request was served the first one's
  figure.
- **An edited viewer config never reached a live session.** The bootstrap marker
  was keyed on the config file's path, so once a viewer had loaded a project there
  was no edit that could reach them: an administrator could change a filter, swap
  a data file or add a dataset, reload, and be served the project as it was when
  they first opened it. Keyed on the modification time now.
- **The condition colour hex field could not be typed into.** Fully controlled on
  the saved colour and rejecting anything that was not already a complete
  `#RRGGBB`, it threw away every intermediate keystroke and snapped back, leaving
  the swatch as the only way to change a colour.
- **The Imputation page re-imputed on every keystroke.** That call stores its
  result as the session's imputed matrix, so it also flushed the cache once per
  typed character and briefly left the stored matrix built from a half-typed
  number. Debounced, like every other panel.
- **The phosphoprotein regulation plot could not reach its own point controls.**
  The advanced panel matched a tab name that does not exist.
- **Width, height and DPI were eight separate systems.** Every plot in the tool
  now sizes through one component with one set of limits (1–60 cm, 72–600 DPI,
  24 MP, the same numbers the backend enforces). Before, the QC fields rendered
  DPI, then height, then width — the reverse of every other page; the comparison
  page had its own copy of the row; the pathway heatmap had three loose number
  fields; and the peptide page put its own floor of 5 cm under the shared one, so
  it alone refused a 3 cm figure the backend would have drawn. Saved sizes are
  also restored through the shared guards: a missing or malformed value now falls
  back to the plot's own default instead of `Number(null)`, which is `0` — a
  request for a figure zero centimetres wide.
- **One dot size meant three different dots.** Every size is now a diameter in
  points, in one helper (`marker_area`). The PCA multiplied its setting by 10 for
  matplotlib and passed it raw to plotly; the correlation scatter used it as an
  area in one renderer and its square root in the other; and the two routes
  behind each single control declared different defaults (5 and 8, 60 and 8). So
  "dot size 60" drew a different dot on every page, and the same page drew a
  different dot depending on whether you were looking at the interactive version.
- **Renaming a condition renamed the legend but not the axis.** The per-sample
  tick labels are built by pasting the condition name in front of a replicate
  number (`Control_1`), which the rename never saw — so QC coverage, the
  per-sample boxplot and the correlation heatmap showed the same group under two
  names in one figure. Renaming now also reaches the ANOVA heatmap legend, the
  pathway heatmap columns, the phospho condition axis, the single-protein
  boxplot axis and legend, and the correlation and Venn labels, all of which
  offered the control and ignored it. A sample-level override still wins.
- **The single-protein boxplot ignored every style setting it was offered.** It
  built its own `tab20` palette instead of the project's condition colours, and
  read none of the box border, median or outlier settings the advanced panel has
  always shown for it. Its jittered points also had no outline, so the points
  inside a box — drawn in that box's own colour — were invisible; they now carry
  a thin dark edge by default.
- **A volcano built on the filtered matrix was logged into the report as
  imputed.** `normalizeDataSource` mapped anything that was not `"data"` to
  `"imputed"`, from when those were the only two matrices, so the report
  described a matrix the figure had not used. An unrecognised value now falls
  back to the least processed matrix rather than inventing the most processed one.
- **The viewer's report carried none of its QC plot styling.** In viewer mode the
  QC page writes its advanced settings to their own session key, and the report
  read only the other one — so renamed conditions, colours and fonts were absent
  from every QC figure in a viewer report.
- The collapsing note on the single-protein plots moved out of the figure title
  and into a note under the plot. A figure taken out of the tool should not carry
  a caption about how the tool built it.

- **The phosphosite-on-protein heatmap merged proteins.** It resolved the
  selected protein by case-insensitive *substring* on the protein-group column,
  while the boxplot, lineplot and table beside it matched exactly. Selecting
  `P12345` therefore also drew the sites of the isoform group `P12345-2` and of
  the multi-protein group `P12345;Q67890`, under the name of the one protein
  chosen, with nothing in the output to say so. All four selection sites now use
  the same exact matcher. No shipped example is affected — none of its 2,301
  protein groups is a substring of another — so this changes nothing about the
  example project and everything about a dataset with isoform accessions.
- **The report described plots with a matrix it had not used, and drew one PCA
  it had not been asked for.** The report still modelled the data source as a
  boolean `imputed`, from before the vocabulary became `data | filtered |
  imputed`. Anything built on the filtered matrix was therefore labelled "Data" —
  and for PCA the label was not merely wrong: the report re-rendered the
  projection on the matrix its own label named, so a figure requested on
  `filtered` came back computed on the unfiltered one. The volcano rendered
  correctly and was described wrongly. Provenance now carries the requested
  source through unchanged, an unrecognised name falls back to `data` rather
  than inventing a label, and the three sources are stated by name.
- **The frontend had never been type-checked against the new data-source
  vocabulary.** `tsc -b` found ten errors: five request types in `types.ts` still
  spelled the union `"data" | "imputed"` by hand, so a page offering
  `filtered` could not describe the request it was sending, and the canvas
  Analysis page still used the retired `"log2"` source name — which the backend
  now rejects, so every canvas boxplot and lineplot tile was returning an error.
  The canvas page also read `filteredAvailable`/`imputedAvailable` from an
  endpoint that had stopped sending them, and its TypeScript type still declared
  them, so `undefined` read as `false` and every matrix but the first showed as
  unavailable. All of it now goes through the one `DataSource` type and the
  served ladder. A saved `"log2"` restores to `"data"`, which is the same matrix
  under its current name.
- ORA in the statistics page did not re-run when the ANOVA cluster method
  changed: three hooks read `clusterMethod` without listing it as a dependency,
  so the enrichment could describe a partition the page was no longer showing.
- The comparison page's plot and table memos guarded on `options` without
  listing it, so they only recomputed once the options arrived because seeding
  the selections happened to produce new state objects. The KSEA page rebuilt an
  empty array on every render, which made every memo downstream of it recompute
  every render. `npm run lint` is now clean: 0 errors, 0 warnings.
- **The exported phosphosite heatmap lost the protein accession.** The table
  ended with `rename(columns={"index": "Site"})`, which never fired because
  `reset_index()` restores the index's own name — so the intended `Site` column
  had never existed and the CSV went out headed `PTM_Collapse_key` over values
  that were not collapse keys: `A0JLT2~MED19_S226_M1` reached the user as
  `MED19_S226`, under a header naming the part that had been removed. The table
  now has both: `Site`, the label drawn on the figure, and `PTM_Collapse_key`,
  the whole identifier. The heatmap image is byte-identical.
- **The Q-Q plot discarded every value at or below zero.** It is fed the
  annotated log2 matrix, where negatives are ordinary intensities below 1, and a
  `robust_site_median` phosphoprotein matrix holds ratios centred on zero — so
  roughly half of it never reached the plot whose job is to show whether the
  distribution is normal, and dropping the lower half is what makes a
  distribution look normal. Neither `notebook_functions.py` nor
  `notebook_functions.R` filtered, so the backend also disagreed with both
  packages. Non-finite values are still dropped, which is new: an infinity has
  no quantile and used to poison the fit line.
- The Q-Q plot now says when it is showing a random sample rather than every
  value, instead of silently drawing 100,000 of them.
- The distribution page read two different matrices: the image came from
  `qc_matrix`, while the statistics and the Q-Q points beside it came from a
  second resolver that substituted the filtered and then the raw matrix. That
  resolver is gone; distribution is QC and reads the annotated matrix.
- The shipped example `viewer_config.json` declared `robust_site_median` over a
  phosphoprotein file that was produced with `sum_ignore_na`, so every
  phosphoprotein axis in the example read "Ratio to Site Median" over plain
  abundances. The config is corrected, and a test now reconstructs the matrix in
  every mode the schema allows and fails unless the declared mode is the one
  that reproduces the file.
- Centred phosphoprotein values were labelled "Intensity" on 8 of 11 plots. All
  call sites now go through `intensity_unit_label`; a test fails naming any file
  and line that hardcodes a unit again.
- A reversed control contrast in `phospho_tools.py`, and — worse — the
  assistant's own methods text, which told users "condition 2 minus condition 1"
  for *every* volcano.
- The viewer ran its own copy of several analysis paths. It now calls the same
  functions as the tool, with routing as the only difference.
- **The viewer showed modules it has no data for.** It is for looking at a
  published dataset, not for processing one, so upload and annotation are now a
  read-only view of what was uploaded and how it was filtered, imputed and
  normalized; the remaining data-processing modules, simulation, external peptide
  collapse, and the phospho and peptide pipelines (including the
  phosphosite-on-protein heatmap) are gone in viewer mode rather than present and
  failing.
- **A viewer served with the analysis bundle looked like broken gating.** The
  two modes are separate builds (`VITE_APP_MODE`), and nothing checked which one
  was on disk. The build now writes a `build-mode.json` marker and `launch.py`
  refuses to serve a bundle that does not match the mode it was asked for, rather
  than serving the wrong UI over the right backend.
- An out-of-range `seed` in a viewer config cost the whole package rather than
  just imputation, because the failure path echoed the bad value into a
  validated model inside the handler meant to contain it.

### Security

- **The login response no longer hands back the session id.** Both auth
  endpoints echoed the id of the session the caller had just been given into the
  response body. The cookie already carries it, `HttpOnly` so script cannot read
  it; putting the same value in JSON undoes that for anything that logs, caches
  or forwards a response body. Nothing read the field, so it is gone rather than
  deprecated.
- **Read-only viewer mode refuses three more writes.**
  `POST /api/restore/export` packages the whole session, matrices included, and a
  viewer has no business taking that with them; the Ctrl/Cmd + S shortcut that
  called it is also gone from viewer builds, so the key no longer fails silently.
  `POST /api/data-tools/imputation/download` runs the same imputation as
  `/imputation/run`, which was already refused, and returns the whole filled
  matrix as CSV with an attacker-chosen seed, method and width, from a deployment
  whose Imputation tab is not there. `POST /api/data-tools/condition-colors/{kind}`
  is a write, and the page that offers it is not in the viewer's tab list; the
  GET stays open, because a viewer has to read the colours the project was
  published with. A test now enumerates every mutating operation the application
  serves and requires each one to be either denied or listed with a reason, so a
  new write route fails the build until somebody decides which it is.
- **Plot HTML is checked against a wider set of injection points.** Generated
  figures inline plotly, so uploaded protein names, gene names and condition
  names are embedded inside a `<script>`. The existing guard covered the point
  text and the title; it now also covers hover text, trace names, custom data,
  the tick labels and both axis titles, and asserts the script element is opened
  and closed exactly once.

## [1.0.1] - 2026-07-28

Releases up to this point predate this file. See the repository history for
their contents.

[Unreleased]: https://github.com/JonasMarx3007/ProteomicsCoPYlot/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/JonasMarx3007/ProteomicsCoPYlot/releases/tag/v1.0.1
