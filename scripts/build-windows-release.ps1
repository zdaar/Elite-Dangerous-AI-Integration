param(
    [switch]$SkipInstall,
    [switch]$SkipTests,
    [switch]$SkipMsi
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# WSL-launched PowerShell sessions can inherit a truncated PATHEXT (for
# example only `.CPL`). npm lifecycle scripts then cannot resolve npx.cmd or
# ordinary .exe tools even though their directories are on PATH.
if (($env:PATHEXT -split ';') -notcontains '.EXE' -or ($env:PATHEXT -split ';') -notcontains '.CMD') {
    $env:PATHEXT = '.COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL'
}

$bundledPython = Join-Path $repo '.tools\python312-win\python.exe'
if (Test-Path $bundledPython) {
    $python = $bundledPython
} else {
    $python = (Get-Command py -ErrorAction Stop).Source
}
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$node = (Get-Command node.exe -ErrorAction Stop).Source

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    if ($python -like '*\py.exe') {
        $processArguments = @('-3.12') + $Arguments
    } else {
        $processArguments = $Arguments
    }
    $process = Start-Process -FilePath $python -ArgumentList $processArguments -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Python command failed with exit code $($process.ExitCode)" }
}

function Invoke-Npm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $process = Start-Process -FilePath $npm -ArgumentList $Arguments -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "npm command failed with exit code $($process.ExitCode)" }
}

function Invoke-Node {
    param(
        [string]$WorkingDirectory = $repo,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    $process = Start-Process -FilePath $node -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Node command failed with exit code $($process.ExitCode)" }
}

if (-not $SkipInstall) {
    Invoke-Python -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt')
    Invoke-Npm -Arguments @('ci')
    Invoke-Npm -Arguments @('--prefix', 'ui', 'ci')
} elseif (-not (Test-Path (Join-Path $repo 'ui\node_modules\@esbuild\win32-x64\esbuild.exe'))) {
    throw 'Windows UI dependencies are missing. Re-run without -SkipInstall (the current node_modules was likely installed by WSL/Linux).'
}

if (-not $SkipTests) {
    Invoke-Python -Arguments @('-m', 'pytest', '--timeout', '10', 'test', '-q')
}

Invoke-Python -Arguments @('-m', 'PyInstaller', '--noconfirm', '--clean', 'Chat.spec')

# Call the JavaScript entry points directly. This also works when dependencies
# were restored from WSL, where node_modules/.bin may contain POSIX symlinks
# instead of the Windows .cmd shims that npx expects.
Invoke-Node -WorkingDirectory (Join-Path $repo 'ui') -Arguments @('node_modules\@angular\cli\bin\ng.js', 'build', '--configuration', 'production')

# electron-builder updates an existing --dir output in place and can leave
# retired resources behind. Remove only generated release outputs so every
# package is a clean mirror of the current source tree.
$unpackedOutput = Join-Path $repo 'dist\win-unpacked'
if (Test-Path $unpackedOutput) {
    Remove-Item $unpackedOutput -Recurse -Force
}
if (-not $SkipMsi) {
    Get-ChildItem (Join-Path $repo 'dist') -Filter '*.msi' -ErrorAction SilentlyContinue | Remove-Item -Force
}
Invoke-Node -Arguments @('node_modules\electron-builder\cli.js', '--dir')

if (-not $SkipMsi) {
    Invoke-Node -Arguments @('node_modules\electron-builder\cli.js', '--win', 'msi')
}

Write-Host 'Build complete:'
Write-Host "  Unpacked app: $repo\dist\win-unpacked"
if (-not $SkipMsi) {
    Get-ChildItem (Join-Path $repo 'dist') -Filter '*.msi' | ForEach-Object {
        Write-Host "  Installer: $($_.FullName)"
    }
}
