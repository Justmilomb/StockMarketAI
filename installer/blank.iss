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
;   * [UninstallDelete] no longer touches user state — data lives in
;     %LOCALAPPDATA%\blank\ (outside {app}) and is managed by
;     desktop/paths.py, so uninstall is now safe.

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
; User state lives in %LOCALAPPDATA%\blank\ now — by default, never touch
; it here (so updates that uninstall+reinstall preserve watchlists, chat
; history, agent journal). The [Code] section below prompts the user
; during a genuine uninstall and wipes the data dir if they opt in.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\engine"
Type: files; Name: "{app}\*.log"
Type: files; Name: "{app}\*.pyc"

[Code]
// Prompt on genuine uninstall to optionally wipe %LOCALAPPDATA%\blank\
// (watchlists, chat history, agent journal, paper broker state).
// Silent uninstalls (auto-updater) skip the prompt and keep the data.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
  Response: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if UninstallSilent then
      Exit;

    UserDataDir := ExpandConstant('{localappdata}\blank');
    if not DirExists(UserDataDir) then
      Exit;

    Response := MsgBox(
      'Also remove your blank user data?' + #13#10#13#10 +
      'This deletes your watchlists, chat history, agent journal,' + #13#10 +
      'and paper broker state in:' + #13#10 +
      UserDataDir + #13#10#13#10 +
      'Choose No to keep this data for a future reinstall.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2);

    if Response = IDYES then
      DelTree(UserDataDir, True, True, True);
  end;
end;
