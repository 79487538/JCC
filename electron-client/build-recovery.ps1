$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $project "..")
$dist = Join-Path $root "dist"
$unpacked = Join-Path $dist "win-unpacked"

function Remove-ProjectPath($name) {
  $path = Join-Path $project $name
  if (Test-Path -LiteralPath $path) {
    $resolved = (Resolve-Path -LiteralPath $path).Path
    if (-not $resolved.StartsWith($project)) {
      throw "Refusing to remove outside project: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
  }
}

function Invoke-NpmInstall() {
  npm install --no-audit --fund=false
  if ($LASTEXITCODE -ne 0) {
    throw "npm install failed"
  }
}

function Invoke-ManualUnpackedFallback() {
  $zip = Join-Path $env:LOCALAPPDATA "electron\Cache\electron-v33.2.1-win32-x64.zip"
  if (-not (Test-Path -LiteralPath $zip)) {
    throw "Electron cached runtime not found for manual fallback: $zip"
  }

  if (Test-Path -LiteralPath $unpacked) {
    $resolved = (Resolve-Path -LiteralPath $unpacked).Path
    if (-not $resolved.StartsWith($root.Path)) {
      throw "Refusing to remove outside workspace: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
  }

  New-Item -ItemType Directory -Force -Path $unpacked | Out-Null
  Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force

  $appDir = Join-Path $unpacked "resources\app"
  New-Item -ItemType Directory -Force -Path $appDir | Out-Null
  foreach ($file in @("index.html", "main.js", "preload.js", "renderer.js", "styles.css", "package.json")) {
    Copy-Item -LiteralPath (Join-Path $project $file) -Destination $appDir -Force
  }

  $electronExe = Join-Path $unpacked "electron.exe"
  if (Test-Path -LiteralPath $electronExe) {
    Rename-Item -LiteralPath $electronExe -NewName "JCC AI Assistant.exe" -Force
  }
}

npm config set registry https://registry.npmmirror.com
npm config set fetch-retries 5
npm config set fetch-retry-mintimeout 20000
npm config set fetch-retry-maxtimeout 120000
npm cache clean --force

Remove-ProjectPath "node_modules"
Remove-ProjectPath "package-lock.json"

$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"

try {
  Invoke-NpmInstall
} catch {
  npm config set registry https://registry.npmjs.org
  Invoke-NpmInstall
}

try {
  npm run dist
  if ($LASTEXITCODE -ne 0) {
    throw "npm run dist failed"
  }
} catch {
  try {
    npx electron-builder --dir
    if ($LASTEXITCODE -ne 0) {
      throw "electron-builder --dir failed"
    }
  } catch {
    Invoke-ManualUnpackedFallback
  }
}

if (-not (Test-Path -LiteralPath (Join-Path $dist "JCC-AI-Setup.exe")) -and -not (Test-Path -LiteralPath $unpacked)) {
  throw "Build recovery failed: no installer or win-unpacked output generated"
}

Write-Output "Build recovery complete."
