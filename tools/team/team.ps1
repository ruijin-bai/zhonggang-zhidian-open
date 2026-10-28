[CmdletBinding()]
param(
  [ValidateSet('Init','Install','Doctor','Backend','Frontend','Check','DbStop')][string]$Action='Doctor',
  [ValidateSet('owner','teammate')][string]$Role='owner',
  [string]$PythonExecutable='python'
)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
& $PythonExecutable (Join-Path $PSScriptRoot 'team.py') $Action --role $Role
if ($LASTEXITCODE -ne 0) { throw "Team $Action failed ($LASTEXITCODE)." }
