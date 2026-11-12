"""Minimal libseccomp wrapper for the adapter worker.

The rule is intentionally narrow: ordinary syscalls remain allowed, while
creation of UDP, raw, RDM and SOCK_SEQPACKET IP sockets is denied. TCP remains
available only to the Landlock-approved broker/meter ports.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno

SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO = 0x00050000 | errno.EPERM
SCMP_CMP_EQ = 4

AF_INET = 2
AF_INET6 = 10
AF_PACKET = 17
_DOMAINS = (AF_INET, AF_INET6, AF_PACKET)
_BASE_TYPES = (2, 3, 4, 5)  # DGRAM, RAW, RDM, SEQPACKET
_TYPE_FLAGS = (0, 0x800, 0x80000, 0x80800)  # NONBLOCK/CLOEXEC variants


class SeccompError(Exception):
    """The worker could not install its socket policy."""


class _ArgCmp(ctypes.Structure):
    _fields_ = [
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    ]


def _load():
    name = ctypes.util.find_library("seccomp") or "libseccomp.so.2"
    try:
        lib = ctypes.CDLL(name, use_errno=True)
    except OSError as exc:
        raise SeccompError(f"libseccomp is unavailable: {exc}") from exc
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    lib.seccomp_rule_add_array.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
        ctypes.c_uint, ctypes.POINTER(_ArgCmp)]
    lib.seccomp_rule_add_array.restype = ctypes.c_int
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    return lib


def available() -> bool:
    try:
        _load()
    except SeccompError:
        return False
    return True


def apply_socket_policy() -> dict[str, object]:
    """Deny non-stream IP socket creation in the current process."""
    lib = _load()
    ctx = lib.seccomp_init(SCMP_ACT_ALLOW)
    if not ctx:
        raise SeccompError("seccomp_init returned a null context")
    try:
        syscall = lib.seccomp_syscall_resolve_name(b"socket")
        if syscall < 0:
            raise SeccompError("libseccomp cannot resolve socket(2)")
        added = 0
        for domain in _DOMAINS:
            for base_type in _BASE_TYPES:
                for flag in _TYPE_FLAGS:
                    comparators = (_ArgCmp * 2)(
                        _ArgCmp(0, SCMP_CMP_EQ, domain, 0),
                        _ArgCmp(1, SCMP_CMP_EQ, base_type | flag, 0))
                    result = lib.seccomp_rule_add_array(
                        ctx, SCMP_ACT_ERRNO, syscall, 2, comparators)
                    if result < 0:
                        raise SeccompError(
                            f"cannot add socket rule for domain={domain}, "
                            f"type={base_type | flag:#x}: {result}")
                    added += 1
        result = lib.seccomp_load(ctx)
        if result < 0:
            raise SeccompError(f"seccomp_load failed: {result}")
    finally:
        lib.seccomp_release(ctx)
    return {
        "socket_rules": added,
        "blocked": "UDP/raw/RDM/SEQPACKET IP sockets",
    }
