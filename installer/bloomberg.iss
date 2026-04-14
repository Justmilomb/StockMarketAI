; blank installer — Inno Setup script
; Build: ISCC.exe installer\bloomberg.iss
; Requires: dist\blank.exe (from pyinstaller installer\bloomberg.spec --clean)
;
; v2.0.0 changes vs v1:
;   * Per-user install under %LOCALAPPDATA%\Programs\blank (no UAC).
;   * AppMutex = BlankTradingTerminalMutex_v2 — the exe creates this
;     mutex in desktop\main_bloomberg.py so the installer can detect a
;     running instance and close it gracefully during auto-update.
;   * CloseApplications=force + RestartApplications=yes so /VERYSILENT
;     upgrades from UpdateService run without user prompts.
;   * [UninstallDelete] no longer touches user state — data lives in
;     %LOCALAPPDATA%\blank\ (outside {app}) and is managed by
;     desktop/paths.py, so uninstall is now safe.

#define MyAppRoot "E:\Coding\StockMarketAI"

[Setup]
AppName=blank
AppVersion=2.0.1
AppPublisher=Certified Random
AppCopyright=Copyright (C) 2026 Certified Random
AppMutex=BlankTradingTerminalMutex_v2
SetupIconFile={#MyAppRoot}\desktop\assets\icon.ico
UninstallDisplayIcon={app}\blank.exe
DefaultDirName={localappdata}\Programs\blank
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
CloseApplications=force
RestartApplications=yes

[Files]
Source: "dist\blank.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist

[InstallDelete]
; Wipe stale bytecode from a previous install before laying down the
; new exe, so PyInstaller's onefile bootstrap can't accidentally pick
; up a mismatched .pyc from the old bundle.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.pyc"

[Icons]
Name: "{group}\blank"; Filename: "{app}\blank.exe"
Name: "{group}\Uninstall blank"; Filename: "{uninstallexe}"
Name: "{autodesktop}\blank"; Filename: "{app}\blank.exe"; IconFilename: "{app}\blank.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\blank.exe"; Description: "Launch blank"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; User state lives in %LOCALAPPDATA%\blank\ now — never touch it here.
; These entries only clean transient cruft inside the install dir.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.pyc"
