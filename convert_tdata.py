#!/usr/bin/env python3
"""
Local script: convert tdata folder → Telethon StringSession.
Run once per account, paste the result into "Import tdata" form.

Usage:
    python3 convert_tdata.py /path/to/tdata
    python3 convert_tdata.py /path/to/tdata --password YOUR_2FA_PASSWORD
"""
import asyncio
import sys
import argparse


async def convert(tdata_path: str, password: str = ""):
    try:
        from opentele.td import TDesktop
        from opentele.api import UseCurrentSession, CreateNewSession, API
        from telethon.sessions import StringSession
    except ImportError:
        print("Installing opentele...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "opentele", "telethon"])
        from opentele.td import TDesktop
        from opentele.api import UseCurrentSession, CreateNewSession, API
        from telethon.sessions import StringSession

    tdesk = TDesktop(tdata_path)
    print(f"Found {len(tdesk.accounts)} account(s) in tdata")

    kwargs = {}
    if password:
        kwargs["password"] = password

    # Try UseCurrentSession first (reuses existing session, no 2FA needed)
    try:
        client = await tdesk.ToTelethon(
            session=StringSession(),
            flag=UseCurrentSession,
            **kwargs,
        )
        await client.connect()
        if await client.is_user_authorized():
            session_str = client.session.save()
            await client.disconnect()
            print("\n✅ Session String (copy this):\n")
            print(session_str)
            return session_str
        await client.disconnect()
    except Exception as e:
        print(f"UseCurrentSession failed: {e}, trying CreateNewSession...")

    # Fallback: create new session (requires 2FA if enabled)
    client = await tdesk.ToTelethon(
        session=StringSession(),
        flag=CreateNewSession,
        api=API.TelegramDesktop,
        **kwargs,
    )
    await client.connect()
    if await client.is_user_authorized():
        session_str = client.session.save()
        await client.disconnect()
        print("\n✅ Session String (copy this):\n")
        print(session_str)
        return session_str

    await client.disconnect()
    print("❌ Account not authorized")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tdata_path", help="Path to tdata folder")
    parser.add_argument("--password", default="", help="2FA password if enabled")
    args = parser.parse_args()
    asyncio.run(convert(args.tdata_path, args.password))
