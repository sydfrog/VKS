"""Entry point used by systemd: python -m unifi_toggle

Reads BIND_HOST, PORT, TLS_CERT_FILE and TLS_KEY_FILE from the environment so
the unit file never has to repeat them on the command line.
"""

from __future__ import annotations

import logging
import sys

import uvicorn

from .config import ConfigError, load_settings
from .main import create_app


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    kwargs: dict = {
        "host": settings.bind_host,
        "port": settings.port,
        "log_level": settings.log_level,
        "access_log": True,
        "proxy_headers": False,
        "server_header": False,
    }
    if settings.tls_enabled:
        kwargs["ssl_certfile"] = settings.tls_cert_file
        kwargs["ssl_keyfile"] = settings.tls_key_file

    uvicorn.run(create_app(settings), **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
