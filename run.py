"""
Tally FastAPI Database Loader
Application Runner
"""

import uvicorn
import argparse
from app.config import config


def main():
    parser = argparse.ArgumentParser(description="Tally FastAPI Database Loader")
    parser.add_argument("--host", default=config.api.host, help="Host to bind")
    parser.add_argument("--port", type=int, default=config.api.port, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    
    print(f"""
    ============================================================
    |         Tally FastAPI Database Loader v1.0.0             |
    ============================================================
    |  Server: http://{args.host}:{args.port}
    |  Docs:   http://{args.host}:{args.port}/docs
    |  Tally:  {config.tally.server}:{config.tally.port}
    ============================================================
    """)
    
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )


if __name__ == "__main__":
    main()
