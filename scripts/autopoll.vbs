' Hidden launcher for autopoll.bat.
' The scheduled task calls this instead of the .bat directly so that no
' console window ever appears on screen (Run style 0 = hidden, no wait).
Option Explicit
Dim sh, scriptDir
Set sh = CreateObject("WScript.Shell")
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.Run """" & scriptDir & "autopoll.bat""", 0, False
