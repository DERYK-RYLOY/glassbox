# GLASSBOX - zero-babysitting Windows installer
# Usage:  powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$server = Join-Path $root 'python\glassbox_server.py'

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    OK: $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !! $msg" -ForegroundColor Yellow }

Write-Host ''
Write-Host '  GLASSBOX - audited by code, not vibes' -ForegroundColor Magenta
Write-Host '  installing...' -ForegroundColor DarkGray

# --- 1. Python ------------------------------------------------------------
Step '1/5' 'Checking Python 3.10+'
$python = $null
foreach ($cmd in @('python', 'py')) {
    try {
        $v = & $cmd --version 2>$null
        if ($v -match 'Python (\d+)\.(\d+)') { $python = $cmd; $maj = [int]$matches[1]; $min = [int]$matches[2]; break }
    } catch {}
}
if (-not $python) {
    Warn 'Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick "Add to PATH"), then re-run this installer.'
    exit 1
}
Ok "$python $v"

# --- 2. Python dependencies -----------------------------------------------
Step '2/5' 'Installing dependencies (mcp, onnxruntime, tokenizers)'
& $python -m pip install -r (Join-Path $root 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { Warn 'pip failed - are you offline? Run again with internet access.'; exit 1 }
Ok 'dependencies installed'

# --- 3. Lua (optional but recommended) ------------------------------------
Step '3/5' 'Checking Lua 5.4'
$luaFound = $null
try { & lua -v 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $luaFound = 'lua' } } catch {}
foreach ($p in @("$env:LOCALAPPDATA\Programs\Lua\bin\lua.exe", 'C:\Program Files\Lua\5.4\lua.exe', 'C:\Program Files (x86)\Lua\5.4\lua.exe')) {
    if (-not $luaFound -and (Test-Path $p)) { $luaFound = $p }
}
if ($luaFound) { Ok "Lua found: $luaFound" }
else {
    Warn 'Lua not found - Glassbox will run on its Python fallback (fully functional).'
    Write-Host '    For the native Lua engine, install with:  winget install DEVCOM.Lua' -ForegroundColor DarkGray
}

# --- 4. Wire into OpenCode (if present) -----------------------------------
Step '4/5' 'Wiring Glassbox into OpenCode (if installed)'
$opencode = Get-Command opencode -ErrorAction SilentlyContinue
if ($opencode) {
    $already = (opencode mcp list 2>$null | Out-String) -match 'glassbox'
    if ($already) { Ok 'OpenCode already has glassbox registered - skipping' }
    else {
        opencode mcp add glassbox --global -- $python $server | Out-Null
        Ok 'OpenCode configured (global). Restart/reconnect MCP to see the tools.'
    }
} else {
    Warn 'OpenCode not on PATH - skipping auto-wire.'
    Write-Host '    Any MCP-capable CLI can use Glassbox. Add to your MCP config:' -ForegroundColor DarkGray
    Write-Host "    { `"mcp`": { `"servers`": { `"glassbox`": { `"type`": `"local`", `"command`": [`"$python`", `"$server`"] } } } }" -ForegroundColor DarkGray
}

# --- 5. Self-test ----------------------------------------------------------
Step '5/5' 'Self-test'
Push-Location $root
$status = & $python -c "import sys; sys.path.insert(0, 'python'); import glassbox_server as g; print(g.glassbox_status())"
Pop-Location
Write-Host "    $status" -ForegroundColor DarkGray
if ($status -match '"backend"') {
    Write-Host ''
    Write-Host '  GLASSBOX is installed. Open your AI CLI and try:' -ForegroundColor Green
    Write-Host '    "use glassbox to plan how to ship my project this month"' -ForegroundColor White
    Write-Host '    "use glassbox deepthink brainstorm on ..."' -ForegroundColor White
    Write-Host ''
    exit 0
} else {
    Warn 'Self-test did not return a backend. Run: python python\glassbox_server.py (it waits for MCP stdio input - Ctrl+C to stop)'
    exit 1
}
