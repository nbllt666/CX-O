; CXO-ModelStation 独立安装程序（Inno Setup 6）
; change-id: package-modelstation-desktop-installer
;
; 载荷 = electron-builder 产出的 win-unpacked/ 目录（Electron 桌面产物，**不是** PyInstaller）。
; 由 tools/build_desktop.py 在 payload 超过 NSIS 2GB 上限（或 --form inno）时生成/调用：
;   iscc /DPayloadDir=<...>\win-unpacked /DOutputDir=<输出目录> /DAppVersion=<版本> "modelstation.iss"
; iscc 缺失时 build_desktop.py 会显式报错并给安装指引，不会静默跳过。
;
; 未传 define 时的缺省值（便于手工试编译）：
;   PayloadDir = ..\..\release\win-unpacked
;   OutputDir  = ..\..\release
;   AppVersion = 0.1.0

#ifndef PayloadDir
  #define PayloadDir "..\..\release\win-unpacked"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define MyAppName "CXO-ModelStation"
#define MyAppExeName "CXO-ModelStation.exe"

[Setup]
; AppId 一经发布不得变更（升级/卸载识别依据）
AppId={{9C2E4A17-7B3D-4F52-8E60-2D5A1F9C4B70}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
; 逐用户安装（PrivilegesRequired=lowest）：不弹 UAC、不写系统目录；
; 与「便携语义」（运行时/引擎都随包落到安装目录内）一致
DefaultDirName={localappdata}\CXO-ModelStation
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=CXO-ModelStation-Setup-{#AppVersion}
; 载荷含 ~5.6GB 运行时/引擎，normal + 非固实压缩（编译速度优先，收益有限）
Compression=lzma2/normal
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

; 说明：不声明 [Languages] —— 沿用 Inno Setup 6 内置默认语言集，
; 避免携带社区中文语言包（languages\ChineseSimplified.isl）缺文件导致编译失败。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; 打入 Electron 产物整套目录树；resources/ 下的 backend/runtime/engines/data 随之一并落位
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[UninstallDelete]
; 卸载策略（人类裁决：数据根不随卸载删除）：
; 1) 应用本体位于 {app}（= %LOCALAPPDATA%\CXO-ModelStation），其下 resources/ 为安装集，
;    卸载时由 Inno 按安装清单自动移除文件与空目录；
; 2) 可写数据根为 %LOCALAPPDATA%\CXO-ModelStation\data（模型权重/训练产物/配置），
;    其中运行期新增文件不在安装清单内，卸载时**不会被删除**；
; 3) 因此这里刻意不声明任何针对 {app}\data 或 {app} 整目录的 [UninstallDelete] 规则，
;    以免误删用户数据。如需彻底清理，请手工删除 %LOCALAPPDATA%\CXO-ModelStation。