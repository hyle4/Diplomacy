# Install uv if needed, then install Diplomacy and open it.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  irm https://astral.sh/uv/install.ps1 | iex
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv was not installed. Open a new terminal and run .\install.ps1 again."
}

uv python install 3.12
uv sync
uv run python app.py
