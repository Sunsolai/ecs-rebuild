#!/usr/bin/env python
"""Launch gateway: python scripts/run_gateway.py"""

import uvicorn

from packages.shared.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "apps.gateway.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.app_env == "dev",
    )


if __name__ == "__main__":
    main()
