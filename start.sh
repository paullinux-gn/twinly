#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP_DIR"
if ! /usr/bin/python3 - <<'PY'
import sys
try:
    import cairo
    import gi
    gi.require_version('Gtk','4.0')
    gi.require_version('Adw','1')
    gi.require_version('WebKit','6.0')
    from gi.repository import Gtk,Adw,WebKit
    assert (Gtk.get_major_version(),Gtk.get_minor_version()) >= (4,12)
    assert (Adw.get_major_version(),Adw.get_minor_version()) >= (1,4)
except (ImportError,ValueError,AssertionError) as exc:
    print('Twinly is missing a dependency or requires GTK ≥ 4.12 and libadwaita ≥ 1.4, plus WebKitGTK 6.0.')
    print('Install on Arch Linux:')
    print('  sudo pacman -S python python-gobject python-cairo gtk4 libadwaita webkitgtk-6.0 poppler')
    sys.exit(1)
PY
then
    exit 1
fi
exec /usr/bin/python3 "$APP_DIR/editor.py" "$@"
