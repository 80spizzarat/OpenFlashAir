#define AppName "OpenFlashAir"
#define AppVersion "0.1.0"
[Setup]
AppId={{8B094C9C-CBD2-4B0C-A4B2-4D40B2E629C9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=OpenFlashAir
DefaultDirName={autopf}\OpenFlashAir
DefaultGroupName=OpenFlashAir
OutputDir=..\outputs
OutputBaseFilename=OpenFlashAir-Setup-0.1.0-final-candidate
SetupIconFile=..\openflashair\OpenFlashAir_icon_centered.ico
UninstallDisplayIcon={app}\OpenFlashAir.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
[Files]
Source: "..\dist\OpenFlashAir-0.1.0\OpenFlashAir\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\BUILDING.md"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\OpenFlashAir"; Filename: "{app}\OpenFlashAir.exe"; IconFilename: "{app}\OpenFlashAir.exe"
Name: "{autodesktop}\OpenFlashAir"; Filename: "{app}\OpenFlashAir.exe"; IconFilename: "{app}\OpenFlashAir.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\OpenFlashAir.exe"; Description: "Launch OpenFlashAir"; Flags: nowait postinstall skipifsilent
