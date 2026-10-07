# azd postprovision hook: write demo-ids.local.json from the azd outputs and,
# optionally, run the Content Understanding setup (defaults + analyzer).
. "$PSScriptRoot\common.ps1"

$tenantId = Get-EnvValue -Name "AZURE_TENANT_ID"
$subscriptionId = Get-EnvValue -Name "AZURE_SUBSCRIPTION_ID"
$resourceGroup = Get-EnvValue -Name "AZURE_RESOURCE_GROUP"

Assert-AzContextMatches -TenantId $tenantId -SubscriptionId $subscriptionId

$values = @{
    tenantId                     = $tenantId
    subscriptionId               = $subscriptionId
    resourceGroup                = $resourceGroup
    location                     = Get-EnvValue -Name "AZURE_LOCATION"
    documentIntelligenceEndpoint = Get-EnvValue -Name "DOCUMENTINTELLIGENCE_ENDPOINT"
    contentUnderstandingEndpoint = Get-EnvValue -Name "CONTENTUNDERSTANDING_ENDPOINT"
    cuCompletionModel            = Get-EnvValue -Name "CU_COMPLETION_MODEL"
    cuCompletionDeployment       = Get-EnvValue -Name "CU_COMPLETION_DEPLOYMENT"
    cuEmbeddingModel             = Get-EnvValue -Name "CU_EMBEDDING_MODEL"
    cuEmbeddingDeployment        = Get-EnvValue -Name "CU_EMBEDDING_DEPLOYMENT"
}

# Keys go only into the gitignored local file, never into azd outputs or deployment history.
if ((Get-EnvValue -Name "WRITE_KEYS_TO_LOCAL_IDS" -Default "true") -eq "true") {
    $values.documentIntelligenceKey = Get-AccountKey -Name (Get-EnvValue -Name "DOCUMENTINTELLIGENCE_NAME") -ResourceGroup $resourceGroup -SubscriptionId $subscriptionId
    $values.contentUnderstandingKey = Get-AccountKey -Name (Get-EnvValue -Name "FOUNDRY_NAME") -ResourceGroup $resourceGroup -SubscriptionId $subscriptionId
    if ([string]::IsNullOrWhiteSpace($values.documentIntelligenceKey)) {
        Write-Host "Could not read account keys (local auth disabled, or missing listKeys permission). Set them via environment variables instead." -ForegroundColor Yellow
    }
}

Write-DemoIds -Values $values

if ((Get-EnvValue -Name "RUN_CU_SETUP" -Default "false") -eq "true") {
    $python = Get-EnvValue -Name "PYTHON" -Default "python"
    Push-Location (Get-DemoRoot)
    try {
        & $python src/run_demo.py setup
        if ($LASTEXITCODE -ne 0) { throw "Content Understanding setup failed (exit $LASTEXITCODE)." }
    }
    finally { Pop-Location }
}
else {
    Write-Host "Next: python src/run_demo.py check ; python src/run_demo.py setup   (or azd env set RUN_CU_SETUP true before azd up)"
}
