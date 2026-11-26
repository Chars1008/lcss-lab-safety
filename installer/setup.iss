; Inno Setup Script Template for LCSS
[Setup]
AppName=實驗室藥品安全管理系統 (LCSS)
AppVersion=0.1.0
DefaultDirName={localappdata}\LCSS
DefaultGroupName=LCSS 實驗室藥品安全管理系統
OutputBaseFilename=LCSS_Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "..\*"; DestDir: "{app}"; Excludes: ".venv\*,__pycache__\*,.pytest_cache\*,.git\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LCSS 實驗室藥品安全管理系統"; Filename: "wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"
Name: "{autodesktop}\LCSS 實驗室藥品安全管理系統"; Filename: "wscript.exe"; Parameters: """{app}\installer\launch.vbs"""; WorkingDir: "{app}"

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\installer\bootstrap.ps1"" -InstallDir ""{app}"""; StatusMsg: "正在建立獨立 Python 虛擬環境與安裝依賴..."; Flags: waituntilterminated
