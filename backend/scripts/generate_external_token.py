#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import time


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate external signed token for Sprint-1 chat")
    parser.add_argument("lead_id")
    parser.add_argument("secret")
    parser.add_argument("--ttl-hours", type=int, default=48)
    args = parser.parse_args()

    expires = int(time.time()) + args.ttl_hours * 3600
    payload = f"{args.lead_id}:{expires}".encode("utf-8")
    signature = hmac.new(args.secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    print(f"{args.lead_id}:{expires}:{signature}")


if __name__ == "__main__":
    main()
