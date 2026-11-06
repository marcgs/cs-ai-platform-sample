// Owner on the subscription for one principal. The principal is part of the assignment name:
// a recreated VM gets a new identity, and an assignment's principal can't be changed.
targetScope = 'subscription'

param principalId string

var ownerRoleId = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'

resource owner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, principalId, ownerRoleId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', ownerRoleId)
  }
}
