---
id: TASK-10
title: Bake private/corporate CA certs into the gateway image via a certs/ drop-in
status: Done
assignee: []
created_date: '2026-07-16 08:42'
updated_date: '2026-07-16 08:51'
labels: []
dependencies: []
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Provide a reusable build-time extension point so the gateway can clone from git hosts behind a private CA (e.g. Bitbucket Data Center with a corporate root). A certs/ directory holds PEM *.crt files installed into the image's system trust store via update-ca-certificates. Empty by default -> no-op; the published image is unchanged for public hosts. Real cert material stays gitignored.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 certs/ placeholder dir is tracked (certs/.gitkeep) and documented (certs/README.md); .gitignore excludes certs/*.crt and certs/*.pem but keeps .gitkeep
- [x] #2 Dockerfile COPYs certs/ into the system trust store and runs update-ca-certificates, stripping non-.crt files; placed so cert edits don't invalidate the dependency layers
- [x] #3 Empty certs/ is a no-op (build succeeds, image trust store unchanged) — COPY still resolves via .gitkeep
- [x] #4 Offline tests in test_docker_packaging.py assert the Dockerfile CA install, the tracked placeholder, and the gitignore rules
- [x] #5 README documents the Private CA trust extension point under the Gateway section
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented: certs/ drop-in (.gitkeep + README contract), Dockerfile COPY certs/ -> /usr/local/share/ca-certificates/okf-extra/ + update-ca-certificates (strips non-.crt; placed after uv sync so cert edits don't bust dep layers), .gitignore excludes certs/*.crt|*.pem but keeps .gitkeep, 3 offline tests, README Private CA trust section. Offline gate: 146 pytest pass (incl 3 new); ruff check+format clean. Pre-existing test_docker_compose_config_validates fails identically on master (env lacks docker compose v2 plugin) — unrelated. Live docker build is the documented manual network step; base-image pull stalls on cred-helper here. Verified corp chain: leaf git.moscow.alfaintra.net -> Alfa-Bank Sub2 CA 2012 -> self-signed Alfa-Bank Root CA 2012 (root staged gitignored into build context as certs/alfa-root.crt, valid to 2035).

task-reviewer: APPROVED (all 5 AC met, secret hygiene clean, mechanism correct). Merging.

Commit: `587330e` - task-10: Bake private CA certs into gateway image via certs/ drop-in
<!-- SECTION:NOTES:END -->
