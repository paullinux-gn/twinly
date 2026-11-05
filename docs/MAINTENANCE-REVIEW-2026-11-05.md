# Twinly maintenance, scalability and security review

5 November 2026. Baseline: `7e78e9d`. Scope: first-party Python and build scripts,
GTK lifecycle and search, document/model limits, encrypted storage, imports,
filesystem safeguards, installed payload and pinned dependencies. This is a code
review, automated analysis and synthetic stress test, not an independent
penetration test or a security certification.

## Changes implemented

- **Virtual workspace search.** Standard and encrypted searches now retain
  lightweight result metadata and let `Gtk.ListView` create rows for the visible
  area. Previously a search created an `Adw.ActionRow` for every document.
  Filtering uses cached normalized names/paths, without reading document bodies.
  Encrypted search models and recycled labels are cleared when their panel closes
  or the workspace locks. A regression verifies that 10,000 results create fewer
  than 500 row widgets and that filtering still finds the last result.
- **Release old formatting objects.** Restoring a document now removes its old
  format tags from GTK's tag table instead of retaining every font/colour/link
  ever opened. Undo can recreate tags from document state. Locking also releases
  tags and their Python metadata. Search highlighting remains separate.
- **Bound native layout work.** Text still supports 4 MiB UTF-8 and 20,000
  paragraph breaks, but each paragraph is now limited to **16,384 characters**.
  A 65,536-character unbroken paragraph took 10.62 seconds to restore; a much
  longer one did not finish inside a 90-second benchmark. Oversized imports are
  rejected before replacing the current document. Clipboard replacements are
  checked before GTK deletes the selection, and insertion/deletion guards prevent
  oversized text or paragraph joins. Input is not silently shortened.
- **Smaller installed templates.** Source introductions remain editable HTML.
  Installed introductions use deterministic gzip and are expanded to ordinary
  HTML when creating a workspace. A staging test compares expanded files byte
  for byte with the originals. Full fonts, glyph coverage, PDF support and
  licence notices are retained.
- **Verified cleanup.** Removed seven unused first-party imports, duplicated
  floating-toolbar CSS, and the obsolete hidden Vault button. Preserved GTK
  callbacks, parser overrides, compatibility exports and migration code: static
  references alone cannot establish that those are orphaned. Bound release-tool
  replacement callbacks explicitly to their loop values.
- **Visible monitoring limit.** Reaching the existing 2,000-folder monitoring
  cap now produces a user-visible warning. Extra folders remain searchable but
  do not receive automatic filesystem refreshes.

## Measured results

Synthetic fixtures on the same Linux workspace; Python 3.13.5, GTK 4.18.6,
libadwaita 1.7.6, Cairo renderer and Xvfb. Filesystem cache and host CPU load vary.
Peak RSS is cumulative for each process, not memory allocated by one operation.
The measurements establish exercised cases, not guarantees for arbitrary hardware.

| Case | Before | After |
| --- | ---: | ---: |
| Open name/path search over 10,000 documents in 100 folders | 10.62 s | 1.91 s |
| Filter that search, including pending GTK work | 0.78 s | 0.48 s |
| Peak RSS after filtering in that fixture | 526.3 MiB | 134.5 MiB |
| Installed app payload | 7,087,050 bytes | 6,360,989 bytes |

The installed payload is about **10% smaller**, saving **726,061 bytes** overall.
This includes application code, fonts, bundled pypdf and notices. It excludes the
GNOME platform, crypto libraries, user documents and Flatpak container overhead;
these figures are not a measured Flatpak download size.

Further successful cases:

| Fixture | Result |
| --- | --- |
| 3,000 folders containing 30,000 documents | Editor setup 1.25 s; search opening 1.94 s; filtering 0.38 s |
| Peak RSS after search in the 30,000-document fixture | 178.7 MiB |
| Approximately 4 MiB text split into normal paragraphs | Editor restore 0.19 s; snapshot 0.003 s in the larger fixture |
| 20,000 paragraph breaks | HTML export/import 0.21 / 0.75 s |
| 20,000 formatting spans | HTML export/import 0.29 / 1.40 s |
| 10,000 encrypted catalog items | Catalog validation 0.096 s; 10,001 items correctly rejected |

The encrypted result tests metadata validation at capacity, not the time to
individually create/write 10,000 encrypted documents. The text stress cases are
plain text; large embedded photos and complex formatting have additional costs.
Raw measurements and dependency results are in
[SCALABILITY-RESULTS-2026-11-05.json](SCALABILITY-RESULTS-2026-11-05.json).

