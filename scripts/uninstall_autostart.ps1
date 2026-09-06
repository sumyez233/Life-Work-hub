# lifehub 开机自启卸载脚本
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$startupFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$shortcutPath = Join-Path $startupFolder "lifehub.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "✓ 开机自启快捷方式已移除 ($shortcutPath)" -ForegroundColor Green
} else {
    Write-Host "未发现已配置的开机自启快捷方式。" -ForegroundColor Gray
}
