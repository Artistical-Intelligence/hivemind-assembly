; HA download-and-cache installer. Generated constants contain exact release
; names, lengths, SHA-256 hashes and HTTPS URLs, not a remotely trusted manifest.
; No PowerShell, Python, Node or additional installation is needed by the owner.
; The unchanged offline installer remains the only application installation owner.
#include "online-assets.iss"

[Setup]
AppId=HivemindAssemblyDownloadSetup
AppName=Hivemind Assembly
AppVersion={#AppVersion}
AppPublisher=Artistical-Intelligence
AppPublisherURL=https://github.com/Artistical-Intelligence/hivemind-assembly
DefaultDirName={code:ExistingInstallDir}
UsePreviousAppDir=no
DefaultGroupName=Hivemind Assembly
DisableProgramGroupPage=yes
DisableDirPage=no
DisableWelcomePage=no
CreateAppDir=yes
Uninstallable=no
CreateUninstallRegKey=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename={#OnlineName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupMutex=Local\HivemindAssemblyDownloadSetup
CloseApplications=no
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Start_Hivemind_Assembly.cmd"; Description: "Start Hivemind Assembly"; Flags: postinstall shellexec nowait skipifsilent; Check: InstalledSuccessfully
Filename: "{code:CacheLocation}"; Description: "Open saved offline installer files"; Flags: postinstall shellexec unchecked skipifsilent; Check: InstalledSuccessfully

[Messages]
WelcomeLabel2=Install HA from one download. Setup retrieves and verifies the required files, then retains them for offline reinstallation.%n%nYour existing projects, settings and browser profiles are kept. Close HA and use Back up now before updating.%n%nThis is the owner-testing beta. Initial download is approximately 2.23 GB; already verified files are reused.
FinishedLabel=Hivemind Assembly is installed. Setup has retained the complete offline installer in your local application data folder under Hivemind Assembly\InstallerCache. Keep this folder for recovery or copy it to another computer. Your HA projects and settings are stored separately.

[Code]
const
  ReparsePoint = $400;
  InvalidAttributes = $FFFFFFFF;
var
  DownloadPage: TDownloadWizardPage;
  CacheDir: String;
  ChildExitCode: Integer;
  Installed: Boolean;
  ExpectedDownloadSize: Int64;

function GetFileAttributesW(const Filename: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function ExistingInstallDir(Param: String): String;
begin
  if not RegQueryStringValue(HKCU64,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F4C2D7E-8B1A-4E3C-9A55-2C7D1B9E0F31}_is1',
    'InstallLocation', Result) then
    Result := ExpandConstant('{localappdata}\Programs\Hivemind Assembly');
end;

function CacheLocation(Param: String): String;
begin
  Result := CacheDir;
end;

function InstalledSuccessfully: Boolean;
begin
  Result := Installed;
end;

procedure CheckOrdinaryPath(const Name: String);
var
  Current, Parent: String;
  Attributes: LongWord;
begin
  Current := ExpandFileName(Name);
  if (Length(Current) < 3) or (Copy(Current, 2, 2) <> ':\') then
    RaiseException('Choose a local drive for the saved installer files.');
  repeat
    Attributes := GetFileAttributesW(Current);
    if (Attributes <> InvalidAttributes) and ((Attributes and ReparsePoint) <> 0) then
      RaiseException('Installer paths must not contain links or directory junctions: ' + Current);
    Parent := ExtractFileDir(Current);
    if Parent = Current then Break;
    Current := Parent;
  until Length(Current) < 3;
end;

function Verified(const Path: String; Index: Integer): Boolean;
var
  Size: Int64;
begin
  CheckOrdinaryPath(Path);
  Result := False;
  if not FileExists(Path) then Exit;
  if not FileSize64(Path, Size) then Exit;
  if Size <> AssetSizes[Index] then Exit;
  DownloadPage.SetText('Verifying saved installation files', AssetNames[Index]);
  Result := CompareText(GetSHA256OfFile(Path), AssetHashes[Index]) = 0;
end;

procedure PreserveRejected(const Path: String);
var
  Saved: String;
  Counter: Integer;
begin
  CheckOrdinaryPath(Path);
  if not FileExists(Path) then Exit;
  Counter := 0;
  repeat
    Saved := Path + '.rejected-' + GetDateTimeString('yyyymmdd-hhnnss', '-', ':') + '-' + IntToStr(Counter);
    Counter := Counter + 1;
  until not FileExists(Saved);
  if not RenameFile(Path, Saved) then
    RaiseException('Could not preserve a changed cached file. No installation was started: ' + Path);
  Log('Preserved changed file: ' + Saved);
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  // A final hash/length check is still mandatory. Do not accept an oversized body.
  Result := (Progress <= ExpectedDownloadSize) and
    ((ProgressMax = 0) or (ProgressMax <= ExpectedDownloadSize));
end;

procedure RetainVerifiedFile(const Source, Destination: String; Index: Integer);
var
  Pending: String;
begin
  CheckOrdinaryPath(Source);
  CheckOrdinaryPath(Destination);
  Pending := Destination + '.partial';
  PreserveRejected(Pending);
  // Rename avoids copying gigabytes when temp/cache are on the same volume.
  if not RenameFile(Source, Pending) then
    if not FileCopy(Source, Pending, True) then
      RaiseException('Could not retain installer data. Free disk space and retry.');
  if not Verified(Pending, Index) then begin
    PreserveRejected(Pending);
    RaiseException('Downloaded data did not match the pinned release. Nothing was installed.');
  end;
  if not RenameFile(Pending, Destination) then
    RaiseException('Could not finish saving verified installer data. Retry without removing the cache.');
end;

procedure EnsureFile(Index: Integer);
var
  Target, BesideSetup, Temporary: String;
  FreeBytes, TotalBytes: Int64;
begin
  Target := AddBackslash(CacheDir) + AssetNames[Index];
  if Verified(Target, Index) then begin
    Log('HA_CACHE_HIT ' + AssetNames[Index]);
    Exit;
  end;
  PreserveRejected(Target);
  if not GetSpaceOnDisk64(CacheDir, FreeBytes, TotalBytes) or
     (FreeBytes < AssetSizes[Index] + 33554432) then
    RaiseException('Not enough space to retain the HA installer files. Choose another cache drive with /CACHE="path".');
  BesideSetup := ExpandConstant('{src}\') + AssetNames[Index];
  if (CompareText(BesideSetup, Target) <> 0) and Verified(BesideSetup, Index) then begin
    // Never move an owner's original offline installer files.
    Temporary := ExpandConstant('{tmp}\') + AssetNames[Index];
    if not FileCopy(BesideSetup, Temporary, False) then
      RaiseException('Could not copy the provided offline file.');
    RetainVerifiedFile(Temporary, Target, Index);
    Log('HA_OFFLINE_IMPORT ' + AssetNames[Index]);
    Exit;
  end;
  if not GetSpaceOnDisk64(ExpandConstant('{tmp}'), FreeBytes, TotalBytes) or
     (FreeBytes < AssetSizes[Index] + 33554432) then
    RaiseException('Not enough temporary disk space to download the HA installer data.');
  DownloadPage.Clear;
  ExpectedDownloadSize := AssetSizes[Index];
  DownloadPage.Add(AssetUrls[Index], AssetNames[Index], AssetHashes[Index]);
  Log('HA_DOWNLOAD ' + AssetNames[Index]);
  DownloadPage.Download;
  Temporary := ExpandConstant('{tmp}\') + AssetNames[Index];
  RetainVerifiedFile(Temporary, Target, Index);
end;

function HasArgument(const Name: String): Boolean;
var I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then begin Result := True; Exit; end;
end;

procedure InitializeWizard;
begin
  DefineAssets;
  CacheDir := ExpandFileName(ExpandConstant('{param:CACHE|{localappdata}\Hivemind Assembly\InstallerCache\{#AppVersion}}'));
  Installed := False;
  ChildExitCode := 0;
  DownloadPage := CreateDownloadPage('Preparing Hivemind Assembly',
    'Downloading, verifying and keeping the required installation files.', @OnDownloadProgress);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I, LaunchError: Integer;
  Params, Sums, SavedSelf: String;
begin
  Result := '';
  if Installed then Exit;
  DownloadPage.Show;
  try
    try
      CheckOrdinaryPath(CacheDir);
      if (Pos(Lowercase(AddBackslash(CacheDir)), Lowercase(AddBackslash(WizardDirValue))) = 1) or
         (Pos(Lowercase(AddBackslash(WizardDirValue)), Lowercase(AddBackslash(CacheDir))) = 1) then
        RaiseException('The offline cache must be separate from the application installation folder.');
      if not ForceDirectories(CacheDir) then RaiseException('Could not create the offline installer cache.');
      CheckOrdinaryPath(CacheDir);
      for I := 0 to AssetCount - 1 do EnsureFile(I);
      // Recheck every file immediately before executing the offline installer.
      Sums := '';
      for I := 0 to AssetCount - 1 do begin
        if not Verified(AddBackslash(CacheDir) + AssetNames[I], I) then
          RaiseException('Cached installer changed before launch. Nothing was installed.');
        Sums := Sums + AssetHashes[I] + '  ' + AssetNames[I] + #13#10;
      end;
      CheckOrdinaryPath(AddBackslash(CacheDir) + 'OFFLINE-SHA256SUMS.txt');
      if not SaveStringToFile(AddBackslash(CacheDir) + 'OFFLINE-SHA256SUMS.txt', Sums, False) then
        RaiseException('Could not retain the offline checksums.');
      CheckOrdinaryPath(AddBackslash(CacheDir) + 'OFFLINE-README.txt');
      if not SaveStringToFile(AddBackslash(CacheDir) + 'OFFLINE-README.txt',
        'HA {#AppVersion} offline installer cache.' + #13#10 +
        'Keep this entire folder. Run {#OnlineName}.exe or the matching Setup.exe to reinstall.' + #13#10 +
        'All matching Setup-*.bin files must stay beside Setup.exe. Rejected files are preserved, never executed.' + #13#10 +
        'Projects and settings are stored separately in %LOCALAPPDATA%\UnifiedWorkbench.' + #13#10, False) then
        RaiseException('Could not retain the offline installation instructions.');
      SavedSelf := AddBackslash(CacheDir) + '{#OnlineName}.exe';
      CheckOrdinaryPath(SavedSelf);
      if CompareText(ExpandConstant('{srcexe}'), SavedSelf) <> 0 then begin
        if FileExists(SavedSelf) then begin
          if CompareText(GetSHA256OfFile(SavedSelf), GetSHA256OfFile(ExpandConstant('{srcexe}'))) <> 0 then
            PreserveRejected(SavedSelf);
        end;
        if not FileExists(SavedSelf) and not FileCopy(ExpandConstant('{srcexe}'), SavedSelf, True) then
          RaiseException('Could not retain the single-file installer for later use.');
      end;
      DownloadPage.SetText('Installing Hivemind Assembly', 'The offline files have been verified and saved.');
      Params := '/SP- /CURRENTUSER /NORESTART /RESTARTEXITCODE=3010 /DIR="' + WizardDirValue + '"';
      if WizardSilent then Params := Params + ' /VERYSILENT /SUPPRESSMSGBOXES'
      else Params := Params + ' /SILENT';
      if HasArgument('/NOICONS') then Params := Params + ' /NOICONS';
      if WizardIsTaskSelected('desktopicon') then Params := Params + ' /TASKS="desktopicon"'
      else Params := Params + ' /TASKS=""';
      Log('HA_CHILD_START');
      if not Exec(AddBackslash(CacheDir) + AssetNames[0], Params, CacheDir,
                  SW_SHOWNORMAL, ewWaitUntilTerminated, LaunchError) then
        RaiseException('Could not start the verified HA installer: ' + SysErrorMessage(LaunchError));
      ChildExitCode := LaunchError;
      if (ChildExitCode <> 0) and (ChildExitCode <> 3010) then
        RaiseException('HA installation did not finish (code ' + IntToStr(ChildExitCode) + '). Cached files were kept; no automatic retry was attempted.');
      Installed := True;
      Log('HA_INSTALL_COMPLETE cache=' + CacheDir);
    except
      Result := GetExceptionMessage + #13#10 + 'Completed downloads are retained in: ' + CacheDir;
      Log(Result);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := ChildExitCode;
end;
