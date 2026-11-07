; Inno Setup Script for IMNID Hub
; Produces a single standalone installer (IMNID-Hub-Setup.exe)

#define MyAppName "IMNID Hub"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Ministry of Health / IMNID"
#define MyAppURL "https://github.com/Kbrom27/IMNID-Hub"
#define MyAppExeName "IMNID-Hub.exe"

[Setup]
AppId={{D37E6B20-5621-4A59-9942-870B9FA15243}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\installer_output
OutputBaseFilename=IMNID-Hub-Setup
SetupIconFile=..\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\IMNID-Hub\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\start-imnid-hub.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\stop-imnid-hub.bat"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\data\db"; Permissions: users-modify
Name: "{app}\data\logs"; Permissions: users-modify
Name: "{app}\data\exports"; Permissions: users-modify
Name: "{app}\data\uploads"; Permissions: users-modify

[Icons]
Name: "{group}\Start {#MyAppName}"; Filename: "{app}\start-imnid-hub.bat"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "Start IMNID Hub Service and Open Web Interface"
Name: "{group}\Stop {#MyAppName}"; Filename: "{app}\stop-imnid-hub.bat"; IconFilename: "shell32.dll"; IconIndex: 27; Comment: "Stop IMNID Hub Background Service"
Name: "{group}\Open {#MyAppName} in Browser"; Filename: "http://localhost:8085"; Comment: "Open IMNID Hub in Web Browser"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Start {#MyAppName}"; Filename: "{app}\start-imnid-hub.bat"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "Start IMNID Hub Service"
Name: "{autodesktop}\Stop {#MyAppName}"; Filename: "{app}\stop-imnid-hub.bat"; IconFilename: "shell32.dll"; IconIndex: 27; Tasks: desktopicon; Comment: "Stop IMNID Hub Service"

[Run]
Filename: "{app}\start-imnid-hub.bat"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: shellexec postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\stop-imnid-hub.bat"; Flags: runhidden
