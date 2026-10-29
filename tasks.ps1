# DevPilot Tasks for Windows PowerShell
param(
    [Parameter(Position=0)]
    [ValidateSet("install", "lint", "format", "typecheck", "test", "web-dev", "web-build", "serve", "demo", "clean")]
    [string]$Task = "test"
)

$ErrorActionPreference = "Stop"

switch ($Task) {
    "install" {
        Write-Host "Installing DevPilot in editable mode with dev dependencies..." -ForegroundColor Cyan
        python -m pip install -e ".[dev]"
    }
    "lint" {
        Write-Host "Running ruff check..." -ForegroundColor Cyan
        python -m ruff check .
    }
    "format" {
        Write-Host "Running ruff format..." -ForegroundColor Cyan
        python -m ruff format .
    }
    "typecheck" {
        Write-Host "Running mypy type checks..." -ForegroundColor Cyan
        python -m mypy devpilot/core devpilot/config.py tests
    }
    "test" {
        Write-Host "Running pytest..." -ForegroundColor Cyan
        python -m pytest -q
    }
    "web-dev" {
        Write-Host "Starting web development server..." -ForegroundColor Cyan
        Set-Location web
        npm run dev
    }
    "web-build" {
        Write-Host "Building web frontend..." -ForegroundColor Cyan
        Set-Location web
        npm run build
    }
    "serve" {
        Write-Host "Starting DevPilot API server..." -ForegroundColor Cyan
        python -m uvicorn devpilot.api.app:app --reload --port 8000
    }
    "demo" {
        Write-Host "Running DevPilot demo..." -ForegroundColor Cyan
        python -m devpilot.cli demo
    }
    "clean" {
        Write-Host "Cleaning cache and build artifacts..." -ForegroundColor Cyan
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .pytest_cache, .mypy_cache, .ruff_cache, runs
        Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}
