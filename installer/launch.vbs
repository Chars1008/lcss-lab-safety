Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appRoot = fso.GetParentFolderName(scriptDir)
pythonw = fso.BuildPath(appRoot, ".venv\Scripts\pythonw.exe")
mainPy = fso.BuildPath(appRoot, "main.py")

shell.CurrentDirectory = appRoot
shell.Run """" & pythonw & """ """ & mainPy & """", 0, False
