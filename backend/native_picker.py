#!/usr/bin/env python3
import sys
import os
import json
import argparse

def main():
    parser = argparse.ArgumentParser(description="Open native OS file chooser dialog")
    parser.add_argument("--initial-path", default="", help="Initial file or folder path")
    parser.add_argument("--title", default="Select Video File", help="Dialog window title")
    parser.add_argument("--timeout-ms", type=int, default=0, help="Optional timeout in ms to cancel dialog")
    args = parser.parse_args()

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GLib
    except Exception as e:
        print(json.dumps({"error": f"Failed to import GTK: {str(e)}", "cancelled": True}))
        sys.exit(1)

    init_ok, _ = Gtk.init_check()
    if not init_ok:
        print(json.dumps({"error": "Cannot open display for GTK file dialog", "cancelled": True}))
        sys.exit(1)

    dialog = Gtk.FileChooserDialog(
        title=args.title,
        action=Gtk.FileChooserAction.OPEN
    )
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OPEN, Gtk.ResponseType.OK
    )
    dialog.set_default_response(Gtk.ResponseType.OK)

    # Filter: Video files
    filter_video = Gtk.FileFilter()
    filter_video.set_name("Video files (*.mp4, *.mov, *.mkv, *.webm, *.avi)")
    filter_video.add_mime_type("video/*")
    for pattern in ["*.mp4", "*.mov", "*.mkv", "*.webm", "*.avi", "*.m4v", "*.MP4", "*.MOV"]:
        filter_video.add_pattern(pattern)
    dialog.add_filter(filter_video)

    # Filter: All files
    filter_all = Gtk.FileFilter()
    filter_all.set_name("All files (*.*)")
    filter_all.add_pattern("*")
    dialog.add_filter(filter_all)

    # Set initial directory or file
    if args.initial_path:
        norm_path = os.path.abspath(os.path.expanduser(args.initial_path))
        if os.path.isfile(norm_path):
            dialog.set_filename(norm_path)
            parent_dir = os.path.dirname(norm_path)
            if os.path.isdir(parent_dir):
                dialog.set_current_folder(parent_dir)
        elif os.path.isdir(norm_path):
            dialog.set_current_folder(norm_path)

    # Ensure dialog is brought forward
    dialog.set_modal(True)
    dialog.set_keep_above(True)

    if args.timeout_ms > 0:
        GLib.timeout_add(args.timeout_ms, lambda: (dialog.response(Gtk.ResponseType.CANCEL), False)[1])

    response = dialog.run()
    selected_path = None
    cancelled = True

    if response == Gtk.ResponseType.OK:
        selected_path = dialog.get_filename()
        cancelled = False

    dialog.destroy()

    # Process pending GTK events to cleanly close window
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)

    print(json.dumps({
        "path": selected_path,
        "cancelled": cancelled
    }))

if __name__ == "__main__":
    main()
