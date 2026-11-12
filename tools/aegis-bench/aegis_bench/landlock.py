"""Small Linux Landlock wrapper for the process-isolated adapter worker.

Landlock is a deny-by-default kernel policy applied after the worker has
loaded the runtime and before adapter code runs. It is used for filesystem
read/write containment and TCP-port restriction. It is not a network namespace:
UDP and non-TCP protocols are outside its scope.
"""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
from typing import Iterable

SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1
LANDLOCK_RULE_NET_PORT = 2

FS_EXECUTE = 1 << 0
FS_WRITE_FILE = 1 << 1
FS_READ_FILE = 1 << 2
FS_READ_DIR = 1 << 3
FS_REMOVE_DIR = 1 << 4
FS_REMOVE_FILE = 1 << 5
FS_MAKE_CHAR = 1 << 6
FS_MAKE_DIR = 1 << 7
FS_MAKE_REG = 1 << 8
FS_MAKE_SOCK = 1 << 9
FS_MAKE_FIFO = 1 << 10
FS_MAKE_BLOCK = 1 << 11
FS_MAKE_SYM = 1 << 12
FS_REFER = 1 << 13
FS_TRUNCATE = 1 << 14
FS_ALL = (FS_EXECUTE | FS_WRITE_FILE | FS_READ_FILE | FS_READ_DIR |
          FS_REMOVE_DIR | FS_REMOVE_FILE | FS_MAKE_CHAR | FS_MAKE_DIR |
          FS_MAKE_REG | FS_MAKE_SOCK | FS_MAKE_FIFO | FS_MAKE_BLOCK |
          FS_MAKE_SYM | FS_REFER | FS_TRUNCATE)
FS_READONLY = FS_EXECUTE | FS_READ_FILE | FS_READ_DIR

NET_BIND_TCP = 1 << 0
NET_CONNECT_TCP = 1 << 1
NET_ALL = NET_BIND_TCP | NET_CONNECT_TCP


class LandlockError(Exception):
    """Landlock is unavailable or a policy could not be installed."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


class _NetPortAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("port", ctypes.c_uint64),
    ]


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.restype = ctypes.c_int
    return libc


def abi_version() -> int:
    """Return the kernel Landlock ABI, or a negative value when unavailable."""
    if not hasattr(os, "O_PATH"):
        return -1
    libc = _libc()
    result = libc.syscall(
        ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET), None, 0,
        LANDLOCK_CREATE_RULESET_VERSION)
    return int(result)


def _check(result: int, operation: str) -> int:
    if result < 0:
        error = ctypes.get_errno()
        raise LandlockError(
            f"landlock {operation} failed: {os.strerror(error)}")
    return int(result)


def _add_path_rule(libc, ruleset_fd: int, path: Path,
                   access: int) -> None:
    path = Path(path)
    if not path.exists():
        return
    flags = os.O_PATH
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(path, flags)
    try:
        attr = _PathBeneathAttr(access, fd)
        _check(
            libc.syscall(
                ctypes.c_long(SYS_LANDLOCK_ADD_RULE),
                ruleset_fd,
                LANDLOCK_RULE_PATH_BENEATH,
                ctypes.byref(attr),
                0),
            f"add path {path}")
    finally:
        os.close(fd)


def _add_port_rule(libc, ruleset_fd: int, port: int) -> None:
    if not 0 < port <= 65535:
        raise LandlockError(f"invalid TCP port: {port}")
    attr = _NetPortAttr(NET_CONNECT_TCP, port)
    _check(
        libc.syscall(
            ctypes.c_long(SYS_LANDLOCK_ADD_RULE),
            ruleset_fd,
            LANDLOCK_RULE_NET_PORT,
            ctypes.byref(attr),
            0),
        f"add TCP port {port}")


def apply(*, rw_paths: Iterable[Path], ro_paths: Iterable[Path],
          tcp_ports: Iterable[int] = ()) -> dict[str, object]:
    """Apply a Landlock ruleset to the current process.

    The caller should invoke this immediately before executing untrusted
    adapter code. Once installed, the restriction applies to the process and
    all descendants and cannot be relaxed.
    """
    abi = abi_version()
    if abi < 1:
        raise LandlockError("Landlock is unavailable on this kernel")
    libc = _libc()
    handled_net = NET_ALL if abi >= 4 else 0
    attr = _RulesetAttr(FS_ALL, handled_net)
    ruleset_fd = _check(
        libc.syscall(
            ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET),
            ctypes.byref(attr),
            ctypes.sizeof(attr),
            0),
        "create ruleset")
    try:
        for path in rw_paths:
            _add_path_rule(libc, ruleset_fd, Path(path), FS_ALL)
        for path in ro_paths:
            _add_path_rule(libc, ruleset_fd, Path(path), FS_READONLY)
        if handled_net:
            for port in tcp_ports:
                _add_port_rule(libc, ruleset_fd, int(port))
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            error = ctypes.get_errno()
            raise LandlockError(
                f"prctl(PR_SET_NO_NEW_PRIVS) failed: "
                f"{os.strerror(error)}")
        _check(
            libc.syscall(
                ctypes.c_long(SYS_LANDLOCK_RESTRICT_SELF),
                ruleset_fd, 0),
            "restrict self")
    finally:
        os.close(ruleset_fd)
    return {
        "abi": abi,
        "filesystem": "workspace/runtime allowlist",
        "network": "TCP connect allowlist",
        "handled_net": bool(handled_net),
    }
