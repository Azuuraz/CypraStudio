CYPRA MATRIX STUDIO OFFLINE DEPENDENCY KIT

Setup contains installers and Python packages only; the main MatrixStudio
folder remains the application.

On a fresh PC, keep Setup inside MatrixStudio and launch:
  MatrixStudio\START.bat

START.bat automatically reuses a valid MatrixStudio\.venv. If none exists,
it scans Setup, installs the bundled Python runtime when needed, creates .venv,
and copies the bundled Python packages without contacting the internet.

OFFLINE_SETUP.bat remains available as an optional manual pre-install step.
When Setup\python_packages is not present, START.bat instead creates/repairs the
environment from the online Python package repository.

Included:
- Python 3.12.10 installer
- Ollama installer/executable supplied by the owner
- Offline Python package cache in python_packages\

The package cache must contain FastAPI, Uvicorn, OpenAI, Requests, HTTPX,
python-multipart, Pydantic, Pillow, pywebview, and pywinpty. Ollama model
weights are not duplicated here; copy the required Ollama model store to the
target PC or install/pull models before using chat.
