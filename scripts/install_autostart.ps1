# lifehub 开机自启安装脚本
# 方式：在当前用户的 Windows 启动文件夹中创建快捷方式，登录时静默无窗启动
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$startupFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$shortcutPath = Join-Path $startupFolder "lifehub.lnk"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$targetScript = Join-Path $scriptDir "start_all.vbs"

if (-not (Test-Path $targetScript)) {
    Write-Host "错误：未找到启动脚本 $targetScript" -ForegroundColor Red
    exit 1
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "wscript.exe"
$shortcut.Arguments = "`"$targetScript`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.Description = "lifehub 个人中台后台常驻服务"
$shortcut.Save()

Write-Host "✓ 开机自启快捷方式已成功创建：" -ForegroundColor Green
Write-Host "  位置: $shortcutPath" -ForegroundColor Gray
Write-Host "  目标: $targetScript" -ForegroundColor Gray
Write-Host "以后开机登录 Windows 时，系统将自动在后台静默拉起 bot 与 serve 服务！" -ForegroundColor Cyan
