; Inno Setup Script for PC Auto Cleaner & Optimizer
; Compile with Inno Setup Compiler (ISCC.exe)
; MyAppName / MyAppVersion / MyAppPublisher MUST match app_meta.py (enforced by tests).

#define MyAppName "PC Auto Cleaner & Optimizer"
#define MyAppVersion "3.8.0"
#define MyAppPublisher "PC Cleaner Team"
#define MyAppURL "https://github.com/mrkiss-it/pc-cleaner-optimizer"
#define MyAppExeName "PCAutoCleaner.exe"

[Setup]
AppId={{C511B416-2917-4F66-9E9C-3386E80D2163}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\PCAutoCleaner
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=PCAutoCleaner_InnoSetup
SetupIconFile=..\assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startwithwindows"; Description: "Tự động khởi động cùng Windows (Thu nhỏ khay hệ thống)"; GroupDescription: "Tùy chọn nâng cao:"; Flags: unchecked

[Files]
Source: "..\dist\PCAutoCleaner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PCAutoCleaner"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Tasks: startwithwindows; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
