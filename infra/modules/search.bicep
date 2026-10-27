// Azure AI Search for logbook and historical-case retrieval. Entra ID only; no keys.

param location string
param tags object = {}
param name string
@description('Principals that manage indexes and documents (developers, seeding hooks).')
param contributorPrincipalIds string[] = []
@description('Service principals that query indexes (e.g. the Foundry project identity).')
param readerPrincipalIds string[] = []
param contributorPrincipalType string = 'User'

var roles = {
  serviceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  indexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  indexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
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

resource readerRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for principalId in readerPrincipalIds: {
    name: guid(search.id, principalId, roles.indexDataReader)
    scope: search
    properties: {
      principalId: principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.indexDataReader)
    }
  }
]

output name string = search.name
output id string = search.id
output endpoint string = 'https://${search.name}.search.windows.net'
