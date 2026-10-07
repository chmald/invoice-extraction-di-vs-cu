# Shared helpers for the azd hooks (preprovision / postprovision) and infra/deploy.ps1,
# so the azd path and the script path can't drift.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Content Understanding regions (Microsoft Learn, "Content Understanding region and
# language support", verified 2026-10-07). Re-check before deploying.
$script:CuRegions = @(
    "australiaeast", "canadacentral", "eastus", "eastus2", "japaneast", "southcentralus",
    "southeastasia", "swedencentral", "uksouth", "westeurope", "westus", "westus3"
)

function Get-DemoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Default = ""
    )
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

function Assert-EnvName {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$EnvironmentName)
    if ($EnvironmentName -cnotmatch '^[a-z][a-z0-9-]{1,10}[a-z0-9]$') {
        throw "AZURE_ENV_NAME must be 3-12 characters: lowercase letters, digits and hyphens, starting with a letter and not ending with a hyphen (it prefixes the resource custom subdomains). Current value: '$EnvironmentName'."
    }
}

function Assert-AllowedValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [Parameter(Mandatory = $true)][string[]]$Allowed
    )
    if ($Allowed -notcontains $Value) {
        throw "$Name must be one of: $($Allowed -join ', '). Current value: '$Value'."
    }
}

function Assert-CuRegion {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Location)
    if ($script:CuRegions -notcontains $Location.ToLowerInvariant()) {
        throw "AZURE_LOCATION '$Location' is not a Content Understanding region. Use one of: $($script:CuRegions -join ', '). See https://learn.microsoft.com/azure/ai-services/content-understanding/language-region-support"
    }
}

function Assert-AzContextMatches {
    # azd and az keep separate logins; the hooks and deploy.ps1 call az, so the az
    # context must match the target before anything is created.
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$TenantId,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$SubscriptionId
    )
    if ([string]::IsNullOrWhiteSpace($TenantId) -or [string]::IsNullOrWhiteSpace($SubscriptionId)) {
        throw "AZURE_TENANT_ID and AZURE_SUBSCRIPTION_ID must be set before provisioning (azd env set AZURE_TENANT_ID <id>; azd env set AZURE_SUBSCRIPTION_ID <id>)."
    }

    $raw = & az account show --query "{tenant:tenantId,subscription:id,user:user.name}" -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($raw -join ""))) {
        throw "Azure CLI is not authenticated. Sign in explicitly with: az login --tenant $TenantId ; az account set --subscription $SubscriptionId"
    }

    $active = ($raw -join "") | ConvertFrom-Json
    if ($active.tenant -ne $TenantId -or $active.subscription -ne $SubscriptionId) {
        Write-Host "Active Azure CLI context does not match the target." -ForegroundColor Yellow
        Write-Host "  Active tenant/subscription:   $($active.tenant) / $($active.subscription)"
        Write-Host "  Expected tenant/subscription: $TenantId / $SubscriptionId"
        Write-Host "Fix with:"
        Write-Host "  az login --tenant $TenantId"
        Write-Host "  az account set --subscription $SubscriptionId"
        throw "Refusing to continue with the wrong Azure CLI tenant/subscription."
    }
    Write-Host "Azure CLI context matches tenant $TenantId / subscription $SubscriptionId." -ForegroundColor Green
}

function Show-SoftDeletedAccounts {
    # A soft-deleted Cognitive Services account keeps its custom subdomain for 48 hours
    # and blocks re-creation with the same name. Surface it instead of failing mid-deploy.
    param([Parameter(Mandatory = $true)][string]$NamePrefix)
    $raw = & az cognitiveservices account list-deleted --query "[?starts_with(name, '$NamePrefix')].{name:name, location:location}" -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($raw -join ""))) { return }
    $deleted = @(($raw -join "") | ConvertFrom-Json)
    foreach ($d in $deleted) {
        Write-Host "Soft-deleted account '$($d.name)' ($($d.location)) blocks re-use of its name. Purge it with:" -ForegroundColor Yellow
        Write-Host "  az cognitiveservices account purge --name $($d.name) --location $($d.location) --resource-group <original-rg>"
    }
}

function Get-AccountKey {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ResourceGroup,
        [Parameter(Mandatory = $true)][string]$SubscriptionId
    )
    $key = & az cognitiveservices account keys list --subscription $SubscriptionId -g $ResourceGroup -n $Name --query key1 -o tsv 2>$null
    if ($LASTEXITCODE -ne 0) { return "" }
    return ($key -join "").Trim()
}

function Write-DemoIds {
    # Writes (merging) the gitignored demo-ids.local.json the harness reads.
    param([Parameter(Mandatory = $true)][hashtable]$Values)
    $path = Join-Path (Get-DemoRoot) "demo-ids.local.json"
    $current = [ordered]@{}
    if (Test-Path $path) {
        $existing = Get-Content $path -Raw | ConvertFrom-Json
        foreach ($p in $existing.PSObject.Properties) { $current[$p.Name] = $p.Value }
    }
    foreach ($k in $Values.Keys) {
        if (-not [string]::IsNullOrWhiteSpace([string]$Values[$k])) { $current[$k] = $Values[$k] }
    }
    $current | ConvertTo-Json -Depth 5 | Set-Content -Path $path -Encoding utf8
    Write-Host "Wrote $path (gitignored - never commit it)." -ForegroundColor Green
}
