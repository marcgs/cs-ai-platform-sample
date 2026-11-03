// Foundry project connections: container registry (image pulls for hosted agents),
// Application Insights (agent traces), AI Search and dedicated evaluation storage (Entra auth).
//
// A separate module because connections need a preview API version (GA 2025-06-01 doesn't
// resolve the ContainerRegistry connection), and a template may define the project only once.

param accountName string
param projectName string
param projectPrincipalId string
param registryName string
param appInsightsId string
@secure()
param appInsightsConnectionString string
param searchId string
param searchEndpoint string
param evaluationStorageAccountName string

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource evaluationStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: evaluationStorageAccountName
}

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName

  resource project 'projects' existing = {
    name: projectName

    resource acrConnection 'connections' = {
      name: '${registryName}-conn'
      properties: {
        category: 'ContainerRegistry'
        target: registry.properties.loginServer
        authType: 'ManagedIdentity'
        credentials: {
          clientId: projectPrincipalId
          resourceId: registry.id
        }
        isSharedToAll: false
        peRequirement: 'NotRequired'
        peStatus: 'NotApplicable'
        useWorkspaceManagedIdentity: false
        metadata: {
          ResourceId: registry.id
        }
      }
    }

    resource appInsightsConnection 'connections' = {
      name: 'appinsights'
      properties: {
        category: 'AppInsights'
        target: appInsightsId
        authType: 'ApiKey'
        isSharedToAll: false
        peRequirement: 'NotRequired'
        peStatus: 'NotApplicable'
        useWorkspaceManagedIdentity: false
        credentials: {
          key: appInsightsConnectionString
        }
        metadata: {
          ApiType: 'Azure'
          ResourceId: appInsightsId
        }
      }
    }

    resource searchConnection 'connections' = {
      name: 'diagnostics-search'
      properties: {
        category: 'CognitiveSearch'
        target: searchEndpoint
        authType: 'AAD'
        isSharedToAll: false
        peRequirement: 'NotRequired'
        peStatus: 'NotApplicable'
        useWorkspaceManagedIdentity: false
        metadata: {
          ApiType: 'Azure'
          ApiVersion: '2024-05-01-preview'
          DeploymentApiVersion: '2023-11-01'
          ResourceId: searchId
        }
      }
    }

    resource evaluationStorageConnection 'connections' = {
      name: evaluationStorage.name
      properties: {
        category: 'AzureStorageAccount'
        target: evaluationStorage.properties.primaryEndpoints.blob
        authType: 'AAD'
        isSharedToAll: false
        metadata: {
          ApiType: 'Azure'
          ResourceId: evaluationStorage.id
          location: evaluationStorage.location
        }
      }
    }
  }
}

output acrConnectionName string = account::project::acrConnection.name
output searchConnectionName string = account::project::searchConnection.name
output searchConnectionId string = account::project::searchConnection.id
output evaluationStorageConnectionName string = account::project::evaluationStorageConnection.name
