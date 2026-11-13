# Development

## Build and test

Python 3.8 or newer is enough; the tests need no extra packages.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_package.py
python3 scripts/check.py
```

`build_package.py` writes `dist/MarkdownFormatting.sublime-package` and its checksum from the file list in `PACKAGE_FILES`. The archive is reproducible: entries are sorted and stored uncompressed, with fixed timestamps and modes, so the same source always gives the same bytes.

`check.py` runs the unit tests, checks that the Python files parse as Python 3.8, compares `dist/` with a fresh build, and checks that the release archive (see below) contains exactly `PACKAGE_FILES`. CI also runs `ruff check .` (Ruff 0.16.9).

The unit tests cover the formatting engine (output text and selections, multiple carets, toggling, escaping), the action catalog and settings validation, the pickers, the Sublime adapter and the package contents. The adapter tests use a small fake of the Sublime API, so menus and commands are also checked in a real editor (below).

## Testing in Sublime Text

`scripts/run_editor_smoke.py` installs the built archive into a portable Sublime Text on a separate Xvfb display, copies the test driver (`scripts/runtime_driver.py`) into its `Packages/User` folder and runs about 80 cases: formatting actions, undo, profiles, settings, the context-menu option and both pickers, including their colors after theme and color scheme changes. It writes `runtime.json` and `editor.log` to the output folder and exits non-zero if any case fails. The driver is a test helper and is never packaged.

```sh
python3 scripts/run_editor_smoke.py \
  --sublime-dir /path/to/throwaway/sublime_text \
  --output build/editor-run
```

Use a freshly extracted Linux portable build from sublimetext.com, never your own installation; the script refuses to reuse an existing `Data` folder. It needs Xvfb and Sublime's usual GTK and audio libraries. CI runs the same script against build 4215 after checking the download's signature and SHA-256.

Some things only show up by hand, mainly native menu behavior on Windows and macOS (see [compatibility](compatibility.md)). Before a release it's worth a quick manual pass: right-click formatting with the mouse, undo, hiding an action in the settings, switching profiles, and both pickers in a light and a dark color scheme.

## Releasing

1. Update `CHANGELOG.md`, rebuild, run `scripts/check.py` and push to `main`. Wait for CI to pass.
2. Tag the commit as `vX.Y.Z` (annotated) and push the tag. Package Control installs GitHub's archive of the newest tag. `export-ignore` in `.gitattributes` limits that archive to `PACKAGE_FILES`, so it matches `dist/` exactly.
3. Upload the archive and its `.sha256` file from `dist/` to the package website (see its `WEBSITE-README.md`).
