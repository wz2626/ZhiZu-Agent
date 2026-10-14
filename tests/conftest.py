"""Offline suite guard: Windows asyncio may use loopback, cloud sockets may not."""

import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_external_network(monkeypatch):
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    local = {"127.0.0.1", "::1", "localhost", None, b"localhost"}

    def checked_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in local:
            pytest.fail("offline suite forbids external network connections")
        return connect(sock, address)

    def checked_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] not in local:
            pytest.fail("offline suite forbids external network connections")
        return connect_ex(sock, address)

    def checked_dns(host, *args, **kwargs):
        if host not in local:
            pytest.fail("offline suite forbids external DNS resolution")
        return getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", checked_dns)
