FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Patch opentele bug: StringSession instance not handled in FromTDesktop
RUN python3 -c "
import re, sys
path = None
try:
    import opentele.tl.telethon as m
    import inspect
    path = m.__file__
except:
    sys.exit(0)

with open(path, 'r') as f:
    src = f.read()

old = '''            elif not isinstance(session, Session):
                raise TypeError(
                    \"The given session must be a str or a Session instance.\"
                )'''

new = '''            elif isinstance(session, Session):
                auth_session = session
            else:
                raise TypeError(
                    \"The given session must be a str or a Session instance.\"
                )'''

if old in src:
    src = src.replace(old, new)
    with open(path, 'w') as f:
        f.write(src)
    print('opentele patched OK')
else:
    print('opentele patch: pattern not found, skipping')
"

ENV PYTHONPATH=/app

CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT
