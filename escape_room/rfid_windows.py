from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

from escape_room.rfid_common import (
    DigitHandler,
    ScanBuffer,
    device_name_matcher,
    preferred_match_tokens,
)

logger = logging.getLogger(__name__)

RFID_DEBUG = __import__("os").environ.get("RFID_DEBUG", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Python 3.9–3.11 do not expose every wintypes alias (3.12+ adds LRESULT, etc.).
if not hasattr(wintypes, "LRESULT"):
    wintypes.LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
if not hasattr(wintypes, "LPARAM"):
    wintypes.LPARAM = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
if not hasattr(wintypes, "WPARAM"):
    wintypes.WPARAM = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
for _name, _ctype in (
    ("HBRUSH", wintypes.HANDLE),
    ("HCURSOR", wintypes.HANDLE),
    ("HICON", wintypes.HANDLE),
):
    if not hasattr(wintypes, _name):
        setattr(wintypes, _name, _ctype)

WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
RIM_TYPEKEYBOARD = 1
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIDI_DEVICENAME = 0x20000007
RI_KEY_BREAK = 0x0001
VK_RETURN = 0x0D
SW_HIDE = 0

WNDPROC = ctypes.WINFUNCTYPE(
    wintypes.LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("keyboard", RAWKEYBOARD)]

    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", _U),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType", wintypes.DWORD),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _configure_win32_api() -> None:
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = wintypes.LRESULT
    user32.GetRawInputData.argtypes = [
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.UINT),
        wintypes.UINT,
    ]
    user32.GetRawInputData.restype = wintypes.UINT


_configure_win32_api()


def _vkey_to_digit(vkey: int) -> str | None:
    if 0x30 <= vkey <= 0x39:
        return chr(vkey)
    if 0x60 <= vkey <= 0x69:
        return str(vkey - 0x60)
    return None


def _device_name(h_device: wintypes.HANDLE) -> str | None:
    size = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(
        h_device,
        RIDI_DEVICENAME,
        None,
        ctypes.byref(size),
    )
    if size.value <= 0:
        return None
    buf = ctypes.create_unicode_buffer(size.value)
    got = user32.GetRawInputDeviceInfoW(
        h_device,
        RIDI_DEVICENAME,
        buf,
        ctypes.byref(size),
    )
    if got == wintypes.UINT(-1).value or got <= 0:
        return None
    return buf.value


def _is_internal_keyboard(name: str) -> bool:
    upper = name.upper()
    if "ACPI#" in upper:
        return True
    if "CONVERTEDDEVICE" in upper:
        return True
    return False


def _is_usb_hid_keyboard(name: str) -> bool:
    return "HID#VID_" in name.upper()


def list_keyboard_devices() -> list[tuple[wintypes.HANDLE, str]]:
    """Return (handle, device path) for each Raw Input keyboard device."""
    count = wintypes.UINT(0)
    if (
        user32.GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
        == wintypes.UINT(-1).value
    ):
        return []

    devices_array = (RAWINPUTDEVICELIST * count.value)()
    got = user32.GetRawInputDeviceList(
        devices_array,
        ctypes.byref(count),
        ctypes.sizeof(RAWINPUTDEVICELIST),
    )
    if got == wintypes.UINT(-1).value:
        return []

    out: list[tuple[wintypes.HANDLE, str]] = []
    for entry in devices_array[: count.value]:
        if entry.dwType != RIM_TYPEKEYBOARD:
            continue
        name = _device_name(entry.hDevice)
        if name:
            out.append((entry.hDevice, name))
    return out


def resolve_target_device(
    spec: str,
    *,
    allow_auto: bool = True,
) -> tuple[wintypes.HANDLE | None, str | None, bool]:
    """
    Resolve a Raw Input keyboard handle from RFID_DEVICE.

    Returns (handle, name, accept_null_hdevice). The third flag is set when we
    auto-selected the only external USB HID keyboard — some readers report a
    NULL hDevice in WM_INPUT, so we accept those only in that narrow case.
    """
    keyboards = list_keyboard_devices()
    if not keyboards:
        return None, None, False

    matcher = device_name_matcher(spec)
    for handle, name in keyboards:
        if matcher(name):
            return handle, name, False

    if not allow_auto:
        return None, None, False

    for token in preferred_match_tokens(spec):
        upper = token.upper()
        for handle, name in keyboards:
            if upper in name.upper():
                logger.info(
                    "RFID auto-selected device matching %r: %s",
                    token,
                    name,
                )
                return handle, name, False

    external = [(handle, name) for handle, name in keyboards if not _is_internal_keyboard(name)]
    usb_hid = [(handle, name) for handle, name in external if _is_usb_hid_keyboard(name)]
    if len(usb_hid) == 1:
        logger.info("RFID auto-selected sole external USB HID keyboard: %s", usb_hid[0][1])
        return usb_hid[0][0], usb_hid[0][1], True
    if len(external) == 1:
        logger.info("RFID auto-selected sole external keyboard: %s", external[0][1])
        return external[0][0], external[0][1], True

    return None, None, False


