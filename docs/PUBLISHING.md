# Publishing Twinly

## Release identity

The permanent application ID is **`io.github.paullinux_gn.Twinly`**, for the
[paullinux-gn/twinly](https://github.com/paullinux-gn/twinly) repository.
Developer/copyright attribution is **Paullinux** and the licence is
**GPL-3.0-or-later**. These choices are recorded in `packaging/publication.json`.

The Flatpak manifest, desktop entry, icon, AppStream metadata, installer and CI
use this ID. The displayed application name remains **Twinly**.

Run the publication checks before building:

```sh
python3 scripts/check_release.py --publication
desktop-file-validate data/io.github.paullinux_gn.Twinly.desktop
appstreamcli validate --pedantic data/io.github.paullinux_gn.Twinly.metainfo.xml
```

The metadata uses the supplied screenshot at `docs/screenshots/screenshot.png`.
Review version numbers, release notes and screenshot URLs for each release.

## Existing preview installations

The previous Flatpak ID was `io.github.twinly.Preview`. Flatpak treats the new
ID as another application, with separate storage:

- Previous: `~/.var/app/io.github.twinly.Preview/`
- Permanent: `~/.var/app/io.github.paullinux_gn.Twinly/`

Existing preview data is not automatically moved or deleted. Back it up and
keep the preview installation while verifying the new one. Use **Workspaces →
More… → Import workspace…** to copy the desired old workspace folders into the
new installation; the file portal grants access and the originals are retained.
Rename imported workspaces as needed. Preferences and open-document sessions
are not transferred by workspace import. Encrypted workspaces must be locked
before making their backup/import copy.

Native installations continue using Twinly's existing XDG data/preferences paths;
the Flatpak sandbox change is specific to the application ID.

## Build the Flatpak

On GitHub:

1. Open **Actions → Build Flatpak preview → Run workflow** on `main`.
2. Wait for success and download the **Twinly-Flatpak** artifact.
3. Unzip it to obtain `Twinly-0.4.0.flatpak`.

Or install `flatpak` and `flatpak-builder` locally, then run:

```sh
sh scripts/build-flatpak.sh
```

The bundle is written to `dist/Twinly-0.4.0.flatpak`. Building downloads the GNOME
51 SDK/runtime and pinned dependencies. The workflow builds an artifact; it does
not create a GitHub release or publish to Flathub.

## Test the actual bundle

```sh
flatpak install --user ./Twinly-0.4.0.flatpak
flatpak run io.github.paullinux_gn.Twinly
```

Verify the first-start **Start to note** guide and images, workspace creation,
restart persistence, encryption/unlock/locking, both panes, Search and Trash,
file-portal imports and exports, image insertion, links/moves, PDF and printing.
Check theme/blur behaviour on the intended desktop, including Wayland and
fallback X11 where supported. A passing source test suite is not a substitute
for testing the built sandbox and its portal permissions.

See [SECURITY.md](../SECURITY.md) for resource limits and remaining test gaps.

## Publish a GitHub release

After testing:

1. Open the repository's **Releases → Draft a new release**.
2. Create/select the matching version tag, such as `v0.4.0`.
3. Attach the tested `.flatpak` bundle and a checksum file.
4. Write release notes describing the version and relevant known limitations.
5. Publish the release.

Create the checksum locally with:

```sh
sha256sum Twinly-0.4.0.flatpak > SHA256SUMS
```

## Submit to Flathub separately

A GitHub release does not put the application on Flathub. Follow the current
[Flathub submission process](https://docs.flathub.org/docs/for-app-authors/submission/)
using the permanent ID, public source, licence, metadata and screenshots.
Only describe Twinly as available on Flathub after it has been accepted and
published there.

References:

- https://docs.flatpak.org/en/latest/python.html
- https://docs.flatpak.org/en/latest/manifests.html
- https://docs.flathub.org/docs/for-app-authors/submission/
