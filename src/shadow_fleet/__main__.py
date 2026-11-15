"""Local administration commands."""
import argparse
import os
from pathlib import Path

from .store import migrate


def main() -> None:
    parser = argparse.ArgumentParser(prog="shadow_fleet")
    parser.add_argument("command", choices=["migrate", "api", "collect"])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--history", action="store_true", help="keep seven days of observations (collect only)")
    args = parser.parse_args()
    if args.history and args.command != "collect":
        parser.error("--history requires collect")
    if args.command == "migrate":
        dsn = os.environ.get("SFD_DATABASE_URL")
        if not dsn:
            parser.error("SFD_DATABASE_URL is required")
        migrate(dsn)
    elif args.command == "collect":
        dsn = os.environ.get("SFD_DATABASE_URL")
        if not dsn:
            parser.error("SFD_DATABASE_URL is required")
        import signal
        from threading import Event
        from .collector import Collector
        from .store import WriterSession
        stop = Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        Collector(store_factory=lambda: WriterSession.open(dsn, 'fintraffic', record_history=args.history),
                  history_maintenance=True).run(stop)
    else:
        dsn = os.environ.get("SFD_API_DATABASE_URL")
        if not dsn:
            parser.error("SFD_API_DATABASE_URL is required")
        if not 1 <= args.port <= 65535:
            parser.error("port must be between 1 and 65535")
        import uvicorn
        from .api import Settings, create_app
        dossier_path = os.getenv("SFD_DOSSIER_CATALOG")
        settings = Settings(database_url=dsn, dossier_path=Path(dossier_path) if dossier_path else None)
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
