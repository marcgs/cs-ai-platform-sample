// Entra-only development host. Bastion and NAT have public IPs; the VM does not.

param location string
param tags object = {}
param name string
param subnetId string
param bastionSubnetId string
@allowed(['Basic', 'Standard'])
param bastionSku string = 'Basic'
param vmSize string = 'Standard_B2s'
param principalId string = ''
param principalType string = 'User'
@description('Provisioning account only: no password or authorized keys are configured.')
param adminUsername string = 'jumpadmin'

var loginRole = '1c0163c0-47e6-4577-8991-ea5c82e286e4'
var readerRole = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${name}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'private'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: { id: subnetId }
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: name
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
      }
    }
    osProfile: {
      computerName: 'jump'
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
      }
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    networkProfile: { networkInterfaces: [{ id: nic.id }] }
  }
}

resource entraLogin 'Microsoft.Compute/virtualMachines/extensions@2024-07-01' = {
  parent: vm
  name: 'AADSSHLoginForLinux'
  location: location
  tags: tags
  properties: {
    publisher: 'Microsoft.Azure.ActiveDirectory'
    type: 'AADSSHLoginForLinux'
    typeHandlerVersion: '1.0'
    autoUpgradeMinorVersion: true
  }
}

resource bastionIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${name}-bastion-ip'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource bastion 'Microsoft.Network/bastionHosts@2024-05-01' = {
  name: '${name}-bastion'
  location: location
  tags: tags
  sku: { name: bastionSku }
  properties: {
    enableTunneling: bastionSku == 'Standard'
    ipConfigurations: [
      {
        name: 'bastion'
        properties: {
          subnet: { id: bastionSubnetId }
          publicIPAddress: { id: bastionIp.id }
        }
      }
    ]
  }
}

resource login 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId) && principalType == 'User') {
  name: guid(vm.id, principalId, loginRole)
  scope: vm
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', loginRole)
  }
}

resource reader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(resourceGroup().id, principalId, readerRole)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)
  }
}

output vmName string = vm.name
output bastionName string = bastion.name
