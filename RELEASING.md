# Cutting a release

The repository's CI is the gate: a release is cut from a commit whose CI run
is green, never from a local build. `dist/AntennaMaster-Setup-<version>.exe`
is committed, so the artefact in the release is byte-identical to the one in
the tree at that commit.

## 1. Verify

```bash
./start.sh --check          # backend, frontend, e2e and benchmark gates
```
and confirm the commit's CI run is green on GitHub — all six jobs, including
**Browser end-to-end (real stack)**.

## 2. Rebuild the installer if anything changed since the version bump

An installer built before the last commit ships a different payload under the
same version name. Rebuild and verify what is actually inside it:

```bash
./tools/build_windows_installer.sh
7z x -o/tmp/exe-check -y dist/AntennaMaster-Setup-<version>.exe
grep -m1 APP_VERSION /tmp/exe-check/backend/app/services/saas/study_record.py
sha256sum dist/AntennaMaster-Setup-<version>.exe
```

## 3. Tag and publish

```bash
git tag -a v<version> -m "AntennaMaster <version>"
git push origin v<version>
gh release create v<version> \
  --title "AntennaMaster <version>" \
  --notes-file <(sed -n '/^## <version>/,/^## /p' CHANGELOG.md | head -n -1) \
  dist/AntennaMaster-Setup-<version>.exe
```

The release notes come from `CHANGELOG.md` so the published text and the
repository never disagree about what shipped.

## Note on automation

A Claude Code session can create branches but **cannot push tags or create
releases**: tag pushes are refused with 403 by the session's git credentials,
and the GitHub MCP server exposes only read operations for releases. Steps 1
and 2 can be automated; step 3 is run by a human or by a workflow with
`contents: write`.
