"""Minimal late-bound COM access for Solid Edge and Design Manager.

pywin32's ``win32com.client`` keeps generated wrappers in ``%TEMP%\\gen_py``. When
that cache goes stale (after a Solid Edge update, an interrupted run, ...) every
script fails until the folder is deleted. This module talks to ``IDispatch``
directly, the way VBScript does, so it never reads or writes that cache.
``clear_gen_py_cache`` is still provided for the older scripts in this folder.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from typing import Any, Iterator

import pythoncom
import pywintypes

_GET = pythoncom.DISPATCH_METHOD | pythoncom.DISPATCH_PROPERTYGET
# Errors meaning "that member is a method, not a property" (or the reverse).
_WRONG_KIND = {-2147352573,   # DISP_E_MEMBERNOTFOUND
               -2147352562,   # DISP_E_BADPARAMCOUNT
               -2147352561}   # DISP_E_PARAMNOTOPTIONAL
_PyIDispatch = pythoncom.TypeIIDs[pythoncom.IID_IDispatch]
_PyIUnknown = pythoncom.TypeIIDs[pythoncom.IID_IUnknown]

# Solid Edge rejects calls while it's busy (starting up, rebuilding a view...).
_BUSY = {-2147418111,   # RPC_E_CALL_REJECTED
         -2147417846}   # RPC_E_SERVERCALL_RETRYLATER
_BUSY_TIMEOUT = 120.0


class ComObject:
    """Wraps a raw IDispatch. Use ``get``/``call`` for members and ``set`` for properties."""

    __slots__ = ("_disp", "_ids", "_name")

    def __init__(self, disp, name: str = "object"):
        self._disp = disp
        self._ids: dict[str, int] = {}
        self._name = name

    def __repr__(self) -> str:
        return f"<ComObject {self._name}>"

    @classmethod
    def create(cls, progid: str) -> "ComObject":
        disp = _retry(lambda: pythoncom.CoCreateInstance(
            progid, None, pythoncom.CLSCTX_SERVER, pythoncom.IID_IDispatch))
        return cls(disp, progid)

    @classmethod
    def running(cls, progid: str) -> "ComObject | None":
        """The already-running instance of ``progid``, or None."""
        try:
            unk = pythoncom.GetActiveObject(progid)
        except pywintypes.com_error:
            return None
        return cls(unk.QueryInterface(pythoncom.IID_IDispatch), progid)

    def _dispid(self, name: str) -> int:
        dispid = self._ids.get(name)
        if dispid is None:
            dispid = self._ids[name] = _retry(lambda: self._disp.GetIDsOfNames(name))
        return dispid

    def _wrap(self, value: Any, name: str) -> Any:
        if isinstance(value, _PyIDispatch):
            return ComObject(value, name)
        if isinstance(value, _PyIUnknown):
            try:
                return ComObject(value.QueryInterface(pythoncom.IID_IDispatch), name)
            except pywintypes.com_error:
                return value
        if isinstance(value, tuple):
            return tuple(self._wrap(v, name) for v in value)
        return value

    def _invoke(self, name: str, flags: tuple[int, int], args: tuple) -> Any:
        dispid = self._dispid(name)
        try:
            result = _retry(lambda: self._disp.Invoke(dispid, 0, flags[0], True, *args))
        except pywintypes.com_error as e:
            if e.hresult not in _WRONG_KIND:
                raise
            result = _retry(lambda: self._disp.Invoke(dispid, 0, flags[1], True, *args))
        return self._wrap(result, name)

    def call(self, name: str, *args: Any) -> Any:
        """Call a method (falls back to a parameterised property get)."""
        return self._invoke(name, (pythoncom.DISPATCH_METHOD, pythoncom.DISPATCH_PROPERTYGET), args)

    def get(self, name: str, *args: Any) -> Any:
        """Read a property (falls back to calling it as a method)."""
        return self._invoke(name, (pythoncom.DISPATCH_PROPERTYGET, pythoncom.DISPATCH_METHOD), args)

    def set(self, name: str, value: Any) -> None:
        dispid = self._dispid(name)
        _retry(lambda: self._disp.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, False, value))

    def call_with_out_param(self, name: str, *args: Any) -> Any:
        """Call a method whose last argument is a by-ref [out] VARIANT and return it."""
        dispid = self._dispid(name)
        arg_types = tuple((pythoncom.VT_VARIANT, 1) for _ in args) + \
            ((pythoncom.VT_VARIANT | pythoncom.VT_BYREF, 2),)
        result = _retry(lambda: self._disp.InvokeTypes(
            dispid, 0, pythoncom.DISPATCH_METHOD, (pythoncom.VT_EMPTY, 0), arg_types, *args, None))
        return result[-1] if isinstance(result, tuple) else result

    def __iter__(self) -> Iterator[Any]:
        enum = _retry(lambda: self._disp.Invoke(pythoncom.DISPID_NEWENUM, 0, _GET, True))
        enum = enum.QueryInterface(pythoncom.IID_IEnumVARIANT)
        while True:
            items = enum.Next(1)
            if not items:
                return
            yield self._wrap(items[0], self._name + "[]")


def _retry(fn):
    deadline = time.monotonic() + _BUSY_TIMEOUT
    while True:
        try:
            return fn()
        except pywintypes.com_error as e:
            if e.hresult in _BUSY and time.monotonic() < deadline:
                time.sleep(0.25)
                continue
            raise


def describe_error(exc: BaseException) -> str:
    """Readable text for COM errors (pywin32's default repr is cryptic)."""
    if isinstance(exc, pywintypes.com_error):
        hresult, message, excepinfo, _ = exc.args
        detail = ""
        if excepinfo and len(excepinfo) > 2 and excepinfo[2]:
            detail = f": {excepinfo[2]}"
        elif excepinfo and len(excepinfo) > 5 and excepinfo[5]:
            detail = f" (code {excepinfo[5] & 0xFFFFFFFF:#010x})"
        return f"{message}{detail}"
    return str(exc) or exc.__class__.__name__


@contextlib.contextmanager
def apartment():
    """Initialise COM for the current (worker) thread."""
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def gen_py_cache_dir() -> str:
    try:
        import win32com
        path = getattr(win32com, "__gen_path__", "")
    except ImportError:
        path = ""
    return path or os.path.join(os.environ.get("TEMP", ""), "gen_py",
                                f"{sys.version_info.major}.{sys.version_info.minor}")


def clear_gen_py_cache() -> tuple[str, bool]:
    """Delete pywin32's generated-wrapper cache (the fix for the classic gen_py error)."""
    path = gen_py_cache_dir()
    for mod in [m for m in sys.modules if m.startswith("win32com.gen_py.")]:
        del sys.modules[mod]
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        return path, not os.path.exists(path)
    return path, False
