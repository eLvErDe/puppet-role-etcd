#!/usr/bin/python3


# pylint: disable=line-too-long


"""
Check etcd cluster v3 using etcdctl command
"""


import re
import sys
import json
import shutil
import argparse
import subprocess
from typing import NamedTuple, List, Optional


class V3ClusterMember(NamedTuple):
    """
    Represent ectd cluster node (v3) and its parameters

    :param id: Unique node id
    :type id: int
    :param name: Unique node name (usually hostname)
    :type name: str
    :param peer_urls: List of URLs advertised to peers
    :type peer_urls: List[str]
    :param client_urls: List of URLs advertised to clients
    :type client_urls: List[str]
    """

    id: int
    name: str
    peer_urls: List[str]
    client_urls: List[str]


class V3ClusterMemberHealth(NamedTuple):
    """
    Represent ectd cluster node (v3) and its health

    :param id: Unique node id
    :type id: int
    :param name: Unique node name (usually hostname)
    :type name: str
    :param peer_urls: List of URLs advertised to peers
    :type peer_urls: List[str]
    :param client_urls: List of URLs advertised to clients
    :type client_urls: List[str]
    :param health: True if node is healthy else False
    :type health: bool
    :param took: Time took by request, as string with unit
    :type took: str
    :param error: Optional error message if node is not healthy
    :type error: str, optional
    """

    id: int
    name: str
    peer_urls: List[str]
    client_urls: List[str]
    health: bool
    took: str
    error: Optional[str] = None


class NagiosException(Exception):
    """
    Raised to return a Nagios state
    """

    def __init__(self, message: str, multiline: Optional[str] = None) -> None:
        super().__init__(message)
        self.multiline = multiline


class NagiosCritical(NagiosException):
    """
    Raised to return critical Nagios state
    """


class NagiosWarning(NagiosException):
    """
    Raised to return warning Nagios state
    """


class NagiosOk(NagiosException):
    """
    Raised to return ok Nagios state
    """


class NagiosArgumentParser(argparse.ArgumentParser):
    """
    Inherit from ArgumentParser but exit with Nagios code 3 (Unknown) in case of argument error
    """

    def error(self, message: str):
        print("UNKNOWN: Bad arguments (see --help): %s" % message)
        sys.exit(3)


