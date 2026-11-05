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

@description('Isolate service data planes and add a jump host. Use a new environment.')
param privateNetworking bool = false

@description('Required in private mode; discard the private key after generating this provisioning key.')
param adminPublicKey string = ''

@description('Private-mode fallback for ADR 0006. Public mode always retains the existing exception.')
param evaluationStorageTrustedServicesBypass bool = false

@description('Basic supports browser Entra SSH; Standard also supports native clients.')
@allowed(['Basic', 'Standard'])
param bastionSku string = 'Basic'

@description('Jump host VM size; local Docker builds need sufficient memory.')
param jumpVmSize string = 'Standard_B2s'

@description('Object ID of the deploying user or service principal; gets data-plane access.')
param principalId string = ''

@description('Type of the deploying principal.')
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('Address space of the virtual network (a /16 or larger RFC 1918 range).')
param vnetAddressPrefix string = '10.40.0.0/16'

@description('Existing NSG on the private-endpoint subnet. Set before reprovisioning an environment with an attached NSG.')
param privateEndpointSubnetNetworkSecurityGroupId string = ''

@description('Existing NSG on the Functions subnet. Set before reprovisioning an environment with an attached NSG.')
param functionsSubnetNetworkSecurityGroupId string = ''

@description('Existing NSG on the agent subnet. Set before reprovisioning an environment with an attached NSG.')
param agentsSubnetNetworkSecurityGroupId string = ''

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
var cosmosAccountName = '${abbrs.documentDBDatabaseAccounts}${token}'
// Known before the account exists, so the platform API's settings don't depend on it.
var cosmosEndpoint = 'https://${cosmosAccountName}.documents.azure.com:443/'
var episodesContainer = 'episodes'
// Created and seeded by the postprovision hook (scripts/setup_platform.py).
var searchIndexName = 'diagnostics-cases'

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
    privateNetworking: privateNetworking
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
    privateEndpointSubnetNetworkSecurityGroupId: privateEndpointSubnetNetworkSecurityGroupId
    functionsSubnetNetworkSecurityGroupId: functionsSubnetNetworkSecurityGroupId
    agentsSubnetNetworkSecurityGroupId: agentsSubnetNetworkSecurityGroupId
    privateNetworking: privateNetworking
  }
}

module jumpHost 'modules/jump-host.bicep' = if (privateNetworking) {
  name: 'jump-host'
  scope: rg
  params: {
    location: location
    tags: tags
    name: 'vm-jump-${token}'
    subnetId: network.outputs.jumpSubnetId
    bastionSubnetId: network.outputs.bastionSubnetId
    bastionSku: bastionSku
    vmSize: jumpVmSize
    principalId: principalId
    principalType: principalType
    adminPublicKey: adminPublicKey
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
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    agentSubnetId: network.outputs.agentsSubnetId
    privateNetworking: privateNetworking
  }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  scope: rg
  params: {
    location: location
    tags: tags
    accountName: cosmosAccountName
    databaseName: cosmosDatabase
    episodesContainerName: episodesContainer
    // The hosted agent's identity is added after deployment (scripts/setup_platform.py).
    dataContributorPrincipalIds: concat(
      [apiApp.outputs.identityPrincipalId],
      hasPrincipal ? [principalId] : []
    )
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
    toolPrincipalIds: [foundry.outputs.accountPrincipalId, foundry.outputs.projectPrincipalId]
    foundryAccountName: foundry.outputs.accountName
    privateNetworking: privateNetworking
  }
}

module evaluationStorage 'modules/evaluation-storage.bicep' = {
  name: 'evaluation-storage'
  scope: rg
  params: {
    location: location
    tags: tags
    name: '${abbrs.storageStorageAccounts}eval${token}'
    projectPrincipalId: foundry.outputs.projectPrincipalId
    foundryAccountId: foundry.outputs.accountId
    logAnalyticsId: monitoring.outputs.logAnalyticsId
    trustedServicesBypass: !privateNetworking || evaluationStorageTrustedServicesBypass
  }
}

