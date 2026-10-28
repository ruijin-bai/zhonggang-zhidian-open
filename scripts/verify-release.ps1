[CmdletBinding()]
param(
    # Fail instead of skipping when Docker CLI is unavailable.
    [switch]$RequireDocker,
    # Verify a running backend after static gates. Password comes from RUNTIME_SMOKE_PASSWORD.
    [switch]$RuntimeSmoke,
    [string]$RuntimeBaseUrl = 'http://127.0.0.1:8010',
    # Build and start the complete Compose stack, then verify both HTTP entrypoints.
    [switch]$ContainerSmoke
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$webRoot = Join-Path $projectRoot 'web'
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$failures = [System.Collections.Generic.List[string]]::new()

function Write-GateResult([string]$state, [string]$name, [string]$detail = '') {
    $suffix = if ($detail) { " - $detail" } else { '' }
    Write-Host "[$state] $name$suffix"
}

function Invoke-GateStep([string]$name, [scriptblock]$action) {
    Write-Host "`n==> $name"
    try {
        $global:LASTEXITCODE = 0
        & $action
        if ($LASTEXITCODE -ne 0) {
            throw "command exited with code $LASTEXITCODE"
        }
        Write-GateResult 'PASS' $name
    } catch {
        $message = $_.Exception.Message
        $script:failures.Add("${name}: $message")
        Write-GateResult 'FAIL' $name $message
    }
}

function Invoke-HttpProbe(
    [string]$Uri,
    [int]$MaxAttempts = 10,
    [int]$DelaySeconds = 2
) {
    $lastFailure = 'no response'
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 20
            if ($response.StatusCode -eq 200) {
                return $response
            }
            $lastFailure = "HTTP $($response.StatusCode)"
        } catch {
            $lastFailure = $_.Exception.Message
        }
        if ($attempt -lt $MaxAttempts) {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    throw "HTTP probe failed after $MaxAttempts attempts: $Uri ($lastFailure)"
}

Write-Host "Zhonggang Zhidan release gate"
Write-Host "Project root: $projectRoot"
Write-Host "Local gates do not install dependencies or delete data. -ContainerSmoke builds and starts the Compose stack."

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $failures.Add("Backend pytest: project virtual environment not found at $python. Prepare local dependencies first.")
    Write-GateResult 'FAIL' 'Backend pytest' 'backend/.venv/Scripts/python.exe not found'
} else {
    Invoke-GateStep 'Backend pytest (isolated SQLite + mock models)' {
        Push-Location -LiteralPath $backendRoot
        try { & $python -m pytest -q } finally { Pop-Location }
    }
}

$migrationPython = $python
if (-not (Test-Path -LiteralPath $migrationPython -PathType Leaf)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $systemPython) { $migrationPython = $systemPython.Source } else { $migrationPython = $null }
}
if ($null -eq $migrationPython) {
    $failures.Add('Migration source-chain check: Python interpreter not found.')
    Write-GateResult 'FAIL' 'Migration source-chain check' 'Python interpreter not found'
} else {
    Invoke-GateStep 'Migration source-chain check (no database connection)' {
        Push-Location -LiteralPath $backendRoot
        try { & $migrationPython scripts/check_migrations.py } finally { Pop-Location }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $webRoot 'node_modules') -PathType Container)) {
    $failures.Add('Frontend build: web/node_modules not found. The release gate does not run npm install or npm ci.')
    Write-GateResult 'FAIL' 'Frontend build' 'web/node_modules not found'
} else {
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npmCommand) { $npmCommand = Get-Command npm -ErrorAction SilentlyContinue }
    if ($null -eq $npmCommand) {
        $failures.Add('Frontend build: npm not found.')
        Write-GateResult 'FAIL' 'Frontend build' 'npm not found'
    } else {
        $npmExecutable = $npmCommand.Source
        Invoke-GateStep 'Frontend production build' {
            Push-Location -LiteralPath $webRoot
            try { & $npmExecutable run build } finally { Pop-Location }
        }
    }
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerExecutable = if ($null -ne $dockerCommand) { $dockerCommand.Source } else { $null }
if ($null -eq $dockerCommand) {
    $desktopDocker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    if (Test-Path -LiteralPath $desktopDocker -PathType Leaf) {
        $dockerCommand = Get-Item -LiteralPath $desktopDocker
        $dockerExecutable = $desktopDocker
    }
}
if ($null -ne $dockerCommand) {
    Invoke-GateStep 'Docker Compose static check (no build or start)' {
        Push-Location -LiteralPath $projectRoot
        $required = @('POSTGRES_PASSWORD', 'MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD', 'SECRET_KEY', 'MODEL_CONFIG_ENCRYPTION_KEY', 'SEED_DEFAULT_PASSWORD')
        $previous = @{}
        try {
            foreach ($name in $required) {
                $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
                if (-not $previous[$name]) {
                    [Environment]::SetEnvironmentVariable($name, "static-check-$name-0123456789abcdef", 'Process')
                }
            }
            & $dockerExecutable compose config --quiet
        } finally {
            foreach ($name in $required) {
                [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
            }
            Pop-Location
        }
    }
} elseif ($RequireDocker) {
    $failures.Add('Docker Compose static check: Docker CLI not found (--RequireDocker was specified).')
    Write-GateResult 'FAIL' 'Docker Compose static check' 'Docker CLI not found'
} else {
    Write-GateResult 'SKIP' 'Docker Compose static check' 'Docker CLI not found; use -RequireDocker to make this a failure'
}

if ($ContainerSmoke) {
    if ($null -eq $dockerCommand) {
        $failures.Add('Container smoke: Docker CLI not found.')
        Write-GateResult 'FAIL' 'Container smoke' 'Docker CLI not found'
    } else {
        Invoke-GateStep 'Container engine readiness' {
            & $dockerExecutable info --format '{{.ServerVersion}}'
        }
        $containerSecrets = @('POSTGRES_PASSWORD', 'MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD', 'SECRET_KEY', 'MODEL_CONFIG_ENCRYPTION_KEY', 'SEED_DEFAULT_PASSWORD')
        $missingSecrets = @($containerSecrets | Where-Object { -not [Environment]::GetEnvironmentVariable($_, 'Process') })
        if ($missingSecrets.Count -gt 0) {
            $failures.Add("Container smoke: missing process environment values: $($missingSecrets -join ', ')")
            Write-GateResult 'FAIL' 'Container smoke' "missing: $($missingSecrets -join ', ')"
        } else {
            Invoke-GateStep 'Compose build and start' {
                Push-Location -LiteralPath $projectRoot
                try { & $dockerExecutable compose up --build --detach --wait } finally { Pop-Location }
            }
            Invoke-GateStep 'Container HTTP smoke' {
                Invoke-HttpProbe -Uri 'http://127.0.0.1:8000/ready' | Out-Null
                Invoke-HttpProbe -Uri 'http://127.0.0.1:8080' | Out-Null
            }
        }
    }
}

if ($RuntimeSmoke) {
    Invoke-GateStep 'Runtime ownership, health, readiness and login smoke' {
        & (Join-Path $PSScriptRoot 'verify-runtime.ps1') -BaseUrl $RuntimeBaseUrl
    }
}

Write-Host "`n=============================="
if ($failures.Count -eq 0) {
    Write-Host 'Release gate passed.'
    exit 0
}

Write-Host "Release gate failed ($($failures.Count) item(s)):"
foreach ($failure in $failures) {
    Write-Host "- $failure"
}
exit 1
