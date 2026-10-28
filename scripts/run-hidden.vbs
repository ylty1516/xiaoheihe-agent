' Generic hidden launcher: run a .bat without any console window.
' Usage (from a scheduled task):
'   wscript.exe //nologo run-hidden.vbs "F:\path\to\script.bat"
Option Explicit
Dim sh, target
If WScript.Arguments.Count = 0 Then WScript.Quit 1
target = WScript.Arguments(0)
Set sh = CreateObject("WScript.Shell")
' 0 = hidden window, False = do not wait for the child to finish
sh.Run """" & target & """", 0, False
