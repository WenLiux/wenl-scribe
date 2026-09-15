import os
import socket
import threading
import webbrowser

os.environ.setdefault("PYSTRAY_BACKEND", "win32")

import pystray
from PIL import Image, ImageDraw
from faster_whisper import WhisperModel  # noqa: F401 - validates the packaged runtime

import server


HOST = "127.0.0.1"
DEFAULT_PORT = 8766
PORT_SCAN_LIMIT = 20
AUTO_OPEN_BROWSER = os.getenv("WENL_DESKTOP_NO_AUTO_OPEN") != "1"


def configured_port():
    raw = (os.getenv("WENL_DESKTOP_PORT") or "").strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("WENL_DESKTOP_PORT 必须是有效端口号") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("WENL_DESKTOP_PORT 必须在 1 到 65535 之间")
    return port


def port_is_in_use(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.25)
    try:
        return probe.connect_ex((HOST, port)) == 0
    finally:
        probe.close()


def create_desktop_server():
    """Bind the requested port, or the first free local port for coexistence."""
    explicit_port = configured_port()
    if explicit_port is not None:
        if port_is_in_use(explicit_port):
            raise OSError(f"本地端口 {explicit_port} 已被占用")
        return server.create_server(HOST, explicit_port), explicit_port

    last_error = None
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN_LIMIT):
        if port_is_in_use(port):
            continue
        try:
            return server.create_server(HOST, port), port
        except OSError as exc:
            last_error = exc
    raise OSError(
        f"无法启动本地服务：{DEFAULT_PORT}-{DEFAULT_PORT + PORT_SCAN_LIMIT - 1} 端口均被占用"
    ) from last_error


def open_application(port):
    webbrowser.open(f"http://{HOST}:{port}")


def tray_image():
    image = Image.new("RGB", (64, 64), "#f4f3ee")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((5, 5, 59, 59), radius=13, fill="#20231f")
    draw.text((17, 14), "W", fill="#f4f3ee", stroke_width=1)
    return image


def run():
    httpd, port = create_desktop_server()
    worker = threading.Thread(target=httpd.serve_forever, name="wenl-http", daemon=True)
    worker.start()
    if AUTO_OPEN_BROWSER:
        threading.Timer(0.6, open_application, args=(port,)).start()

    def quit_application(icon, _item):
        httpd.shutdown()
        httpd.server_close()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("打开留文", lambda _icon, _item: open_application(port), default=True),
        pystray.MenuItem("退出留文", quit_application),
    )
    icon = pystray.Icon("wenl-scribe", tray_image(), "留文 · WENL SCRIBE", menu)
    icon.run()


if __name__ == "__main__":
    run()
