Set shell = CreateObject("WScript.Shell")
scriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\start_blog_auto.bat"
shell.Run """" & scriptPath & """ __hidden__", 0, False