module evaluationEndpoint 'modules/private-endpoint.bicep' = {
  name: 'pe-evaluation-storage-blob'
  scope: rg
  params: {
    location: location
    tags: tags
    name: '${abbrs.networkPrivateEndpoints}eval-blob-${token}'
    subnetId: network.outputs.privateEndpointSubnetId
    serviceId: evaluationStorage.outputs.id
    groupId: 'blob'
    dnsZoneId: network.outputs.dnsZoneIds.blob
  }
}

module connections 'modules/foundry-connections.bicep' = {
  name: 'foundry-connections'
  scope: rg
  params: {
    accountName: foundry.outputs.accountName
    projectName: foundry.outputs.projectName
    projectPrincipalId: foundry.outputs.projectPrincipalId
    registryName: foundry.outputs.registryName
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.connectionString
    searchId: search.outputs.id
    searchEndpoint: search.outputs.endpoint
    evaluationStorageAccountName: evaluationStorage.outputs.name
  }
  dependsOn: [evaluationEndpoint]
}

// Private storage shared by the function apps (host state and deployment packages).
module functionStorage 'modules/function-storage.bicep' = {
  name: 'function-storage'
  scope: rg
  params: {
    location: location
    tags: tags
    name: '${abbrs.storageStorageAccounts}mcp${token}'
    deploymentContainers: ['app-package', 'app-package-api']
  }
}

// The diagnostics MCP server (agent tools).
module mcpApp 'modules/function-app.bicep' = {
  name: 'function-app-mcp'
  scope: rg
  params: {
    location: location
    tags: tags
    appName: '${abbrs.webSitesFunctions}mcp-${token}'
    planName: '${abbrs.webServerFarms}mcp-${token}'
    identityName: '${abbrs.managedIdentityUserAssignedIdentities}mcp-${token}'
    serviceName: 'diagnostics-mcp'
    storageAccountName: functionStorage.outputs.name
    deploymentContainer: 'app-package'
    appInsightsName: monitoring.outputs.appInsightsName
    subnetId: network.outputs.functionsSubnetId
    privateNetworking: privateNetworking
  }
}

// The platform API: episodes and feedback over the private episode store.
module apiApp 'modules/function-app.bicep' = {
  name: 'function-app-api'
  scope: rg
  params: {
    location: location
    tags: tags
    appName: '${abbrs.webSitesFunctions}api-${token}'
    planName: '${abbrs.webServerFarms}api-${token}'
    identityName: '${abbrs.managedIdentityUserAssignedIdentities}api-${token}'
    serviceName: 'platform-api'
    storageAccountName: functionStorage.outputs.name
    deploymentContainer: 'app-package-api'
    appInsightsName: monitoring.outputs.appInsightsName
    subnetId: network.outputs.functionsSubnetId
    privateNetworking: privateNetworking
    settings: {
      COSMOS_ENDPOINT: cosmosEndpoint
      COSMOS_DATABASE: cosmosDatabase
      COSMOS_EPISODES_CONTAINER: episodesContainer
    }
  }
}

// Private endpoints for the data stores: the Functions host storage and the episode store.
var privateEndpoints = [
  { service: 'storage', groupId: 'blob', dnsZone: 'blob' }
  { service: 'storage', groupId: 'queue', dnsZone: 'queue' }
  { service: 'storage', groupId: 'table', dnsZone: 'table' }
  { service: 'cosmos', groupId: 'Sql', dnsZone: 'cosmosSql' }
]

var isolatedServiceIds = {
  foundry: foundry.outputs.accountId
  registry: foundry.outputs.registryId
  search: search.outputs.id
  monitor: monitoring.outputs.privateLinkScopeId
  mcp: mcpApp.outputs.id
  api: apiApp.outputs.id
}

