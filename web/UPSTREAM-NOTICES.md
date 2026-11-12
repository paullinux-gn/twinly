# Bundled editor dependencies

The JavaScript bundle includes the following packages. Their copyright and licence notices are retained in `licenses/`.

| Package | Version | Licence |
|---|---|---|
| orderedmap | 2.1.1 | MIT |
| prosemirror-commands | 1.7.2 | MIT |
| prosemirror-history | 1.5.1 | MIT |
| prosemirror-keymap | 1.2.3 | MIT |
| prosemirror-model | 1.25.12 | MIT |
| prosemirror-schema-basic | 1.2.5 | MIT |
| prosemirror-schema-list | 1.6.0 | MIT |
| prosemirror-state | 1.4.4 | MIT |
| prosemirror-tables | 1.8.5 | MIT |
| prosemirror-transform | 1.12.5 | MIT |
| prosemirror-view | 1.42.9 | MIT |
| rope-sequence | 1.3.4 | MIT |
| w3c-keyname | 2.2.8 | MIT |

WebKitGTK, GTK4, libadwaita and PyGObject are supplied by the operating system. Their own licences apply. esbuild and jsdom are development tools, not included in the runtime bundle. This application retains the repository GPLv3 licence. No WordCraft code is included in the replacement runtime.

## Twinly toolbar styling

Flat toolbar controls, hover/active colours and group separators are adapted from
[Twinly](https://github.com/paullinux-gn/twinly), `theme.py`, revision
`07a2a43f45c1a03de17d43ba4e14a496440558b3`.
Twinly is copyright © 2026 Paullinux, GPL-3.0-or-later; its licence is retained
in `licenses/Twinly-GPL-3.0.txt`. Matching icons use the same GNOME symbolic
icon names as Twinly and are supplied by the installed desktop icon theme.
Additional controls without a Twinly counterpart retain local symbolic SVGs.

The monochrome symbolic application icon is an unmodified Adwaita `x-office-document` icon by the GNOME Project (https://www.gnome.org), from https://download.gnome.org/sources/adwaita-icon-theme/. Distributed under the applicable attribution/share-alike terms retained in `../data/ADWAITA-LICENSE.txt`.

## Flatpak PDF preview tools

Flatpak builds include Poppler 26.07.0 (`pdfinfo`, `pdftoppm` and their supporting library). The pinned source archive and SHA-256 are recorded in `flatpak/io.github.paullinux_gn.WebkitGN.json`, using the Debian source mirror. Poppler's copyright/licence notices are retained in `data/poppler-licenses/` and installed with the app. This dependency is only built for Flatpak; desktop runs use their distribution's Poppler utilities.

Native blur runtime/session requirements follow Twinly `preferences.py` at revision `e08319fe4557a6dcd44afc67a375e48db8dde627` (https://github.com/paullinux-gn/twinly/blob/e08319fe4557a6dcd44afc67a375e48db8dde627/preferences.py). Twinly's GPL-3.0-or-later notice above applies.
