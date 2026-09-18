"""Üretim iptali: Ctrl+X (ve üretim sırasında Ctrl+C) turu keser, programı kapatmaz."""

from __future__ import annotations

import os
import select
import signal
import sys
import termios
import threading
import tty


class GenerationCancelled(Exception):
    """Kullanıcı bu yanıtı kesti; REPL devam eder."""


class CancelWatch:
    """Akış sırasında Ctrl+X / SIGINT'i yakalar.

    stdin cbreak'e alınır ki Ctrl+X Enter beklemeden görülsün. Soket
    blokunu çözmek için bind_closer ile stream.close bağlanır.
    """

    def __init__(self):
        self.event = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._old_term = None
        self._old_handler = None
        self._fd = None
        self._closer = None

    def bind_closer(self, fn):
        self._closer = fn
        if self.event.is_set() and fn:
            try:
                fn()
            except Exception:
                pass

    def _trip(self):
        self.event.set()
        closer = self._closer
        if closer:
            try:
                closer()
            except Exception:
                pass

    def check(self):
        if self.event.is_set():
            raise GenerationCancelled

    def _watch(self):
        fd = self._fd
        while not self._stop.is_set():
            if fd is None:
                if self._stop.wait(0.15):
                    return
                continue
            ready, _, _ = select.select([fd], [], [], 0.15)
            if not ready:
                continue
            try:
                data = os.read(fd, 16)
            except OSError:
                return
            if not data:
                return
            if b"\x18" in data:  # Ctrl+X
                self._trip()
                return

    def __enter__(self):
        if sys.stdin.isatty():
            self._fd = sys.stdin.fileno()
            try:
                self._old_term = termios.tcgetattr(self._fd)
                tty.setcbreak(self._fd)
            except termios.error:
                self._old_term = None
                self._fd = None
        self._old_handler = signal.getsignal(signal.SIGINT)

        def _on_sigint(signum, frame):
            self._trip()

        signal.signal(signal.SIGINT, _on_sigint)
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._old_handler is not None:
            signal.signal(signal.SIGINT, self._old_handler)
        if self._old_term is not None and self._fd is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_term)
            except termios.error:
                pass
        return False
