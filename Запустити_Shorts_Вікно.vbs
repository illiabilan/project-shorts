' Silent Launcher for Project Shorts Desktop Window (No Command Prompt)
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDir

VenvPythonw = ScriptDir & "\.venv\Scripts\pythonw.exe"
LauncherScript = ScriptDir & "\windows_launcher.py"

If Not FSO.FileExists(VenvPythonw) Then
    MsgBox "Віртуальне оточення ще не встановлено!" & vbCrLf & "Будь ласка, спочатку двічі клікніть на 'Встановити_Windows.bat'.", vbExclamation, "Project Shorts"
    WScript.Quit 1
End If

WshShell.Run """" & VenvPythonw & """ """ & LauncherScript & """", 0, False
