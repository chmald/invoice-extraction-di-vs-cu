# azd preprovision hook: validate the environment and refuse to run against the
# wrong tenant/subscription before any resource is created.
. "$PSScriptRoot\common.ps1"

$envName = Get-EnvValue -Name "AZURE_ENV_NAME"
$location = Get-EnvValue -Name "AZURE_LOCATION" -Default "eastus2"
$tenantId = Get-EnvValue -Name "AZURE_TENANT_ID"
$subscriptionId = Get-EnvValue -Name "AZURE_SUBSCRIPTION_ID"

Assert-EnvName -EnvironmentName $envName
Assert-CuRegion -Location $location
Assert-AllowedValue -Name "DEPLOY_DEDICATED_DOCUMENT_INTELLIGENCE" -Value (Get-EnvValue -Name "DEPLOY_DEDICATED_DOCUMENT_INTELLIGENCE" -Default "true") -Allowed @("true", "false")
Assert-AllowedValue -Name "DEPLOY_MODELS" -Value (Get-EnvValue -Name "DEPLOY_MODELS" -Default "true") -Allowed @("true", "false")
Assert-AllowedValue -Name "DOCUMENT_INTELLIGENCE_SKU" -Value (Get-EnvValue -Name "DOCUMENT_INTELLIGENCE_SKU" -Default "S0") -Allowed @("F0", "S0")
Assert-AllowedValue -Name "DISABLE_LOCAL_AUTH" -Value (Get-EnvValue -Name "DISABLE_LOCAL_AUTH" -Default "false") -Allowed @("true", "false")
Assert-AzContextMatches -TenantId $tenantId -SubscriptionId $subscriptionId

if ((Get-EnvValue -Name "DISABLE_LOCAL_AUTH" -Default "false") -eq "true") {
    Write-Host "DISABLE_LOCAL_AUTH=true: key auth is disabled, but the harness authenticates with keys. Use this only after switching the harness to Entra ID." -ForegroundColor Yellow
}

Show-SoftDeletedAccounts -NamePrefix $envName

Write-Host "Preprovision checks passed for '$envName' in '$location'."
