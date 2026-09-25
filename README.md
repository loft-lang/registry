<!--
This file is shipped to `loft-lang/registry/README.md`.
Copy it as part of REGISTRY_BOOTSTRAP.md Step 3.

The doc/claude/registry_ci_template/README.md is the deploy-side
instruction set (read by the loft maintainer); THIS file is what
ecosystem contributors see when they land on the registry repo.
-->

# loft-lang / registry

The package registry for the [loft](https://github.com/loft-lang/loft)
language ecosystem.  A single static `index.json` file that the
loft client consumes when you run `loft install <pkg>`.

If you want to install a package, you don't need this repo — just
run `loft install <name>` (or `loft search <query>`) from your
loft project.  The client fetches the index automatically.

If you want to **publish** a package or understand how the
registry works, read on.

---

## How packages get added

**Full guide for library authors**: [SUBMITTING.md](SUBMITTING.md)
— prerequisites, the 5-step flow, troubleshooting, what NOT to
include in your package, yanking, mirror policy.  Read that
before opening a PR.

**Short version:**

1. **Tag the release** in your package repo as `<name>-v<version>`
   (`git tag my-lib-v0.1.0 && git push --tags`).
2. **Run `loft package`** in the package directory: it writes
   `<name>-<version>.tar.gz` and prints the index entry for it.
3. **Upload the tarball** as the asset of a GitHub release for that tag.
4. **Open a PR here** that adds one staging file,
   `submissions/<name>-<version>.json`, holding that entry — the
   recommended route, since it never touches `index.json`.  Editing
   `index.json` directly also works; see SUBMITTING.md for both.
5. **The submission is validated.**  A staging file goes through the
   maintainer's publish run: your tests against the current loft, the
   metadata, and a human review of any native code.  A direct
   `index.json` edit runs `tools/validate.py` on the PR — schema lint,
   tarball verify, and a reproducible build from the tag your release
   url names, which catches a moved tag or a mis-uploaded tarball.
6. **The maintainer signs the new `index.json`** on hardware they
   control and merges.  You sign nothing.

`loft install` clients fetch both `index.json` and
`index.json.sig`, verify the signature against the public key
embedded in the loft binary, then proceed with the install.

**Why local signing?**  The private key never lives in GitHub
Secrets; it stays on hardware the maintainer controls.  Trade-off:
maintainer has to be at a keyboard for each merge.  For an
early-stage ecosystem with weekly publishes this is the right
balance — it removes a third-party trust dependency in exchange
for ~30 seconds of human work per merge.

---

## Schema

See [loft's PKG_REGISTRY.md § Schema](https://github.com/loft-lang/loft/blob/main/doc/claude/PKG_REGISTRY.md#schema)
for the full field reference.  Minimum required per version row:
`url`, `sha256`, `size`, `loft`, `published`.  Everything else
(`deps`, `conflicts`, `replaces`, `provides`, `binaries`,
`prerelease`, `categories`) is optional.

---

## Trust roots

`index.json` is signed with an Ed25519 key held by the loft
maintainers.  The public half is embedded in every loft binary
release (in `src/registry_keys.rs::TRUSTED_PUBLIC_KEYS`).

If you suspect the signing key is compromised, file an issue
ASAP — see [REGISTRY_BOOTSTRAP.md § Trust-root recovery](https://github.com/loft-lang/loft/blob/main/doc/claude/REGISTRY_BOOTSTRAP.md#trust-root-recovery)
for the response procedure.

---

## Mirrors

Anyone can host a mirror by forking this repo and pointing users
at the fork:

```sh
export LOFT_REGISTRY_URL=https://raw.githubusercontent.com/<your-fork>/registry/main/index.json
loft install crypto
```

The loft client refuses to use a mirror that doesn't have a valid
signature from a key in `TRUSTED_PUBLIC_KEYS` (unless
`--allow-unsigned` is passed).  If you want your mirror to sign
its own index with a different key, file an issue to discuss
adding your key to the loft binary's trust root list.

---

## Yanking

Open a PR that removes the version from `versions` and adds it
to the package's `yanked` array.  Yanked versions stay listed
(so existing `loft.lock` pins still resolve) but new installs
skip them.  Use the PR description to record the reason.

---

## Reporting issues

- **Bad / malicious package**: file an issue here AND in the
  package's home repo.  Maintainers will yank pending
  investigation.
- **Registry bug**: file an issue here.
- **Loft client bug** (install fails, sig verify fails): file
  an issue in [loft-lang/loft](https://github.com/loft-lang/loft/issues).

---

## License

Index data (`index.json`) is offered as-is, no warranty.
Tooling (`tools/*.py`, workflows) is LGPL-3.0-or-later.
