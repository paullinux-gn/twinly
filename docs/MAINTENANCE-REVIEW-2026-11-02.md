# Twinly maintenance and security review

Date: 2 November 2026. Scope: first-party Python modules, GTK/CSS integration,
document serialization, recovery and filesystem operations, vault storage/UI,
Office/PDF import and export, CI and packaging inputs. Bundled pypdf was checked
against its upstream release metadata, without modifying third-party source.
This is a code review and regression pass, not an independent penetration test
or a certification that the application is vulnerability-free.

## Implemented changes

| Area | Change and reason |
| --- | --- |
| HTML serialization | Added a forward-only span resolver with per-property precedence and indexed boundaries. Avoids scanning every span for every paragraph and text fragment; preserves the original last-span precedence. |
| Outline | Heading lookup now sweeps spans as it advances through paragraphs, retaining the existing first-matching paragraph-role behaviour. |
| PDF layout | Computes UTF-8 byte offsets once per boundary instead of repeatedly encoding the full text prefix for each formatting attribute. Accented letters and emoji receive the correct attributes. |
| Vault storage | Ordinary commits delete known retired/uncommitted blobs without listing every object. Unlock performs the full interrupted-write cleanup scan. Referenced documents and drafts are retained. |
| Vault validation | Validates every node before following parent chains, checks boolean trash state and rejects active children under trashed folders. Saving a folder or trashed item as an active document is rejected. |
| Vault inactivity | Activity in transient vault dialogs resets the timer. A wall-time check also accounts for time spent suspended, alongside the monotonic inactivity check. Forward clock changes may lock early. |
| Vault trash | Restore and empty-trash disk failures show an error and retain the last committed catalog, instead of escaping from GTK signal callbacks. |
| PDF save | Replaced deprecated FileChooserNative with GTK FileDialog, added a PDF filter, cancellation ownership and protection against late export callbacks after the preview closes or the vault locks. |
| Preview/print lifecycle | Closing destroys preview document/page references, cancels pending file dialogs and active print operations. Vault direct-print destroys its hidden preview in a finally block. Tiny or closed previews skip drawing. |
| Search boundary | Ordinary document overview/search does not descend into vault directories, including stray HTML files placed there externally. |
| Code cleanup | Removed unused imports, two unused exception bindings, the unused vault receive_drop method and an unused credential-dialog error label. Bound the printing image-flush closure explicitly. Runtime imports now use the filesystem module directly where appropriate. |
| Packaging checks | Recursively checks nested Flatpak modules and verifies HTTPS/SHA256 pins on remote sources. CI compiles Python and runs native tests with GTK critical errors fatal. |

Public compatibility exports from model and GTK/HTML-parser virtual methods
remain deliberately: external callers, signal dispatch and framework overrides
are not orphaned code. No mass formatting rewrite was applied.

## Performance evidence

A single local synthetic benchmark used 2,500 paragraphs with 2,500 formatting
spans. The previous serializer took **2.9824 s** and the updated serializer
**0.0176 s**, about **169×** faster for that workload. The HTML output was
byte-for-byte identical. This is an operation-specific single measurement,
not a promise of overall UI speed or a cross-machine benchmark.

Outline tests cover existing heading behaviour. Vault tests assert that routine
saves/settings updates do not list the object directory, that superseded blobs
are removed, and that a failed catalog commit remains recoverable on retry.
Catalog validation/serialization still scales with catalog size.

## Security findings and disposition

- Existing protections retained: bounded HTML/model/images, offline Office
  parsing, no archive extraction, DTD/entity rejection, XML depth/node/attribute
  limits, fixed PDF worker command with time/memory/output limits, descriptor
  anchored filesystem operations and symlink rejection, authenticated vault
  encryption, separate password/recovery key wrapping and writer leases.
- Bandit reported **12 findings, none high severity**. The XML import warning
  is covered by UTF-8-only decoding, explicit DTD/entity rejection and parser
  budgets. XML exports only generate XML; release scripts parse trusted local
  metadata. Subprocess warnings refer to fixed Python commands without shell
  execution and pinned offline build inputs. These findings were reviewed,
  not hidden by blanket suppressions or described as an automated clean bill
  of health.
- Vault lifecycle fixes reduce plaintext retention in preview objects and
  prevent pending PDF exports after locking. They do not guarantee forensic
  memory erasure or erase OS clipboard history, swap, crash dumps or spool files.
- An unlocked vault is accessible to the running session. Old backups remain
  usable with old credentials. Rollback is not detected. Encryption needs a
  separate backup strategy. Folder locations in the remembered-vault list
  remain visible in ordinary preferences.
- Upstream checks: the bundled **pypdf 6.21.4** matches the checked release;
  vault dependencies require **PyNaCl >=1.6.2**, whose upstream release notes
  include the libsodium CVE-2025-69277 update. Actual system libraries still
  depend on the user's OS packages; this review does not scan the whole OS.

Primary references checked:
https://pypdf.readthedocs.io/en/stable/meta/CHANGELOG.html
https://pypi.org/project/pypdf/6.21.4/
https://pynacl.readthedocs.io/en/latest/changelog/

## Validation

- Full native and model regression suite under Python 3.12, GTK 4.14/Xvfb,
  PyNaCl 1.6.2, cffi 2.0.0 and pycparser 2.23, with `G_DEBUG=fatal-criticals`.
- Python compilation; Pyflakes first-party runtime/build scripts; Ruff F and
  B023 checks; source, metadata and embedded English introduction validation.
- Added regression coverage for span precedence, vault garbage collection and
  failed writes, malformed catalogs, dialog activity and suspend-time locking,
  trash failures, late PDF callbacks, PDF save dismissal, Unicode attributes,
  all four supported themes, hidden-preview cleanup and vault search boundaries.
- No GTK criticals or application CSS parsing errors in the tested runtime.
  Headless EGL/DRI3 and missing session-bus warnings describe this test host.

The final test total and result are recorded in REVIEW-VALIDATION.txt beside
this report.

## Remaining limits and publication work

GNOME 51 Wayland blur, real desktop lock/suspend notifications, file portals,
physical printers and a complete Flatpak build need testing on the target
desktop. The headless tests do not validate those integrations. The previously
reported compositor frame-timing warning was not reproducible in Xvfb and is
not claimed fixed.

Large ordinary-library searches still scan directories synchronously; a
cancellable background index is a possible next performance project. The main
editor remains a large controller despite its existing mixins. Splitting it
further should be a separate, tested structural change. An independent vault
security review remains appropriate before stronger security claims.

Publication validation intentionally remains blocked by unchosen public app
identity, project licence, repository URL and developer attribution. The
ordinary offline package validation passes. A fuller About page remains the
previously deferred task.
