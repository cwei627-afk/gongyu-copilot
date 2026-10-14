"""Export directly from the application, without starting a server or opening databases."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from app.main import create_app


def export_openapi(output: Path, server_url: str = "http://127.0.0.1:8000") -> None:
    url = urlsplit(server_url)
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("server-url must be an HTTP(S) base URL without credentials, query or fragment")
    schema = create_app(server_url=server_url.rstrip("/")).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/openapi.json"))
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    export_openapi(args.output, args.server_url)
    print(f"Exported: {args.output}")