var isolatedEndpoints = [
  {
    name: 'foundry'
    groupId: 'account'
    zones: ['cognitive', 'openai', 'foundry']
  }
  {
    name: 'registry'
    groupId: 'registry'
    zones: ['registry']
  }
  {
    name: 'search'
    groupId: 'searchService'
    zones: ['search']
  }
  {
    name: 'monitor'
    groupId: 'azuremonitor'
    zones: ['monitor', 'oms', 'ods', 'agentService', 'blob']
  }
  {
    name: 'mcp'
    groupId: 'sites'
    zones: ['web']
  }
  {
    name: 'api'
    groupId: 'sites'
    zones: ['web']
  }
]

module isolatedEndpointsModule 'modules/private-endpoint.bicep' = [
  for pe in isolatedEndpoints: if (privateNetworking) {
    name: 'pe-${pe.name}'
    scope: rg
    params: {
      location: location
      tags: tags
      name: '${abbrs.networkPrivateEndpoints}${pe.name}-${token}'
      subnetId: network.outputs.privateEndpointSubnetId
      serviceId: isolatedServiceIds[pe.name]
      groupId: pe.groupId
      dnsZoneId: network.outputs.dnsZoneIds[pe.zones[0]]
      additionalDnsZoneIds: map(skip(pe.zones, 1), zone => network.outputs.dnsZoneIds[zone])
    }
  }
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
      serviceId: pe.service == 'storage' ? functionStorage.outputs.id : cosmos.outputs.accountId
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
output AZURE_PRIVATE_NETWORKING bool = privateNetworking
output AZURE_BASTION_SKU string = bastionSku
output JUMP_VM_NAME string = privateNetworking ? jumpHost!.outputs.vmName : ''
output BASTION_NAME string = privateNetworking ? jumpHost!.outputs.bastionName : ''
output AZURE_AI_ACCOUNT_ID string = foundry.outputs.accountId
output AZURE_SEARCH_SHARED_PRIVATE_LINK_ID string = search.outputs.sharedPrivateLinkId
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_MODEL_DEPLOYMENT_NAME string = chatModel.name
output FOUNDRY_EMBEDDING_DEPLOYMENT_NAME string = embeddingModel.name
output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_PROJECT_ID string = foundry.outputs.projectId
output AZURE_OPENAI_ENDPOINT string = foundry.outputs.openAiEndpoint
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = foundry.outputs.registryLoginServer
output AZURE_CONTAINER_REGISTRY_RESOURCE_ID string = foundry.outputs.registryId
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = connections.outputs.acrConnectionName
output COSMOS_ENDPOINT string = cosmos.outputs.endpoint
output COSMOS_ACCOUNT_NAME string = cosmos.outputs.accountName
output COSMOS_DATABASE string = cosmos.outputs.databaseName
output COSMOS_EPISODES_CONTAINER string = cosmos.outputs.episodesContainerName
output AZURE_SEARCH_ENDPOINT string = search.outputs.endpoint
output AZURE_SEARCH_NAME string = search.outputs.name
output AZURE_SEARCH_CONNECTION_NAME string = connections.outputs.searchConnectionName
output AZURE_SEARCH_CONNECTION_ID string = connections.outputs.searchConnectionId
output AZURE_SEARCH_INDEX_NAME string = searchIndexName
output EVALUATION_STORAGE_ACCOUNT_NAME string = evaluationStorage.outputs.name
output EVALUATION_STORAGE_RESOURCE_ID string = evaluationStorage.outputs.id
output EVALUATION_STORAGE_ENDPOINT string = evaluationStorage.outputs.blobEndpoint
output EVALUATION_STORAGE_CONNECTION_NAME string = connections.outputs.evaluationStorageConnectionName
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString
output DIAGNOSTICS_MCP_FUNCTION_NAME string = mcpApp.outputs.name
output DIAGNOSTICS_MCP_ENDPOINT string = 'https://${mcpApp.outputs.hostName}/runtime/webhooks/mcp'
output PLATFORM_API_FUNCTION_NAME string = apiApp.outputs.name
output PLATFORM_API_ENDPOINT string = 'https://${apiApp.outputs.hostName}/api'
