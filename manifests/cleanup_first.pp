#
# @summary Cleanup etcd datadir before bootstrap, do not call it directly, use cleanup_first => true of role_etcd instead
#
# @example 
#   class { 'role_etcd::cleanup_first':
#     data_dir => '/var/lib/etcd/somefolder',
#   }
#
# @param data_dir
#  Absolute path to folder containing etcd data
#
# @param wait
#  Number of seconds to wait for other member of the cluster to also clea themselve and forget about me
#

class role_etcd::cleanup_first (
  Stdlib::Absolutepath $data_dir = undef,
  Integer[1] $wait = 60,

  ) {

  exec { 'wait_for_other_node_to_clean':
    require     => Transition['stop etcd for cleanup first'],
    command     => "sleep ${wait}",
    path        => '/usr/bin:/bin',
    refreshonly => true,
  }

  transition { 'stop etcd for cleanup first':
    resource   => Service['etcd'],
    attributes => { ensure => stopped },
    prior_to   => File[$data_dir],
  }

  file {"purge-${data_dir}":
    path    => $data_dir,
    ensure  => directory,
    recurse => true,
    purge   => true,
    force   => true,
    notify  => Exec['wait_for_other_node_to_clean'],
  }

}
