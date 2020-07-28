class role_etcd (

  Array[Stdlib::Host, 3] $cluster_hosts = undef,

  ) {

  fail("Got cluster hosts ${cluster_hosts}")

}
