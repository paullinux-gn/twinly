# Public preview preparation — 0.4.0

Prepared:

- English Start to note HTML covering every current feature and how to invoke it.
- The owner-approved embedded desk photo, a working companion document link and first-run opening.
- Writable XDG data/configuration paths for installed and Flatpak builds; legacy portable settings preserved.
- HTML file-opening support for desktop launchers.
- Native installer, desktop entry, provisional SVG icon and AppStream metadata.
- GNOME 51 Flatpak manifest, local bundle-build script and a manually triggered GitHub build workflow.
- GitHub native CI, contribution/issue guidance, ignore rules and a real UI screenshot.
- An explicit identity/licence configuration helper and a publication check.

Verified here: **91 passing tests**, source/manifest consistency, valid XML syntax,
embedded HTML parsing/photo/link checks, first start, staged installation contents,
and identity/licence configuration in an isolated copy. GNOME 51 platform availability
was checked against the Flathub runtime reference. Nothing has been published.

Still required before distributing a public release:

1. The owner's real GitHub account/repository, application ID and selected project licence.
2. An actual Flatpak build on a machine with flatpak-builder and working sandbox support.
3. Installation/run tests on GNOME: folder grants, trash, printers, PDF, links and blur.
4. Current desktop/AppStream/Flathub validation and review. The full About page remains deferred.

No untested `.flatpak` binary is presented as a finished build. The manifest and
workflow are the build preparation. README.md and PUBLISHING.md give the commands.

## Security hardening update

The source now includes document resource limits, outside-library link confirmation,
anchored filesystem helpers, private default permissions, pinned CI actions and a
Flatpak manifest without blanket Documents/trash/GVfs access. Sandboxed trash uses
a recoverable private directory inside the chosen library. See SECURITY.md. These
changes do not constitute an independent security audit or a completed sandbox test.

Security update validation: **109 tests pass**, including malformed HTML/image budgets,
private permissions, symlink/race resistance, outside-root confirmation and private
trash restore/delete. Flatpak build and real portal behaviour remain unverified here.
