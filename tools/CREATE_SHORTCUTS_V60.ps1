# Creates .lnk files in the first CoinCat_v70 folder. Windows BAT files
# themselves cannot have arbitrary native icons; Windows shortcuts can.
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$icon = Join-Path $root 'app\CoinCat50.ico'
$items = @(
  @{Title='CoinCat v70 - START.lnk'; File='app\coincat_v601_silent.py'; Gui=$true},
  @{Title='CoinCat v70 - DEBUG START.lnk'; File='09_DEBUG_START_COINCAT_V60.bat'},
  @{Title='CoinCat v70 - SETUP.lnk'; File='02_SETUP_COINCAT_V60.bat'},
  @{Title='CoinCat v70 - VERIFY.lnk'; File='03_VERIFY_COINCAT_V60.bat'},
  @{Title='CoinCat v70 - GPU TEST.lnk'; File='05_VERIFY_GPU_V60.bat'},
  @{Title='CoinCat v70 - PRIVATE DATA CHECK.lnk'; File='06_VERIFY_PRIVATE_DATA_V60.bat'},
  @{Title='CoinCat v70 - FINAL SAFETY GATES.lnk'; File='07_FINAL_SAFETY_GATES_V60.bat'},
  @{Title='CoinCat v70 - COINBASE READ ONLY.lnk'; File='08_COINBASE_HISTORY_READONLY_V60.bat'}
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
    $shortcut.Description = 'CoinCat v70 source-mode, live Coinbase POST blocked'
    $shortcut.Save()
    Write-Host "Created $($item.Title)"
}
