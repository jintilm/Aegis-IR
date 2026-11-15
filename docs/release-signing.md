# Release signing and verification

Release artifacts are signed with Sigstore cosign in keyless mode from the
GitHub Actions release workflow. No long-lived signing private key is stored in
the repository or in Actions secrets.

## Trust chain

The `release` workflow runs on a version tag or explicit dispatch. It:

1. checks out the exact tag;
2. builds the pinned container and runs the full package test suite;
3. produces the reproducible tarball, `SHA256SUMS` and `SBOM.cdx.json`;
4. requests a GitHub OIDC identity token;
5. signs the tarball and checksum file through Fulcio;
6. records both signatures in the Rekor transparency log;
7. verifies the signatures before creating the GitHub Release.

The expected certificate identity is:

```text
https://github.com/jintilm/Aegis-IR/.github/workflows/release.yml
```

The expected OIDC issuer is:

```text
https://token.actions.githubusercontent.com
```

## Verify

With the tagged version substituted below:

```bash
tag=v0.4.1-alpha
archive="aegis-ir-${tag#v}-linux-x86_64.tar.gz"

cosign verify-blob \
  --bundle "$archive.cosign.bundle" \
  --certificate-identity-regexp \
    '^https://github.com/jintilm/Aegis-IR/.github/workflows/release.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "$archive"

sha256sum -c SHA256SUMS
```

`SHA256SUMS` has its own `.cosign.bundle` and should be verified before using
it to check the archive.
