import tkinter as tk
from tkinter import messagebox, scrolledtext
import subprocess
import os
import threading
import sys

process = None

BG_MAIN = "#0b1020"
BG_PANEL = "#121a2b"
BG_INPUT = "#0f172a"
FG_TEXT = "#e5e7eb"
FG_MUTED = "#94a3b8"
ACCENT = "#22c55e"
ACCENT_2 = "#38bdf8"
DANGER = "#ef4444"
WARN = "#f59e0b"
BORDER = "#1f2a44"

def append_output(text, tag=None):
    output_box.configure(state="normal")
    if tag:
        output_box.insert(tk.END, text, tag)
    else:
        output_box.insert(tk.END, text)
    output_box.see(tk.END)
    output_box.configure(state="disabled")

def set_status(text, color):
    status_value.config(text=text, fg=color)

def read_stream(stream, tag=None):
    while True:
        line = stream.readline()
        if not line:
            break
        root.after(0, append_output, line, tag)

def start_crawler():
    global process

    if process and process.poll() is None:
        messagebox.showwarning("Crawler running", "The crawler is already running.")
        return

    query = entry.get().strip()
    if not query:
        messagebox.showwarning("Input needed", "Please enter a search term.")
        return

    env = os.environ.copy()
    env["CRAWLER_PROMPT"] = query

    append_output(f"\n[UI] Starting crawler for query: {query}\n", "info")
    append_output("[UI] Launching testscraper.py ...\n", "info")
    set_status("RUNNING", ACCENT)

    try:
        process = subprocess.Popen(
            [sys.executable, "testscraper.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env
        )

        threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True).start()
        threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True).start()
        threading.Thread(target=watch_process, daemon=True).start()

    except Exception as e:
        set_status("ERROR", DANGER)
        messagebox.showerror("Error", f"Failed to start crawler:\n{e}")

def watch_process():
    global process
    if not process:
        return

    return_code = process.wait()

    if return_code == 0:
        root.after(0, append_output, "\n[UI] Crawler finished successfully.\n", "success")
        root.after(0, set_status, "IDLE", ACCENT_2)
    else:
        root.after(0, append_output, f"\n[UI] Crawler exited with code {return_code}.\n", "stderr")
        root.after(0, set_status, "STOPPED", WARN)

def stop_crawler():
    global process

    if process and process.poll() is None:
        try:
            process.terminate()
            append_output("\n[UI] Stop requested.\n", "info")
            set_status("STOPPING", WARN)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop crawler:\n{e}")
    else:
        messagebox.showinfo("Not running", "No crawler process is currently running.")

def clear_console():
    output_box.configure(state="normal")
    output_box.delete("1.0", tk.END)
    output_box.configure(state="disabled")

# =========================
# UI SETUP
# =========================
root = tk.Tk()
root.title("AI Tor Crawler")
root.geometry("980x680")
root.configure(bg=BG_MAIN)
root.minsize(850, 560)

# Fonts
TITLE_FONT = ("Segoe UI", 22, "bold")
LABEL_FONT = ("Segoe UI", 11, "bold")
TEXT_FONT = ("Consolas", 10)
BUTTON_FONT = ("Segoe UI", 11, "bold")
ENTRY_FONT = ("Segoe UI", 12)

# Header
header = tk.Frame(root, bg=BG_MAIN)
header.pack(fill="x", padx=20, pady=(18, 10))

title_label = tk.Label(
    header,
    text="AI Tor Crawler",
    bg=BG_MAIN,
    fg=FG_TEXT,
    font=TITLE_FONT
)
title_label.pack(side="left")

status_frame = tk.Frame(header, bg=BG_MAIN)
status_frame.pack(side="right")

status_label = tk.Label(
    status_frame,
    text="STATUS",
    bg=BG_MAIN,
    fg=FG_MUTED,
    font=("Segoe UI", 10, "bold")
)
status_label.pack(side="left", padx=(0, 8))

