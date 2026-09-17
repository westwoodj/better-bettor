"""Entry point for running the Gridiron Oracle API server."""

import os

from .app import create_app

app = create_app()

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(
        "nfl_data_aggregator.api.server:app",
        host=host,
        port=port,
        reload=True,
    )
