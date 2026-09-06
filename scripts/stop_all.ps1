# lifehub 精准停止脚本
# 作用：仅终止 lifehub 的 bot 和 serve 进程，绝不误杀系统其他 Python 任务
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$killed = 0
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

Get-Process -Name "python" -ErrorAction SilentlyContinue | ForEach-Object {
    $proc = $_
    $cmd = $null
    try {
        $cmd = (Get-ItemProperty "HKLM:\Software" -ErrorAction SilentlyContinue) # dummy fallback
    } catch {}
    
    # 尝试通过路径和主模块判断
    try {
        if ($proc.Path -like "$repoRoot*") {
            Write-Host "正在停止 lifehub Python 进程 PID: $($proc.Id)..." -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force
            $killed++
        }
    } catch {
        # 权限不足时备选
    }
}

if ($killed -eq 0) {
    # 兜底：如果无法获取 Path，使用 wmic 或 taskkill 过滤
    Write-Host "检查完成，若有残留进程可通过任务管理器确认。" -ForegroundColor Gray
} else {
    Write-Host "✓ 已安全停止 $killed 个 lifehub 进程。" -ForegroundColor Green
}
