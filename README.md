# Viral Content Hunter

The T1 backend provides local SQLite persistence, a durable job queue, Claude review, the approved Discovery Inbox, and an authenticated FastAPI API.

## Run on Windows

From the repository root, use Python 3.12 and install the project and its test dependencies into a local virtual environment. The project metadata and pytest configuration live in the root `pyproject.toml`.

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -q
uvicorn hunter.api.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

The last command starts a single local process. Check it from another PowerShell window with `Invoke-RestMethod http://127.0.0.1:8000/health`. Startup migrates the database, reclaims expired job leases, and runs retention.

## Configure access

Copy `config/settings.example.toml` to `config/settings.local.toml`. Keep the local file on this machine. Generate the admin password hash interactively with `python -m hunter.api.auth` and assign the result to `auth.admin_password_hash`. Set `auth.claude_service_token` to a separately generated random token of at least 32 characters. Both settings can also come from the environment.

The dashboard exchanges the admin password at `POST /auth/login` for a bearer session. The Claude leader uses its own service token. Until credentials are configured, those access paths deny requests. The incremental budget stays at 0 VND.

See [architecture and integration contracts](docs/ARCHITECTURE.md) and the [API reference](docs/API.md).
