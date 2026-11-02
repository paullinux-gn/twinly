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
    from gi.repository import Gtk,Adw
    assert (Gtk.get_major_version(),Gtk.get_minor_version()) >= (4,12)
    assert (Adw.get_major_version(),Adw.get_minor_version()) >= (1,4)
except (ImportError,ValueError,AssertionError) as exc:
    print('Twinly mist een afhankelijkheid of vereist GTK ≥ 4.12 en libadwaita ≥ 1.4.')
    print('Installeer op Arch Linux:')
    print('  sudo pacman -S python python-gobject python-cairo gtk4 libadwaita')
    sys.exit(1)
PY
then
    exit 1
fi
exec /usr/bin/python3 "$APP_DIR/editor.py" "$@"
