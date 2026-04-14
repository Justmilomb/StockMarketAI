; blank installer — Inno Setup script
; Build: ISCC.exe installer\bloomberg.iss
; Requires: dist\blank.exe (from pyinstaller installer\bloomberg.spec --clean)

#define MyAppRoot "E:\Coding\StockMarketAI"

[Setup]
AppName=blank
AppVersion=2.0.0
AppPublisher=Certified Random
AppCopyright=Copyright (C) 2026 Certified Random
SetupIconFile={#MyAppRoot}\desktop\assets\icon.ico
UninstallDisplayIcon={app}\blank.exe
DefaultDirName={autopf}\blank
DefaultGroupName=blank
OutputDir={#MyAppRoot}\dist
OutputBaseFilename=BlankSetup
SourceDir={#MyAppRoot}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

DisableProgramGroupPage=yes
DisableWelcomePage=no
DisableDirPage=yes
DisableReadyPage=yes

PrivilegesRequired=lowest

[Files]
Source: "dist\blank.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\blank"; Filename: "{app}\blank.exe"
Name: "{group}\Uninstall blank"; Filename: "{uninstallexe}"
Name: "{autodesktop}\blank"; Filename: "{app}\blank.exe"; IconFilename: "{app}\blank.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\blank.exe"; Description: "Launch blank"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.log"
