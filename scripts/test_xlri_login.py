"""Standalone smoke test for the ported XLRI ERP client (app/services/xlri_client.py).

Run this yourself, interactively -- it prompts for your ERP email/password so they
never end up in shell history or a chat transcript.

Usage (from repo root, inside the dev container so deps are available):
    docker compose -f docker-compose.dev.yml run --rm app python scripts/test_xlri_login.py
"""

import asyncio
import getpass
from datetime import date, timedelta

from app.services.xlri_client import fetch_class_activities, fetch_schedule, login, make_client


async def main():
    email = input("XLRI ERP email: ").strip()
    password = getpass.getpass("XLRI ERP password: ")

    today = date.today()
    start = today.isoformat()
    end = (today + timedelta(days=7)).isoformat()

    async with make_client() as client:
        auth = await login(client, email, password)
        token = auth["token"]
        print(f"Login OK, token: {token[:12]}...")

        sessions = await fetch_schedule(client, token, start, end)
        print(f"Fetched {len(sessions)} class session(s) for {start}..{end}")
        if sessions:
            s = sessions[0]
            print(f"  e.g. {s['course']['courseCode']} on {s['classDate']} {s['startTime']}-{s['endTime']}")

        activities = await fetch_class_activities(client, token, start, end)
        print(f"Fetched {len(activities)} activit(y/ies) for {start}..{end}")
        if activities:
            a = activities[0]
            print(f"  e.g. {a['name']} on {a['date']} {a['startTime']}-{a['endTime']}")


if __name__ == "__main__":
    asyncio.run(main())
