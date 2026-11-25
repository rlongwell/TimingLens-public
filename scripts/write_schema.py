"""Regenerate the public JSON schema from the application model."""
import json
from pathlib import Path

from timinglens import Session


def main():
    path = Path(__file__).resolve().parents[1] / "docs" / "session-v1.schema.json"
    path.write_text(json.dumps(Session.model_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
