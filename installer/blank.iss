; Blank installer — Inno Setup script
; Build: ISCC.exe installer\blank.iss
; Requires: dist\blank.exe (from pyinstaller trading.spec --clean)

#define MyAppRoot "E:\Coding\StockMarketAI"

[Setup]
AppName=Blank
AppVersion=1.0.0
AppPublisher=Certified Random
AppCopyright=Copyright (C) 2025 Certified Random
DefaultDirName={autopf}\Blank
DefaultGroupName=Blank
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

PrivilegesRequired=admin

[Files]
Source: "dist\blank.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\Blank"; Filename: "{app}\blank.exe"
Name: "{group}\Uninstall Blank"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Blank"; Filename: "{app}\blank.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\blank.exe"; Description: "Launch Blank"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.log"
