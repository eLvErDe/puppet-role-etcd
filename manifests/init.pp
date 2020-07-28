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

class role_etcd (

  Array[Stdlib::Host, 3] $cluster_hosts = undef,

  ) {

  # Validate cluster config is okay
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

}
