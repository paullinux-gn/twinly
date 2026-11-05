# Contributing

Twinly is feature-complete for this preview. Focus contributions on correctness,
accessibility, packaging, performance and small UI improvements. Keep the calm native
GTK4/libadwaita design and standalone HTML compatibility.

Run `python3 scripts/check_release.py` and the native tests described in README.md.
Add regression tests for data loss, file operations, links and pane lifecycle changes.
Do not include personal documents, preferences, build outputs or credentials in commits.
The bundled introduction is the user-authored `data/Start to note.html`. Edit
that HTML directly or export an updated copy from Twinly. Preserve its embedded
images and relative links; run `scripts/check_release.py` afterwards. There is
no generator that should replace its formatting or content.

The project licence and public repository identity must be selected before the first
public release. See LICENSING.md and docs/PUBLISHING.md.
