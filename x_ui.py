from __future__ import annotations

"""Minimal X URL importer backed by the new SQLite CLI."""

import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import END, Button, Frame, Label, Text, Tk
from tkinter.scrolledtext import ScrolledText

BASE_DIR = Path(__file__).resolve().parent


class XImportUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("AutoPublicador Duo - X Manual Import")
        self.running = False

        Frame(root).pack(fill="x", padx=12, pady=6)
        Label(root, text="Links X (uno por linea):").pack(anchor="w", padx=12)
        self.links_text = Text(root, height=8)
        self.links_text.pack(fill="x", padx=12, pady=6)

        actions = Frame(root)
        actions.pack(fill="x", padx=12, pady=6)
        Button(actions, text="Importar URLs", width=18, command=self.import_urls).pack(side="left", padx=4)
        Button(actions, text="Ver cola", width=18, command=lambda: self.run_cli(["queue", "--format", "table"])).pack(side="left", padx=4)
        Button(actions, text="Dry run", width=18, command=lambda: self.run_cli(["dry-run", "--max-news", "0"])).pack(side="left", padx=4)

        self.log_widget = ScrolledText(root, height=22)
        self.log_widget.pack(fill="both", expand=True, padx=12, pady=8)

    def import_urls(self) -> None:
        links = [
            token.strip()
            for line in self.links_text.get("1.0", END).splitlines()
            for token in line.replace(",", " ").split()
            if token.strip()
        ]
        if not links:
            self.log("No hay URLs para importar.")
            return
        self.run_batch([["import-x-url", "--url", link] for link in links])

    def run_cli(self, args: list[str]) -> None:
        self.run_batch([args])

    def run_batch(self, commands: list[list[str]]) -> None:
        if self.running:
            self.log("Ya hay un proceso en curso.")
            return

        def worker() -> None:
            self.running = True
            try:
                for args in commands:
                    cmd = [sys.executable, "-m", "cli.main", *args]
                    self.log(f"$ {' '.join(cmd)}")
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(BASE_DIR),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                    )
                    if proc.stdout:
                        for line in proc.stdout:
                            self.log(line.rstrip())
                    self.log(f"exit={proc.wait()}")
            finally:
                self.running = False

        threading.Thread(target=worker, daemon=True).start()

    def log(self, message: str) -> None:
        def append() -> None:
            self.log_widget.insert(END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_widget.see(END)

        self.root.after(0, append)


def main() -> None:
    root = Tk()
    root.geometry("900x640")
    XImportUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
