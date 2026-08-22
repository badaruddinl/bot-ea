param(
    [string]$SecretPath = "$env:ProgramData\bot-ea\g20\telegram-token.dpapi"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-OptionalProperty {
    param($Object, [Parameter(Mandatory = $true)][string]$Name)
    if ($null -eq $Object) { return "" }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) { return "" }
    return [string]$property.Value
}

if (-not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) {
    throw "G20 Telegram DPAPI secret is missing"
}
$encrypted = (Get-Content -LiteralPath $SecretPath -Raw).Trim()
$secure = $encrypted | ConvertTo-SecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $response = Invoke-RestMethod -Method Get `
        -Uri ("https://api.telegram.org/bot{0}/getUpdates" -f $token)
    if ($response.ok -ne $true) {
        throw "Telegram getUpdates did not return ok=true"
    }
    $chats = @()
    foreach ($update in @($response.result)) {
        $candidates = @()
        foreach ($propertyName in @('message', 'edited_message', 'channel_post', 'edited_channel_post')) {
            $property = $update.PSObject.Properties[$propertyName]
            if ($null -ne $property -and $null -ne $property.Value) {
                $chatProperty = $property.Value.PSObject.Properties['chat']
                if ($null -ne $chatProperty -and $null -ne $chatProperty.Value) {
                    $candidates += $chatProperty.Value
                }
            }
        }
        $callback = $update.PSObject.Properties['callback_query']
        if ($null -ne $callback -and $null -ne $callback.Value) {
            $message = $callback.Value.PSObject.Properties['message']
            if ($null -ne $message -and $null -ne $message.Value) {
                $chatProperty = $message.Value.PSObject.Properties['chat']
                if ($null -ne $chatProperty -and $null -ne $chatProperty.Value) {
                    $candidates += $chatProperty.Value
                }
            }
        }
        foreach ($chat in $candidates) {
            $chats += [ordered]@{
                chat_id = [string]$chat.id
                type = [string]$chat.type
                title = Get-OptionalProperty -Object $chat -Name 'title'
                username = Get-OptionalProperty -Object $chat -Name 'username'
                first_name = Get-OptionalProperty -Object $chat -Name 'first_name'
            }
        }
    }
    $chats | Sort-Object chat_id -Unique | ConvertTo-Json -Compress
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secure.Dispose()
    $token = $null
}
