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
# @param cleanup_first
#  DANGEREOUS: Cleanup etcd files before deploying, useful if you want to boostrap over existing and do not care about existing data
#
# @debug
#  Enable etcd verbose log messages
#
# @deploy_nagios_script
#  Deploy Nagios style monitoring script to be run through NRPE, defaults to true
#

class role_etcd (

  Array[Stdlib::Host, 3] $cluster_hosts = undef,
  String[3] $cluster_token = 'etcd-cluster',
  Stdlib::Port $client_port = 2379,
  Stdlib::Port $peer_port = 2380,
  Boolean $cleanup_first = false,
  Boolean $debug = false,
  Optional[Integer[0]] $auto_compaction_retention = undef,
  Boolean $deploy_nagios_script = true,

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
  $data_dir = "/var/lib/etcd/${myself}.etcd"

  ### If cleanup is asked (to re-boostrap from scratch, do it as first stage)
  stage { 'cleanup_first': }
  Stage['cleanup_first'] -> Stage['main']
  if ($cleanup_first) {
    class { 'role_etcd::cleanup_first':
      data_dir => $data_dir,
      stage    => cleanup_first,
    }
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
    data_dir                    => $data_dir,
    etcd_name                   => $myself,
    listen_client_urls          => "http://0.0.0.0:${client_port}",
    advertise_client_urls       => "http://${myself}:${client_port},http://127.0.0.1:${client_port}",
    listen_peer_urls            => "http://0.0.0.0:${peer_port}",
    initial_advertise_peer_urls => "http://${myself}:${peer_port}",
    initial_cluster             => $initial_cluster,
    debug                       => $debug,
    auto_compaction_retention   => $auto_compaction_retention,
  }
  File['/etc/etcd'] -> Class['etcd']

  # Deploy a cron job doing weekly defrag and remote start sleep
  # To avoid defragmenting all cluster nodes at the same
  file { '/etc/cron.weekly/puppet-etcd-defrag':
    source => 'puppet:///modules/role_etcd/target/etc/cron.weekly/puppet-etcd-defrag',
    mode   => '0755',
  }

  # Deploy Nagios monitoring script
  if $deploy_nagios_script {
    case $::osfamily {
      'RedHat': {
        $nrpe_conf = '/etc/nrpe.d'
        $nrpe_service = 'nrpe'
      }
      'Debian': {
        $nrpe_conf = '/etc/nagios/nrpe.d'
        $nrpe_service = 'nagios-nrpe-server'
      }
    }
    exec { "role_etcd_restart_${nrpe_service}":
      path        => ['/usr/bin','/usr/sbin', '/bin', '/sbin'],
      command     => "service ${nrpe_service} restart",
      refreshonly => true,
    }
    file { '/usr/lib/nagios/plugins/check_etcd_v3_cluster.py':
      source => 'puppet:///modules/role_etcd/target/usr/lib/nagios/plugins/check_etcd_v3_cluster.py',
      mode   => '0755',
    }
    file { "${nrpe_conf}/00_puppet_check_etcd_v3_cluster_members_health.cfg":
      path    => "${nrpe_conf}/00_puppet_check_etcd_v3_cluster_members_health.cfg",
      ensure  => 'file',
      content => "command[check_etcd_v3_cluster_members_health]=/usr/lib/nagios/plugins/check_etcd_v3_cluster.py cluster_members --warning \$ARG1\$ --critical \$ARG2\$\n",
      notify  => Exec["role_etcd_restart_${nrpe_service}"],
    }
  }

}
