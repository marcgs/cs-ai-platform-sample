// Roles for the developer (or CI principal) running azd: use models and agents in the
// project, and push agent images. Data-plane roles for Cosmos DB and AI Search are granted
// in their own modules.

param principalId string
param principalType string
param foundryAccountName string
param registryName string

var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Azure AI User
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, principalId, roles.foundryUser)
  scope: account
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource acrPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, principalId, roles.acrPush)
  scope: registry
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPush)
  }
}
