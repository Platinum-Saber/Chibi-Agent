; Raphael installer (Inno Setup 6). Built by packaging\build.ps1, which stages the app first:
;   ISCC /DVersion=0.1.1 /DStage=<staged app folder> /DOut=<output folder> packaging\raphael.iss
; A per-user install (no admin): Godot writes its import cache into overlay3d\, and 3D models
; are dropped into overlay3d\models\, so the app folder must be the user's to write.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Stage
  #error Pass /DStage=<staged app folder>
#endif
#ifndef Out
  #define Out "..\dist"
#endif

[Setup]
AppId={{6F3A2C1E-5B7D-4E8A-9C21-7A0D5B3E9F41}
AppName=Raphael
AppVersion={#Version}
AppVerName=Raphael {#Version}
AppPublisher=Saber
AppPublisherURL=https://github.com/Platinum-Saber/Chibi-Agent
DefaultDirName={localappdata}\Programs\Raphael
DefaultGroupName=Raphael
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#Out}
OutputBaseFilename=Raphael-{#Version}-setup
SetupIconFile={#Stage}\assets\icon\raphael-launcher.ico
UninstallDisplayIcon={app}\Raphael.exe
LicenseFile={#Stage}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Shortcuts:"
Name: "runsetup"; Description: "Download her models now (about 4.5 GB; needs internet)"; GroupDescription: "First run:"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\overlay3d\models"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\Raphael"; Filename: "{app}\Raphael.exe"; IconFilename: "{app}\assets\icon\raphael-launcher.ico"
Name: "{group}\Raphael setup (repair)"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\packaging\setup.ps1"""; IconFilename: "{app}\assets\icon\raphael-launcher.ico"
Name: "{group}\Uninstall Raphael"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Raphael"; Filename: "{app}\Raphael.exe"; IconFilename: "{app}\assets\icon\raphael-launcher.ico"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\packaging\setup.ps1"""; StatusMsg: "Setting up Raphael (Python, Ollama, her voice and models)..."; Tasks: runsetup; Flags: waituntilterminated
Filename: "{app}\Raphael.exe"; Description: "Start Raphael"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; the Python environments and Godot's import cache are made on this PC, not installed
Type: filesandordirs; Name: "{app}\agent\.venv"
Type: filesandordirs; Name: "{app}\overlay\.venv"
Type: filesandordirs; Name: "{app}\voice\.venv"
Type: filesandordirs; Name: "{app}\shared\.venv"
Type: filesandordirs; Name: "{app}\overlay3d\.godot"
; Python's bytecode caches, written when she runs
Type: filesandordirs; Name: "{app}\agent\chibi_agent\__pycache__"
Type: filesandordirs; Name: "{app}\agent\chibi_agent\memory\__pycache__"
Type: filesandordirs; Name: "{app}\agent\chibi_agent\tools\__pycache__"
Type: filesandordirs; Name: "{app}\overlay\chibi_overlay\__pycache__"
Type: filesandordirs; Name: "{app}\overlay\chibi_overlay\body\__pycache__"
Type: filesandordirs; Name: "{app}\overlay\chibi_overlay\vector\__pycache__"
Type: filesandordirs; Name: "{app}\shared\chibi_shared\__pycache__"
Type: filesandordirs; Name: "{app}\voice\chibi_voice\__pycache__"

[Messages]
FinishedLabel=Raphael is installed. Her memory, settings and any 3D models you added are kept if you uninstall.
