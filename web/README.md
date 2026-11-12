# Twinly WebKit editor

The editor source is adapted from Paullinux's Webkit-GN, commit
`ec78fd77634f78fd1269b9c324ae054c294ce8f6`:
https://github.com/paullinux-gn/Webkit-GN

Webkit-GN and Twinly are GPL-3.0-or-later, copyright © 2026 Paullinux.
ProseMirror and its dependencies retain the notices in `licenses/`.

`npm ci && npm run build` rebuilds the committed local bundle. No network is
required at runtime. Twinly's native GTK toolbar controls this editor; the
Webkit-GN application window and its file-access code are not used.
