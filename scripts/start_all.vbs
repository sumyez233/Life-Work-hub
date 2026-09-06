' lifehub 静默后台启动器 (VBScript)
' 路径自适应：由脚本位置推导仓库根目录，克隆到任意目录均可运行
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
hubDir = fso.GetParentFolderName(scriptDir)
pythonExe = hubDir & "\.venv\Scripts\python.exe"
Set WshShell = CreateObject("WScript.Shell")

' 切换工作目录
WshShell.CurrentDirectory = hubDir

' 启动 bot (飞书长连接机器人)
cmdBot = """" & pythonExe & """ -m lifehub.cli bot"
WshShell.Run cmdBot, 0, False

WScript.Sleep 1000

' 启动 serve (后台服务)
cmdServe = """" & pythonExe & """ -m lifehub.cli serve"
WshShell.Run cmdServe, 0, False
