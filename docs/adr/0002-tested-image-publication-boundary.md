# ADR 0002: Tested-image publication boundary

- Status: Accepted
- Date: 2026-08-04

## Context

ADR 0001 introduced a common functional gate, but build and publication originally shared one nested reusable-workflow graph. Disabling push steps did not create an auditable least-privilege boundary: the same graph still contained registry login, push, and OIDC signing behavior, and nested `GITHUB_TOKEN` permission propagation is easy to misconfigure. GitHub documents that every reusable-workflow calling job has its own permission boundary and nested workflows can only maintain or reduce permissions ([GitHub Actions reusable workflow reference](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations#supported-keywords-for-jobs-that-call-a-reusable-workflow)).

Release publication must also preserve the connection between the bytes that passed the application contract and the bytes sent to the registry. Rebuilding in a privileged job would weaken that connection because mutable Debian repositories can produce different output even at the same commit.

## Decision

### Read-only build graph

The central contract workflow and every family workflow receive only read permissions. Family workflows call the reusable builder for native architecture legs, aggregate the exact expected functional results, and never log in, push, or sign.

The builder accepts `export_image`, not `push`. When export is false, no release artifact is produced. When a trusted release wrapper sets it to true, export occurs only after rootfs policy, smoke, application contract, SBOM, and vulnerability gates succeed.

### Exact tested-image handoff

Immediately after the local build, the builder records the shared image ID behind the primary and architecture tags. Static, smoke, and functional tests use the primary tag. Before export, both tags must still resolve to that captured ID; this prevents a later SBOM or scanner action from silently replacing the image selected for publication.

The builder saves the architecture-tagged local Docker image without rebuilding it. A metadata document binds:

- repository, commit SHA, workflow run ID, and run attempt;
- family, version, Debian suite, architecture, and platform;
- registry reference, primary tag, architecture tag, and local image ID;
- archive file name, byte size, and SHA-256 digest.

The archive and metadata are uploaded under a unique matrix-leg and run-attempt artifact name with one-day retention. A release retry must re-run the entire workflow so every architecture archive belongs to the same attempt; re-running only failed jobs fails closed instead of mixing attempts.

### Release-only publisher

Each family has a thin main-branch release wrapper. Its `release_build` job calls the read-only family workflow and exports tested archives. Only after that call succeeds does `release_publish` receive `packages: write` and `id-token: write` and call the common publisher.

The publisher downloads the named artifact from the current run without a cross-run token or run identifier. It validates all metadata against the current GitHub context, checks archive size and digest, loads the archive, and proves the loaded image ID and platform match the tested image. It then pushes and signs each architecture digest and uploads a small same-attempt digest record. Manifest publication validates the exact expected architecture record set and composes only from immutable `image@sha256:…` references after all declared architecture publishers succeed.

Every reusable-workflow call declares its token permissions explicitly. Write operations and write scopes are confined to the two reusable publisher workflows and the release wrapper call boundary. Pull requests continue to use `pull_request`, never `pull_request_target`.

Release wrappers use a distinct concurrency group per family and ref with cancellation disabled. An active publisher is allowed to finish before the next release starts, preventing concurrent writers from racing on the same tags. Immediately before architecture and manifest writes, publishers require their commit to remain an ancestor of current `main` and compare intervening paths. A newer documentation-only or unrelated-family commit is allowed, but a force-pushed lineage or a change to the same image or any shared release input makes the queued release fail instead of rolling tags back. The tested path classifier and every wrapper's trigger paths must remain identical.

## Consequences

- Pull-request, merge-queue, scheduled contract, and manual validation graphs are structurally read-only.
- Registry credentials and OIDC signing capability are unavailable while untrusted image build and application test code executes.
- The published architecture image is the same Docker image ID and archive that passed the gates; there is no privileged rebuild.
- Same-run provenance and archive integrity are checked before any registry write.
- A release retry must use **Re-run all jobs**; a partial failed-job rerun intentionally cannot reuse or mix archives from an earlier attempt.
- Releases consume additional artifact storage and transfer time, and a sufficiently large Docker archive can hit GitHub artifact limits.
- Architecture tags remain mutable conveniences, but final manifests are constructed from captured immutable architecture digest references and are not affected if an architecture tag later moves.
- A failed multi-architecture release can leave one new architecture tag published while withholding the final manifest. Retry and cleanup policy remain operational work.

## Alternatives considered

- **Keep one conditional build-and-publish graph:** rejected because permission and behavior boundaries remain difficult to audit across nested reusable workflows.
- **Rebuild in the privileged publisher:** rejected because it would not prove that published bytes are the bytes tested before privilege escalation.
- **Push to a staging registry before tests:** rejected because pull-request validation would require registry write access and cleanup of untrusted artifacts.
- **Convert the entire builder to a composite action:** deferred because it would be a much larger workflow rewrite and would not remove the need for an exact tested-image handoff across privilege boundaries.
