; blank installer — Inno Setup script
; Build: ISCC.exe installer\blank.iss
; Requires: dist\blank.exe (from pyinstaller installer\blank.spec --clean)
;
; v2.0.0 changes vs v1:
;   * Per-user install under %LOCALAPPDATA%\Programs\blank (no UAC).
;   * AppMutex = BlankTradingTerminalMutex_v2 — the exe creates this
;     mutex in desktop\main_desktop.py so the installer can detect a
;     running instance and close it gracefully during auto-update.
;   * CloseApplications=force + RestartApplications=yes so /VERYSILENT
;     upgrades from UpdateService run without user prompts.
;   * Uninstall wipes EVERYTHING with no prompt: install dir +
;     %LOCALAPPDATA%\blank\ (config, paper_state, personality,
;     logs, models) + the registered AppData session token + every
;     blank registry key. Auto-update uninstalls (UninstallSilent)
;     skip the wipe so a /VERYSILENT replace doesn't erase the user
;     between versions.

#define MyAppRoot "E:\Coding\StockMarketAI"

[Setup]
AppName=blank
AppVersion=1.0.0
AppPublisher=certified random
AppCopyright=Copyright (C) 2026 certified random
AppMutex=BlankTradingTerminalMutex_v2
SetupIconFile={#MyAppRoot}\desktop\assets\icon.ico
UninstallDisplayIcon={app}\blank.exe
DefaultDirName={localappdata}\Programs\blank
DefaultGroupName=blank
OutputDir={#MyAppRoot}\dist
OutputBaseFilename=blank-setup
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

; Bundled AI engine: portable runtime + CLI. Staged by
; scripts/prepare_engine.py before the installer is compiled.
; Missing-file errors here mean the engine prep step was skipped.
Source: "build\engine\node\*"; DestDir: "{app}\engine\node"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "build\engine\cli\*"; DestDir: "{app}\engine\cli"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Wipe stale bytecode from a previous install before laying down the
; new exe, so PyInstaller's onefile bootstrap can't accidentally pick
; up a mismatched .pyc from the old bundle.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\*.pyc"

[Icons]
Name: "{group}\blank"; Filename: "{app}\blank.exe"
Name: "{group}\Uninstall blank"; Filename: "{uninstallexe}"
Name: "{group}\blank"; Filename: "{app}\blank.exe"; IconFilename: "{app}\blank.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Run]
Filename: "{app}\blank.exe"; Description: "Launch blank"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; Nuke everything inside {app}. The matching wipe of user state under
; %LOCALAPPDATA%\blank\ happens in [Code] below — Inno Setup expands
; {localappdata} to the *uninstaller's* profile, so we resolve the
; path at runtime instead of relying on a static rule here.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\engine"
Type: filesandordirs; Name: "{app}"
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.pyc"

[Code]
// Wipe every blank trace on every uninstall path EXCEPT the silent
// update flow. The auto-updater (UpdateService) shells out the
// uninstaller with /VERYSILENT before laying the new build down — if
// that wipes user state every release, watchlists and the personality
// JSON evaporate on every minor version bump.
//
// Genuine uninstalls (Settings → Apps, Programs and Features) all run
// non-silent, so they fall through to the wipe routine and leave zero
// trace on disk or in the registry.
//
// Things removed:
//   * %LOCALAPPDATA%\blank\ — config.json, paper_state.json,
//     trader_personality.json, logs/, models/, telemetry cache
//   * %USERPROFILE%\.blank\ — JWT session token (desktop/auth.py)
//   * HKCU\Software\certified random\blank — Qt QSettings written
//     by account_settings.py
//   * HKCU\Software\certified random — only when no other sibling
//     keys exist (so a future Certified Random product can co-exist)
//   * HKCU\Software\blank, HKCU\Software\Classes\blank — defensive
//     sweep against any URL handler / file-association keys a future
//     build might register
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  LocalDataDir: String;
  HomeDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if UninstallSilent then
      Exit;

    LocalDataDir := ExpandConstant('{localappdata}\blank');
    if DirExists(LocalDataDir) then
      DelTree(LocalDataDir, True, True, True);

    HomeDataDir := ExpandConstant('{userprofile}\.blank');
    if DirExists(HomeDataDir) then
      DelTree(HomeDataDir, True, True, True);

    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\certified random\blank');
    RegDeleteKeyIfEmpty(HKCU, 'Software\certified random');
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\blank');
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\blank');
  end;
end;