Reproduce with the system Python and installed GTK dependencies:

```sh
python3 scripts/benchmark_scalability.py
xvfb-run -a python3 scripts/benchmark_scalability.py --gui --folders 100 --documents-per-folder 100
xvfb-run -a python3 scripts/benchmark_scalability.py --gui --folders 3000 --documents-per-folder 10
```

Fixtures and settings are temporary and removed afterwards. The benchmark has a
120-second diagnostic timeout and permits at most 100,000 generated documents.

## Security checks

- Reviewed bounded import reads, descriptor-anchored filesystem writes, safe
  moves/trash, HTML/link sanitization, image budgets, Office ZIP/XML limits,
  encrypted storage and pending asynchronous callbacks. Existing regression
  tests exercise symlink attacks, malformed data, oversized images, save
  conflicts, failed writes and plaintext absence. New tests cover paragraph
  denial of service, rejected selection replacement and format-tag retention.
- Ruff F/B023 checks pass for first-party runtime/build scripts. Vulture found
  unused positional callback arguments; these are required signal signatures
  and were not deleted. Bandit reported no high-severity findings. Its XML
  warnings were reviewed: Office XML rejects DTD/entity declarations before
  parsing and enforces size, nesting, node and attribute limits; build scripts
  parse repository metadata rather than imported documents. Scanner output is
  evidence to review, not proof of safety.
- PyPI advisory checks reported **no known vulnerabilities** for pinned
  PyNaCl 1.6.2, cffi 2.0.0, pycparser 2.23 and bundled pypdf 6.21.4 at the time of
  this review. GTK, the operating system and the GNOME runtime were not covered
  by that Python advisory query. Dependencies still require updates and review.
- The Flatpak manifest retains no blanket home/host filesystem or network
  permission. File portals and bounded readers handle selected imports. PDF
  extraction stays in its constrained subprocess and anonymous memory output;
  converted encrypted-workspace documents use encrypted storage.

## Validation and remaining limits

Full suite with GTK criticals fatal:

- Python 3.13 / GTK 4.18: **286 tests, OK, one skipped** (legacy GTK icon guard).
- Ubuntu 24.04 / Python 3.12 / GTK 4.14 / libadwaita 1.5, normal CI display:
  **286 tests, OK, one skipped** (resize test requires a wider display).
- Wide-display resize checks were exercised separately earlier; source,
  metadata, introduction, installation staging, compilation and static checks
  pass. Clipboard/package checks were repeated after the final paste-context
  guard and introduction updates.

One **unresolved native tooltip issue** was observed twice in an extra-wide
2560×1440 full-suite run on GTK 4.14. GDB placed the failure in GTK's pending
`gtk_tooltip_show_tooltip` path calling `gdk_surface_get_device_position` after
its surface was gone. With `G_DEBUG=fatal-criticals` that aborts the test process.
The normal CI-display full run passes. This review does not establish whether
application lifecycle timing contributes, does not claim the issue fixed, and
does not suppress GTK criticals to obtain a passing run. Real desktop tooltip
and window/dialog teardown testing remains necessary.

Practical limits remain:

- Standard workspaces: 30,000 documents / 3,000 folders exercised. Search still
  scans directories synchronously; slow disks, network mounts and much larger
  trees may pause the UI. A cancellable background index is the next larger
  architectural improvement. Only 2,000 folders are monitored automatically.
- Encrypted workspaces: at most **10,000 catalog items**, including folders and
  trashed items, **100 drafts**, and an **8 MiB catalog**. Whole-catalog validation,
  encryption and filesystem sync mean edits may become slower near capacity.
- Documents: **4 MiB UTF-8 text, 20,000 paragraph breaks, 16,384 characters per
  paragraph, 20,000 formatting spans**, plus the existing image/HTML limits in
  [SECURITY.md](../SECURITY.md). Undo retains at most 60 structural snapshots with
  an estimated 32 MiB budget, while retaining at least the current entry. These
  are per-document safeguards, not a hard process-wide RAM cap.
- The main editor remains a large controller. A broad module split would be a
  separate structural change, not a justified automatic dead-code deletion.
- Actual Flatpak build/download size, Wayland blur, desktop suspend/lock, portal
  interaction and physical printers need target-desktop validation. No claim
  of an independent cryptographic or penetration audit is made.
