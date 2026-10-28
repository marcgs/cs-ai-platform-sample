// Foundry project connections: container registry (image pulls for hosted agents),
// Application Insights (agent traces) and AI Search (knowledge tool, Entra auth).
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

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
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
        isSharedToAll: true
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
        isSharedToAll: true
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
        isSharedToAll: true
        metadata: {
          ApiType: 'Azure'
          ResourceId: searchId
        }
      }
    }
  }
}

output acrConnectionName string = account::project::acrConnection.name
output searchConnectionName string = account::project::searchConnection.name
output searchConnectionId string = account::project::searchConnection.id
