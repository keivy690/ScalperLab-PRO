from __future__ import annotations

import threading
from pathlib import Path

from werkzeug.serving import make_server

from .single_instance import SingleInstanceLock
from .web import create_app


def run_desktop() -> None:
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        raise SystemExit("O ScalperLab já está aberto nesta sessão do Windows.")
    app = None
    engine = None
    analyst = None
    server = None
    thread = None
    try:
        try:
            import webview
        except ImportError as exc:
            raise SystemExit("pywebview não está instalado. Execute pip install -e .") from exc

        app = create_app()
        engine = app.extensions["scalper_engine"]
        analyst = app.extensions["scalper_analyst"]
        engine.start_service()
        analyst.start_service()
        server = make_server("127.0.0.1", 0, app, threaded=True)
        port = int(server.server_port)
        app.config["APP_HOST"] = f"127.0.0.1:{port}"
        app.config["APP_ORIGIN"] = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, name="scalperlab-http", daemon=True)
        thread.start()
        webview.create_window("ScalperLab PRO", f"http://127.0.0.1:{port}/", min_size=(960, 640),
                              width=1600, height=1000, background_color="#131315")
        icon_path = Path(__file__).resolve().parent.parent / "static" / "brand" / "scalperlab-pro.ico"
        webview.start(debug=False, icon=str(icon_path) if icon_path.is_file() else None)
    finally:
        try:
            if engine is not None:
                engine.shutdown()
            if analyst is not None:
                analyst.shutdown()
            if app is not None:
                app.extensions["scalper_mt5"].shutdown()
            if server is not None:
                server.shutdown()
            if thread is not None:
                thread.join(timeout=3)
        finally:
            instance_lock.release()
