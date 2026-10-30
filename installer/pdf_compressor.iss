; PDF Compressor installer. Needs Inno Setup 6.3 or newer (x64compatible).
; build.ps1 runs: ISCC.exe /DMyAppVersion=<version> /O<dist> installer\pdf_compressor.iss

#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif
#define MyAppName "PDF Compressor"
#define MyAppExeName "PDF Compressor.exe"

[Setup]
; Never change AppId: upgrades and the uninstaller find the install by it.
AppId={{4B0639DB-6D0E-46A3-A747-77DBB4062E09}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Per-user install with no admin prompt. The override directives stay unset,
; so Setup can never switch to an all-users install.
PrivilegesRequired=lowest
; For a per-user install {autopf} is %LOCALAPPDATA%\Programs.
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
; The PyInstaller build is 64-bit only, and the app supports Windows 10 and 11.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputBaseFilename=PDF-Compressor-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
; portable.txt belongs only in the portable zip; installed, it would make the
; app keep its settings in the program folder.
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Excludes: "\portable.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{usersendto}\Compress PDF"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Open PDF Compressor now"; Flags: nowait postinstall skipifsilent

; The uninstaller removes everything above. Settings and logs in
; %APPDATA%\PDF Compressor are the user's data and stay.
