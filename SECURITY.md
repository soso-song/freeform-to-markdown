# Security Policy

## Supported versions

Security and privacy fixes are applied to the latest released minor version and the `main` branch.
Pre-release builds are supported only until a newer pre-release or stable version is available.

| Version | Supported |
| --- | --- |
| Latest `0.1.x` | Yes |
| `main` before the first release | Yes |
| Older versions | No |

## Report a vulnerability privately

Use GitHub's **Report a vulnerability** form in the repository Security tab. Do not open a public
issue for a vulnerability, exposed secret, path disclosure, source-mutation risk, or case in which
generated output leaks information that should have been filtered.

Include only synthetic reproduction data. Do not attach a real Freeform database, asset, board
export, screenshot, archive, or private URL. A useful report contains:

- the affected version and macOS version;
- the output of `freeform-to-markdown doctor` after removing paths and board details;
- impact and expected behavior;
- minimal reproduction steps using a fixture created from scratch;
- a proposed mitigation, if known.

Maintainers will acknowledge a complete report within seven days, provide a status update within
fourteen days, and coordinate disclosure after a fix is available. Timelines may change with
severity or reproduction complexity.

## Security boundaries

The project treats the following as security-sensitive invariants:

- Freeform source files and directories are never modified.
- Unknown database schemas fail closed.
- Original attachments remain byte-identical.
- Generated searchable text does not intentionally expose recognized credentials or sensitive URL
  parameters.
- Archive paths cannot escape the selected output directory.
- Symlinks and malformed asset names cannot redirect reads or writes outside approved roots.
- No telemetry or network upload occurs in the core export path.

Local access control, backups, disk encryption, and the contents of retained originals remain the
operator's responsibility. An exported archive can contain sensitive original attachments even
when its Markdown indexes have been filtered.
