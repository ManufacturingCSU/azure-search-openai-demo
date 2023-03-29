
$output = azd env get-values

foreach ($line in $output) {
  $name, $value = $line.Split("=")
  $value = $value -replace '^\"|\"$'
  Write-Host $name $value
  [Environment]::SetEnvironmentVariable($name, $value)
}

Write-Host "Environment variables set."

$connstring = az storage account show-connection-string --name $env:azure_storage_account --resource-group $env:azure_resource_group -o tsv
$searchKeys = az search admin-key show --resource-group $env:AZURE_RESOURCE_GROUP --service-name $env:AZURE_SEARCH_SERVICE -o tsv
$searchKey = $searchKeys.split("`t")[0]
$formKey = az cognitiveservices account keys list --name $env:AZURE_FORMRECOGNIZER_SERVICE --resource-group $env:azure_resource_group -o tsv
$formKey = $formKey.split("`t")[0]


$storageKey=$(az storage account keys list -g $env:AZURE_RESOURCE_GROUP -n $env:AZURE_STORAGE_ACCOUNT --query [0].value -o tsv)


Write-Host "Creating search index"
python ./scripts/create_index.py --searchservice $env:AZURE_SEARCH_SERVICE --index $env:AZURE_CHAT_SEARCH_INDEX --searchkey $searchKey

Write-Host "Publishing FunctionApp"
                         
az functionapp config appsettings set --name $env:FUNCTION_APP_NAME --resource-group $env:AZURE_RESOURCE_GROUP --settings `
  "DOCUMENT_SEARCH_INDEX=$env:AZURE_DOCUMENT_SEARCH_INDEX" `
  "CHAT_SEARCH_INDEX=$env:AZURE_CHAT_SEARCH_INDEX" `
  "SEARCH_SERVICE=$env:AZURE_SEARCH_SERVICE" `
  "SEARCH_KEY=$searchKey" `
  "DOCUMENT_CONNECTION_STRING=$connString" `
  "AZURE_SOURCE_STORAGE_PATH=$($env:AZURE_SOURCE_STORAGE_CONTAINER+'/{name}')" `
  "AZURE_STORAGE_CONTAINER=$env:AZURE_STORAGE_CONTAINER" `
  "AZURE_STORAGE_ACCOUNT=$env:AZURE_STORAGE_ACCOUNT" `
  "FORM_RECOGNIZER_KEY=$formKey"

Set-Location indexapp
try {
  func azure functionapp publish $env:FUNCTION_APP_NAME --python
} finally {
  Set-Location ..
}


Write-Host "Uploading local data"

pip install -r ./scripts/requirements.txt
python ./scripts/upload_data.py './data/*' --storageaccount $env:AZURE_STORAGE_ACCOUNT --container raw --storagekey $storageKey

# Write-Host "Set local search key"
azd env set AZURE_SEARCH_KEY $searchKey
azd env set AZURE_STORAGE_KEY $storageKey