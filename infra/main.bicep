// Provisions the two services this demo compares (resource-group scope).
//
//   Microsoft Foundry resource (kind AIServices)  -> Azure Content Understanding in Foundry Tools
//                                                   (+ the completion and embedding model deployments
//                                                   a GA custom analyzer needs)
//   Document Intelligence (kind FormRecognizer)   -> Azure Document Intelligence in Foundry Tools
//                                                   (optional - DI also runs on the Foundry resource)
//
// Entry points (all three use this file unchanged):
//   azd up                      -> infra/azd.bicep (subscription scope) calls this as a module
//   infra/deploy.ps1            -> az deployment group create (tenant-guarded)
//   az deployment group create --subscription <SUBSCRIPTION_ID> --resource-group <RG> \
//     --template-file infra/main.bicep --parameters baseName=<unique-name>
//
// Confirm the target region supports Content Understanding before deploying - its
// region list is narrower than Document Intelligence's (see docs/02-prerequisites.md).

@description('Base name used to derive resource names. Lowercase letters, digits and hyphens.')
@minLength(3)
@maxLength(18)
param baseName string

@description('Azure region. Must be a Content Understanding region (see docs/02-prerequisites.md).')
param location string = resourceGroup().location

@description('Deploy a dedicated Document Intelligence (FormRecognizer) resource. When false, Document Intelligence runs on the Foundry resource.')
param deployDedicatedDocumentIntelligence bool = true

@description('SKU for the dedicated Document Intelligence resource.')
@allowed([
  'F0'
  'S0'
])
param documentIntelligenceSku string = 'S0'

@description('Deploy the completion + embedding models a GA Content Understanding custom analyzer needs.')
param deployModels bool = true

@description('Completion model name. Must be a Content Understanding supported generative model.')
param completionModelName string = 'gpt-5.2'

@description('Completion model version.')
param completionModelVersion string = '2025-12-11'

@description('Completion model deployment name (mapped in contentunderstanding/defaults).')
param completionDeploymentName string = 'gpt-5.2'

@description('Completion deployment SKU.')
param completionSku string = 'GlobalStandard'

@description('Completion deployment capacity (thousands of tokens per minute).')
@minValue(1)
param completionCapacity int = 50

@description('Embedding model name.')
param embeddingModelName string = 'text-embedding-3-large'

@description('Embedding model version.')
param embeddingModelVersion string = '1'

@description('Embedding model deployment name (mapped in contentunderstanding/defaults).')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Embedding deployment SKU.')
param embeddingSku string = 'GlobalStandard'

@description('Embedding deployment capacity (thousands of tokens per minute).')
@minValue(1)
param embeddingCapacity int = 50

@description('Disable key auth on both resources (Entra ID only). The harness uses keys, so leave false unless you switch it to Entra ID.')
param disableLocalAuth bool = false

@description('Optional principal (user or service principal) granted Cognitive Services User on both resources.')
param principalId string = ''

@description('Principal type for principalId.')
@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string = 'User'

@description('Tags applied to all resources.')
param tags object = {
  purpose: 'demo'
  pattern: 'document-intelligence-vs-content-understanding'
}

var foundryName = toLower('${baseName}-foundry')
var docIntelName = toLower('${baseName}-docintel')
// Built-in role: Cognitive Services User
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

// ---------------------------------------------------------------------------
// Microsoft Foundry resource - hosts Content Understanding (and DI when no
// dedicated resource is deployed).
// ---------------------------------------------------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  tags: tags
  sku: {
    name: 'S0'
  }
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // customSubDomainName is REQUIRED for the Content Understanding endpoint
    // to resolve as https://<name>.services.ai.azure.com/
    customSubDomainName: foundryName
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
    disableLocalAuth: disableLocalAuth
  }
}

// Deployments on one account must be created one at a time.
resource completionDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployModels) {
  parent: foundry
  name: completionDeploymentName
  sku: {
    name: completionSku
    capacity: completionCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: completionModelName
      version: completionModelVersion
    }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (deployModels) {
  parent: foundry
  name: embeddingDeploymentName
  sku: {
    name: embeddingSku
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
  dependsOn: [
    completionDeployment
  ]
}

// ---------------------------------------------------------------------------
// Document Intelligence (dedicated) - serves the prebuilt-invoice and
// prebuilt-read tiers.
// ---------------------------------------------------------------------------
resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2025-06-01' = if (deployDedicatedDocumentIntelligence) {
  name: docIntelName
  location: location
  tags: tags
  sku: {
    name: documentIntelligenceSku
  }
  kind: 'FormRecognizer'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: docIntelName
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
    disableLocalAuth: disableLocalAuth
  }
}

resource foundryUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(foundry.id, principalId, cognitiveServicesUserRoleId)
  scope: foundry
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}

resource docIntelUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployDedicatedDocumentIntelligence && !empty(principalId)) {
  name: guid(resourceId('Microsoft.CognitiveServices/accounts', docIntelName), principalId, cognitiveServicesUserRoleId)
  scope: documentIntelligence
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}

// ---------------------------------------------------------------------------
// Outputs - feed demo-ids.local.json (the azd postprovision hook writes it)
// ---------------------------------------------------------------------------
output documentIntelligenceEndpoint string = deployDedicatedDocumentIntelligence
  ? 'https://${docIntelName}.cognitiveservices.azure.com/'
  : 'https://${foundryName}.cognitiveservices.azure.com/'
output documentIntelligenceName string = deployDedicatedDocumentIntelligence ? docIntelName : foundry.name

output contentUnderstandingEndpoint string = 'https://${foundryName}.services.ai.azure.com/'
output foundryName string = foundry.name

output completionModelName string = completionModelName
output completionDeploymentName string = completionDeploymentName
output embeddingModelName string = embeddingModelName
output embeddingDeploymentName string = embeddingDeploymentName

output resourceGroupName string = resourceGroup().name
output deployedLocation string = location

// Keys are intentionally NOT emitted as outputs - deployment outputs are stored
// in the deployment history and readable by anyone with read access on the RG.
// Retrieve them explicitly instead:
//   az cognitiveservices account keys list -n <name> -g <rg> --query key1 -o tsv
