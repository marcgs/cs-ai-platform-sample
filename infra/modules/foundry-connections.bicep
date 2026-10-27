// Foundry project connections: container registry (image pulls for hosted agents) and
// Application Insights (agent traces).
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
  }
}

output acrConnectionName string = account::project::acrConnection.name
