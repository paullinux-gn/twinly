# Contributing

Twinly is feature-complete for this preview. Focus contributions on correctness,
accessibility, packaging, performance and small UI improvements. Keep the calm native
GTK4/libadwaita design and standalone HTML compatibility.

Run `python3 scripts/check_release.py` and the native tests described in README.md.
Add regression tests for data loss, file operations, links and pane lifecycle changes.
Do not include personal documents, preferences, build outputs or credentials in commits.
The bundled introduction is maintained by `scripts/build_getting_started.py`.

The project licence and public repository identity must be selected before the first
public release. See LICENSING.md and docs/PUBLISHING.md.
