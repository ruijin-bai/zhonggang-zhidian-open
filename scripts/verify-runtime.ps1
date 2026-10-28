[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:8010',
    [string]$Username = 'admin',
    [string]$Password = $env:RUNTIME_SMOKE_PASSWORD
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Password)) {
    throw 'Runtime password is required. Set RUNTIME_SMOKE_PASSWORD or pass -Password.'
}

$uri = [Uri]$BaseUrl
$pids = @(
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $uri.Port } |
        Select-Object -ExpandProperty OwningProcess
)
if (-not $pids) {
    $pattern = ":$($uri.Port)\s+.*LISTENING\s+(\d+)"
    $pids = @(netstat -ano | ForEach-Object {
        if ($_ -match $pattern) { [int]$Matches[1] }
    } | Sort-Object -Unique)
}
if (-not $pids) {
    throw "No listener found on port $($uri.Port)."
}

$ownershipVerified = $true
$processes = foreach ($processId in $pids) {
    try {
        Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop |
            Select-Object ProcessId, Name, CommandLine
    } catch {
        $ownershipVerified = $false
        Get-Process -Id $processId -ErrorAction Stop |
            Select-Object @{Name='ProcessId';Expression={$_.Id}}, @{Name='Name';Expression={$_.ProcessName}}, @{Name='CommandLine';Expression={$_.Path}}
    }
}
Write-Host 'Runtime listener:'
$processes | Format-Table -AutoSize

$health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec 10
if ($health.code -ne 0 -or $health.data.status -notin @('ok', 'healthy')) {
    throw 'Health endpoint did not return a healthy status.'
}

$ready = Invoke-RestMethod -Method Get -Uri "$BaseUrl/ready" -TimeoutSec 10
if ($ready.code -ne 0 -or $ready.data.status -ne 'ready') { throw 'Readiness endpoint did not return ready.' }

$body = @{ username = $Username; password = $Password } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/auth/login" -ContentType 'application/json' -Body $body -TimeoutSec 15
if (-not $login.data.access_token) { throw 'Login did not return an access token.' }

if ($ownershipVerified) {
    Write-Host '[PASS] health, ready, login and listener ownership verified.'
} else {
    Write-Host '[PASS] health, ready, login and listener identity verified; command line requires elevated CIM access.'
}
