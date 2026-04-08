; Blank Bloomberg installer — Inno Setup script
; Build: ISCC.exe installer\bloomberg.iss
; Requires: dist\blank-bloomberg.exe (from pyinstaller installer\bloomberg.spec --clean)

#define MyAppRoot "E:\Coding\StockMarketAI"

[Setup]
AppName=Blank Bloomberg
AppVersion=1.0.0
AppPublisher=Certified Random
AppCopyright=Copyright (C) 2026 Certified Random
SetupIconFile={#MyAppRoot}\desktop\assets\icon.ico
UninstallDisplayIcon={app}\blank-bloomberg.exe
DefaultDirName={autopf}\Blank Bloomberg
DefaultGroupName=Blank Bloomberg
OutputDir={#MyAppRoot}\dist
OutputBaseFilename=BlankBloombergSetup
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
Source: "dist\blank-bloomberg.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\Blank Bloomberg"; Filename: "{app}\blank-bloomberg.exe"
Name: "{group}\Uninstall Blank Bloomberg"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Blank Bloomberg"; Filename: "{app}\blank-bloomberg.exe"; IconFilename: "{app}\blank-bloomberg.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\blank-bloomberg.exe"; Description: "Launch Blank Bloomberg"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.log"
