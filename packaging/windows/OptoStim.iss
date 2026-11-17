; Inno Setup script. Built in CI with:
;   iscc /DAppVersion=1.0.0 /DNumericVersion=1.0.0.0 packaging\windows\OptoStim.iss
; Installs per user (no administrator rights needed).

#ifndef AppVersion
  #define AppVersion "0.0.0-test"
#endif
#ifndef NumericVersion
  #define NumericVersion "0.0.0.0"
#endif

[Setup]
AppId={{6D1B7C0E-3F52-4B8A-9C17-0E5A4D2F8B61}
AppName=OptoStim
AppVersion={#AppVersion}
AppVerName=OptoStim {#AppVersion}
AppPublisher=Gergely Szarka
AppPublisherURL=https://github.com/jerjely/OptoStim
AppSupportURL=https://github.com/jerjely/OptoStim/issues
DefaultDirName={autopf}\OptoStim
DefaultGroupName=OptoStim
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\installer_out
OutputBaseFilename=OptoStim-{#AppVersion}-Windows-setup
SetupIconFile=..\..\assets\OptoStim.ico
UninstallDisplayIcon={app}\OptoStim.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#NumericVersion}
VersionInfoProductName=OptoStim
VersionInfoDescription=OptoStim setup

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\OptoStim\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\OptoStim"; Filename: "{app}\OptoStim.exe"
Name: "{autodesktop}\OptoStim"; Filename: "{app}\OptoStim.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OptoStim.exe"; Description: "Start OptoStim"; Flags: nowait postinstall skipifsilent
