; =============================================================================
; Petrophyter Windows Installer Script
; Inno Setup 6.x
; =============================================================================
; 
; This script creates a Windows installer for Petrophyter application.
; 
; Prerequisites:
;   - Inno Setup 6 installed (https://jrsoftware.org/isinfo.php)
;   - PyInstaller build completed (dist\Petrophyter\ exists)
;
; Build:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\Petrophyter.iss
;
; =============================================================================

; -----------------------------------------------------------------------------
; APPLICATION CONSTANTS
; IMPORTANT: Do not change AppId GUID - it identifies this app across updates
; -----------------------------------------------------------------------------
#define AppId           "{{978A90D9-EDFB-4F2E-AB78-840138C1574F}"
#define AppName         "Petrophyter"
#define AppVersion      "1.4.0 (Build 20260113)"
#define AppVersionFile  "1.4.0_Build20260113"
#define AppPublisher    "Petrophysics TAU Research Group"
#define AppURL          "https://github.com/rcrohmana/petrophyter"
#define AppExeName      "Petrophyter.exe"
#define AppCopyright    "Copyright (C) 2025-2026 Rian Cahya Rohmana"

; -----------------------------------------------------------------------------
; SETUP CONFIGURATION
; -----------------------------------------------------------------------------
[Setup]
; Unique application identifier - DO NOT CHANGE after first release
AppId={#AppId}

; Application metadata
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright={#AppCopyright}

; Installation directories
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes

; Output configuration
OutputDir=Output
OutputBaseFilename=Petrophyter_Setup_{#AppVersionFile}

; Installer appearance
SetupIconFile=..\icons\app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
WizardSizePercent=100

; Compression settings (LZMA2 for best compression)
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Privileges and architecture
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

; Uninstall settings
Uninstallable=yes
UninstallDisplayName={#AppName}
CreateUninstallRegKey=yes

; Misc settings
DisableWelcomePage=no
DisableDirPage=no
DisableFinishedPage=no
ShowLanguageDialog=no

; -----------------------------------------------------------------------------
; LANGUAGES
; -----------------------------------------------------------------------------
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; -----------------------------------------------------------------------------
; INSTALLATION TASKS (User Choices)
; -----------------------------------------------------------------------------
[Tasks]
; Desktop shortcut - optional (unchecked by default)
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; -----------------------------------------------------------------------------
; FILES TO INSTALL
; Copy entire PyInstaller output (one-folder mode)
; -----------------------------------------------------------------------------
[Files]
; Main application files from PyInstaller dist folder
Source: "..\dist\Petrophyter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; -----------------------------------------------------------------------------
; SHORTCUTS (Start Menu and Desktop)
; -----------------------------------------------------------------------------
[Icons]
; Start Menu - Main application shortcut
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "Desktop Petrophysics Application"

; Start Menu - Uninstall shortcut
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"; Comment: "Uninstall {#AppName}"

; Desktop shortcut (only if user selected the task)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "Desktop Petrophysics Application"; Tasks: desktopicon

; -----------------------------------------------------------------------------
; POST-INSTALL ACTIONS
; -----------------------------------------------------------------------------
[Run]
; Option to launch application after installation
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; -----------------------------------------------------------------------------
; REGISTRY ENTRIES (for file associations if needed in future)
; -----------------------------------------------------------------------------
[Registry]
; App Paths registration (allows running from Run dialog)
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{#AppExeName}"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName}"; Flags: uninsdeletekey

; -----------------------------------------------------------------------------
; UNINSTALL DELETE (clean up user data - optional)
; -----------------------------------------------------------------------------
[UninstallDelete]
; Remove any log files created during runtime
Type: files; Name: "{app}\*.log"
