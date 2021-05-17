#!/usr/bin/python3

# pylint: disable=line-too-long,bad-continuation

"""
Periodic poll etcd to find current cluster leader and write its name to /services/etcd/leader/{name,id} keys
"""


import os
import sys
import time
import signal
import logging
import argparse

import etcd  # type: ignore


LOGGER = logging.getLogger()


def get_cli() -> argparse.Namespace:
    """
    Get command line arguments

    :return: Namespace object containing command line arguments
    :rtype: argparse.Namespace
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--peers", type=str, nargs="+", default=("127.0.0.1:2379",), help="List of etcd endpoints", metavar=("127.0.0.1:2379", "10.0.0.2:2379"))
    parser.add_argument("--ssl", action="store_true", help="Connect using https instead of http")
    parser.add_argument("--delay", type=int, help="Number of seconds to wait before each poll", default=10, metavar="10")
    config = parser.parse_args()
    return config


def main() -> None:  # pylint: disable=too-many-branches
    """
    Poll etcd leader forever
    """

    if os.getenv("NO_LOGS_TS", None) is not None:
        log_formatter = "%(levelname)-8s %(message)s"
    else:
        log_formatter = "%(asctime)s %(levelname)-8s %(message)s"

    logging.basicConfig(level=logging.INFO, format=log_formatter, stream=sys.stdout)

    # Spams with etcd response did not contain a cluster ID
    logging.getLogger("etcd.client").setLevel(logging.ERROR)

    # Map sigterm to sigint
    signal.signal(signal.SIGTERM, signal.getsignal(signal.SIGINT))

    config = get_cli()
    hosts = tuple((x.split(":")[0], int(x.split(":")[1])) for x in config.peers)
    protocol = "https" if config.ssl else "http"
    client = etcd.Client(host=hosts, protocol=protocol, allow_reconnect=True, read_timeout=5)

    exc_info = False

    logging.info("Polling etcd leader every %d seconds", config.delay)
    while True:
        try:
            try:
                current_id = client.read("/services/etcd/leader/id").value  # pylint: disable=no-member
            except etcd.EtcdKeyNotFound:
                current_id = None
            try:
                current_name = client.read("/services/etcd/leader/name").value  # pylint: disable=no-member
            except etcd.EtcdKeyNotFound:
                current_name = None
            leader = client.leader
            leader_id = leader["id"]
            leader_name = leader["name"]
            if current_id != leader_id:
                logging.info("Updating /services/etcd/leader/id from %s to %s", current_id, leader_id)
                if current_id is None:
                    client.write("/services/etcd/leader/id", leader_id, prevExist=False)
                else:
                    client.write("/services/etcd/leader/id", leader_id, prevValue=current_id)
                logging.info("Updated /services/etcd/leader/id from %s to %s", current_id, leader_id)
            if current_name != leader_name:
                logging.info("Updating /services/etcd/leader/name from %s to %s", current_name, leader_name)
                if current_name is None:
                    client.write("/services/etcd/leader/name", leader_name, prevExist=False)
                else:
                    client.write("/services/etcd/leader/name", leader_name, prevValue=current_name)
                logging.info("Updated /services/etcd/leader/name from %s to %s", current_name, leader_name)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.error("Unable to refresh current etcd leader: %s: %s", exc.__class__.__name__, exc, exc_info=exc_info)
        except KeyboardInterrupt:
            LOGGER.warning("Exiting on SIGINT/SIGTERM")
            break
        finally:
            try:
                time.sleep(config.delay)
            except KeyboardInterrupt:
                LOGGER.warning("Exiting on SIGINT/SIGTERM")
                break


if __name__ == "__main__":
    main()
