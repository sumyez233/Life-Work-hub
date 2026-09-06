# lifehub 状态检查脚本
$Host.UI.RawUI.WindowTitle = 'lifehub 状态巡检'

Write-Host '=== lifehub 服务状态巡检 ===' -ForegroundColor Cyan

$pyList = Get-Process -Name 'python' -ErrorAction SilentlyContinue

if ($pyList) {
    Write-Host ('发现运行中的 Python 进程: ' + $pyList.Count + ' 个') -ForegroundColor Yellow
    foreach ($p in $pyList) {
        $ws = [math]::Round($p.WorkingSet64 / 1MB, 1)
        Write-Host ('  - PID: ' + $p.Id + ' (内存占用: ' + $ws + ' MB)') -ForegroundColor Gray
    }
} else {
    Write-Host '当前未发现运行中的 Python 进程' -ForegroundColor Gray
}

# 检查 8420 API 服务状态 (HTTP 请求探测)
try {
    $res = Invoke-RestMethod -Uri 'http://127.0.0.1:8420/api/health' -TimeoutSec 2 -ErrorAction Stop
    if ($res.ok) {
        Write-Host '✓ API 与定时服务 (端口 8420) 运行正常！' -ForegroundColor Green
    } else {
        Write-Host '○ API 端口 8420 响应异常' -ForegroundColor Yellow
    }
} catch {
    Write-Host '○ API 与定时服务 (端口 8420) 未在运行 (可执行 python -m lifehub.cli serve 启动)' -ForegroundColor Gray
}
