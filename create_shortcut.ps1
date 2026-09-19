$targetDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$exePath = Join-Path $targetDir "dist\PCAutoCleaner\PCAutoCleaner.exe"
$vbsPath = Join-Path $targetDir "start_silent.vbs"
$icoPath = Join-Path $targetDir "assets\icon.ico"

$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut((Join-Path $DesktopPath "PC Auto Cleaner.lnk"))

if (Test-Path $exePath) {
    $Shortcut.TargetPath = $exePath
    $Shortcut.WorkingDirectory = (Split-Path $exePath -Parent)
    $Shortcut.IconLocation = "$exePath,0"
} else {
    $Shortcut.TargetPath = "wscript.exe"
    $Shortcut.Arguments = "`"$vbsPath`""
    $Shortcut.WorkingDirectory = $targetDir
    if (Test-Path $icoPath) {
        $Shortcut.IconLocation = "$icoPath,0"
    }
}
$Shortcut.Description = "PC Auto Cleaner & RAM Optimizer"
$Shortcut.Save()
Write-Host "Desktop shortcut created successfully at: $DesktopPath\PC Auto Cleaner.lnk"

# Clean up obsolete bat shortcut if present
$oldBatShortcut = Join-Path $DesktopPath "start_cleaner.bat - Shortcut.lnk"
if (Test-Path $oldBatShortcut) {
    Remove-Item $oldBatShortcut -Force -ErrorAction SilentlyContinue
}
