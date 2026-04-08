; Blank Simple installer — Inno Setup script
; Build: ISCC.exe installer\simple.iss
; Requires: dist\blank-simple.exe (from pyinstaller installer\simple.spec --clean)

#define MyAppRoot "E:\Coding\StockMarketAI"

[Setup]
AppName=Blank Simple
AppVersion=1.0.0
AppPublisher=Certified Random
AppCopyright=Copyright (C) 2026 Certified Random
SetupIconFile={#MyAppRoot}\desktop\assets\icon.ico
UninstallDisplayIcon={app}\blank-simple.exe
DefaultDirName={autopf}\Blank Simple
DefaultGroupName=Blank Simple
OutputDir={#MyAppRoot}\dist
OutputBaseFilename=BlankSimpleSetup
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
Source: "dist\blank-simple.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\Blank Simple"; Filename: "{app}\blank-simple.exe"
Name: "{group}\Uninstall Blank Simple"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Blank Simple"; Filename: "{app}\blank-simple.exe"; IconFilename: "{app}\blank-simple.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\blank-simple.exe"; Description: "Launch Blank Simple"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.log"
