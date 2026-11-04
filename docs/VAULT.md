# Encrypted workspaces

The interface now calls vaults **encrypted workspaces**. Use **Workspaces → New
workspace**, enter a name, and choose **Encrypted — Password protected**. There
is no default encrypted workspace. Twinly stores its opaque encrypted folder
inside the same managed main folder as standard workspaces. The existing vault
file format, password derivation and recovery key behavior described below are
unchanged. Import workspace makes a verified copy of an older vault without
decrypting it and retains the original. Workspace names and lock status are
visible in the ordinary workspace catalog; encrypted document names are not.

## Use

Install PyNaCl 1.6.2 or newer (`sudo pacman -S python-pynacl` on Arch).
Create an encrypted workspace from the unified Workspaces list. Set a password
of at least 12 characters and save the recovery key separately before opening it.
Losing both credentials means losing the data; Twinly has no password reset
service. Select its locked entry to enter the password or recovery key.

Each encrypted workspace opens in a separate window. Create, rename, move, search, duplicate
and trash documents/folders there. Both editing panes, photos, formatting,
custom styles, autosave and recovery remain inside encrypted storage. Links
use stable document IDs and survive moves and renames within the same encrypted workspace.
Use the header lock button or sidebar Lock encrypted workspace. Closing a encrypted workspace also locks
it and preserves dirty documents as encrypted recovery drafts. Auto-lock is
five minutes by default; choose 1, 5, 15 or 30 minutes in the encrypted workspace sidebar menu.
GTK desktop screen-lock notifications also request locking when the desktop
provides them. Desktop integration varies; use manual locking when needed.
Activity in encrypted workspace dialogs also resets the inactivity timer. Elapsed wall time
provides an additional lock check after suspension; large forward clock changes
may therefore lock the encrypted workspace early.

Open recovery drafts from Recover Documents in the encrypted workspace menu; they reopen
as new unsaved documents. Change Password in that menu rewraps the encrypted workspace key.
The recovery key remains valid. It does not rotate the document encryption key.

HTML, ODT and DOCX import parses in memory, with a conversion warning. The
original remains outside the encrypted workspace. PDF import is unavailable inside encrypted workspaces
because its current extraction path uses temporary plaintext files. Export
HTML/ODT/DOCX, print and PDF require confirmation that the result is plaintext.
Choose a destination outside any encrypted workspace. Internal encrypted workspace links do not work in
exported files. Printing may leave data in the operating system spooler.

## Recovery and backups

Back up the entire encrypted workspace directory while locked. Restore it as a complete
directory. Keep the recovery key away from the backup. Do not synchronise an
unlocked encrypted workspace across computers: the local writer lease is not a distributed
lock. Only one process may write a encrypted workspace on one machine at a time.

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

## Workspace management

Names can be changed in the workspace list, including while unlocked; this does
not rename the encrypted files. Move a workspace to Workspace Trash only while
locked. Trash is inside Twinly’s main folder. Restore returns it to the managed
workspace list; permanent deletion requires another confirmation. Files stay
encrypted throughout. The workspace catalog records public names, IDs and
protection types, never passwords, recovery keys or private document names.
