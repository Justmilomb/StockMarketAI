; Blank installer — Inno Setup script
; Build: iscc installer\blank.iss
; Requires: dist\blank.exe (from pyinstaller trading.spec --clean)

[Setup]
AppName=Blank
AppVersion=1.0.0
AppPublisher=Certified Random
AppCopyright=Copyright (C) 2025 Certified Random
DefaultDirName={autopf}\Blank
DefaultGroupName=Blank
OutputDir=..\dist
OutputBaseFilename=BlankSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

; Uncomment when icon.ico exists in desktop\assets\
; SetupIconFile=..\desktop\assets\icon.ico
; UninstallDisplayIcon={app}\blank.exe

[Files]
Source: "..\dist\blank.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{group}\Blank"; Filename: "{app}\blank.exe"
Name: "{autodesktop}\Blank"; Filename: "{app}\blank.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional:"; Flags: unchecked

[Run]
Filename: "{app}\blank.exe"; Description: "Launch Blank"; Flags: nowait postinstall skipifsilent
