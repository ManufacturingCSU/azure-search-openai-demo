
$output = azd env get-values

foreach ($line in $output) {
  $name, $value = $line.Split("=")
  $value = $value -replace '^\"|\"$'
  [Environment]::SetEnvironmentVariable($name, $value)
}

$res = az rest --method get --header 'Accept=application/json' -u "https://management.azure.com/subscriptions/$env:AZURE_SUBSCRIPTION_ID/providers/Microsoft.CognitiveServices/deletedAccounts?api-version=2021-04-30"
$res = $res | ConvertFrom-Json
foreach ($value in $res.value) {
    az resource delete --ids $value.id
}
