# Security safeguards

Twinly is a local document editor. These protections reduce risk; they are not
an independent security audit or a guarantee against every malicious file or a
compromised account. Documents remain plaintext HTML, including embedded photos.

## Untrusted documents

Imports are parsed as data, not executed in a web engine. JavaScript is not run,
remote images are not fetched, and only supported HTTP(S) or relative HTML links
are retained. An internal link that resolves outside the selected library asks
for confirmation and shows its resolved destination before opening.

Resource limits are enforced before replacing the current document:

| Resource | Limit |
| --- | ---: |
| HTML input | 64 MiB |
| Text | 4 MiB UTF-8 |
| Paragraph breaks | 20,000 |
| Formatting spans | 20,000 |
| HTML nesting | 128 levels |
| HTML elements | 100,000 |
| Attributes per start tag | 64 |
| Ordinary start-tag length | 16 KiB |
| Images | 128 |
| Encoded image file | 20 MiB each |
| Image dimensions | 16 megapixels each |
| Total image dimensions | 32 megapixels per document, approximately 128 MB RGBA |
| Total embedded image bytes | 32 MiB per document |
| Print-preview pages | 1,000 |

Image headers are checked before passing bytes to the native decoder, with a
second pixel check in the decoder callback. Interactive photo insertion also
checks the aggregate budget. Invalid or over-limit imports leave the open document
unchanged. Limits apply per document, not to the process's total resident memory.

## Files and concurrent changes

On Linux, reads and writes use directory descriptors opened without following
symlinks. Reads are bounded, reject special files/FIFOs, and return the identity of
the file that was actually read. Save conflict checks use that identity. New files
and moves use atomic no-replacement operations; existing saves use temporary files,
fsync, identity rechecks and atomic replacement. PDFs use the same safe writer.

These measures resist symlink redirection and accidental overwrite races. They do
not provide a full compare-and-swap transaction against an adversary who can modify
all files as the same user, or protect against root, a compromised kernel or a
malicious filesystem. Shared edits by other programs still require conflict handling.
Some unusual filesystems may reject safe move operations rather than permit an
unsafe fallback. Directory fsync is best-effort where the filesystem does not
support it; file data fsync is still required.

## Privacy

New app-owned directories use mode 0700. New documents and preference files use
0600; preference saves also restrict an existing preference file to 0600. Existing
user documents retain their permissions on save, and user-selected shared libraries
are not silently made private. Nothing here is encryption: copies, backups and
existing shared folders remain subject to their own access controls.

## Flatpak

The manifest requests no blanket home, Documents, host-trash, GVfs D-Bus or network
access. Additional files/directories must be selected through the file portal.
Wayland/fallback X11, graphics, IPC and CUPS are retained for display and printing.
Fallback X11 and printing expose host integration; prefer Wayland when available.

The Flatpak uses a recoverable `.twinly-trash` directory inside the chosen library.
It supports restoring without overwrite and emptying without following symlinks.
The native app continues to use the GNOME system trash. This keeps trash usable
without granting the sandbox access to the entire host trash service.

A real Flatpak build/run and desktop portal/printing tests are still required. A
manifest review and native tests do not establish sandbox security.

## Builds and reporting

GitHub Actions are pinned to commit hashes rather than floating tags. Updates to
those hashes and the GNOME runtime should be reviewed and kept current. The project
licence/public identity still need the owner's choices before publication.

Before a public security contact is configured, report ordinary reproducible bugs
through the repository's issue process. Do not post private documents, credentials
or sensitive exploit details publicly. Once the repository exists, its owner should
enable a private vulnerability reporting channel and document it here.

## Office import

ODT/DOCX import reads packages in memory without extracting paths or running
macros, fields, scripts or office processes. No external images or linked content
are fetched. Limits: 64 MiB input, 128 MiB declared uncompressed size, 4096 ZIP
entries, 16 MiB per XML part, plus the normal text/image/formatting budgets.
Duplicate and traversal member paths, encrypted ZIP entries, DTD/entity
declarations, deep or excessive XML, unsupported encodings and invalid image
headers are rejected. Conversion produces a separate HTML file using the same
anchored, exclusive file writer. Existing files and source documents are not
overwritten. This is a supported-content conversion, not a full Office renderer.

## PDF text import

Only the PDF text layer is read; no OCR, scripts, actions, attachments, links
or remote resources are executed or retrieved. Encrypted files are rejected.
The vendored pypdf parser runs with isolated Python (-I), 512 MiB address-space,
20-second CPU, 30-second wall-time and bounded-file-output limits. Input is
read through the anchored file reader (64 MiB maximum); extraction is limited
to 1000 pages, 32 MiB decoded content per page, 4 MiB text and the ordinary
paragraph limit. A malformed or over-budget PDF leaves the editor untouched.
Resource limits contain parser failures; the subprocess is not a full OS
security sandbox. vendor/README.md records the pinned upstream version and
wheel SHA256; vendor/pypdf-LICENSE.txt preserves its BSD-3-Clause licence.

## Optional encrypted vault

Ordinary HTML documents and ordinary recovery remain plaintext. The optional
vault encrypts document content, embedded pictures, names, folders, drafts,
trash and private style settings at rest. It uses PyNaCl/libsodium Argon2id,
XChaCha20-Poly1305 key wrapping and authenticated secretstream encryption.
See docs/VAULT.md for the versioned format and recovery procedure.

An unlocked vault is accessible to the current process and user session.
Python/GTK cannot guarantee complete memory erasure; swap, crash dumps,
malware, screenshots and clipboard managers are outside this protection.
Vault existence, sizes, counts and modification times remain observable.
Exports and printing deliberately disclose plaintext after confirmation.
Imports do not erase their original files. Password changes do not revoke
old backups, which may still be unlocked with the old password. Restoring an
older authentic vault is not detected as rollback. Encryption is not a backup.
This implementation is a preview and has not been independently audited.
