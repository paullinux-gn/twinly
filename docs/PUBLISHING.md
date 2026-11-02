# Publishing checklist

The source, initial content, metadata, installer, Flatpak manifest and CI workflows
are prepared. Nothing has been pushed, uploaded as a GitHub release or submitted
to Flathub. A manifest is not an already-tested Flatpak binary.

## 1. Set the real identity and licence

Create/choose your GitHub account and repository name. Choose an application ID
derived from an identity you control. The current `io.github.twinly.Preview`
is the existing preview identifier, not a claim that a GitHub account is owned.
Choose the project licence and copyright holder explicitly:

```sh
python3 scripts/configure_release.py \
  --app-id io.github.YOUR_ACCOUNT.Twinly \
  --repository https://github.com/YOUR_ACCOUNT/twinly \
  --author 'YOUR COPYRIGHT HOLDER NAME' \
  --license MIT
python3 scripts/check_release.py --publication
```

`MIT` is an example of syntax, not a licence chosen on the owner's behalf.
The helper also supports `GPL-3.0-or-later`. For another licence, add its full text
and AppStream SPDX identifier deliberately. Application-ID segments cannot contain
hyphens. The helper updates application IDs, filenames, manifest, desktop entry,
metadata, installer and workflows, then writes LICENSE and developer/repository data.
Do this **before distributing Flatpaks**, because changing IDs later changes storage
and installation identity.

## 2. Review the public source

Confirm README, LICENSE, CREDITS, provisional icon and English guide. Add real
screenshots to AppStream after the public repository provides stable screenshot URLs.
Review SECURITY.md and test the tightened portal permissions. The fuller About dialog remains deferred as requested. Do not include personal
Documenten/Instellingen directories, logs, credentials or local build outputs.
No project git history or invented public URLs have been created for you.

## 3. Push to GitHub

From the clean project directory, after creating an empty repository:

```sh
git init -b main
git add .
git commit -m 'Prepare Twinly preview'
git remote add origin https://github.com/YOUR_ACCOUNT/twinly.git
git push -u origin main
```

Review `git status` before committing. Native tests run on push and pull requests.
In GitHub Actions, run **Build Flatpak preview** manually. Download its artifact,
which contains the `.flatpak` bundle. The workflow does not create a public release.

## 4. Verify the actual Flatpak

Install the bundle on a clean GNOME user account. Verify first-start English guide
and photo, restart persistence, files outside the sandbox through the folder picker,
HTML file association, image insertion, links/moves, both panes, the sandbox’s private library trash,
restoration, PDF, printers, light/dark and blur. Check on Wayland and fallback X11.
GNOME runtime 51 availability was checked, but a full sandbox build/run must still
be completed on a host with working Flatpak and user namespaces.

Validate metadata with current tools:

```sh
desktop-file-validate data/APP_ID.desktop
appstreamcli validate --pedantic data/APP_ID.metainfo.xml
```

Replace APP_ID with your configured ID. A public catalogue submission also needs
real homepage/issue URLs, developer attribution, a selected licence, actual screenshots
and any current Flathub review requirements. Do not call the app “on Flathub” before
it is accepted and published there.

## 5. Make a release

After all checks, create a version tag and a GitHub release, attach the tested
Flatpak and checksums, and state runtime requirements and preview limitations.
Publishing to GitHub Releases and submitting to Flathub are separate operations.

References:
- https://docs.flatpak.org/en/latest/python.html
- https://docs.flatpak.org/en/latest/manifests.html
- https://docs.flathub.org/docs/for-app-authors/submission/
- https://www.freedesktop.org/software/appstream/docs/chap-Metadata.html
