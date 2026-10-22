; Hivemind Assembly per-user Windows installer (Inno Setup 6).
; Build: iscc /DAppVersion=0.25.1 /DSourceDir=<extracted Hivemind_Assembly folder> /DOutputDir=<dir> dev\installer.iss
;
; Installs the same files as the Windows ZIP into the user's Programs folder
; without administrator rights. User data stays in %LOCALAPPDATA%\UnifiedWorkbench,
; so installing a newer version replaces only application files, and uninstalling
; keeps projects, settings, histories, browser profiles and learned assets.

#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{6F4C2D7E-8B1A-4E3C-9A55-2C7D1B9E0F31}
AppName=Hivemind Assembly
AppVersion={#AppVersion}
AppPublisher=Artistical-Intelligence
AppPublisherURL=https://github.com/Artistical-Intelligence/hivemind-assembly
DefaultDirName={localappdata}\Programs\Hivemind Assembly
DefaultGroupName=Hivemind Assembly
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Hivemind_Assembly_{#AppVersion}_Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Hivemind Assembly {#AppVersion}
CloseApplications=yes

[InstallDelete]
; Application files only: remove the previous release so stale modules cannot load.
Type: filesandordirs; Name: "{app}\_app"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Hivemind Assembly"; Filename: "{app}\Start_Hivemind_Assembly.cmd"; WorkingDir: "{app}"
Name: "{group}\Hivemind Assembly README"; Filename: "{app}\README.md"
Name: "{userdesktop}\Hivemind Assembly"; Filename: "{app}\Start_Hivemind_Assembly.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Start_Hivemind_Assembly.cmd"; Description: "Start Hivemind Assembly now"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_app"

[Messages]
FinishedLabel=Hivemind Assembly is installed. The first start prepares its private Python runtime and needs internet access. Your projects and settings are kept in your local application data folder (UnifiedWorkbench) and are not removed by updates or uninstalling.
