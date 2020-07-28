#
# @summary Deploy etcd cluster easily
#
# @example role_etcd class
#   class { 'role_etcd':
#     cluster_hosts => ['host1.com", 'host2.com', '10.0.0.3'],
#   }
#
# @param cluster_hosts
#  List of members of the cluster, as IPv4, IPv6 or hostname, must be at least 3 members
#
# @param cluster_token
#  Unique cluster identifier, can be left to default value
#
# @param client_port
#  Etcd port to communicate with clients
#
# @param peer_port
#  Etcd port to communicate with cluster peers
#
# @debug
#  Enable etcd verbose log messages
#

class role_etcd (

  Array[Stdlib::Host, 3] $cluster_hosts = undef,
  String[3] $cluster_token = 'etcd-cluster',
  Stdlib::Port $client_port = 2379,
  Stdlib::Port $peer_port = 2380,
  Boolean $debug = false,

  ) {

  ### Validate cluster config is okay
  # No need to validate parameter content, thanks to Puppet typing I am sure there is at least 3
  # hosts or addresses in $cluster_host but I need to check if I am seening myself in this list
  notify{"Etcd cluster masters are ${cluster_hosts}": loglevel => 'info'}

  $net_if = $::interfaces.split(',').filter |$if| { $if !~ /^(lo|dockerO)$/ }
  $_ipv4_addr = $net_if.map |$if| { $facts["ipaddress_${if}"] }
  $_ipv6_addr = $net_if.map |$if| { $facts["ipaddress6_${if}"] }
  $ipv4_addr = $_ipv4_addr.filter |$val| { $val =~ NotUndef }
  $ipv6_addr = $_ipv6_addr.filter |$val| { $val =~ NotUndef }

  $matchs_ipv4_addr = intersection($ipv4_addr, $cluster_hosts)
  $matchs_ipv6_addr = intersection($ipv6_addr, $cluster_hosts)

  if ($::fqdn in $cluster_hosts) {
    notify{"Found myself in etcd \$cluster_host using my fqdn ${::fqdn}": loglevel => 'info'}
    $myself = $::fqdn
  } elsif ($::hostname in $cluster_hosts) {
    notify{"Found myself in etcd \$cluster_host using my hostname ${::hostname}": loglevel => 'info'}
    $myself = $::hostname
  } elsif (!empty($matchs_ipv4_addr)) {
    $myself = $matchs_ipv4_addr[0]
    notify{"Found myself in etcd \$cluster_host using my IPv4 addr ${myself}": loglevel => 'info'}
  } elsif (!empty($matchs_ipv6_addr)) {
    $myself = $matchs_ipv6_addr[0]
    notify{"Found myself in etdc \$cluster_host using my IPv6 addr ${myself}": loglevel => 'info'}
  } else {
    fail("Cannot find myself in etcd \$cluster_host, as fqdn (${::fqdn}), hostname (${::hostname}), IPv4 addr (${ipv4_addr}) or IPv6 addr (${ipv6_addr})  on the system")
  }

  ### Deploy cluster using cristifalcas/etcd
  $initial_cluster = $cluster_hosts.map |$host| { "${host}=http://${host}:${peer_port}" }

  # Puppet module cristifalcas/etcd has wrong config path for Debian, at least for Debian Buster distrib packages
  case $::osfamily {
    'Debian' : {
      $config_file_path = '/etc/default/etcd'
    }
    default  : {
      $config_file_path = $::etcd::config_file_path
    }
  }

  file { '/etc/etcd': ensure => 'directory' }
  class { 'etcd':
    config_file_path            => $config_file_path,
    etcd_name                   => $myself,
    listen_client_urls          => "http://0.0.0.0:${client_port}",
    advertise_client_urls       => "http://${myself}:${client_port},http://127.0.0.1:${client_port}",
    listen_peer_urls            => "http://0.0.0.0:${peer_port}",
    initial_advertise_peer_urls => "http://${myself}:${peer_port}",
    initial_cluster             => $initial_cluster,
    debug                       => $debug,
  }
  File['/etc/etcd'] -> Class['etcd']

}
