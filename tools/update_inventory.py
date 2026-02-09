from __future__ import annotations

import json


def handler() -> dict:
    return {"sku": "fixed", "status": "updated"}


if __name__ == "__main__":
    print(json.dumps(handler()))
