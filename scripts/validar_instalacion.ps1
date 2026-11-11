[CmdletBinding()]
param(
    [ValidateSet('Preparar', 'Descargar', 'Recuperar', 'Validar')]
    [string]$Modo = 'Preparar',
    [string]$Commit = 'HEAD',
    [string]$DirectorioTrabajo,
    [string]$Python,
    [string]$OrigenPreparacion,
    [switch]$AutorizarDescargas,
    [switch]$AutorizarInstalacion,
    [switch]$AutorizarRecuperacion
)

$ErrorActionPreference = 'Stop'
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Se requiere Windows.' }
    if ($Modo -eq 'Descargar' -and -not $AutorizarDescargas) {
        throw 'Descargar requiere -AutorizarDescargas. No se ha descargado nada.'
    }
    if ($Modo -eq 'Validar' -and -not $AutorizarInstalacion) {
        throw 'Validar requiere -AutorizarInstalacion. No se ha instalado nada.'
    }
    if ($Modo -eq 'Recuperar' -and (-not $AutorizarRecuperacion -or -not $OrigenPreparacion)) {
        throw 'Recuperar requiere origen y -AutorizarRecuperacion.'
    }
    if (($AutorizarDescargas -and $Modo -ne 'Descargar') -or
        ($AutorizarInstalacion -and $Modo -ne 'Validar') -or
        ($AutorizarRecuperacion -and $Modo -ne 'Recuperar') -or
        ($OrigenPreparacion -and $Modo -ne 'Recuperar')) {
        throw 'La autorizacion no corresponde al modo seleccionado.'
    }
    if ($Modo -eq 'Preparar' -and $DirectorioTrabajo) {
        throw 'Preparar siempre crea una carpeta temporal nueva.'
    }
    if ($Modo -ne 'Preparar' -and -not $DirectorioTrabajo) {
        throw 'Indica -DirectorioTrabajo con la ruta devuelta por Preparar.'
    }
    if (-not $Python) {
        $Python = (Get-Command python.exe -ErrorAction Stop).Source
    }
    # No invocar aliases de Store ni gestores que puedan instalar Python.
    if ($Python -match '[\\/]WindowsApps[\\/]') { throw 'Indica -Python con el ejecutable base real.' }
    $argumentos = @('-I', '-B', (Join-Path $PSScriptRoot 'comprobar_entorno.py'),
                   '--modo', $Modo.ToLowerInvariant())
    if ($Modo -eq 'Preparar') {
        $argumentos += @('--repositorio', (Split-Path -Parent $PSScriptRoot), '--commit', $Commit)
    } else {
        $argumentos += @('--directorio', $DirectorioTrabajo)
    }
    if ($AutorizarDescargas) { $argumentos += '--autorizar-descargas' }
    if ($AutorizarInstalacion) { $argumentos += '--autorizar-instalacion' }
    if ($AutorizarRecuperacion) { $argumentos += '--autorizar-recuperacion' }
    if ($OrigenPreparacion) { $argumentos += @('--origen', $OrigenPreparacion) }
    & $Python @argumentos
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} catch {
    # No volcar excepciones del shell: pueden contener rutas o credenciales.
    [Console]::Error.WriteLine('No se pudo iniciar el procedimiento. Comprueba Windows, Python 3.14 y los parametros/autorizaciones indicados en docs/instalacion.md.')
    exit 1
}
