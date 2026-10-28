// Azure AI Search for logbook and historical-case retrieval. Entra ID only; no keys.

param location string
param tags object = {}
param name string
@description('Principals that manage indexes and documents (developers, seeding hooks).')
param contributorPrincipalIds string[] = []
param contributorPrincipalType string = 'User'
@description('Service principals behind the Foundry AI Search tool (Foundry account and project identities).')
param toolPrincipalIds string[] = []
@description('Foundry account whose embedding deployment vectorizes queries at search time.')
param foundryAccountName string

var roles = {
  serviceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  indexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'basic'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    disableLocalAuth: true
    semanticSearch: 'free'
    publicNetworkAccess: 'enabled'
  }
}

resource contributorRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for assignment in flatten(map(contributorPrincipalIds, id => [
    { principalId: id, role: roles.serviceContributor }
    { principalId: id, role: roles.indexDataContributor }
  ])): {
    name: guid(search.id, assignment.principalId, assignment.role)
    scope: search
    properties: {
      principalId: assignment.principalId
      principalType: contributorPrincipalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', assignment.role)
    }
  }
]

// The Foundry AI Search tool needs index data and service contributor roles.
resource toolRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for assignment in flatten(map(toolPrincipalIds, id => [
    { principalId: id, role: roles.serviceContributor }
    { principalId: id, role: roles.indexDataContributor }
  ])): {
    name: guid(search.id, assignment.principalId, assignment.role)
    scope: search
    properties: {
      principalId: assignment.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', assignment.role)
    }
  }
]

// The index vectorizer calls the embedding deployment with the search service's identity.
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource vectorizerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, search.id, roles.openAiUser)
  scope: foundryAccount
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
  }
}

output name string = search.name
output id string = search.id
output endpoint string = 'https://${search.name}.search.windows.net'
