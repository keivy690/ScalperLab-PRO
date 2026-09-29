# ScalperLab 1.0

Desktop workspace for researching, reviewing and validating MetaTrader 5 strategies on Windows, with a first demo-only declarative execution engine.

## Safety status

- The MT5 connector is read-only by default and reports the connected terminal/account state.
- Demo order closing requires an explicit demo arming step and a confirmation phrase.
- The explicit demo smoke test submits one minimum-size EURUSD buy (capped at 0.01 lot), then reconciles and immediately requests its close; it refuses to run when any position already exists.
- The declarative engine includes adaptations for FX cross-sectional momentum, daily time-series momentum, broker-swap carry, weekend-gap reversal and London ORB. These are executable hypotheses, not exact reproductions of the studies or profitability claims. It defaults to observation and requires a separate confirmation to send orders on DEMO. It starts stopped after application restart.
- Imported `.mq5`, `.py` and `.txt` files are analyzed and saved as review drafts; their source is never executed or compiled by the application. Text files may contain other indicator languages and require manual rule mapping before the engine can use them.
- Engine limits are capped at 0.01 lot, one attempted entry per strategy session, one account position maximum, user-configured trade risk no higher than 0.25% and daily stop no higher than 1%. Risk estimates exclude costs and execution gaps.
- REAL order paths exist for the analyst and declarative strategy engines. They require the matching REAL account, explicit text confirmation at every start, terminal/account trading permissions, fresh data, broker checks, configured risk limits, protective stops, no existing position or pending order, and post-send reconciliation. CONTEST accounts are rejected. REAL has not completed independent operational or statistical homologation; availability in code is not a readiness or profitability claim.
- Search providers are optional. GitHub repository search works without a key; YouTube, Brave Search and OpenAI require keys supplied through process environment variables.

## Run on Windows

Use Python 3.12 (MetaTrader5's native package may not support the newest Python versions yet):

For normal use, double-click `Iniciar-ScalperLab.bat` in the project folder. It reuses `.venv`, creates it with Python 3.12 if needed, checks pinned dependencies from `requirements.lock`, warns if the MT5 terminal is not open, and launches the desktop interface. Search keys remain optional and are not requested or stored by the launcher.

For a Windows pilot package, install the development dependencies and run `powershell -ExecutionPolicy Bypass -File .\build-windows-pilot.ps1`. The script creates a PyInstaller `onedir` bundle under `dist\ScalperLab` and a ZIP for transfer. The Python MT5 connector and its native API are bundled with the app; the read-only MQL5 calendar service and an assisted terminal installer are included as separate files. This is a test package, not a signed installer; see `docs/BUILD_WINDOWS_PILOT.md` for prerequisites and validation steps.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python run.py
```

Install and log in to the MetaTrader 5 desktop terminal separately. ScalperLab does not save the terminal password.

Developer verification uses the separate test dependencies:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.lock
.\.venv\Scripts\python -m pytest -q
```

Optional provider variables: `SCALPERLAB_BRAVE_API_KEY`, `SCALPERLAB_YOUTUBE_API_KEY`, `OPENAI_API_KEY`, and `SCALPERLAB_AI_MODEL`.

The database and imported strategy text are stored under `%USERPROFILE%\ScalperLabData\`, outside this project directory.

## Project map

- `scalperlab/`: local desktop service, MT5 adapter, source search, storage and validation.
- `templates/` and `static/`: responsive dashboard.
- `.agents/skills/`: nine project skills grouped by responsibility.
- `tests/`: local regression tests; MT5 tests use a fake terminal and do not send orders.

See `docs/SAFETY_AND_LIMITS.md` and `docs/ARCHITECTURE.md` before enabling demo operations.
