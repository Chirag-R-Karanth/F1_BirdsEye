# F1 TUI

A Python/Textual Formula 1 terminal interface using OpenF1.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Replay

```bash
python server.py
```

The first run downloads the latest completed race into `cache/<session_key>/`. Later runs replay locally.

Specific session:

```bash
SESSION_KEY=9839 python server.py
```

## Live

Current OpenF1 live access requires an authenticated subscription. Set the credentials supplied by OpenF1:

```bash
MODE=live OPENF1_USER='...' OPENF1_PASS='...' python server.py
```

The credentials are exchanged for a short-lived access token and are not written to the cache.
