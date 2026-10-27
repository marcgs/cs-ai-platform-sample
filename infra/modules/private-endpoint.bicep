// Private endpoint for one sub-resource (group) of a service, registered in its private DNS zone.

param location string
param tags object = {}
param name string
param subnetId string
param serviceId string
@description('Private link group, e.g. blob, queue, table or Sql.')
param groupId string
param dnsZoneId string

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: name
        properties: {
          privateLinkServiceId: serviceId
          groupIds: [groupId]
        }
      }
    ]
  }

  resource dnsGroup 'privateDnsZoneGroups' = {
    name: 'default'
    properties: {
      privateDnsZoneConfigs: [
        {
          name: groupId
          properties: { privateDnsZoneId: dnsZoneId }
        }
      ]
    }
  }
}
