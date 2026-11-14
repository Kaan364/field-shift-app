"""Project Alphecca - tek komutla backend + test arayüzü.

Kullanım::

    python run_ui.py                 # backend'i gerekirse başlatır, arayüzü açar
    python run_ui.py --no-backend    # backend zaten açıksa
    python run_ui.py --api-port 8001 --ui-port 8502

Backend ayaktaysa yeniden başlatılmaz, mevcut sunucu kullanılır. Bu betik
kapandığında yalnızca kendi başlattığı backend sürecini durdurur.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_SCRIPT = ROOT / "ui" / "app.py"


def _backend_ready(port: int, timeout: float = 2.0) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait_for_backend(port: int, seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _backend_ready(port):
            return True
        time.sleep(0.5)
    return False


def _start_backend(port: int) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    print(f"[alphecca] Backend başlatılıyor: {' '.join(command)}", flush=True)
    return subprocess.Popen(command, cwd=str(ROOT))


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(description="Project Alphecca backend + Streamlit arayüzü")
    parser.add_argument("--api-port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--ui-port", type=int, default=8501)
    parser.add_argument("--no-backend", action="store_true", help="Backend'i başlatma, mevcut olanı kullan")
    args = parser.parse_args()

    if not UI_SCRIPT.exists():
        print(f"[alphecca] Arayüz dosyası bulunamadı: {UI_SCRIPT}")
        return 1

    if importlib.util.find_spec("streamlit") is None:
        print("[alphecca] Streamlit kurulu değil. Kurulum:")
        print(f'  "{sys.executable}" -m pip install -r requirements-ui.txt')
        return 1

    api_url = f"http://127.0.0.1:{args.api_port}"
    backend: subprocess.Popen | None = None

    already_running = _backend_ready(args.api_port)
    if already_running:
        print(f"[alphecca] Mevcut backend kullanılacak: {api_url}")
    elif args.no_backend:
        print(f"[alphecca] UYARI: {api_url} yanıt vermiyor ve --no-backend verildi.")
    else:
        backend = _start_backend(args.api_port)
        if not _wait_for_backend(args.api_port):
            print("[alphecca] Backend başlatılamadı. Logları kontrol et.")
            _stop(backend)
            return 1
        print(f"[alphecca] Backend hazır: {api_url}")

    env = os.environ.copy()
    env["ALPHECCA_API_URL"] = api_url

    ui_command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(UI_SCRIPT),
        "--server.port",
        str(args.ui_port),
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]

    print("=" * 68)
    print("  Arayüz     : http://127.0.0.1:%d" % args.ui_port)
    print("  API /docs  : %s/docs" % api_url)
    print("  Kapatmak için terminalde Ctrl+C")
    print("=" * 68)

    try:
        return subprocess.call(ui_command, cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        print("\n[alphecca] Kapatılıyor...")
        return 0
    finally:
        if backend is not None:
            _stop(backend)
            print("[alphecca] Başlatılan backend durduruldu.")


if __name__ == "__main__":
    raise SystemExit(main())
