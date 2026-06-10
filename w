$ErrorActionPreference = "Stop"

$BaseUrl = $env:NEUROGATE_SETUP_BASE_URL
if (-not $BaseUrl) {
    $BaseUrl = "https://github.com/OlegGorsky/VS-Code-NeuroGate-Extensions/raw/main"
}

$TmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ng-vscode-" + [System.Guid]::NewGuid().ToString("N"))
$Setup = Join-Path $TmpDir "setup_neurogate_vscode.py"

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Get-PythonInvocation {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }

    foreach ($name in @("python3", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            return @($cmd.Source)
        }
    }

    return $null
}

function Install-Python {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
        Refresh-Path
        return
    }
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install python -y
        Refresh-Path
        return
    }
    throw "Python is missing. Install Python 3 or winget/choco, then run again."
}

function Install-VSCode {
    if (Get-Command code -ErrorAction SilentlyContinue) {
        return
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Microsoft.VisualStudioCode --accept-package-agreements --accept-source-agreements
        Refresh-Path
        return
    }
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install vscode -y
        Refresh-Path
        return
    }
}

function Invoke-PythonSetup($Invocation, $Script, $ScriptArgs) {
    $allArgs = @()
    if ($Invocation.Count -gt 1) {
        $allArgs += $Invocation[1..($Invocation.Count - 1)]
    }
    $allArgs += $Script
    $allArgs += "--install-missing-deps"
    $allArgs += $ScriptArgs
    & $Invocation[0] @allArgs
}

New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null
try {
    Invoke-WebRequest -UseBasicParsing "$BaseUrl/setup_neurogate_vscode.py" -OutFile $Setup

    $python = Get-PythonInvocation
    if (-not $python) {
        Install-Python
        $python = Get-PythonInvocation
    }
    if (-not $python) {
        throw "Python is missing and could not be installed automatically."
    }

    Install-VSCode
    Invoke-PythonSetup $python $Setup $args
}
finally {
    Remove-Item -Recurse -Force $TmpDir -ErrorAction SilentlyContinue
}
