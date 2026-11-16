# Creates shortcuts for the app on the Desktop and in the Start menu.
# (This file is ASCII only on purpose: the Korean shortcut name is stored as Base64.)
param([string]$OutDir = "")

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('7Jeg7YG0656Y7Iqk7IiY7ZWZ6rO87ZWZ7KCE66y47ZWZ7JuQ'))
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
    $lnk.Description      = $name
    $lnk.Save()
    Write-Host "Created: $path"
}

# Remove the shortcut that an earlier version created under the old name (only if it points at this start.bat).
$oldName = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('7IiY7JeFIOyKrOudvOydtOuTnCDrqZTsnbTsu6Q='))
function Remove-OldLink($dir) {
    $old = Join-Path $dir ($oldName + '.lnk')
    if (Test-Path $old) {
        $ws = New-Object -ComObject WScript.Shell
        if ($ws.CreateShortcut($old).Arguments -like '*start.bat*') { Remove-Item $old -Force; Write-Host "Removed old shortcut: $old" }
    }
}

if ($OutDir -ne "") {
    Remove-OldLink $OutDir
    New-AppLink $OutDir
} else {
    $desktop = [Environment]::GetFolderPath('Desktop'); $programs = [Environment]::GetFolderPath('Programs')   # Start menu (searchable)
    Remove-OldLink $desktop; Remove-OldLink $programs
    New-AppLink $desktop
    New-AppLink $programs
}
