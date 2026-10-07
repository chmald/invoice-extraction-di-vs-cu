// Subscription wrapper for the Azure Developer CLI. Creates (or reuses, via
// AZURE_RESOURCE_GROUP) the resource group and passes every main.bicep
// parameter through. Outputs are UPPER_SNAKE_CASE so azd writes them to
// .azure/<env>/.env and exports them to the hooks.
targetScope = 'subscription'

@description('azd environment name. Lowercase letters, digits and hyphens, 3-12 characters (enforced by the preprovision hook).')
@minLength(3)
@maxLength(12)
param environmentName string

@description('Azure region. Must be a Content Understanding region.')
param location string

@description('Existing resource group to reuse. Empty = create rg-<environmentName>.')
param resourceGroupName string = ''

@description('Principal granted Cognitive Services User on the resources (azd sets AZURE_PRINCIPAL_ID).')
param principalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string = 'User'

param deployDedicatedDocumentIntelligence bool = true

@allowed([
  'F0'
  'S0'
])
param documentIntelligenceSku string = 'S0'

param deployModels bool = true
param completionModelName string = 'gpt-5.2'
param completionModelVersion string = '2025-12-11'
param completionDeploymentName string = 'gpt-5.2'
param completionSku string = 'GlobalStandard'
param completionCapacity int = 50
param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'
param embeddingDeploymentName string = 'text-embedding-3-large'
param embeddingSku string = 'GlobalStandard'
param embeddingCapacity int = 50
param disableLocalAuth bool = false

var rgName = empty(resourceGroupName) ? 'rg-${environmentName}' : resourceGroupName
// Globally unique custom subdomains: <env>-<5 chars> (max 18, the main.bicep baseName limit).
var baseName = '${environmentName}-${take(uniqueString(subscription().id, environmentName, location), 5)}'
var tags = {
  'azd-env-name': environmentName
  purpose: 'demo'
  pattern: 'document-intelligence-vs-content-understanding'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: tags
}

module demo 'main.bicep' = {
  name: 'di-vs-cu-${environmentName}'
  scope: rg
  params: {
    baseName: baseName
    location: location
    deployDedicatedDocumentIntelligence: deployDedicatedDocumentIntelligence
    documentIntelligenceSku: documentIntelligenceSku
    deployModels: deployModels
    completionModelName: completionModelName
    completionModelVersion: completionModelVersion
    completionDeploymentName: completionDeploymentName
    completionSku: completionSku
    completionCapacity: completionCapacity
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingDeploymentName: embeddingDeploymentName
    embeddingSku: embeddingSku
    embeddingCapacity: embeddingCapacity
    disableLocalAuth: disableLocalAuth
    principalId: principalId
    principalType: principalType
    tags: tags
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output DOCUMENTINTELLIGENCE_ENDPOINT string = demo.outputs.documentIntelligenceEndpoint
output DOCUMENTINTELLIGENCE_NAME string = demo.outputs.documentIntelligenceName
output CONTENTUNDERSTANDING_ENDPOINT string = demo.outputs.contentUnderstandingEndpoint
output FOUNDRY_NAME string = demo.outputs.foundryName
output CU_COMPLETION_MODEL string = demo.outputs.completionModelName
output CU_COMPLETION_DEPLOYMENT string = demo.outputs.completionDeploymentName
output CU_EMBEDDING_MODEL string = demo.outputs.embeddingModelName
output CU_EMBEDDING_DEPLOYMENT string = demo.outputs.embeddingDeploymentName
