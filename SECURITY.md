# Security policy

## Scope

Aegis-IR is a software-asset-protection toolkit. Security reports of interest:

- bugs that break the semantics-preserving guarantee of the default profile;
- build-reproducibility breaks;
- ways a protection transform's *documented* effect claim is wrong.

Out of scope: using this toolkit to attack third-party software; requests for
evasion-oriented features (see `docs/threat-model.md` §5).

## Reporting

Do not open public issues for security-relevant bugs. Report privately via
GitHub Security Advisories ("Report a vulnerability" in the Security tab).

We aim to acknowledge within 72 hours. Known limitations that are documented
in `docs/threat-model.md` are not vulnerabilities.

## Supported versions

Pre-alpha: only `main` at the latest tag receives fixes.