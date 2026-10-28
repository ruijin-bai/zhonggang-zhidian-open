[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendEnv = Join-Path $projectRoot 'backend\.env'
$devDataDir = Join-Path $projectRoot 'backend\devdata'
$devDb = Join-Path $devDataDir 'run12.db'

function Get-LocalEnvValue([string]$Name) {
    if (-not (Test-Path -LiteralPath $backendEnv -PathType Leaf)) { return $null }
    $prefix = "$Name="
    $line = Get-Content -LiteralPath $backendEnv |
        Where-Object { $_.StartsWith($prefix) } |
        Select-Object -First 1
    if (-not $line) { return $null }
    return $line.Substring($prefix.Length).Trim().Trim('"').Trim("'")
}

function Set-ProcessValue([string]$Name, [string]$Value) {
    if (-not [Environment]::GetEnvironmentVariable($Name, 'Process')) {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
    }
}

if (-not (Test-Path -LiteralPath $devDb -PathType Leaf)) {
    throw "Governed development database not found: $devDb. Restore the approved dataset or initialize a new database before startup."
}

$localSecret = Get-LocalEnvValue 'SECRET_KEY'
if (-not $localSecret) { throw 'backend/.env is missing SECRET_KEY; saved model settings cannot be decrypted.' }
$modelKey = Get-LocalEnvValue 'MODEL_CONFIG_ENCRYPTION_KEY'
if (-not $modelKey) { $modelKey = $localSecret }

Set-ProcessValue 'POSTGRES_PASSWORD' 'DevPostgres@2026'
$minioUser = Get-LocalEnvValue 'MINIO_ACCESS_KEY'
if (-not $minioUser) { $minioUser = 'minioadmin' }
$minioPassword = Get-LocalEnvValue 'MINIO_SECRET_KEY'
if (-not $minioPassword) { $minioPassword = 'minioadmin123' }
Set-ProcessValue 'MINIO_ROOT_USER' $minioUser
Set-ProcessValue 'MINIO_ROOT_PASSWORD' $minioPassword
Set-ProcessValue 'SECRET_KEY' $localSecret
Set-ProcessValue 'MODEL_CONFIG_ENCRYPTION_KEY' $modelKey
Set-ProcessValue 'DEV_MODEL_CONFIG_ENCRYPTION_KEY' $modelKey
Set-ProcessValue 'SEED_DEFAULT_PASSWORD' 'Zhonggang@123'

$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    $docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
}
if (-not (Test-Path -LiteralPath $docker -PathType Leaf)) {
    throw 'Docker CLI not found. Start Docker Desktop first.'
}

Push-Location -LiteralPath $projectRoot
try {
    & $docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build --detach --wait
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Zhonggang Zhidan development environment: http://127.0.0.1:8080'
Write-Host 'Shared development password: Zhonggang@123'
Write-Host 'R1 employee | R2 reviewer | R3 kbadmin | R4 admin'
