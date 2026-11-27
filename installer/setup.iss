; Inno Setup Script for 勤思實驗室藥品安全管理系統(GLCSS)
[Setup]
AppId={{8D4F6A9C-3B2E-4E12-9A7B-1F3C5E7D9A01}
AppName=勤思實驗室藥品安全管理系統(GLCSS)
AppVersion=0.1.0
AppPublisher=GEMS Laboratory
DefaultDirName={localappdata}\GLCSS
DefaultGroupName=勤思實驗室藥品安全管理系統(GLCSS)
OutputDir=..\dist
OutputBaseFilename=GLCSS_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName=勤思實驗室藥品安全管理系統(GLCSS)

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\*"; DestDir: "{app}"; Excludes: ".venv,.venv\*,__pycache__,__pycache__\*,*.pyc,.pytest_cache,.pytest_cache\*,.git,.git\*,dist,dist\*,storage,storage\*,config,config\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\勤思實驗室藥品安全管理系統(GLCSS)"; Filename: "wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"
Name: "{group}\解除安裝 GLCSS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\勤思實驗室藥品安全管理系統(GLCSS)"; Filename: "wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\bootstrap.ps1"" -InstallDir ""{app}"""; StatusMsg: "正在建立獨立 Python 虛擬環境與安裝依賴..."; Flags: waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -Command ""Remove-Item -Path '$env:USERPROFILE\Desktop\勤思實驗室藥品安全管理系統(GLCSS).lnk' -Force -ErrorAction SilentlyContinue"""; Flags: runhidden

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\installer"
