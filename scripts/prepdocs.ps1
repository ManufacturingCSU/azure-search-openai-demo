$output = azd env get-values

foreach ($line in $output) {
  $name, $value = $line.Split("=")
  $value = $value -replace '^\"|\"$'
  Write-Host $name $value
  [Environment]::SetEnvironmentVariable($name, $value)
}

Write-Host "Environment variables set."

$connString = az storage account show-connection-string --name $env:AZURE_STORAGE_CONTAINER --resource-group $env:AZURE_RESOURCE_GROUP
$apiKey = az functionapp keys list -g $env:AZURE_RESOURCE_GROUP -n $env:FUNCTION_APP_NAME

Write-Host $apiKey
Write-Host $connString

# pip install -r ./scripts/requirements.txt
# python ./scripts/prepdocs.py './data/*' --storageaccount $env:AZURE_STORAGE_ACCOUNT --container $env:AZURE_STORAGE_CONTAINER --searchservice $env:AZURE_SEARCH_SERVICE --index $env:AZURE_SEARCH_INDEX -v
