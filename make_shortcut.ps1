# Creates shortcuts for "Class Slide Maker" on the Desktop and in the Start menu.
# (This file is ASCII only on purpose: the Korean shortcut name is stored as Base64.)
param([string]$OutDir = "")

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('7IiY7JeFIOyKrOudvOydtOuTnCDrqZTsnbTsu6Q='))
$bat  = Join-Path $root 'start.bat'
$icon = Join-Path $root 'mathslide\static\icon.ico'

if (-not (Test-Path $bat)) { Write-Host "start.bat not found next to this script."; exit 1 }

function New-AppLink($dir) {
    New-Item -ItemType Directory -Force $dir | Out-Null
    $path = Join-Path $dir ($name + '.lnk')
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($path)
    # Target is cmd.exe (not the .bat) so that Windows allows "Pin to taskbar" on this shortcut.
    $lnk.TargetPath       = $env:ComSpec
    $lnk.Arguments        = '/c ""' + $bat + '""'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation     = $icon + ',0'
    $lnk.WindowStyle      = 7        # start minimized (the console window stays in the taskbar; close it to quit)
    $lnk.Description      = 'Class Slide Maker'
    $lnk.Save()
    Write-Host "Created: $path"
}

if ($OutDir -ne "") {
    New-AppLink $OutDir
} else {
    New-AppLink ([Environment]::GetFolderPath('Desktop'))
    New-AppLink ([Environment]::GetFolderPath('Programs'))   # Start menu (searchable)
}
