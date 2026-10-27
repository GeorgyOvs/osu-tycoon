"""Russian text for the tycoon client, produced by the web UI's own dictionaries.

The translations live in frontend/src/i18n*.ts (plain entries and regex templates, some with logic). Rather than
keep a second copy in Python, `npm run build:i18n` bundles them into app/i18n/ru.mjs and a small Node worker
translates through the very same `tx()`. Without Node or the bundle, text simply stays English.
"""
import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"
BUNDLE = I18N_DIR / "ru.mjs"
WORKER = I18N_DIR / "worker.mjs"
CACHE_LIMIT = 5000

log = logging.getLogger(__name__)


class _Worker:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.unavailable = False
        self.cache: dict[str, str] = {}

    def _start(self) -> None:
        node = shutil.which("node")
        if node is None or not BUNDLE.is_file():
            self.unavailable = True
            log.warning("Russian text for the client is off: %s", "node not found" if node is None
                        else "run `npm run build:i18n` in frontend/")
            return
        self.proc = subprocess.Popen([node, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)

    def ru(self, texts: list[str]) -> list[str]:
        missing = sorted({t for t in texts if t and t not in self.cache})
        if missing and not self.unavailable:
            with self.lock:
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self._start()
                    if self.proc is not None:
                        self.proc.stdin.write(json.dumps(missing, ensure_ascii=False) + "\n")
                        self.proc.stdin.flush()
                        line = self.proc.stdout.readline()
                        translated = json.loads(line) if line else []
                        if len(translated) == len(missing):
                            if len(self.cache) > CACHE_LIMIT:
                                self.cache.clear()
                            self.cache.update(zip(missing, translated))
                except (OSError, ValueError) as e:
                    log.warning("translation worker failed, text stays English: %s", e)
                    self.unavailable = True
        return [self.cache.get(t, t) for t in texts]


_worker = _Worker()


def ru(texts: list[str]) -> list[str]:
    return _worker.ru(texts)


def ru1(text: str | None) -> str | None:
    return ru([text])[0] if text else text
