#!/usr/bin/env python3
import sys
import os

# Ensure system dist-packages are in sys.path when running inside a Python virtual environment on Linux
for p in [
    "/usr/lib/python3/dist-packages",
    "/usr/local/lib/python3/dist-packages",
    f"/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages",
    f"/usr/local/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages"
]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.append(p)

import json
import argparse
import subprocess
from typing import Optional, Tuple

def pick_file_macos(title: str, initial_path: str) -> Tuple[bool, Optional[str]]:
    """Native macOS Finder file picker via osascript."""
    safe_title = title.replace('"', '\\"')
    script = f'''
    tell application "System Events"
        activate
    end tell
    try
        set chosenFile to choose file with prompt "{safe_title}" of type {{"public.movie", "public.audio", "mp4", "mov", "mkv", "avi", "webm", "wav", "mp3"}}
        return POSIX path of chosenFile
    on error number -128
        return ""
    end try
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
        if res.returncode == 0:
            out = res.stdout.strip()
            return (True, out if out else None)
        return (False, None)
    except Exception:
        return (False, None)

def pick_file_windows(title: str, initial_path: str) -> Tuple[bool, Optional[str]]:
    """Native Windows Explorer file picker via PowerShell."""
    init_dir = initial_path.replace('"', '`"') if initial_path and os.path.exists(initial_path) else ""
    ps_code = f'''
    [System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null
    $d = New-Object System.Windows.Forms.OpenFileDialog
    $d.Title = "{title}"
    $d.Filter = "Video & Audio Files (*.mp4;*.mov;*.mkv;*.webm;*.avi;*.wav;*.mp3)|*.mp4;*.mov;*.mkv;*.webm;*.avi;*.wav;*.mp3|All Files (*.*)|*.*"
    if ("{init_dir}" -ne "") {{
        $d.InitialDirectory = "{init_dir}"
    }}
    $d.ShowHelp = $false
    if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
        [Console]::WriteLine($d.FileName)
    }}
    '''
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=300
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            return (True, out if out else None)
        return (False, None)
    except Exception:
        return (False, None)

def pick_file_gtk(title: str, initial_path: str, timeout_ms: int = 0) -> Tuple[bool, Optional[str]]:
    """Linux GTK 3.0 file picker using FileChooserNative (XDG Desktop Portal) or FileChooserDialog."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk, GLib

        init_ok, _ = Gtk.init_check()
        if not init_ok:
            return (False, None)

        # 1. Try Gtk.FileChooserNative first (official portal integration for Wayland, COSMIC, GNOME, etc.)
        try:
            native = Gtk.FileChooserNative.new(
                title,
                None,
                Gtk.FileChooserAction.OPEN,
                "_Open",
                "_Cancel"
            )
            native.set_modal(True)

            filter_video = Gtk.FileFilter()
            filter_video.set_name("Video & Audio files (*.mp4, *.mov, *.mkv, *.webm, *.avi, *.wav, *.mp3)")
            for pattern in ["*.mp4", "*.mov", "*.mkv", "*.webm", "*.avi", "*.wav", "*.mp3", "*.m4v", "*.MP4", "*.MOV"]:
                filter_video.add_pattern(pattern)
            native.add_filter(filter_video)

            filter_all = Gtk.FileFilter()
            filter_all.set_name("All files (*.*)")
            filter_all.add_pattern("*")
            native.add_filter(filter_all)

            if initial_path:
                norm_path = os.path.abspath(os.path.expanduser(initial_path))
                if os.path.isfile(norm_path):
                    native.set_filename(norm_path)
                    parent_dir = os.path.dirname(norm_path)
                    if os.path.isdir(parent_dir):
                        native.set_current_folder(parent_dir)
                elif os.path.isdir(norm_path):
                    native.set_current_folder(norm_path)

            if timeout_ms > 0:
                GLib.timeout_add(timeout_ms, lambda: (native.hide(), False)[1])

            resp = native.run()
            selected = None
            if resp in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
                selected = native.get_filename()
                native.destroy()
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                return (True, selected)
            elif resp in (Gtk.ResponseType.CANCEL, -1):
                native.destroy()
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                return (True, None)

            native.destroy()
        except Exception:
            pass

        # 2. Fallback to Gtk.FileChooserDialog
        dialog = Gtk.FileChooserDialog(
            title=title,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        dialog.set_default_response(Gtk.ResponseType.OK)

        filter_video = Gtk.FileFilter()
        filter_video.set_name("Video & Audio files (*.mp4, *.mov, *.mkv, *.webm, *.avi, *.wav, *.mp3)")
        for pattern in ["*.mp4", "*.mov", "*.mkv", "*.webm", "*.avi", "*.wav", "*.mp3", "*.m4v", "*.MP4", "*.MOV"]:
            filter_video.add_pattern(pattern)
        dialog.add_filter(filter_video)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("All files (*.*)")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)

        if initial_path:
            norm_path = os.path.abspath(os.path.expanduser(initial_path))
            if os.path.isfile(norm_path):
                dialog.set_filename(norm_path)
                parent_dir = os.path.dirname(norm_path)
                if os.path.isdir(parent_dir):
                    dialog.set_current_folder(parent_dir)
            elif os.path.isdir(norm_path):
                dialog.set_current_folder(norm_path)

        dialog.set_modal(True)
        try:
            dialog.set_position(Gtk.WindowPosition.CENTER)
            dialog.set_keep_above(True)
        except Exception:
            pass
        dialog.present()

        if timeout_ms > 0:
            GLib.timeout_add(timeout_ms, lambda: (dialog.response(Gtk.ResponseType.CANCEL), False)[1])

        response = dialog.run()
        selected_path = None
        if response in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT):
            selected_path = dialog.get_filename()

        dialog.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        return (True, selected_path)
    except Exception:
        return (False, None)

def pick_file_zenity(title: str, initial_path: str) -> Tuple[bool, Optional[str]]:
    """Linux Zenity file picker."""
    cmd = ["zenity", "--file-selection", f"--title={title}"]
    if initial_path:
        cmd.append(f"--filename={initial_path}")
    cmd.extend([
        "--file-filter=Media files | *.mp4 *.mov *.mkv *.webm *.avi *.wav *.mp3 *.MP4 *.MOV",
        "--file-filter=All files | *"
    ])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode == 0:
            out = res.stdout.strip()
            return (True, out if out else None)
        elif res.returncode == 1:
            return (True, None)
        return (False, None)
    except FileNotFoundError:
        return (False, None)
    except Exception:
        return (False, None)

def pick_file_kdialog(title: str, initial_path: str) -> Tuple[bool, Optional[str]]:
    """Linux KDE kdialog file picker."""
    init_dir = initial_path or "."
    filter_spec = "*.mp4 *.mov *.mkv *.webm *.avi *.wav *.mp3|Media files\n*|All Files"
    cmd = ["kdialog", "--title", title, "--getopenfilename", init_dir, filter_spec]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode == 0:
            out = res.stdout.strip()
            return (True, out if out else None)
        elif res.returncode == 1:
            return (True, None)
        return (False, None)
    except FileNotFoundError:
        return (False, None)
    except Exception:
        return (False, None)

def pick_file_tkinter(title: str, initial_path: str) -> Tuple[bool, Optional[str]]:
    """Universal Tkinter fallback dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        init_dir = initial_path if os.path.isdir(initial_path) else os.path.dirname(initial_path) if os.path.isfile(initial_path) else None
        path = filedialog.askopenfilename(
            title=title,
            initialdir=init_dir,
            filetypes=[
                ("Video & Audio files", "*.mp4 *.mov *.mkv *.webm *.avi *.wav *.mp3 *.MP4 *.MOV"),
                ("All files", "*.*")
            ]
        )
        root.destroy()
        return (True, path if path else None)
    except Exception:
        return (False, None)

def main():
    parser = argparse.ArgumentParser(description="Cross-platform native OS file chooser dialog")
    parser.add_argument("--initial-path", default="", help="Initial file or folder path")
    parser.add_argument("--title", default="Select Video File", help="Dialog window title")
    parser.add_argument("--timeout-ms", type=int, default=0, help="Optional timeout in ms")
    args = parser.parse_args()

    platform = sys.platform
    dialog_launched = False
    selected_path = None

    if platform == "darwin":
        dialog_launched, selected_path = pick_file_macos(args.title, args.initial_path)
    elif platform == "win32":
        dialog_launched, selected_path = pick_file_windows(args.title, args.initial_path)
    else:
        # Linux / BSD: Try GTK/Portal -> Zenity -> Kdialog -> Tkinter
        dialog_launched, selected_path = pick_file_gtk(args.title, args.initial_path, args.timeout_ms)
        if not dialog_launched:
            dialog_launched, selected_path = pick_file_zenity(args.title, args.initial_path)
        if not dialog_launched:
            dialog_launched, selected_path = pick_file_kdialog(args.title, args.initial_path)
        if not dialog_launched:
            dialog_launched, selected_path = pick_file_tkinter(args.title, args.initial_path)

    if dialog_launched:
        cancelled = selected_path is None or not os.path.exists(selected_path)
        print(json.dumps({
            "success": True,
            "dialog_available": True,
            "path": selected_path if not cancelled else None,
            "cancelled": cancelled
        }))
    else:
        print(json.dumps({
            "success": False,
            "dialog_available": False,
            "path": None,
            "cancelled": False,
            "error": "No graphical desktop file chooser could be opened on this system."
        }))

if __name__ == "__main__":
    main()
