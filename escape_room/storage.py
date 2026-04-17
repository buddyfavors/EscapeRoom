from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from escape_room.config import CODES_FILE
from escape_room.models import CodePools


def default_codes_path() -> Path:
    return CODES_FILE


def load_code_pools(path: Path | None = None) -> CodePools:
    p = path or default_codes_path()
    if not p.exists():
        return CodePools()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return CodePools.model_validate(raw)


def save_code_pools_json(text: str, path: Path | None = None) -> CodePools:
    """Parse and persist JSON; returns validated model."""
    p = path or default_codes_path()
    data = json.loads(text)
    pools = CodePools.model_validate(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(pools.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return pools


def validate_codes_json(text: str) -> tuple[bool, str]:
    try:
        CodePools.model_validate_json(text)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except ValidationError as e:
        return False, str(e)
    return True, ""
