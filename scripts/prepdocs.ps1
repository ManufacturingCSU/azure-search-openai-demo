Write-Host ""
Write-Host "Loading azd .env file from current environment"
Write-Host ""

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
$searchKey = az search admin-key show --resource-group $env:AZURE_RESOURCE_GROUP --service-name $env:AZURE_SEARCH_SERVICE
                         
Write-Host $apiKey
Write-Host $connString

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
  # fallback to python3 if python not found
  $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}

Write-Host 'Creating python virtual environment "scripts/.venv"'
Start-Process -FilePath ($pythonCmd).Source -ArgumentList "-m venv ./scripts/.venv" -Wait -NoNewWindow

$venvPythonPath = "./scripts/.venv/scripts/python.exe"
if (Test-Path -Path "/usr") {
  # fallback to Linux venv path
  $venvPythonPath = "./scripts/.venv/bin/python"
}

Write-Host 'Installing dependencies from "requirements.txt" into virtual environment'
Start-Pruuuuuuuocess -FilePath $venvPythonPath -ArgumentList "-m pip install -r ./scripts/requirements.txt" -Wait -NoNewWindow

Write-Host 'Running "prepdocs.py"'
$cwd = (Get-Location)
Start-Process -FilePath $venvPythonPath -ArgumentList "./scripts/create_index.py $cwd/data/* --storageaccount $env:AZURE_STORAGE_ACCOUNT --container $env:AZURE_STORAGE_CONTAINER --searchservice $env:AZURE_SEARCH_SERVICE --index $env:AZURE_SEARCH_INDEX --formrecognizerservice $env:AZURE_FORMRECOGNIZER_SERVICE --tenantid $env:AZURE_TENANT_ID -v" -Wait -NoNewWindow
