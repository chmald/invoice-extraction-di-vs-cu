<#
.SYNOPSIS
  Script-path deployment (no azd): tenant-guarded az deployment of infra/main.bicep,
  then writes demo-ids.local.json exactly like the azd postprovision hook.

.EXAMPLE
  ./infra/deploy.ps1 -TenantId <TENANT_ID> -SubscriptionId <SUBSCRIPTION_ID> `
      -ResourceGroup rg-di-vs-cu -Location eastus2 -BaseName dicu-demo01
#>
param(
    [Parameter(Mandatory = $true)][string]$TenantId,
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [Parameter(Mandatory = $true)][string]$ResourceGroup,
    [Parameter(Mandatory = $true)][string]$BaseName,
    [string]$Location = "eastus2",
    [bool]$DeployDedicatedDocumentIntelligence = $true,
    [bool]$DeployModels = $true,
    [string]$CompletionModelName = "gpt-5.2",
    [string]$CompletionModelVersion = "2025-12-11",
    [string]$EmbeddingModelName = "text-embedding-3-large",
    [switch]$SkipKeys
)

. "$PSScriptRoot\hooks\common.ps1"

Assert-CuRegion -Location $Location
Assert-AzContextMatches -TenantId $TenantId -SubscriptionId $SubscriptionId
Show-SoftDeletedAccounts -NamePrefix $BaseName

& az group create --subscription $SubscriptionId --name $ResourceGroup --location $Location -o none
if ($LASTEXITCODE -ne 0) { throw "az group create failed." }

$outputsJson = & az deployment group create `
    --subscription $SubscriptionId `
    --resource-group $ResourceGroup `
    --name "di-vs-cu-$BaseName" `
    --template-file (Join-Path $PSScriptRoot "main.bicep") `
    --parameters baseName=$BaseName location=$Location `
        deployDedicatedDocumentIntelligence=$($DeployDedicatedDocumentIntelligence.ToString().ToLowerInvariant()) `
        deployModels=$($DeployModels.ToString().ToLowerInvariant()) `
        completionModelName=$CompletionModelName completionModelVersion=$CompletionModelVersion `
        completionDeploymentName=$CompletionModelName `
        embeddingModelName=$EmbeddingModelName embeddingDeploymentName=$EmbeddingModelName `
    --query properties.outputs -o json
if ($LASTEXITCODE -ne 0) { throw "az deployment group create failed." }
$o = ($outputsJson -join "") | ConvertFrom-Json

$values = @{
    tenantId                     = $TenantId
    subscriptionId               = $SubscriptionId
    resourceGroup                = $ResourceGroup
    location                     = $Location
    documentIntelligenceEndpoint = $o.documentIntelligenceEndpoint.value
    contentUnderstandingEndpoint = $o.contentUnderstandingEndpoint.value
    cuCompletionModel            = $o.completionModelName.value
    cuCompletionDeployment       = $o.completionDeploymentName.value
    cuEmbeddingModel             = $o.embeddingModelName.value
    cuEmbeddingDeployment        = $o.embeddingDeploymentName.value
}
if (-not $SkipKeys) {
    $values.documentIntelligenceKey = Get-AccountKey -Name $o.documentIntelligenceName.value -ResourceGroup $ResourceGroup -SubscriptionId $SubscriptionId
    $values.contentUnderstandingKey = Get-AccountKey -Name $o.foundryName.value -ResourceGroup $ResourceGroup -SubscriptionId $SubscriptionId
}
Write-DemoIds -Values $values
Write-Host "Next: python src/run_demo.py check ; python src/run_demo.py setup"
