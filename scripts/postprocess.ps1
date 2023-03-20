
$output = azd env get-values

foreach ($line in $output) {
  $name, $value = $line.Split("=")
  $value = $value -replace '^\"|\"$'
  [Environment]::SetEnvironmentVariable($name, $value)
}

Write-Host "Environment variables set."

$connstring = az storage account show-connection-string --name $env:azure_storage_account --resource-group $env:azure_resource_group -o tsv
$searchKeys = az search admin-key show --resource-group $env:AZURE_RESOURCE_GROUP --service-name $env:AZURE_SEARCH_SERVICE -o tsv
$searchKey = $searchKeys.split("`t")[0]

# functionapp keys list showing intermittent 'Bad Request' failures
# https://github.com/Azure/Azure-Functions/issues/2221
$appKey = $null
$appKeys = az functionapp keys list --name $env:FUNCTION_APP_NAME --resource-group $env:AZURE_RESOURCE_GROUP -o tsv
$numRetries = 0
while (($null -eq $appKey) -and ($numRetries -lt 4)) {
  try {
    foreach ($key in $appKeys.split("`t")) {
      if ($key.length -gt 0) {
        $appKey = $key
        break
      }
    }
  } catch {
    $numRetries++
    $appKeys = az functionapp keys list --name $env:FUNCTION_APP_NAME --resource-group $env:AZURE_RESOURCE_GROUP -o tsv
    Start-Sleep -Seconds 2
    continue
  }
}


Write-Host "Publishing FunctionApp"
                         
az functionapp config appsettings set --name $env:FUNCTION_APP_NAME --resource-group $env:AZURE_RESOURCE_GROUP --settings `
  "DOCUMENT_SEARCH_INDEX=$env:AZURE_DOCUMENT_SEARCH_INDEX" `
  "CHAT_SEARCH_INDEX=$env:AZURE_CHAT_SEARCH_INDEX" `
  "SEARCH_SERVICE=$env:AZURE_SEARCH_SERVICE" `
  "SEARCH_KEY=$searchKey" `
  "DOCUMENT_CONNECTION_STRING=$connString" `
  "AZURE_SOURCE_STORAGE_PATH=$($env:AZURE_SOURCE_STORAGE_CONTAINER+'/{name}')" `
  "AZURE_STORAGE_CONTAINER=$env:AZURE_STORAGE_CONTAINER" `
  "AZURE_STORAGE_ACCOUNT=$env:AZURE_STORAGE_ACCOUNT"

Set-Location indexapp
try {
  func azure functionapp publish $env:FUNCTION_APP_NAME
} finally {
  Set-Location ..
}


Write-Host "Creating search indices"

python ./scripts/create_index.py --searchservice $env:AZURE_SEARCH_SERVICE --index $env:AZURE_CHAT_SEARCH_INDEX --searchkey $searchKey

python ./scripts/create_document_index.py `
  --searchservice $env:AZURE_SEARCH_SERVICE `
  --index $env:AZURE_DOCUMENT_SEARCH_INDEX `
  --searchkey $searchKey `
  --container $env:AZURE_SOURCE_STORAGE_CONTAINER `
  --connection_string $connstring `
  --function_app_name $env:FUNCTION_APP_NAME `
  --function_key $appKey



Write-Host "Uploading local data"
$ts = New-TimeSpan -Minutes 30
$end = ((get-date) + $ts).ToUniversalTime().ToString("yyyy-MM-ddTHH:mmZ")
$sasToken = az storage account generate-sas --permissions cdlruwap --account-name $env:AZURE_STORAGE_ACCOUNT --services b --resource-types sco --expiry $end -o tsv

pip install -r ./scripts/requirements.txt
python ./scripts/upload_data.py './data/*' --storageaccount $env:AZURE_STORAGE_ACCOUNT --container raw --sas $sasToken