class WindowsRfidListener:
    """
    Windows RFID listener using Raw Input on a dedicated keyboard HID device.

    Matches Pi/evdev behavior: only the configured reader contributes scans;
    the main keyboard is ignored.
    """

    backend_name = "windows-raw-input"

    def __init__(self, device_spec: str, on_submit_buffer: DigitHandler) -> None:
        self._device_spec = device_spec
        self._scan = ScanBuffer(on_submit_buffer)
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._stop = threading.Event()
        self._target_handle: wintypes.HANDLE | None = None
        self._target_name: str | None = None
        self._accept_null_hdevice = False
        self._hwnd: wintypes.HWND | None = None
        self._wnd_proc_ref: WNDPROC | None = None
        self._ready = threading.Event()
        self._started_ok = False

    def start(self) -> bool:
        self._stop.clear()
        self._ready.clear()
        self._started_ok = False
        self._thread = threading.Thread(
            target=self._run,
            name="rfid-raw-input",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            logger.warning("RFID listener timed out while starting.")
            return False
        return self._started_ok

    def stop(self) -> None:
        self._stop.set()
        thread_id = self._thread_id
        if thread_id is not None:
            user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None
        self._hwnd = None

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()

        handle, name, accept_null = resolve_target_device(self._device_spec)
        if handle is None or name is None:
            logger.warning(
                "RFID device not found for spec %r. Available Raw Input keyboards:",
                self._device_spec,
            )
            for _handle, dev_name in list_keyboard_devices():
                logger.warning("  - %s", dev_name)
            logger.warning(
                "Set RFID_DEVICE to a substring of the device path or VID_xxxx&PID_yyyy."
            )
            self._started_ok = False
            self._ready.set()
            return

        self._target_handle = handle
        self._target_name = name
        self._accept_null_hdevice = accept_null
        if accept_null:
            logger.info(
                "RFID reader may report NULL hDevice — accepting unqualified keyboard input "
                "(player station should use the reader only, not the main keyboard)."
            )

        if not self._create_message_window():
            logger.warning("Failed to create hidden window for Raw Input RFID listener.")
            self._started_ok = False
            self._ready.set()
            return

        if not self._register_raw_input():
            logger.warning("RegisterRawInputDevices failed for RFID listener.")
            self._started_ok = False
            self._ready.set()
            return

        logger.info("RFID Raw Input listener bound to %s", name)
        self._started_ok = True
        self._ready.set()

        msg = wintypes.MSG()
        while not self._stop.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0 or result == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _create_message_window(self) -> bool:
        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                self._on_raw_input(lparam)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(
                hwnd,
                msg,
                wparam,
                wintypes.LPARAM(lparam),
            )

        self._wnd_proc_ref = wnd_proc

        class_name = "KnottyBytesEscapeRoomRfidRawInput"
        hinstance = kernel32.GetModuleHandleW(None)

        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wnd_proc_ref
        wc.hInstance = hinstance
        wc.lpszClassName = class_name

        atom = user32.RegisterClassW(ctypes.byref(wc))
        if atom == 0 and kernel32.GetLastError() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            return False

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "EscapeRoomRfid",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            return False

        user32.ShowWindow(hwnd, SW_HIDE)

        self._hwnd = hwnd
        return True

    def _register_raw_input(self) -> bool:
        assert self._hwnd is not None
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01
        rid.usUsage = 0x06
        rid.dwFlags = RIDEV_INPUTSINK
        rid.hwndTarget = self._hwnd
        return bool(
            user32.RegisterRawInputDevices(
                ctypes.byref(rid),
                1,
                ctypes.sizeof(rid),
            )
        )

    def _input_from_target(self, h_device: wintypes.HANDLE | None) -> bool:
        device_id = 0
        try:
            device_id = int(h_device or 0)
        except (TypeError, ValueError):
            device_id = 0
        if device_id == 0:
            return self._accept_null_hdevice
        if self._target_handle is None:
            return False
        try:
            if device_id == int(self._target_handle):
                return True
        except (TypeError, ValueError):
            return False
        if not self._target_name:
            return False
        name = _device_name(h_device)
        return name == self._target_name

    def _on_raw_input(self, lparam: wintypes.LPARAM) -> None:
        if self._target_handle is None:
            return

        size = wintypes.UINT(0)
        user32.GetRawInputData(
            wintypes.LPARAM(lparam),
            RID_INPUT,
            None,
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if size.value <= 0:
            return

        buf = ctypes.create_string_buffer(size.value)
        got = user32.GetRawInputData(
            wintypes.LPARAM(lparam),
            RID_INPUT,
            buf,
            ctypes.byref(size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if got == wintypes.UINT(-1).value or got <= 0:
            return

        raw = RAWINPUT.from_buffer(buf)
        if raw.header.dwType != RIM_TYPEKEYBOARD:
            return

        kb = raw.data.keyboard
        if kb.Flags & RI_KEY_BREAK:
            return

        matched = self._input_from_target(raw.header.hDevice)
        if RFID_DEBUG:
            logger.info(
                "RFID raw key vkey=%#x hDevice=%s matched=%s",
                kb.VKey,
                int(raw.header.hDevice or 0),
                matched,
            )
        if not matched:
            return

        digit = _vkey_to_digit(kb.VKey)
        if digit is not None:
            self._scan.feed_digit(digit)
            return
        if kb.VKey in (VK_RETURN, 0x0A):  # Enter / line feed
            self._scan.feed_enter()
