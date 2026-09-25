<!--
Copyright (c) 2026 Jurjen Stellingwerff
SPDX-License-Identifier: LGPL-3.0-or-later
-->

# Submitting a library to the loft registry

This is the guide for publishing a loft library you maintain: adding a new
package, releasing a new version, or yanking a broken release.  If you only want
to *use* a library, run `loft install <name>` and stop reading here.

The same flow, with the rules behind it, is maintained with the compiler in
[REGISTRY_SUBMIT.md](https://github.com/loft-lang/loft/blob/main/doc/claude/REGISTRY_SUBMIT.md);
the standing rules for writing a library are
[LIBRARY_AUTHORING.md § The library contract](https://github.com/loft-lang/loft/blob/main/doc/claude/LIBRARY_AUTHORING.md).

---

## Prerequisites

1. **A loft package** — a directory with a valid `loft.toml` and its source:

   ```text
   my-lib/
   ├── loft.toml          # [package] name, version, loft, levels, categories
   ├── src/<name>.loft    # entry point (or [library] entry = "...")
   ├── tests/             # expected
   ├── docs/01-getting-started.loft   # the guide
   └── native/            # optional Rust crate
   ```

   The manifest declares the package's **three compatibility levels** — `loft`,
   `api_compatible_with` and `data_compatible_with` — and a new package declares a
   non-empty **`categories`** list.  `loft compat levels` must pass: it is the
   admission gate for the levels.
2. **A public source repo on GitHub.**  The registry clones your release tag and
   re-runs `loft package` to check the tarball.
3. **A loft binary** at least as new as the `loft` level you declare.

You do **not** need a signing key.  The registry maintainer signs `index.json`;
you sign nothing.

---

## The five-step submit flow

### 1. Tag the release in your source repo

The tag is **`<name>-v<version>`**, whatever the repo layout, and its version must
match `[package] version`:

```sh
cd my-lib/
git tag my-lib-v0.1.0
git push --tags
```

That is the name `loft package` gives the release in the url it prints (step 2),
and the registry clones exactly the tag your release url names.  A repo holding
several packages (the `loft-lang/loft-libs-*` repos hold several each) is why the
package name is in the tag.

### 2. Build the tarball with `loft package`

```sh
loft package
```

It writes `my-lib-0.1.0.tar.gz` and prints its size, its sha256 and the index
entry for it, including the release url under your tag.  The tarball is
**deterministic** — the same source gives the same sha256 on every machine — and
the registry checks that by rebuilding it from your tag.

### 3. Upload the tarball as a GitHub release asset

```sh
gh release create my-lib-v0.1.0 my-lib-0.1.0.tar.gz \
    --title "my-lib v0.1.0" \
    --notes "Initial release."
```

**Don't re-upload the asset after this point.**  A re-uploaded tarball has
different bytes, and the sha256 you submit no longer matches.  To fix a release,
ship the next version instead.

### 4. Open a PR against `loft-lang/registry`

**Recommended: add a staging file, `submissions/<name>-<version>.json`, and
nothing else.**  It never touches `index.json`, so it cannot race the signed
index, and it is vetted before it is trusted:

```json
{
  "name": "my-lib",
  "version": "0.1.0",
  "repo": "<owner>/<repo>",
  "tag": "my-lib-v0.1.0",
  "subpath": "my-lib",
  "description": "One sentence on what the library does.",
  "homepage": "https://github.com/<owner>/<repo>",
  "categories": ["text"],
  "entry": {
    "url": "https://github.com/<owner>/<repo>/releases/download/my-lib-v0.1.0/my-lib-0.1.0.tar.gz",
    "sha256": "<hex from step 2>",
    "size": <N from step 2>,
    "loft": ">=0.8",
    "subpath": "my-lib",
    "deps": {}
  }
}
```

| Field | Required | Meaning |
|---|---|---|
| `name`, `version` | ✓ | as in your `loft.toml` |
| `repo` | ✓ | `<owner>/<repo>` on GitHub — the vetter clones it |
| `tag` | ✓ | the release tag from step 1 |
| `subpath` | ✓ when the repo holds several packages | the package's directory in the repo; defaults to `name` |
| `entry` | ✓ | the index entry `loft package` printed in step 2 — **omit `published`**, the maintainer's run stamps it |
| `description`, `homepage` | for a new package | the package's catalogue text; ignored for an existing package |
| `categories` | ✓ for a new package | a non-empty list of catalogue tags — reuse one the registry already has |

Title the PR `submit my-lib 0.1.0`.  The registry's own CI checks `index.json`
only, so it has nothing to say about a staging file; the vetting happens on the
maintainer's next publish run, described in step 5.

**Alternative: edit `index.json` directly.**  Add your package (or your new
version row) to `index.json` and title the PR `add my-lib 0.1.0`.  This still
works and runs the registry's CI on your PR, but it can race another publish, and
the maintainer must re-sign the file before it merges — an `index.json` merged
without its signature breaks every `loft install`.

### 5. Wait for review

**A staging file** is picked up by the maintainer's publish run, which puts your
`repo@tag` through the same validation every loft-lang library passes: it
compiles and runs your tests against the current loft, checks the metadata, and
flags any `#rust` or `#native` code.

- A pure-loft library that passes is folded into `index.json`, the staging file
  is removed, and the index is re-signed, all in one commit.  The signing step
  re-checks your `sha256` against the release tarball.
- A library with native code gets a one-time human review before admission.
- A library that fails is reported on the PR and not admitted.

**A direct `index.json` edit** runs `tools/validate.py` on the PR:

| Gate | What it checks | Common failure cause |
|---|---|---|
| Schema lint | required fields and types, a non-empty `categories` for a new package | a typo in a field name, `size` as a string, a missing `published` |
| Tarball verify | downloads `url`, compares sha256 and size | the release asset was re-uploaded; a wrong hash was pasted |
| Prebuilt verify | each `binaries[<triple>]` archive's sha256 | a rebuilt binary after the PR opened |
| Reproducible build | clones your repo at the tag your `url` names, runs `loft package`, compares the sha256 | the tag points at different source than the tarball; untracked files leaked into the tarball |

Fix a failure and push to your PR branch; CI re-runs.  After the gates pass, a
maintainer reviews, re-signs the index and merges.

**Once merged, `loft install my-lib` works for everyone.**

---

## Subsequent releases

1. Bump `version` in `loft.toml`, and move a compatibility level if the release
   needs it (below).
2. Run `loft compat check --full` — it verifies your declared levels against every
   release you have published.
3. `git tag my-lib-v0.2.0 && git push --tags`, then `loft package` and
   `gh release create my-lib-v0.2.0 my-lib-0.2.0.tar.gz`.
4. Submit the new version (step 4).  Add only the new version; never touch an
   existing row.

The registry **never deletes** a version.  Old versions stay so existing
`loft.lock` pins keep resolving.

---

## Yanking a broken release

Yank a version that is **broken or vulnerable** — never one that is merely
superseded.  A yanked version stays in the index: a range or `*` never picks it,
so nothing new installs it by accident, while an exact pin — a `loft.lock` entry,
or `"0.1.2"` in a manifest — still resolves it.
Publish the fixed version first, so a consumer has somewhere to go.

To yank `0.1.2`, open a PR that changes only the package's `yanked` list:

```diff
   "my-lib": {
     ...
-    "yanked": [],
+    "yanked": ["0.1.2"],
     "versions": {
       ...
```

Title it `yank my-lib 0.1.2 — <reason>` and explain the reason in the PR body.

---

## What NOT to include in your package

`loft package` leaves out `.git`, `target`, `.loft`, `node_modules`, `.vscode`,
`.idea` and any `*.tar.gz` / `*.tar`.  Everything else in the directory ships, so
check the tarball (`tar tzf my-lib-0.1.0.tar.gz | sort`) before uploading:

- **Build artefacts** outside `target/` (an `out/` directory, say).
- **Local configuration** — `.envrc`, `.tool-versions`, editor settings.
- **Secrets** — `.env`, credentials.  The registry does not scan for them.
- **Private test data** — recorded responses from a service you have credentials
  for.
- **A machine-local dependency** — a `path = …` dependency in `loft.toml` or in
  `native/Cargo.toml` builds on your machine and nowhere else.  Depend on a
  registry package instead, and submit that package first if it is not listed.

---

## Etiquette

- **Compatibility is declared, not implied by the version number.**  The version
  is only an identity.  What tells a consumer a release is safe to take is its
  three declared levels, and raising a level is how a break is declared — which
  should be rare.  Adding things is free.
- **`loft = ">=X.Y"`** should name the oldest loft you actually tested against.
- **Deprecation is a signal, never a removal.**  Point at the successor in your
  docs and keep the old version working.
- **Co-maintainers**: open an issue on `loft-lang/registry` asking for
  co-maintainer status.

---

## Troubleshooting

### "Tarball sha256 mismatch"

The release asset changed after you ran `loft package` (a re-upload, or a
re-run against changed source).  Re-run `loft package` on the unchanged source at
your tag, upload that tarball, and update the `sha256` and `size` you submitted —
or ship the next version.

### "Reproducible-build sha256 mismatch"

The registry cloned your repo at the tag in your `url`, ran `loft package`, and got
a different sha256.  Causes:

- The tag was moved after you built the tarball.  Never force-push a release tag.
- Your local `loft package` saw files a clean clone does not: uncommitted changes
  or untracked files.  `git status --ignored` shows them; commit them, ignore
  them, or remove them, then re-tag.

### "Validation says my dep is missing"

A dependency in your `loft.toml` is not in the registry yet.  Submit it first:
a package may depend on a registry package only once that package is in the
signed index.

---

## Mirroring the registry

The registry is a single static `index.json`, and anyone can mirror it:

```sh
git clone https://github.com/loft-lang/registry
# host the resulting directory however you like
export LOFT_REGISTRY_URL=https://<your-mirror>/index.json
loft install my-lib
```

A mirror that keeps the upstream `index.json.sig` works as is — clients verify
the upstream signature.  A mirror signed with a different key needs that key in
the loft binary's `TRUSTED_PUBLIC_KEYS`; open an issue on `loft-lang/loft` to
discuss it.
