# How changes reach users

Goal: nobody should ever install a version of Beat Sorter that doesn't open
or that breaks their library. Four layers make sure of that.

## 1. Automatic tests on a real Windows PC (GitHub Actions)

Every push runs `.github/workflows/test-and-release.yml` on **Windows** and
Linux. It installs Beat Sorter the same way `setup.bat` does, then:

| Check | What it catches |
|---|---|
| `pyflakes` | typos, undefined names, code that would crash when it runs |
| Unit tests (`tests/test_*.py`) | BPM/key parsing, key detection, sorting, the Sorted folder (build, live sync, never touching originals), My Folders, player, updater |
| `tests/test_app_e2e.py` | opens the real window and goes through every feature like a user: scan, build, tags, fixes, Sorted tab (My Folders, drag to folder, rename, layouts), duplicates, FL tag sync, player, problem report, reopening the app; checks the Sorted folder on disk at every step and that original beats are unchanged |
| `tests/test_apply_update.py` | updates that wait for locked files, never leave a half-replaced app, roll back if the new version won't open, and work while the Essentia helper is running (the 1.9.1 bug) |
| `python -m beatsorter --smoke-test` | the app opens through the exact startup path Windows uses |
| Windows download (`packaging/`) | builds BeatSorter-Windows.zip (Python included), unzips it into a folder with spaces on a PC with **no Python on PATH**, starts `Beat Sorter.exe`, then runs the whole test suite with the bundled Python |

## 2. Users only get versions that passed

The app's updater installs from the **`release`** branch (`update.json`),
not `main`. The workflow moves `release` to a commit only after every test
passed on Windows and Linux and the Windows download built and passed its
tests; it then attaches BeatSorter-Windows.zip to a GitHub Release
(`v<version>`). The README links to the latest one. A broken commit on `main` never reaches users.

Want to approve each release by hand as well? In GitHub: Settings >
Environments > New environment "release" > Required reviewers (add
yourself), then add `environment: release` to the `release` job. The
release then waits for your click in the Actions tab.

## 3. The updater protects users anyway

`beatsorter/apply_update.py`, if something still goes wrong on someone's PC:
- closes leftover Beat Sorter helpers before touching files;
- moves the old program folder aside (waiting up to a minute if Windows is
  holding it) instead of deleting it in place, so it's never half-replaced;
- starts the new version and waits for it to open (it writes
  `started.txt`). If it hasn't opened within 2 minutes, the previous
  version is put back and started, and the user is told;
- keeps the last 3 versions in `_backup` (More > Undo last update).

If the app can't start at all, it now says why and how to repair, instead
of closing silently.

## 4. Users can report problems

Report a problem (top right, More menu, and every error message) opens a
pre-filled GitHub issue or an email to the support address in
`update.json`. Technical details are shown to the user first, with personal
folder names hidden. Reports from the app are titled `[Bug]` or `[Idea]`
and labeled automatically (`.github/workflows/label-issues.yml`).

Where reports go: **GitHub > Issues** (filter by `bug` / `enhancement`),
and the support email inbox.

## Checklist for each change

1. Make the change. Add or update a test for it (a bug fix gets a test that
   fails without the fix).
2. Bump `beatsorter/version.py` and add a section at the top of
   `CHANGELOG.txt` (the first lines are shown in the update banner).
   Bump `ANALYSIS_VERSION` in `analyzer.py` only if detection results
   change (forces everyone's library to re-analyze once).
3. Run the tests locally: `python -m pytest` (and `python -m beatsorter --smoke-test`).
4. Push to `main`. Watch the Actions tab: when both test jobs are green,
   the `release` job publishes it.
5. Check: an older copy of the app offers the new version
   (More > Check for updates).

If a bad version ever gets out: push a fix with a **higher** version number
(the updater only offers newer versions). Users can also use
More > Undo last update.
