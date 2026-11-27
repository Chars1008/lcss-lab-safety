Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appRoot = fso.GetParentFolderName(scriptDir)
pythonw = fso.BuildPath(appRoot, ".venv\Scripts\pythonw.exe")
pythonExe = fso.BuildPath(appRoot, ".venv\Scripts\python.exe")
mainPy = fso.BuildPath(appRoot, "main.py")

shell.CurrentDirectory = appRoot
If fso.FileExists(pythonw) Then
    shell.Run """" & pythonw & """ """ & mainPy & """", 1, False
ElseIf fso.FileExists(pythonExe) Then
    shell.Run """" & pythonExe & """ """ & mainPy & """", 0, False
Else
    bootstrap = fso.BuildPath(scriptDir, "bootstrap.ps1")
    shell.Run "powershell.exe -ExecutionPolicy Bypass -File """ & bootstrap & """ -InstallDir """ & appRoot & """", 1, True
    If fso.FileExists(pythonw) Then
        shell.Run """" & pythonw & """ """ & mainPy & """", 1, False
    ElseIf fso.FileExists(pythonExe) Then
        shell.Run """" & pythonExe & """ """ & mainPy & """", 0, False
    Else
        MsgBox "找不到虛擬環境執行檔 (.venv\Scripts\pythonw.exe)，請重新執行安裝程式。", 16, "GLCSS 啟動失敗"
    End If
End If
