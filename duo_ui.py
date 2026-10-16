from __future__ import annotations

"""Tkinter wrapper for the new SQLite runtime.

The previous UI executed the legacy JSON pipeline directly. It is intentionally
replaced with CLI-backed actions so there is only one runtime pipeline.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import END, Button, Entry, Frame, Label, StringVar, Text, Tk
from tkinter.scrolledtext import ScrolledText

BASE_DIR = Path(__file__).resolve().parent


class DuoRuntimeUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("AutoPublicador Duo - Runtime SQLite")
        self.running = False
        self.status_var = StringVar(value="Idle")
        self.max_news_var = StringVar(value="1")

        header = Frame(root)
        header.pack(fill="x", padx=12, pady=8)
        Label(header, text="Estado:").pack(side="left")
        Label(header, textvariable=self.status_var).pack(side="left", padx=6)

        limits = Frame(root)
        limits.pack(fill="x", padx=12, pady=4)
        Label(limits, text="Max noticias:").pack(side="left")
        Entry(limits, textvariable=self.max_news_var, width=8).pack(side="left", padx=6)

        actions = Frame(root)
        actions.pack(fill="x", padx=12, pady=8)
        Button(actions, text="Doctor", width=18, command=lambda: self.run_cli(["doctor"])).pack(side="left", padx=4)
        Button(actions, text="Dry run", width=18, command=self.run_dry_run).pack(side="left", padx=4)
        Button(actions, text="Run once safe", width=18, command=self.run_safe_once).pack(side="left", padx=4)
        Button(actions, text="Queue", width=18, command=lambda: self.run_cli(["queue", "--format", "table"])).pack(side="left", padx=4)
        Button(actions, text="Preview publish", width=18, command=lambda: self.run_cli(["publish-pending", "--max-posts", "1"])).pack(side="left", padx=4)
        Button(actions, text="Growth report", width=18, command=lambda: self.run_cli(["growth-report", "--no-write"])).pack(side="left", padx=4)

        x_frame = Frame(root)
        x_frame.pack(fill="x", padx=12, pady=4)
        Label(x_frame, text="Links X (uno por linea):").pack(anchor="w")
        self.x_links_text = Text(root, height=4)
        self.x_links_text.pack(fill="x", padx=12, pady=4)
        Button(x_frame, text="Importar URLs X", width=18, command=self.import_x_urls).pack(anchor="w", pady=4)

        scheduler = Frame(root)
        scheduler.pack(fill="x", padx=12, pady=8)
        Button(scheduler, text="Smoke 24/7 1 ciclo", width=22, command=lambda: self.run_cli(["run-24-7", "--cycles", "1", "--max-news", "0"])).pack(side="left", padx=4)

        log_frame = Frame(root)
        log_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.log_widget = ScrolledText(log_frame, height=22)
        self.log_widget.pack(fill="both", expand=True)

    def run_dry_run(self) -> None:
        self.run_cli(["run-once", "--dry-run", "--max-news", self._max_news()])

    def run_safe_once(self) -> None:
        self.run_cli(["run-once", "--safe-mode", "--max-news", self._max_news(), "--max-posts", "1"])

    def import_x_urls(self) -> None:
        links = [
            token.strip()
            for line in self.x_links_text.get("1.0", END).splitlines()
            for token in line.replace(",", " ").split()
            if token.strip()
        ]
        if not links:
            self.log("No hay URLs de X para importar.")
            return
        commands = [["import-x-url", "--url", link] for link in links]
        self.run_cli_batch(commands)

    def run_cli(self, args: list[str]) -> None:
        self.run_cli_batch([args])

    def run_cli_batch(self, commands: list[list[str]]) -> None:
        if self.running:
            self.log("Ya hay un proceso en curso.")
            return

        def worker() -> None:
            self.running = True
            self.set_status("Running")
            try:
                for args in commands:
                    self._run_command([sys.executable, "-m", "cli.main", *args])
            finally:
                self.running = False
                self.set_status("Idle")

        threading.Thread(target=worker, daemon=True).start()

    def _run_command(self, cmd: list[str]) -> int:
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
        code = proc.wait()
        self.log(f"exit={code}")
        return code

    def _max_news(self) -> str:
        raw = self.max_news_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return str(max(0, value))

    def log(self, message: str) -> None:
        def append() -> None:
            stamp = time.strftime("%H:%M:%S")
            self.log_widget.insert(END, f"[{stamp}] {message}\n")
            self.log_widget.see(END)

        self.root.after(0, append)

    def set_status(self, value: str) -> None:
        self.root.after(0, lambda: self.status_var.set(value))


def main() -> None:
    root = Tk()
    root.geometry("1080x720")
    DuoRuntimeUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
