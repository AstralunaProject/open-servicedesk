import os
import socket

from waitress import serve

from app import __version__, create_app
from app.worker import start_background_worker


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    app = create_app()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    threads = int(os.environ.get("THREADS", "8"))
    start_background_worker(app)
    print(f"\n  T.I Chamados {__version__}")
    print(f"  Dados em:   {app.config['DATA_DIR']}")
    print(f"  Acesse:     http://localhost:{port}   ou   http://{_local_ip()}:{port}")
    print("  Para parar: Ctrl+C\n")
    serve(app, host=host, port=port, threads=threads, ident="TI-Chamados")


if __name__ == "__main__":
    main()
