```

yt_summary/
│── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entrypoint
│   ├── models.py            # Pydantic request/response models
│   ├── prompts.py           # Prompt templates
│   ├── services/
│   │    ├── youtube_service.py   # Transcript fetcher
│   │    ├── llm_service.py       # Summarizer/LLM calls
│   │    └── rate_limiter.py      # (future) rate limiter
│   └── routes/
│        ├── summary.py      # Routes for /process
│        └── playlist.py     # Routes for /process_playlist
│
│── requirements.txt
│── run.sh                   # Script to run app


```

## Rest API

```
http://127.0.0.1:8000/docs#/Summary/process_video_process__post
```

https://chatgpt.com/c/68d4d9c4-ce94-8328-a772-6921f1fe78ae


https://youtu.be/WLth6Dqafak

## Local Packaging and Deployment

This repository can be distributed as a local package so others can run it on their own machine without a public API backend.

### Local install steps

- Create a virtual environment:
  - `python -m venv .venv`
- Activate it:
  - Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
  - Windows CMD: `.\.venv\Scripts\activate.bat`
  - macOS/Linux: `source .venv/bin/activate`
- Install dependencies:
  - `pip install -r requirements.txt`
- Run the app from `yt_summarizer_v2`:
  - `python -m uvicorn main:app --host 127.0.0.1 --port 8000`

### Packaging as a reusable distributable

To make this behave like a software package:

- Add packaging metadata with `pyproject.toml` (or `setup.py`/`setup.cfg`).
- Define the package name, version, author, and runtime dependencies.
- Add a console script entry point so users can run a command like `yt-summarizer`.
- Build a wheel or source distribution:
  - `python -m pip install build`
  - `python -m build`
- Share the generated wheel file.

### Update workflow

- Bump the package version for each release.
- Rebuild the package artifact and redistribute it.
- Users can update locally with:
  - `python -m pip install --upgrade path\to\yt_summary-<version>-py3-none-any.whl`

## Backfill Script

Use `scripts/backfill.py` to populate missing column values for existing videos in the database.
It fetches data from YouTube (or any other source) for rows where the target column is `NULL`.

### Run all registered columns

```bash
python scripts/backfill.py
```

### Run a specific column only

```bash
python scripts/backfill.py --columns description
```

### Preview without writing (dry-run)

```bash
python scripts/backfill.py --dry-run
python scripts/backfill.py --columns description --dry-run
```

### Control request rate

```bash
python scripts/backfill.py --delay 1.0   # 1 second between requests (default: 0.5)
```

### Adding a new column backfiller

1. Open `scripts/backfill.py`.
2. Write a fetcher function:
   ```python
   def fetch_mycolumn(video_id: str, row: dict) -> optional_value:
       # fetch the value, return None to skip the row
       ...
   ```
3. Register it in `BACKFILLERS`:
   ```python
   BACKFILLERS = {
       "description": fetch_description,
       "mycolumn":    fetch_mycolumn,   # <-- add here
   }
   ```
4. Run: `python scripts/backfill.py --columns mycolumn`

---

### Notes

- Keep a `.env.example` file to document required environment variables such as `DEEPINFRA_API_KEY`.
- This is still a local deployment: the app runs on `http://127.0.0.1:8000` on each user’s machine.
- A simple hosted version check can be added later by publishing a small remote metadata file or endpoint with the latest package version.



Start ser command

```
uvicorn app.main:app --host 127.0.0.1 --port 8000
```