Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = currentDir

args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " """ & WScript.Arguments(i) & """"
Next

exePath = currentDir & "\dist\PCAutoCleaner\PCAutoCleaner.exe"
If fso.FileExists(exePath) Then
    ' File EXE da build windowed khong he co console CMD, khoi chay hien thi giao dien binh thuong (1 = SW_SHOWNORMAL)
    WshShell.Run """" & exePath & """" & args, 1, False
Else
    ' Chay bang pythonw.exe khong co cua so console
    pythonExe = "C:\Users\ASUS\AppData\Local\Programs\Python\Python310\pythonw.exe"
    If Not fso.FileExists(pythonExe) Then
        pythonExe = "pythonw.exe"
    End If
    cmd = """" & pythonExe & """ main.py" & args
    WshShell.Run cmd, 1, False
End If
