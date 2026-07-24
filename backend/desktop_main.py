import os
import threading
import urllib.error
import urllib.request
import webbrowser

os.environ.setdefault("PYSTRAY_BACKEND", "win32")

import pystray
from PIL import Image, ImageDraw
from faster_whisper import WhisperModel  # noqa: F401 - validates the packaged runtime

import server


HOST = "127.0.0.1"
PORT = 8766
APP_URL = f"http://{HOST}:{PORT}"


def service_is_running():
    try:
        with urllib.request.urlopen(f"{APP_URL}/api/health", timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def open_application(_icon=None, _item=None):
    webbrowser.open(APP_URL)


def tray_image():
    image = Image.new("RGB", (64, 64), "#f4f3ee")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((5, 5, 59, 59), radius=13, fill="#20231f")
    draw.text((17, 14), "W", fill="#f4f3ee", stroke_width=1)
    return image


def run():
    if service_is_running():
        open_application()
        return

    httpd = server.create_server(HOST, PORT)
    worker = threading.Thread(target=httpd.serve_forever, name="wenl-http", daemon=True)
    worker.start()
    threading.Timer(0.6, open_application).start()

    def quit_application(icon, _item):
        httpd.shutdown()
        httpd.server_close()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开留文", open_application, default=True),
        pystray.MenuItem("退出留文", quit_application),
    )
    icon = pystray.Icon("wenl-scribe", tray_image(), "留文 · WENL SCRIBE", menu)
    icon.run()


if __name__ == "__main__":
    run()
