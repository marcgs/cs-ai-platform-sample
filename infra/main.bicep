// CS AI platform sample: all Azure resources for one environment.
//
// Subscription-scoped so the resource group is part of the deployment and
// `azd provision --preview` stays side-effect free.

targetScope = 'subscription'

@description('azd environment name; used for the resource group and resource names.')
@minLength(1)
@maxLength(64)
param environmentName string

@description('Region for all resources.')
param location string

@description('Region for AI Search; defaults to location. Use another region when it lacks capacity.')
param searchLocation string = ''

@description('Object ID of the deploying user or service principal; gets data-plane access.')
param principalId string = ''

@description('Type of the deploying principal.')
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('Address space of the virtual network (a /16 or larger RFC 1918 range).')
param vnetAddressPrefix string = '10.40.0.0/16'

@description('Chat model for the agents. Must be available as DataZoneStandard in the region.')
param chatModel object = {
  name: 'gpt-5.4-mini'
  version: '2026-03-17'
  capacity: 50
}

@description('Embedding model for search vectors.')
param embeddingModel object = {
  name: 'text-embedding-3-large'
  version: '1'
  capacity: 50
}

var abbrs = loadJsonContent('abbreviations.json')
var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }
var hasPrincipal = !empty(principalId)
var cosmosDatabase = 'cs-platform'
var episodesContainer = 'episodes'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    tags: tags
    logAnalyticsName: '${abbrs.operationalInsightsWorkspaces}${token}'
    appInsightsName: '${abbrs.insightsComponents}${token}'
  }
}

module network 'modules/network.bicep' = {
  name: 'network'
  scope: rg
  params: {
    location: location
    tags: tags
    vnetName: '${abbrs.networkVirtualNetworks}${token}'
    addressPrefix: vnetAddressPrefix
  }
}

module foundry 'modules/foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    location: location
    tags: tags
    accountName: '${abbrs.cognitiveServicesAccounts}${token}'
    projectName: 'cs-platform'
    registryName: '${abbrs.containerRegistryRegistries}${token}'
    deployments: [
      {
        name: chatModel.name
        model: { format: 'OpenAI', name: chatModel.name, version: chatModel.version }
        sku: { name: 'DataZoneStandard', capacity: chatModel.capacity }
      }
      {
        name: embeddingModel.name
        model: { format: 'OpenAI', name: embeddingModel.name, version: embeddingModel.version }
        sku: { name: 'DataZoneStandard', capacity: embeddingModel.capacity }
      }
    ]
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.connectionString
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    agentSubnetId: network.outputs.agentsSubnetId
  }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  scope: rg
  params: {
    location: location
    tags: tags
    accountName: '${abbrs.documentDBDatabaseAccounts}${token}'
    databaseName: cosmosDatabase
    episodesContainerName: episodesContainer
    // The hosted agent's identity is added after deployment (scripts/grant_agent_access.py).
    dataContributorPrincipalIds: hasPrincipal ? [principalId] : []
  }
}

module search 'modules/search.bicep' = {
  name: 'search'
  scope: rg
  params: {
    location: empty(searchLocation) ? location : searchLocation
    tags: tags
    name: '${abbrs.searchSearchServices}${token}'
    contributorPrincipalIds: hasPrincipal ? [principalId] : []
    contributorPrincipalType: principalType
    readerPrincipalIds: [foundry.outputs.projectPrincipalId]
  }
}

module functions 'modules/functions.bicep' = {
  name: 'functions'
  scope: rg
  params: {
    location: location
    tags: tags
    appName: '${abbrs.webSitesFunctions}mcp-${token}'
    planName: '${abbrs.webServerFarms}mcp-${token}'
    storageAccountName: '${abbrs.storageStorageAccounts}mcp${token}'
    identityName: '${abbrs.managedIdentityUserAssignedIdentities}mcp-${token}'
    appInsightsName: monitoring.outputs.appInsightsName
    subnetId: network.outputs.functionsSubnetId
  }
}

// Private endpoints for the data stores: the Functions host storage and the episode store.
var privateEndpoints = [
  { service: 'storage', groupId: 'blob', dnsZone: 'blob' }
  { service: 'storage', groupId: 'queue', dnsZone: 'queue' }
  { service: 'storage', groupId: 'table', dnsZone: 'table' }
  { service: 'cosmos', groupId: 'Sql', dnsZone: 'cosmosSql' }
]

module endpoints 'modules/private-endpoint.bicep' = [
  for pe in privateEndpoints: {
    name: 'pe-${pe.service}-${toLower(pe.groupId)}'
    scope: rg
    params: {
      location: location
      tags: tags
      name: '${abbrs.networkPrivateEndpoints}${pe.service}-${toLower(pe.groupId)}-${token}'
      subnetId: network.outputs.privateEndpointSubnetId
      serviceId: pe.service == 'storage' ? functions.outputs.storageAccountId : cosmos.outputs.accountId
      groupId: pe.groupId
      dnsZoneId: network.outputs.dnsZoneIds[pe.dnsZone]
    }
  }
]

module developerAccess 'modules/developer-access.bicep' = if (hasPrincipal) {
  name: 'developer-access'
  scope: rg
  params: {
    principalId: principalId
    principalType: principalType
    foundryAccountName: foundry.outputs.accountName
    registryName: foundry.outputs.registryName
  }
}

// Outputs become azd environment values (and the agent's settings).
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT_NAME string = chatModel.name
output FOUNDRY_EMBEDDING_DEPLOYMENT_NAME string = embeddingModel.name
output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = foundry.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_RESOURCE_ID string = foundry.outputs.registryId
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = foundry.outputs.acrConnectionName
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_ACCOUNT_NAME string = cosmos.outputs.accountName
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output COSMOS_EPISODES_CONTAINER string = cosmos.outputs.episodesContainerName
output AZURE_SEARCH_ENDPOINT string = search.outputs.endpoint
output AZURE_SEARCH_NAME string = search.outputs.name
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString
output DIAGNOSTICS_MCP_FUNCTION_NAME string = functions.outputs.name
output DIAGNOSTICS_MCP_ENDPOINT string = functions.outputs.mcpEndpoint
