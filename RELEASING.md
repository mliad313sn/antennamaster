# Cutting a release

Releases are published by the repository itself, through
`.github/workflows/release.yml`, with a `contents: write` token scoped to that
job and nothing else. Nobody uploads an installer by hand.

`dist/AntennaMaster-Setup-<version>.exe` is committed, so the artefact on the
release page is byte-identical to the one in the tree at the released commit.

## Release it

1. **Bump the version** in all four places the workflow checks —
   `packaging/windows/antennamaster.nsi`, `frontend/package.json`,
   `backend/app/services/saas/study_record.py` (`APP_VERSION`) and a
   `## <version> — <date>` section in `CHANGELOG.md`.

   `APP_VERSION` is stamped into every filed study of record, so a version
   that disagrees with the release would make studies cite a build that was
   never published. That is why it is checked, not assumed.

2. **Rebuild the installer** and commit it:

   ```bash
   ./tools/build_windows_installer.sh
   ```

   Do this even if "nothing much" changed since the bump. An installer built
   two commits ago ships a different payload under the same version name —
   this repository did exactly that once, and only caught it by extracting
   the `.exe`. The workflow now extracts it too and refuses a mismatch.

3. **Push the commit and wait for CI to go green.** All six jobs, including
   *Browser end-to-end (real stack)*.

4. **Trigger the release**, either way:

   ```bash
   git push origin HEAD:refs/heads/release/v<version>    # branch push
   ```

   or, from the Actions tab, run **Release** and give it the version.

   Both run the same job. The branch push exists because an automated session
   can push branches but cannot dispatch workflows (`actions: write`) or push
   tags — both return 403. The branch name carries the version; the workflow
   creates the tag itself.

5. **Delete the release branch** once the run is green. The tag is the record.

## What the workflow refuses

Each check is a mistake that is easy, silent, and expensive once the artefact
is downloadable:

| Refusal | Why |
|---|---|
| CI on the commit is not green | a release cut from a red commit is a guess about what works (`allow_red_ci` overrides, and says so in a warning) |
| the version disagrees with the tree | four sources, one number; `APP_VERSION` ends up inside filed studies |
| no installer for that version | nothing to release |
| the installer's payload is stale | one version name, two payloads — verified by extracting the `.exe`, not by trusting its filename |
| no `## <version>` section in the CHANGELOG | notes come from the CHANGELOG so the published text and the repository cannot disagree |
| the version is already released | a published version is immutable; cut a new one |

## Note on the default branch

The repository's default branch is still an old `claude/*` branch, so
`release.yml` is duplicated there purely to register `workflow_dispatch` —
GitHub only exposes that trigger for workflows on the default branch. Once
the default is switched to `main` in the repository settings, that copy can
be deleted.