class CheckEtcdCluster:
    """
    Check etcd cluster v3 using etcdctl command
    """

    def __init__(self) -> None:
        self.etcdctl_path = shutil.which("etcdctl")
        assert self.etcdctl_path is not None, "Unable to find etcdctl command in path"

    def get_v3_members_list(self) -> List[V3ClusterMember]:
        """
        Get cluster nodes and their states

        :return: List of named tuples representing each cluster node
        .rtype: list
        """

        assert self.etcdctl_path is not None  # for mypy
        env = {"ETCDCTL_API": "3"}
        cmd = [self.etcdctl_path, "member", "list", "-w", "json"]
        try:
            output = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as exc:
            cmd_str = " ".join("%s=%s" % x for x in env.items()) + " " + " ".join(cmd)
            stdout_l = [x.strip() for x in str(exc.stdout, "utf-8").splitlines() if x.strip()]
            if stdout_l:
                raise NagiosCritical("Command %s failed with code %s: %s" % (cmd_str, exc.returncode, stdout_l[0]), multiline="\n".join(stdout_l)) from None
            raise NagiosCritical("Command %s failed with code %s: No output" % (cmd_str, exc.returncode)) from None

        parsed = json.loads(output)
        members = [V3ClusterMember(id=x["ID"], name=x["name"], peer_urls=x["peerURLs"], client_urls=x["clientURLs"]) for x in parsed["members"]]
        return members

    def get_v3_members_health(self) -> List[V3ClusterMemberHealth]:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """
        Get cluster members health, member list does not return it

        See: https://github.com/etcd-io/etcd/issues/2711 for an explanation of all this mess

        :return: List of named tuples representing member health
        :rtype: list
        """

        members_health: List[V3ClusterMemberHealth] = []
        members = self.get_v3_members_list()
        endpoint_all_members = [x.peer_urls[0] for x in members]

        assert self.etcdctl_path is not None  # for mypy
        env = {"ETCDCTL_API": "3"}
        cmd = [self.etcdctl_path, "--endpoints=%s" % ",".join(endpoint_all_members), "endpoint", "health", "-w", "json"]
        try:
            res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output = res.stdout
            try:
                parsed = json.loads(output)
            except json.decoder.JSONDecodeError:  # older version does not handle -w json :/
                parsed = []
                for entry in str(output, "utf-8").splitlines():
                    matcher_healthy = re.match(r"^(?P<endpoint>[^ ]+) is (?P<health>healthy):.+took = (?P<took>[^ ]+)$", entry)
                    matcher_unhealthy = re.match(r"^(?P<endpoint>[^ ]+) is (?P<health>unhealthy): (?P<error>.+)$", entry)
                    if matcher_healthy:
                        matched_dict = matcher_healthy.groupdict()
                        health = True
                    elif matcher_unhealthy:
                        matched_dict = matcher_unhealthy.groupdict()
                        health = False
                    else:
                        raise AssertionError("Old etcd without JSON support but unparsable line %s" % entry)
                    assert "endpoint" in matched_dict, "Old etcd without JSON support but unparsable line %s" % entry
                    assert "health" in matched_dict, "Old etcd without JSON support but unparsable line %s" % entry
                    assert "took" in matched_dict, "Old etcd without JSON support but unparsable line %s" % entry
                    parsed_entry = {
                        "endpoint": matched_dict["endpoint"],
                        "health": health,
                        "took": matched_dict["took"],
                        "peer_urls": [matched_dict["endpoint"]],
                        "client_urls": [],
                        "error": matched_dict.get(error, None),
                    }
                    parsed.append(parsed_entry)
            else:  # If no json.decoder.JSONDecodeError raised, we're running a recent etcdctl not returning 1 in case of failure with json mode
                res.check_returncode()
        except subprocess.CalledProcessError as exc:
            cmd_str = " ".join("%s=%s" % x for x in env.items()) + " " + " ".join(cmd)
            stdout_l = [x.strip() for x in str(exc.stdout, "utf-8").splitlines() if x.strip()]
            stderr_l = [x.strip() for x in str(exc.stderr, "utf-8").splitlines() if x.strip()]
            try:
                parsed = json.loads(exc.stdout)
            except:  # pylint: disable=bare-except
                if stdout_l:
                    main_line = stdout_l[0]
                elif stderr_l:
                    main_line = stderr_l[0]
                else:
                    main_line = "No output"
                if stdout_l + stderr_l:
                    raise NagiosCritical(
                        "Command %s failed with code %s: %s" % (cmd_str, exc.returncode, main_line), multiline="\n".join(stdout_l + stderr_l)
                    ) from None
                raise NagiosCritical("Command %s failed with code %s: %s" % (cmd_str, exc.returncode, main_line)) from None

        for parsed_member in parsed:
            matchings = [x for x in members if parsed_member["endpoint"] in x.peer_urls]
            assert len(matchings) == 1, "Unable to find node definition matching endpoint %s" % parsed_member["endpoint"]
            matching = matchings[0]
            members_health.append(
                V3ClusterMemberHealth(
                    id=matching.id,
                    name=matching.name,
                    peer_urls=matching.peer_urls,
                    client_urls=matching.client_urls,
                    health=parsed_member["health"],
                    took=parsed_member["took"],
                    error=parsed_member.get("error", None),
                )
            )
        return members_health

    def check_cluster_members(self, warning: Optional[int] = None, critical: Optional[int] = None) -> None:
        """
        Check cluster members and their health and raise exception corresponding to thresholds

        :param warning: Raise NagiosWarning if number of dead nodes is above or equal to this threshold
        :type warning: int, optional
        :param critical: Raise NagiosCritical if number of dead nodes is above or equal to this threshold
        :type critical: int, optional
        """

        members = self.get_v3_members_health()
        healthy_members = [x for x in members if x.health is True]
        dead_members = [x for x in members if x.health is False]
        lines_healthy = ["%s: healthy: took %s" % (x.name, x.took) for x in healthy_members]
        lines_dead = ["%s: dead: took %s: %s" % (x.name, x.took, x.error) for x in dead_members]
        multiline = "\n".join(lines_healthy + lines_dead)

        if critical is not None and len(dead_members) >= critical:
            raise NagiosCritical(
                "%d/%d healthy nodes: %s" % (len(healthy_members), len(members), ", ".join("%s: %s" % (x.name, x.error) for x in dead_members)),
                multiline=multiline,
            )
        if warning is not None and len(dead_members) >= warning:
            raise NagiosWarning(
                "%d/%d healthy nodes: %s" % (len(healthy_members), len(members), ", ".join("%s: %s" % (x.name, x.error) for x in dead_members)),
                multiline=multiline,
            )
        if not dead_members:
            raise NagiosOk("%d/%d healthy nodes: %s" % (len(healthy_members), len(members), ", ".join(x.name for x in healthy_members)), multiline=multiline)
        # Dead nodes but no thresholds requested
        raise NagiosOk(
            "%d/%d healthy nodes: %s" % (len(healthy_members), len(members), ", ".join("%s: %s" % (x.name, x.error) for x in dead_members)), multiline=multiline
        )


def parse_args() -> argparse.Namespace:
    """
    Parse command line arguments

    :return: argparse.Namespace object with all command line arguments as attributes (dash replace by underscore)
    :type: argparse.Namespace
    """

    parser = NagiosArgumentParser(description=__doc__.strip())
    subparsers = parser.add_subparsers(help="Type of check to perform", dest="action", required=True)

    cluster_members_parser = subparsers.add_parser("cluster_members", help="Check members of etcd cluster")
    cluster_members_parser.add_argument(
        "--warning", type=int, nargs="?", required=False, help="Minimum number (inclusive) of dead node(s) in cluster to trigger warning, -1 as null value"
    )
    cluster_members_parser.add_argument(
        "--critical", type=int, nargs="?", required=False, help="Mimumum number (inclusive) of dead node(s) in cluster to trigger critical, -1 as null value"
    )
    args = parser.parse_args()

    if args.action == "cluster_members":
        if args.warning == -1:
            args.warning = None
        if args.critical == -1:
            args.critical = None
        if args.warning is not None and args.critical is not None and args.warning > args.critical:
            parser.error("Warning threshold cannot be greater than critical one")

    return args


if __name__ == "__main__":

    config = parse_args()

    try:
        etcd = CheckEtcdCluster()
        if config.action == "cluster_members":
            etcd.check_cluster_members(warning=config.warning, critical=config.critical)
        else:
            raise ValueError("Unsupported action %s" % config.action)
    except NagiosOk as exc:
        print("OK: %s" % exc)
        if exc.multiline:
            print(exc.multiline)
        sys.exit(0)
    except NagiosWarning as exc:
        print("WARNING: %s" % exc)
        if exc.multiline:
            print(exc.multiline)
        sys.exit(1)
    except NagiosCritical as exc:
        print("CRITICAL: %s" % exc)
        if exc.multiline:
            print(exc.multiline)
        sys.exit(2)
    except Exception as exc:  # pylint: disable=broad-except
        print("UNKNOWN: %s. %s" % (exc.__class__.__name__, exc))
        sys.exit(3)
