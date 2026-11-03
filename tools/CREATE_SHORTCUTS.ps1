# Creates .lnk files in the current CoinCat folder. Windows BAT files
# themselves cannot have arbitrary native icons; Windows shortcuts can.
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$icon = Join-Path $root 'app\CoinCat50.ico'
$items = @(
  @{Title='CoinCat v1.02 - START.lnk'; File='app\coincat_start.py'; Gui=$true}
)
$shell = New-Object -ComObject WScript.Shell
foreach ($item in $items) {
    $bat = Join-Path $root $item.File
    if (-not (Test-Path $bat)) { throw "Missing launcher: $($item.File)" }
    $shortcut = $shell.CreateShortcut((Join-Path $root $item.Title))
    if ($item.Gui) {
        $pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
        if (-not (Test-Path $pythonw)) { throw 'Run SETUP first to create local pythonw.exe' }
        $shortcut.TargetPath = $pythonw
        $shortcut.Arguments = '"' + $bat + '"'
    } else {
        $shortcut.TargetPath = $bat
    }
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = 'CoinCat v1.02 ETH Growth research, live Coinbase POST blocked'
    $shortcut.Save()
    Write-Host "Created $($item.Title)"
}
