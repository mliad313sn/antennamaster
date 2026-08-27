; AntennaMaster — Windows installer (NSIS 3, buildable from Linux via makensis).
;
; Per-user install (no admin prompt): unpacks the application source to
; %LOCALAPPDATA%\AntennaMaster, creates Start-menu shortcuts, and offers to
; run the self-bootstrapping environment setup (install.ps1 fetches Python
; and Node dependencies exactly like the documented manual path). Built by
; tools/build_windows_installer.sh which stages the payload into .\stage.

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APPNAME   "AntennaMaster"
!define VERSION   "1.3.0"
!define PUBLISHER "AntennaMaster project"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Name "${APPNAME} ${VERSION}"
OutFile "..\..\dist\AntennaMaster-Setup-${VERSION}.exe"
InstallDir "$LOCALAPPDATA\${APPNAME}"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show

!define MUI_ICON   "antennamaster.ico"
!define MUI_UNICON "antennamaster.ico"
!define MUI_WELCOMEPAGE_TITLE "AntennaMaster ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "Free, complete and exact RF planning — outdoor, indoor, underground.$\r$\n$\r$\nThis wizard installs the application and its launcher. On the last page you can start the environment setup, which downloads the Python and Node.js dependencies (internet required once; the app itself then runs fully offline)."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunSetup
!define MUI_FINISHPAGE_RUN_TEXT "Run environment setup now (recommended)"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\INSTALL_GUIDE.md"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Open the install guide"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "French"

Section "Application" SecApp
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "stage\*.*"
  File "antennamaster.ico"

  ; Start-menu shortcuts (per-user).
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" \
    "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" \
    '-ExecutionPolicy Bypass -File "$INSTDIR\launch.ps1"' \
    "$INSTDIR\antennamaster.ico" 0 SW_SHOWMINIMIZED "" \
    "Launch AntennaMaster (backend + web app + browser)"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME} setup (repair).lnk" \
    "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" \
    '-ExecutionPolicy Bypass -NoExit -File "$INSTDIR\install.ps1" -Yes' \
    "$INSTDIR\antennamaster.ico" 0 SW_SHOWNORMAL "" \
    "Re-run the dependency bootstrap"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall.lnk" \
    "$INSTDIR\Uninstall.exe"

  ; Uninstall bookkeeping (per-user registry).
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"       "${PUBLISHER}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\antennamaster.ico"
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ; EstimatedSize (KB) so Add/Remove shows a figure.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" "$0"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Function RunSetup
  ExecShell "open" "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" \
    '-ExecutionPolicy Bypass -NoExit -File "$INSTDIR\install.ps1" -Yes'
FunctionEnd

Section "Uninstall"
  ; Remove the whole install dir (includes the .venv/node_modules the
  ; bootstrap created inside it) + shortcuts + registry.
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME} setup (repair).lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  DeleteRegKey HKCU "${UNINSTKEY}"
SectionEnd
