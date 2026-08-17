; Parallels SQL Admin installer
; Автоматически устанавливает codesign.cer в системные хранилища
; Trusted Root и Trusted Publishers (требует прав администратора, UAC).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define MyAppName "Parallels SQL Admin"
#define MyAppPublisher "alekos corp"
#define MyAppExeName "Parallels SQL Admin.exe"

[Setup]
AppId={{BD65671E-4A64-4703-8B98-37A4F6E6639D}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=ParallelsSQLAdmin-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Parallels SQL Admin\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
Source: "..\codesign.cer"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "certutil.exe"; Parameters: "-addstore -f Root ""{app}\codesign.cer"""; StatusMsg: "Установка сертификата доверия..."; Flags: runhidden
Filename: "certutil.exe"; Parameters: "-addstore -f TrustedPublisher ""{app}\codesign.cer"""; StatusMsg: "Установка сертификата издателя..."; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent