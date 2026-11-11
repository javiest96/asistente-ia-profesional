[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Puerto = 8501,
    [switch]$Preparar
)

$ErrorActionPreference = 'Stop'
try {
    $raizDemo = Split-Path -Parent $PSScriptRoot
    $pythonDemo = Join-Path $raizDemo '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonDemo -PathType Leaf)) {
        throw 'No existe el entorno original del proyecto.'
    }
    $argumentosDemo = @('-I', '-B', (Join-Path $PSScriptRoot 'demo_local.py'), '--puerto', [string]$Puerto)
    if ($Preparar) { $argumentosDemo += '--preparar' }
    # Primer plano: Ctrl+C se entrega al proceso, sin arrancar Ollama.
    & $pythonDemo @argumentosDemo
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} catch {
    [Console]::Error.WriteLine('No se pudo iniciar la demo. Revisa el entorno original y demo/README.md.')
    exit 1
}
