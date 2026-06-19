#!/usr/bin/env python3
# Copyright (c) 2026 Jurjen Stellingwerff
# SPDX-License-Identifier: LGPL-3.0-or-later

"""PKG.REG R9 — `loft-lang/registry` PR validation.

Drop this file at `tools/validate.py` in the `loft-lang/registry`
repo.  Wired in by `.github/workflows/pr-validate.yml` (also in this
template directory).

Three gates per PR:

1. **Schema lint** — every package + version row has the required
   fields, types match, schema_version is unchanged; AND every package
   carries correct docs (non-empty description, non-empty categories,
   http(s) homepage) so the auto-generated library catalogue can never be
   incomplete — a doc-less library is invisible and gets reimplemented.
2. **Tarball verify** — download every newly-added `versions.<v>.url`,
   hash it, compare to the PR's declared sha256.  Reject on
   mismatch.  Caught: publisher pasted wrong hash, tarball was
   re-uploaded after PR opened, opportunistic supply-chain swap.
3. **Reproducible-build re-check** — for each newly-added version
   whose homepage points at a public GitHub repo, clone the tag,
   run `loft package`, compare the produced sha256 to the PR's
   claim.  Caught: source repo's tag points at different bytes
   than the uploaded release tarball.

Exits 0 on all-pass; non-zero with line-prefixed errors on any
failure.  The workflow surfaces those lines as PR comments.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

INDEX_PATH = Path("index.json")
SCHEMA_VERSION = 1


def fail(msg: str) -> None:
    print(f"::error::{msg}")
    sys.exit(1)


def load_index() -> dict:
    if not INDEX_PATH.exists():
        fail(f"{INDEX_PATH} not found")
    with INDEX_PATH.open(encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            fail(f"{INDEX_PATH}: invalid JSON: {e}")


def load_previous_index() -> dict:
    """Read the version of index.json on `main` so we can find the
    NEW entries (ones the PR adds)."""
    try:
        out = subprocess.check_output(
            ["git", "show", "origin/main:index.json"], text=True
        )
        return json.loads(out)
    except subprocess.CalledProcessError:
        # First publish — main may not have index.json yet.
        return {"schema_version": SCHEMA_VERSION, "packages": {}}


def gate_schema(idx: dict) -> None:
    if idx.get("schema_version") != SCHEMA_VERSION:
        fail(
            f"schema_version must be {SCHEMA_VERSION}, "
            f"got {idx.get('schema_version')!r}"
        )
    if "packages" not in idx or not isinstance(idx["packages"], dict):
        fail("`packages` must be an object")
    for name, pkg in idx["packages"].items():
        if "versions" not in pkg or not isinstance(pkg["versions"], dict):
            fail(f"package `{name}`: missing or non-object `versions`")
        # Docs gate — a library whose docs are missing or wrong is invisible in
        # the auto-generated catalogue (loft `doc/claude/LIBRARIES.md`), so agents
        # never find it and reimplement it (duplicate code, new bugs).  Reject a
        # package that does not carry correct per-package docs.
        desc = pkg.get("description")
        if not isinstance(desc, str) or len(desc.strip()) < 10:
            fail(
                f"package `{name}`: `description` missing or too short — it is the "
                f"library's one-line docs in the catalogue; write a real summary"
            )
        cats = pkg.get("categories")
        if not isinstance(cats, list) or not cats or not all(
            isinstance(c, str) and c.strip() for c in cats
        ):
            fail(
                f"package `{name}`: `categories` must be a non-empty list of "
                f"non-empty strings (it groups the library in the catalogue)"
            )
        hp = pkg.get("homepage")
        if not isinstance(hp, str) or not hp.strip().lower().startswith("http"):
            fail(
                f"package `{name}`: `homepage` must be an http(s) URL "
                f"(the catalogue links to it for the full API docs)"
            )
        for ver, vobj in pkg["versions"].items():
            for required in ("url", "sha256", "size", "loft", "published"):
                if required not in vobj:
                    fail(f"`{name}` v{ver}: missing required field `{required}`")
            if not isinstance(vobj["sha256"], str) or len(vobj["sha256"]) != 64:
                fail(f"`{name}` v{ver}: sha256 must be 64-char hex")
            if not isinstance(vobj["size"], int) or vobj["size"] <= 0:
                fail(f"`{name}` v{ver}: size must be a positive integer")


def gate_tarball_verify(idx: dict, prev: dict) -> None:
    new_entries = _new_entries(idx, prev)
    for name, ver, vobj in new_entries:
        print(f"[verify] downloading {name} v{ver} from {vobj['url']}")
        try:
            with urllib.request.urlopen(vobj["url"], timeout=60) as resp:
                data = resp.read()
        except Exception as e:  # noqa: BLE001 — surface any failure
            fail(f"`{name}` v{ver}: download failed: {e}")
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha.lower() != vobj["sha256"].lower():
            fail(
                f"`{name}` v{ver}: sha256 MISMATCH\n"
                f"  PR claims: {vobj['sha256']}\n"
                f"  actual:    {actual_sha}"
            )
        if len(data) != vobj["size"]:
            fail(
                f"`{name}` v{ver}: size MISMATCH\n"
                f"  PR claims: {vobj['size']} bytes\n"
                f"  actual:    {len(data)} bytes"
            )
        print(f"[verify] {name} v{ver} sha256 + size match")


def gate_reproducible_build(idx: dict, prev: dict) -> None:
    """Clone the homepage repo at the version tag, run `loft package`,
    compare sha256 to the PR's claim.

    Caught here: PR claims hash X, but the source tree at the tag
    produces hash Y when re-packaged.  Either publisher tampered or
    upstream history rewrote the tag.

    Skipped when the package has no `homepage` (private deps,
    third-party-hosted tarballs).  Schema lint always runs; this gate
    is the additional reproducibility check.

    ## Single-package vs multi-package chunk-repo homepages

    For a **single-package repo**, `homepage` is the repo root
    (`https://github.com/<owner>/<repo>`), the tag is `v<version>`,
    and `loft package` runs at the repo root.

    For a **multi-package chunk repo** (e.g. `loft-libs-core` hosts
    `arguments`, `crypto`, `random` in separate subdirectories), the
    convention is:

      - `homepage` = `https://github.com/<owner>/<repo>/tree/<branch>/<pkg>`
      - tag = `<pkg>-v<version>` (so `arguments-v0.1.1` not `v0.1.1`)
      - `subpath` field carries `<pkg>` (also extractable from the homepage)

    Both shapes coexist in the registry today: `time`, `markdown`,
    `html` (planned) are single-package; `arguments`, `crypto`,
    `random`, `shapes`, `gridmesh`, `web`, `server`, `game_protocol`
    are multi-package chunk-repo members.
    """
    # Matches `https://github.com/<owner>/<repo>/tree/<branch>/<subpath>`.
    # The subpath captures any subdirectory path (may contain slashes
    # for nested packages, though current convention is single-segment).
    chunk_homepage = re.compile(
        r"^(https://github\.com/[^/]+/[^/]+)/tree/[^/]+/(.+?)/?$"
    )

    new_entries = _new_entries(idx, prev)
    for name, ver, vobj in new_entries:
        pkg_meta = idx["packages"][name]
        homepage = pkg_meta.get("homepage", "")
        if not homepage or "github.com" not in homepage:
            print(f"[repro] {name} v{ver} — no GitHub homepage, skipping")
            continue

        m = chunk_homepage.match(homepage)
        if m:
            # Multi-package chunk repo: clone the parent + cd subpath.
            clone_url = m.group(1)
            url_subpath = m.group(2)
            # Prefer the explicit `subpath` field on the version object
            # when present; fall back to the homepage-derived value.  If
            # both exist and disagree, the explicit subpath wins (it's
            # the canonical declaration; the homepage URL is a hint).
            subpath = vobj.get("subpath", url_subpath)
            tag = f"{name}-v{ver}"
        else:
            # Single-package repo: clone the homepage directly, repo
            # root is the package root.
            clone_url = homepage
            subpath = ""
            tag = f"v{ver}"

        with tempfile.TemporaryDirectory() as tmp:
            print(f"[repro] cloning {clone_url} @ {tag}"
                  + (f" (subpath: {subpath})" if subpath else ""))
            try:
                subprocess.check_call(
                    ["git", "clone", "--depth", "1", "--branch", tag, clone_url, tmp],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except subprocess.CalledProcessError as e:
                fail(
                    f"`{name}` v{ver}: git clone of {clone_url}@{tag} failed: "
                    f"{e.stderr.decode(errors='replace') if e.stderr else e}"
                )
            pkg_dir = Path(tmp) / subpath if subpath else Path(tmp)
            if not pkg_dir.is_dir():
                fail(
                    f"`{name}` v{ver}: subpath `{subpath}` does not exist "
                    f"in the cloned tree at {clone_url}@{tag}"
                )
            try:
                subprocess.check_call(
                    ["loft", "package"], cwd=pkg_dir, stdout=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError as e:
                fail(f"`{name}` v{ver}: `loft package` failed: {e}")
            artefact = pkg_dir / f"{name}-{ver}.tar.gz"
            if not artefact.exists():
                fail(f"`{name}` v{ver}: `loft package` produced no artefact")
            actual = hashlib.sha256(artefact.read_bytes()).hexdigest()
            if actual.lower() != vobj["sha256"].lower():
                fail(
                    f"`{name}` v{ver}: REPRODUCIBLE-BUILD MISMATCH\n"
                    f"  PR claims sha256: {vobj['sha256']}\n"
                    f"  rebuilt from src: {actual}\n"
                    f"  clone url:        {clone_url}@{tag}"
                    + (f" (subpath: {subpath})" if subpath else "") + "\n"
                    f"  The source repo at {tag} produces a different "
                    f"tarball than the one uploaded to releases.  Either:\n"
                    f"    (a) the GitHub release tarball is stale — re-upload, OR\n"
                    f"    (b) the git tag was force-pushed — investigate.\n"
                )
            print(f"[repro] {name} v{ver} reproduces from source")


def _new_entries(idx: dict, prev: dict) -> list[tuple[str, str, dict]]:
    """Return list of (name, version, version_object) for rows that
    are present in `idx` but not in `prev`."""
    out: list[tuple[str, str, dict]] = []
    for name, pkg in idx.get("packages", {}).items():
        prev_versions: dict = (
            prev.get("packages", {}).get(name, {}).get("versions", {})
        )
        for ver, vobj in pkg.get("versions", {}).items():
            if ver not in prev_versions:
                out.append((name, ver, vobj))
    return out


def main() -> None:
    idx = load_index()
    prev = load_previous_index()
    print("[gate 1] schema lint")
    gate_schema(idx)
    print("[gate 2] tarball sha256 + size verify")
    gate_tarball_verify(idx, prev)
    skip_repro = os.environ.get("LOFT_VALIDATE_SKIP_REPRO") == "1"
    if skip_repro:
        print("[gate 3] reproducible-build re-check — SKIPPED (env)")
    else:
        print("[gate 3] reproducible-build re-check")
        gate_reproducible_build(idx, prev)
    print("All gates passed.")


if __name__ == "__main__":
    main()
