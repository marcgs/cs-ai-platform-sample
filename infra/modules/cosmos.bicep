// Cosmos DB for NoSQL (serverless) holding agent episodes. Entra ID only, no keys, and
// reachable only through its private endpoint.

param location string
param tags object = {}
param accountName string
param databaseName string
param episodesContainerName string
@description('Principals that get the built-in Data Contributor role (data plane).')
param dataContributorPrincipalIds string[] = []

// Built-in "Cosmos DB Built-in Data Contributor" data-plane role.
var dataContributorRoleId = '00000000-0000-0000-0000-000000000002'

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: accountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
  }

  resource database 'sqlDatabases' = {
    name: databaseName
    properties: {
      resource: {
        id: databaseName
      }
    }

    resource episodes 'containers' = {
      name: episodesContainerName
      properties: {
        resource: {
          id: episodesContainerName
          partitionKey: {
            paths: ['/id']
            kind: 'Hash'
          }
        }
      }
    }
  }
}

resource dataContributors 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for principalId in dataContributorPrincipalIds: {
    parent: account
    name: guid(account.id, principalId, dataContributorRoleId)
    properties: {
      principalId: principalId
      roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributorRoleId}'
      scope: account.id
    }
  }
]

output accountName string = account.name
output accountId string = account.id
output endpoint string = account.properties.documentEndpoint
output databaseName string = databaseName
output episodesContainerName string = episodesContainerName