status_value = tk.Label(
    status_frame,
    text="IDLE",
    bg=BG_MAIN,
    fg=ACCENT_2,
    font=("Segoe UI", 10, "bold")
)
status_value.pack(side="left")

subtitle = tk.Label(
    root,
    text="Run your crawler like a local AI agent and view all live logs here.",
    bg=BG_MAIN,
    fg=FG_MUTED,
    font=("Segoe UI", 10)
)
subtitle.pack(anchor="w", padx=22, pady=(0, 14))

# Search panel
search_panel = tk.Frame(root, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
search_panel.pack(fill="x", padx=20, pady=(0, 14), ipady=12)

search_label = tk.Label(
    search_panel,
    text="Search prompt",
    bg=BG_PANEL,
    fg=FG_TEXT,
    font=LABEL_FONT
)
search_label.pack(anchor="w", padx=16, pady=(10, 6))

entry_row = tk.Frame(search_panel, bg=BG_PANEL)
entry_row.pack(fill="x", padx=16, pady=(0, 4))

entry = tk.Entry(
    entry_row,
    width=50,
    font=ENTRY_FONT,
    bg=BG_INPUT,
    fg=FG_TEXT,
    insertbackground=FG_TEXT,
    relief="flat",
    highlightthickness=1,
    highlightbackground=BORDER,
    highlightcolor=ACCENT_2
)
entry.pack(side="left", fill="x", expand=True, ipady=8)
entry.insert(0, "secure boot")

start_btn = tk.Button(
    entry_row,
    text="Start Crawl",
    command=start_crawler,
    font=BUTTON_FONT,
    bg=ACCENT,
    fg="white",
    activebackground=ACCENT,
    activeforeground="white",
    relief="flat",
    padx=18,
    pady=8,
    cursor="hand2"
)
start_btn.pack(side="left", padx=(12, 0))

stop_btn = tk.Button(
    entry_row,
    text="Stop",
    command=stop_crawler,
    font=BUTTON_FONT,
    bg=DANGER,
    fg="white",
    activebackground=DANGER,
    activeforeground="white",
    relief="flat",
    padx=18,
    pady=8,
    cursor="hand2"
)
stop_btn.pack(side="left", padx=(10, 0))

clear_btn = tk.Button(
    search_panel,
    text="Clear Console",
    command=clear_console,
    font=("Segoe UI", 10, "bold"),
    bg=ACCENT_2,
    fg="white",
    activebackground=ACCENT_2,
    activeforeground="white",
    relief="flat",
    padx=12,
    pady=6,
    cursor="hand2"
)
clear_btn.pack(anchor="e", padx=16, pady=(10, 0))

# Console panel
console_panel = tk.Frame(root, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
console_panel.pack(fill="both", expand=True, padx=20, pady=(0, 20))

console_header = tk.Frame(console_panel, bg=BG_PANEL)
console_header.pack(fill="x", padx=14, pady=(12, 8))

console_title = tk.Label(
    console_header,
    text="Live Output",
    bg=BG_PANEL,
    fg=FG_TEXT,
    font=("Segoe UI", 12, "bold")
)
console_title.pack(side="left")

console_hint = tk.Label(
    console_header,
    text="stdout and stderr from testscraper.py",
    bg=BG_PANEL,
    fg=FG_MUTED,
    font=("Segoe UI", 9)
)
console_hint.pack(side="right")

output_box = scrolledtext.ScrolledText(
    console_panel,
    wrap=tk.WORD,
    font=TEXT_FONT,
    bg="#020617",
    fg="#d1d5db",
    insertbackground=FG_TEXT,
    relief="flat",
    borderwidth=0
)
output_box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
output_box.configure(state="disabled")

output_box.tag_config("stdout", foreground="#d1d5db")
output_box.tag_config("stderr", foreground="#fca5a5")
output_box.tag_config("info", foreground="#7dd3fc")
output_box.tag_config("success", foreground="#86efac")

append_output("[UI] Ready.\n", "info")
append_output("[UI] Enter a prompt and click Start Crawl.\n", "info")

root.mainloop()