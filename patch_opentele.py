"""Patch opentele bug: StringSession instance not handled in FromTDesktop."""
import sys

try:
    import opentele.tl.telethon as m
    path = m.__file__
except Exception as e:
    print(f"opentele not found, skipping: {e}")
    sys.exit(0)

with open(path, "r") as f:
    src = f.read()

old = """            elif not isinstance(session, Session):
                raise TypeError(
                    "The given session must be a str or a Session instance."
                )"""

new = """            elif isinstance(session, Session):
                auth_session = session
            else:
                raise TypeError(
                    "The given session must be a str or a Session instance."
                )"""

if old in src:
    src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    print("opentele patched OK")
else:
    print("opentele patch: pattern not found, may already be patched")
