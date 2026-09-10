!macro customInstallMode
  StrCpy $isForceCurrentInstall "1"
!macroend

!macro customInstall
  CreateDirectory "$INSTDIR\bin"
  CopyFiles /SILENT "$INSTDIR\resources\installer\zeus.cmd" "$INSTDIR\bin"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\installer\register-cli.ps1" -Action Install -InstallDirectory "$INSTDIR"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    DetailPrint "ZeusAgent command registration failed: $1"
    MessageBox MB_OK|MB_ICONSTOP "Could not register the zeus command. $1" /SD IDOK
    Abort
  ${EndIf}
  DetailPrint "zeus is ready in new CMD and PowerShell windows."
!macroend

!macro customUnInstall
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\installer\register-cli.ps1" -Action Uninstall -InstallDirectory "$INSTDIR"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    DetailPrint "Could not remove the owned ZeusAgent PATH entry: $1"
    MessageBox MB_OK|MB_ICONEXCLAMATION "The zeus command PATH entry could not be removed. $1" /SD IDOK
    Abort
  ${EndIf}
!macroend
