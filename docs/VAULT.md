# Encrypted vault — preview

## Use

Install PyNaCl 1.6.2 or newer (`sudo pacman -S python-pynacl` on Arch).
In the normal sidebar menu choose Vault, then New Vault and choose a **new**
directory name. Set a password of at least 12 characters. Save the recovery
key separately before opening the vault. Losing both credentials means losing
the data; Twinly has no password reset service. Open Vault from the sidebar
menu or bottom lock icon. Add an existing vault once, then use Unlock beside
its remembered entry and enter the password or recovery key.

Each vault opens in a separate window. Create, rename, move, search, duplicate
and trash documents/folders there. Both editing panes, photos, formatting,
custom styles, autosave and recovery remain inside encrypted storage. Links
use stable document IDs and survive moves and renames within the same vault.
Use the header lock button or sidebar Lock Vault. Closing a vault also locks
it and preserves dirty documents as encrypted recovery drafts. Auto-lock is
five minutes by default; choose 1, 5, 15 or 30 minutes in the vault sidebar menu.
GTK desktop screen-lock notifications also request locking when the desktop
provides them. Desktop integration varies; use manual locking when needed.
Activity in vault dialogs also resets the inactivity timer. Elapsed wall time
provides an additional lock check after suspension; large forward clock changes
may therefore lock the vault early.

Open recovery drafts from Recover Documents in the vault menu; they reopen
as new unsaved documents. Change Password in that menu rewraps the vault key.
The recovery key remains valid. It does not rotate the document encryption key.

HTML, ODT and DOCX import parses in memory, with a conversion warning. The
original remains outside the vault. PDF import is unavailable inside vaults
because its current extraction path uses temporary plaintext files. Export
HTML/ODT/DOCX, print and PDF require confirmation that the result is plaintext.
Choose a destination outside any vault. Internal vault links do not work in
exported files. Printing may leave data in the operating system spooler.

## Recovery and backups

Back up the entire vault directory while locked. Restore it as a complete
directory. Keep the recovery key away from the backup. Do not synchronise an
unlocked vault across computers: the local writer lease is not a distributed
lock. Only one process may write a vault on one machine at a time.

Writes use private permissions, immutable encrypted document objects and
atomic encrypted catalog replacement. An interrupted save retains the prior
committed catalog. Unreferenced encrypted objects are collected after commit.
If locking cannot write a dirty draft, it retains an encrypted copy in RAM and
warns you: keep Twinly running and unlock again to retry. Quitting or losing
power in that situation loses those changes. No ciphertext can recover a
corrupt/missing key header or replace a backup.

## Format version 1

`vault.json` is a bounded public header with UUID, Argon2id parameters/salt and
two authenticated wrapped-key slots. The production password KDF uses three
passes and 256 MiB. A random 256-bit vault key is wrapped separately by the
password-derived key and a random 256-bit recovery key, using XChaCha20-Poly1305.
Key wrapping authenticates its version, vault identity, purpose and parameters.

`catalog.bin` encrypts names, hierarchy, document references, drafts, settings
and a generation counter. `objects/<random UUID>.bin` holds encrypted HTML or
recovery data. Secretstream uses 64 KiB chunks, authenticated final tags and
context bound to vault/purpose/document/blob identities. Truncation, reordering,
appended data and substitution are rejected. Header/KDF/catalog/document limits
are checked before expensive processing. `writer.lock` holds an advisory lease.

## Limits

This is encryption at rest, not protection from a compromised running session.
Python and GTK cannot promise forensic memory wiping. OS swap, crash dumps,
clipboard history, screenshots and external exports can retain plaintext.
The app clears its owned clipboard on lock but cannot erase clipboard history.
Vault presence, directory location, file sizes/counts and timestamps are public.
Old backups remain usable with old credentials; rollback is not detected.
There is no independent security audit yet. Flatpak crypto build sources are
pinned in the manifest; a complete Flatpak build still needs release validation.

### Remembered vaults

In the regular Twinly window choose **Vault** in the sidebar menu or click
the bottom lock icon. The right pane lists remembered vaults, with an Unlock
button and controls to create a new vault or add an existing one. Newly created
and added vaults are remembered automatically. Locate vaults created before
this update once with Add Existing Vault. Removing a list entry leaves the
vault files intact. Missing folders show Locate instead of Unlock.
Only directory locations are saved in ordinary preferences, never passwords,
recovery keys or private document names. Vault folder names and locations are
therefore visible in the normal window.
