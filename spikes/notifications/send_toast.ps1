# Shows a fake chat toast that asks for a reply, so listen.py has something new to see.
# Windows PowerShell 5.1 only (pwsh 7 can't load WinRT types): powershell -File send_toast.ps1
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
$text.Item(0).AppendChild($xml.CreateTextNode('Alex')) | Out-Null
$text.Item(1).AppendChild($xml.CreateTextNode('Can you send me the lab slides tonight? Please reply.')) | Out-Null
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
