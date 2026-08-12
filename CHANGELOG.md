# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-12

### Added

- Initial privacy-first, read-only Apple Freeform archive exporter.
- Deterministic Markdown, original-asset, relationship, checksum, and verification outputs.
- CLI workflows for preflight checks, board discovery, archive creation, Scene refinement,
  verification, and Skill installation.
- Optional preservation of an official Freeform PDF as a checksummed visual baseline.
- Reasoned acceptance of reviewed unresolved objects through `scene-map.yml`.
- Archive schema 1.0 and verified structural fingerprints for Freeform database schema
  `user_version=16`, with explicit opt-in for compatible unverified fingerprints.
- Bundled Codex/Claude Skill and synthetic fixture test policy.

[Unreleased]: https://github.com/soso-song/freeform-to-markdown/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/soso-song/freeform-to-markdown/releases/tag/v0.1.0
