// Development host inside the private network, reached through Bastion Developer. Neither has a
// public IP: governed subscriptions can block new public IPs, and Developer uses a shared pool.

param location string
param tags object = {}
param name string
param subnetId string
param vnetId string
param vmSize string = 'Standard_B2s'
@description('SSH public key for the admin account; the private key stays on the developer machine.')
@minLength(1)
param adminPublicKey string
@description('Admin account; password authentication is disabled.')
param adminUsername string = 'jumpadmin'

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
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: adminPublicKey
            }
          ]
        }
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

resource bastion 'Microsoft.Network/bastionHosts@2024-05-01' = {
  name: '${name}-bastion'
  location: location
  tags: tags
  sku: { name: 'Developer' }
  properties: {
    virtualNetwork: { id: vnetId }
  }
}

output vmName string = vm.name
output bastionName string = bastion.name
