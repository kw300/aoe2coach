#!/usr/bin/env python3
"""Thin wrapper around ``aoe2coach.dataupdate`` — see that module for details.

Run with `python scripts/update_data.py` or `aoe2coach update-data`.
Requires the full backend: `pip install -e ".[full]"`.
"""

from aoe2coach.dataupdate import main

if __name__ == "__main__":
    raise SystemExit(main())
