from __future__ import annotations

import json


def handler() -> dict:
    return {"product_id": "fixed", "name": "demo", "price": 1}


if __name__ == "__main__":
    print(json.dumps(handler()))
