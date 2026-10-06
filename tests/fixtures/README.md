# Test fixtures

`viewer_config.json` is the tests' own copy of the HEK293 example project. It
reads the bundled example data in `proteomicscopylot/example_data/` but is
separate from the shipped `viewer_config.json`, so editing the demo does not
change what the tests compute. Tests that check the shipped configuration itself
(for example `test_viewer_collapse_provenance.py`) still read the root file.

`pca_default_scaling.json`, `assistant_plot_modules.json` and
`comparison_contrast.json` are contracts between the frontend and the backend:
each side's tests compare their own values with the file, so the two cannot
disagree without one of them failing.
`assistant_plot_modules.json` lists the views the app offers that show a plot
or a result (`<section>.<tab>`), each of which the assistant has evidence for.
