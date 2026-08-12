# Governance

`freeform-to-markdown` is a maintainer-led open-source project. Soso Song is the initial maintainer
and final steward of the project's privacy, compatibility, and archive-schema guarantees.

## How decisions are made

- Small fixes and documentation improvements are decided in pull-request review.
- User-visible CLI or archive-schema changes begin with an issue or Discussion and include a
  migration plan.
- Privacy, source-integrity, and fail-closed behavior take precedence over convenience or broader
  compatibility claims.
- The maintainer seeks consensus for substantial changes. When consensus is not possible, the
  maintainer records the decision and rationale publicly.

## Maintainers

Maintainers triage issues, review changes, manage releases, moderate community spaces, and protect
the repository. New maintainers may be invited after sustained, constructive contributions and a
demonstrated understanding of the privacy model. The initial maintainer approves appointments and
may revoke access to protect users or the project.

## Contributions and releases

All contributors follow [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). A pull request requires passing CI and maintainer approval;
the project uses squash merges. Releases require:

- passing Linux and macOS CI;
- a clean repository privacy scan;
- archive-schema and compatibility notes for relevant changes;
- an updated changelog;
- signed or GitHub-attested build artifacts and checksums.

Emergency security releases may use an abbreviated review process, followed by public
documentation after coordinated disclosure.

## Project assets

The repository, package name, domains, and project accounts are managed for the benefit of the
community. If the initial maintainer steps down, stewardship should transfer to an established
maintainer who agrees to preserve the Apache-2.0 license and privacy-first charter.
