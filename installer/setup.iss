; Inno Setup Script Template for LCSS
[Setup]
AppName=勤思實驗室藥品安全管理系統(GLCSS)
AppVersion=0.1.0
DefaultDirName={localappdata}\GLCSS
DefaultGroupName=勤思實驗室藥品安全管理系統(GLCSS)
OutputBaseFilename=GLCSS_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "..\*"; DestDir: "{app}"; Excludes: ".venv\*,__pycache__\*,.pytest_cache\*,.git\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\勤思實驗室藥品安全管理系統(GLCSS)"; Filename: "wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"
Name: "{autodesktop}\勤思實驗室藥品安全管理系統(GLCSS)"; Filename: "wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\bootstrap.ps1"" -InstallDir ""{app}"""; StatusMsg: "正在建立獨立 Python 虛擬環境與安裝依賴..."; Flags: waituntilterminated
