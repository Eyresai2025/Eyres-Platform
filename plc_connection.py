# plc_connection.py
"""Common PLC connection / read adapter layer for the EYRES PLC monitor.

The module keeps the original ``check_plc_and_get_active`` helper API while
adding a production-friendly adapter interface used by ``PLC_GUI.py``.

Supported runtime adapters:
    - Allen-Bradley / Rockwell Logix  -> pylogix
    - Siemens S7                      -> python-snap7
    - Delta / Schneider / Keyence /
      Generic Modbus TCP              -> pymodbus
    - Mitsubishi MC Protocol          -> pymcprotocol
    - Omron FINS                      -> connection check only in this generic layer

Notes:
    * Allen-Bradley can browse controller tags using pylogix GetTagList().
    * Siemens / Modbus / Mitsubishi normally do not expose a generic symbolic
      tag browser through these protocol libraries. The UI therefore supports
      manual PLC addresses for these drivers.
    * Omron is exposed for connection validation, but generic FINS memory reads
      are deliberately not guessed here because the memory-area/address mapping
      is machine-project specific.
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Public profiles used by the GUI
# ---------------------------------------------------------------------------
PLC_PROFILES: Dict[str, Dict[str, Any]] = {
    "Allen-Bradley": {
        "protocol": "EtherNet/IP (CIP)",
        "default_port": 44818,
        "uses_slot": True,
        "uses_rack": False,
        "uses_unit_id": False,
        "supports_tag_browse": True,
        "supports_read": True,
        "supports_symbolic_tags": True,
        "address_help": "Controller symbolic tags are discovered automatically.",
    },
    "Siemens": {
        "protocol": "S7 TCP",
        "default_port": 102,
        "uses_slot": True,
        "uses_rack": True,
        "uses_unit_id": False,
        "supports_tag_browse": False,
        "supports_read": True,
        "supports_symbolic_tags": False,
        "address_help": "Use S7 addresses such as DB1.DBX0.0, DB1.DBW2, DB1.DBD4 or DB1.REAL8.",
    },
    "Delta": {
        "protocol": "Modbus TCP",
        "default_port": 502,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": True,
        "supports_tag_browse": False,
        "supports_read": True,
        "supports_symbolic_tags": False,
        "address_help": "Use Modbus addresses such as HR:0, IR:0, COIL:0 or DI:0.",
    },
    "Schneider": {
        "protocol": "Modbus TCP",
        "default_port": 502,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": True,
        "supports_tag_browse": False,
        "supports_read": True,
        "supports_symbolic_tags": False,
        "address_help": "Use Modbus addresses such as HR:0, IR:0, COIL:0 or DI:0.",
    },
    "Keyence": {
        "protocol": "Modbus TCP",
        "default_port": 502,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": True,
        "supports_tag_browse": False,
        "supports_read": True,
        "supports_symbolic_tags": False,
        "address_help": "Use Modbus addresses such as HR:0, IR:0, COIL:0 or DI:0.",
    },
    "Generic Modbus TCP": {
        "protocol": "Modbus TCP",
        "default_port": 502,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": True,
        "supports_tag_browse": False,
        "supports_read": True,
        "supports_symbolic_tags": False,
        "address_help": "Use Modbus addresses such as HR:0, IR:0, COIL:0 or DI:0.",
    },
    "Mitsubishi": {
        "protocol": "MC Protocol",
        "default_port": 5007,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": False,
        "supports_tag_browse": False,
        "supports_read": True,
        "supports_symbolic_tags": False,
        "address_help": "Use Mitsubishi device addresses such as D100, M0, X0 or Y0.",
    },
    "Omron": {
        "protocol": "FINS UDP",
        "default_port": 9600,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": False,
        "supports_tag_browse": False,
        "supports_read": False,
        "supports_symbolic_tags": False,
        "address_help": "Connection validation is supported. Generic FINS memory mapping must be configured per PLC project before reading.",
    },
    "Simulation": {
        "protocol": "Simulation",
        "default_port": 0,
        "uses_slot": False,
        "uses_rack": False,
        "uses_unit_id": False,
        "supports_tag_browse": True,
        "supports_read": True,
        "supports_symbolic_tags": True,
        "address_help": "No physical PLC is required. Generated tags and values are used.",
    },
}


def get_supported_plc_profiles() -> Dict[str, Dict[str, Any]]:
    """Return a copy so GUI code cannot mutate the module constants."""
    return {name: dict(values) for name, values in PLC_PROFILES.items()}


# ---------------------------------------------------------------------------
# Common result / exceptions
# ---------------------------------------------------------------------------
class PLCAdapterError(RuntimeError):
    pass


class PLCCapabilityError(PLCAdapterError):
    pass


@dataclass
class PLCReadResult:
    TagName: str
    Value: Any = None
    Status: str = "Success"


class PLCAdapter:
    brand = "Generic"
    protocol = "Unknown"
    supports_tag_browse = False
    supports_read = True
    supports_symbolic_tags = False

    def __init__(self, config: Dict[str, Any]):
        self.config = dict(config or {})
        self.ip = str(self.config.get("ip_address") or "").strip()
        self.slot = int(self.config.get("slot") or 0)
        self.rack = int(self.config.get("rack") or 0)
        self.port = int(self.config.get("port") or 0)
        self.unit_id = int(self.config.get("unit_id") or 1)
        self.connected = False

    def connect(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def disconnect(self) -> None:
        self.connected = False

    def get_all_tags(self) -> List[str]:
        raise PLCCapabilityError(
            f"Automatic tag discovery is not supported for {self.brand} / {self.protocol}."
        )

    def read_one(self, tag: str) -> PLCReadResult:
        raise NotImplementedError

    def read_many(self, tags: Iterable[str]) -> List[PLCReadResult]:
        return [self.read_one(t) for t in tags]


# ---------------------------------------------------------------------------
# Allen-Bradley / Rockwell - pylogix
# ---------------------------------------------------------------------------
class AllenBradleyAdapter(PLCAdapter):
    brand = "Allen-Bradley"
    protocol = "EtherNet/IP (CIP)"
    supports_tag_browse = True
    supports_read = True
    supports_symbolic_tags = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._plc = None

    def connect(self) -> Tuple[bool, str]:
        if not self.ip:
            return False, "IP address is required."
        try:
            from pylogix import PLC
        except Exception as e:
            return False, f"pylogix is not installed/available: {e}"

        try:
            self._plc = PLC()
            self._plc.IPAddress = self.ip
            self._plc.ProcessorSlot = self.slot
            result = self._plc.GetPLCTime()
            ok = str(getattr(result, "Status", "")) == "Success"
            self.connected = ok
            if ok:
                return True, f"Connected to Allen-Bradley PLC at {self.ip} (slot {self.slot})."
            return False, f"Allen-Bradley connection failed: {getattr(result, 'Status', 'Unknown status')}"
        except Exception as e:
            self.connected = False
            return False, f"Allen-Bradley connection failed: {e}"

    def disconnect(self) -> None:
        try:
            if self._plc is not None and hasattr(self._plc, "Close"):
                self._plc.Close()
        except Exception:
            pass
        self._plc = None
        self.connected = False

    def get_all_tags(self) -> List[str]:
        if not self._plc or not self.connected:
            raise PLCAdapterError("Allen-Bradley PLC is not connected.")
        result = self._plc.GetTagList()
        if str(getattr(result, "Status", "")) != "Success":
            raise PLCAdapterError(f"GetTagList failed: {getattr(result, 'Status', 'Unknown status')}")
        return [str(tag.TagName) for tag in (getattr(result, "Value", None) or []) if getattr(tag, "TagName", None)]

    @staticmethod
    def _normalise_result(result: Any, fallback_tag: str) -> PLCReadResult:
        return PLCReadResult(
            TagName=str(getattr(result, "TagName", None) or fallback_tag),
            Value=getattr(result, "Value", None),
            Status=str(getattr(result, "Status", "Error")),
        )

    def read_one(self, tag: str) -> PLCReadResult:
        if not self._plc or not self.connected:
            return PLCReadResult(tag, None, "NotConnected")
        try:
            return self._normalise_result(self._plc.Read(tag), tag)
        except Exception as e:
            return PLCReadResult(tag, None, f"Error:{type(e).__name__}")

    def read_many(self, tags: Iterable[str]) -> List[PLCReadResult]:
        tags = list(tags)
        if not self._plc or not self.connected:
            return [PLCReadResult(t, None, "NotConnected") for t in tags]
        if not tags:
            return []
        try:
            raw = self._plc.Read(tags)
            if not isinstance(raw, list):
                raw = [raw]
            out: List[PLCReadResult] = []
            for i, result in enumerate(raw):
                fallback = tags[i] if i < len(tags) else ""
                out.append(self._normalise_result(result, fallback))
            return out
        except Exception:
            return [self.read_one(t) for t in tags]


# ---------------------------------------------------------------------------
# Siemens S7 - python-snap7
# ---------------------------------------------------------------------------
class SiemensS7Adapter(PLCAdapter):
    brand = "Siemens"
    protocol = "S7 TCP"
    supports_tag_browse = False
    supports_read = True
    supports_symbolic_tags = False

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.port = self.port or 102
        self._client = None
        self._snap7 = None

    def connect(self) -> Tuple[bool, str]:
        if not self.ip:
            return False, "IP address is required."
        try:
            import snap7
            self._snap7 = snap7
            self._client = snap7.client.Client()
            try:
                self._client.connect(self.ip, self.rack, self.slot, self.port)
            except TypeError:
                self._client.connect(self.ip, self.rack, self.slot)
            ok = bool(self._client.get_connected())
            self.connected = ok
            if ok:
                return True, f"Connected to Siemens S7 at {self.ip} (rack {self.rack}, slot {self.slot})."
            return False, "Siemens S7 client did not report a connected state."
        except Exception as e:
            self.connected = False
            return False, f"Siemens S7 connection failed: {e}"

    def disconnect(self) -> None:
        try:
            if self._client is not None:
                self._client.disconnect()
        except Exception:
            pass
        self._client = None
        self.connected = False

    @staticmethod
    def _decode_word(data: bytes, dtype: str) -> Any:
        dtype = dtype.upper()
        if dtype in ("BYTE", "UBYTE"):
            return data[0]
        if dtype in ("INT", "INT16"):
            return struct.unpack(">h", bytes(data[:2]))[0]
        if dtype in ("UINT", "UINT16", "WORD"):
            return struct.unpack(">H", bytes(data[:2]))[0]
        if dtype in ("DINT", "INT32"):
            return struct.unpack(">i", bytes(data[:4]))[0]
        if dtype in ("UDINT", "UINT32", "DWORD"):
            return struct.unpack(">I", bytes(data[:4]))[0]
        if dtype in ("REAL", "FLOAT", "FLOAT32"):
            return struct.unpack(">f", bytes(data[:4]))[0]
        raise PLCAdapterError(f"Unsupported S7 data type: {dtype}")

    @staticmethod
    def _area_enum(snap7_module: Any, code: str) -> Any:
        try:
            from snap7.type import Areas as AreaEnum
        except Exception:
            try:
                from snap7.type import Area as AreaEnum
            except Exception as e:
                raise PLCAdapterError(f"Could not resolve snap7 memory-area enum: {e}")

        code = code.upper()
        candidates = {
            "M": ("MK", "M"),
            "I": ("PE", "I"),
            "Q": ("PA", "Q"),
        }[code]
        for name in candidates:
            if hasattr(AreaEnum, name):
                return getattr(AreaEnum, name)
        raise PLCAdapterError(f"snap7 does not expose the {code} memory area in this version.")

    def _read_non_db(self, area_code: str, byte_index: int, size: int) -> bytes:
        if self._client is None:
            raise PLCAdapterError("Siemens PLC is not connected.")
        area = self._area_enum(self._snap7, area_code)
        return bytes(self._client.read_area(area, 0, byte_index, size))

    def read_one(self, tag: str) -> PLCReadResult:
        if not self.connected or self._client is None:
            return PLCReadResult(tag, None, "NotConnected")

        raw = str(tag).strip().upper().replace(" ", "")
        try:
            # DB1.DBX0.0
            import re
            m = re.fullmatch(r"DB(\d+)\.DBX(\d+)\.(\d+)", raw)
            if m:
                db, byte_idx, bit_idx = map(int, m.groups())
                data = bytes(self._client.db_read(db, byte_idx, 1))
                value = bool((data[0] >> bit_idx) & 1)
                return PLCReadResult(tag, value, "Success")

            # DB1.DBB0 / DB1.DBW2 / DB1.DBD4 / DB1.REAL8
            m = re.fullmatch(r"DB(\d+)\.(DBB|DBW|DBD|REAL)(\d+)", raw)
            if m:
                db = int(m.group(1))
                kind = m.group(2)
                start = int(m.group(3))
                dtype, size = {
                    "DBB": ("BYTE", 1),
                    "DBW": ("INT16", 2),
                    "DBD": ("INT32", 4),
                    "REAL": ("REAL", 4),
                }[kind]
                data = bytes(self._client.db_read(db, start, size))
                return PLCReadResult(tag, self._decode_word(data, dtype), "Success")

            # M0.0 / I0.0 / Q0.0
            m = re.fullmatch(r"([MIQ])(\d+)\.(\d+)", raw)
            if m:
                area_code, byte_s, bit_s = m.groups()
                data = self._read_non_db(area_code, int(byte_s), 1)
                value = bool((data[0] >> int(bit_s)) & 1)
                return PLCReadResult(tag, value, "Success")

            # MB0/MW0/MD0, IB/IW/ID, QB/QW/QD
            m = re.fullmatch(r"([MIQ])([BWD])(\d+)", raw)
            if m:
                area_code, width, start_s = m.groups()
                dtype, size = {
                    "B": ("BYTE", 1),
                    "W": ("INT16", 2),
                    "D": ("INT32", 4),
                }[width]
                data = self._read_non_db(area_code, int(start_s), size)
                return PLCReadResult(tag, self._decode_word(data, dtype), "Success")

            return PLCReadResult(tag, None, "InvalidAddress")
        except Exception as e:
            return PLCReadResult(tag, None, f"Error:{type(e).__name__}:{e}")


# ---------------------------------------------------------------------------
# Modbus TCP - pymodbus
# ---------------------------------------------------------------------------
class ModbusTCPAdapter(PLCAdapter):
    protocol = "Modbus TCP"
    supports_tag_browse = False
    supports_read = True
    supports_symbolic_tags = False

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.brand = str(config.get("plc_brand") or "Generic Modbus TCP")
        self.port = self.port or 502
        self._client = None

    def connect(self) -> Tuple[bool, str]:
        if not self.ip:
            return False, "IP address is required."
        try:
            from pymodbus.client import ModbusTcpClient
            self._client = ModbusTcpClient(self.ip, port=self.port, timeout=float(self.config.get("timeout", 2.5)))
            ok = bool(self._client.connect())
            self.connected = ok
            if ok:
                return True, f"Connected to {self.brand} using Modbus TCP at {self.ip}:{self.port}."
            return False, f"Modbus TCP connection to {self.ip}:{self.port} failed."
        except Exception as e:
            self.connected = False
            return False, f"Modbus TCP connection failed: {e}"

    def disconnect(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None
        self.connected = False

    def _call_read(self, method_name: str, address: int, count: int):
        method = getattr(self._client, method_name)
        # pymodbus changed the unit-id keyword across versions.
        for kwargs in (
            {"address": address, "count": count, "slave": self.unit_id},
            {"address": address, "count": count, "unit": self.unit_id},
            {"address": address, "count": count, "device_id": self.unit_id},
            {"address": address, "count": count},
        ):
            try:
                return method(**kwargs)
            except TypeError:
                continue
        return method(address, count)

    @staticmethod
    def _normalise_address(area: str, address: int) -> int:
        # Accept common 5-digit reference notation in addition to 0-based offsets.
        if area == "HR" and address >= 40001:
            return address - 40001
        if area == "IR" and address >= 30001:
            return address - 30001
        if area == "DI" and address >= 10001:
            return address - 10001
        if area == "COIL" and address >= 1_0001:  # 00001 style once parsed as int
            return address - 1
        return address

    @staticmethod
    def _parse_tag(tag: str) -> Tuple[str, int, str]:
        parts = [p.strip().upper() for p in str(tag).split(":") if p.strip()]
        if len(parts) < 2:
            raise PLCAdapterError("Use Modbus address syntax AREA:ADDRESS[:TYPE], e.g. HR:0 or HR:0:FLOAT32")
        area_alias = {
            "HR": "HR", "4X": "HR", "HOLDING": "HR",
            "IR": "IR", "3X": "IR", "INPUT": "IR",
            "COIL": "COIL", "C": "COIL", "0X": "COIL",
            "DI": "DI", "DISCRETE": "DI", "1X": "DI",
        }
        if parts[0] not in area_alias:
            raise PLCAdapterError(f"Unknown Modbus area '{parts[0]}'.")
        area = area_alias[parts[0]]
        address = int(parts[1], 0)
        dtype = parts[2] if len(parts) >= 3 else ("BOOL" if area in ("COIL", "DI") else "UINT16")
        return area, ModbusTCPAdapter._normalise_address(area, address), dtype

    @staticmethod
    def _decode_registers(registers: List[int], dtype: str) -> Any:
        dtype = dtype.upper()
        if dtype in ("UINT16", "WORD"):
            return int(registers[0]) & 0xFFFF
        if dtype in ("INT16", "INT"):
            return struct.unpack(">h", struct.pack(">H", int(registers[0]) & 0xFFFF))[0]
        if len(registers) < 2:
            raise PLCAdapterError(f"{dtype} requires two Modbus registers.")
        raw = struct.pack(">HH", int(registers[0]) & 0xFFFF, int(registers[1]) & 0xFFFF)
        if dtype in ("UINT32", "DWORD"):
            return struct.unpack(">I", raw)[0]
        if dtype in ("INT32", "DINT"):
            return struct.unpack(">i", raw)[0]
        if dtype in ("FLOAT32", "FLOAT", "REAL"):
            return struct.unpack(">f", raw)[0]
        raise PLCAdapterError(f"Unsupported Modbus data type '{dtype}'.")

    def read_one(self, tag: str) -> PLCReadResult:
        if not self.connected or self._client is None:
            return PLCReadResult(tag, None, "NotConnected")
        try:
            area, address, dtype = self._parse_tag(tag)
            count = 2 if dtype.upper() in ("UINT32", "DWORD", "INT32", "DINT", "FLOAT32", "FLOAT", "REAL") else 1
            if area == "HR":
                response = self._call_read("read_holding_registers", address, count)
            elif area == "IR":
                response = self._call_read("read_input_registers", address, count)
            elif area == "COIL":
                response = self._call_read("read_coils", address, 1)
            else:
                response = self._call_read("read_discrete_inputs", address, 1)

            if response is None or (hasattr(response, "isError") and response.isError()):
                return PLCReadResult(tag, None, "ReadError")

            if area in ("COIL", "DI"):
                bits = getattr(response, "bits", None) or []
                if not bits:
                    return PLCReadResult(tag, None, "NoData")
                return PLCReadResult(tag, bool(bits[0]), "Success")

            regs = list(getattr(response, "registers", None) or [])
            if not regs:
                return PLCReadResult(tag, None, "NoData")
            return PLCReadResult(tag, self._decode_registers(regs, dtype), "Success")
        except Exception as e:
            return PLCReadResult(tag, None, f"Error:{type(e).__name__}:{e}")


# ---------------------------------------------------------------------------
# Mitsubishi MC Protocol - pymcprotocol
# ---------------------------------------------------------------------------
class MitsubishiMCAdapter(PLCAdapter):
    brand = "Mitsubishi"
    protocol = "MC Protocol"
    supports_tag_browse = False
    supports_read = True
    supports_symbolic_tags = False

    BIT_PREFIXES = ("M", "X", "Y", "L", "F", "B")

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.port = self.port or 5007
        self._client = None

    def connect(self) -> Tuple[bool, str]:
        if not self.ip:
            return False, "IP address is required."
        try:
            import pymcprotocol
            self._client = pymcprotocol.Type3E()
            self._client.connect(self.ip, self.port)
            self.connected = True
            return True, f"Connected to Mitsubishi PLC using MC Protocol at {self.ip}:{self.port}."
        except Exception as e:
            self.connected = False
            return False, f"Mitsubishi MC Protocol connection failed: {e}"

    def disconnect(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:
            pass
        self._client = None
        self.connected = False

    def read_one(self, tag: str) -> PLCReadResult:
        if not self.connected or self._client is None:
            return PLCReadResult(tag, None, "NotConnected")
        address = str(tag).strip().upper()
        if not address:
            return PLCReadResult(tag, None, "InvalidAddress")
        try:
            if address.startswith(self.BIT_PREFIXES):
                values = self._client.batchread_bitunits(headdevice=address, readsize=1)
            else:
                values = self._client.batchread_wordunits(headdevice=address, readsize=1)
            value = values[0] if isinstance(values, (list, tuple)) else values
            return PLCReadResult(tag, value, "Success")
        except Exception as e:
            return PLCReadResult(tag, None, f"Error:{type(e).__name__}:{e}")


# ---------------------------------------------------------------------------
# Omron FINS - connectivity only in this generic adapter
# ---------------------------------------------------------------------------
class OmronFINSAdapter(PLCAdapter):
    brand = "Omron"
    protocol = "FINS UDP"
    supports_tag_browse = False
    supports_read = False
    supports_symbolic_tags = False

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.port = self.port or 9600
        self._conn = None

    def connect(self) -> Tuple[bool, str]:
        if not self.ip:
            return False, "IP address is required."
        try:
            from fins.udp import UDPFinsConnection
            self._conn = UDPFinsConnection()
            self._conn.connect(self.ip)
            self._conn.dest_node_add = int(self.config.get("dest_node", 1))
            self._conn.srce_node_add = int(self.config.get("source_node", 25))
            self.connected = True
            return True, f"Connected to Omron PLC using FINS at {self.ip}."
        except Exception as e:
            self.connected = False
            return False, f"Omron FINS connection failed: {e}"

    def disconnect(self) -> None:
        try:
            if self._conn is not None and hasattr(self._conn, "close"):
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        self.connected = False

    def read_one(self, tag: str) -> PLCReadResult:
        return PLCReadResult(tag, None, "UnsupportedGenericFINSRead")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_plc_adapter(config: Dict[str, Any]) -> PLCAdapter:
    brand = str(config.get("plc_brand") or "Allen-Bradley").strip()
    protocol = str(config.get("plc_protocol") or "").strip().lower()
    b = brand.lower()

    if brand == "Simulation" or protocol == "simulation":
        raise PLCCapabilityError("Simulation is handled by the PLC worker, not a physical adapter.")
    if "allen" in b or "rockwell" in b or "ethernet/ip" in protocol or "cip" in protocol:
        return AllenBradleyAdapter(config)
    if "siemens" in b or "s7" in protocol:
        return SiemensS7Adapter(config)
    if brand in ("Delta", "Schneider", "Keyence", "Generic Modbus TCP") or "modbus" in protocol:
        return ModbusTCPAdapter(config)
    if "mitsubishi" in b or "mc protocol" in protocol:
        return MitsubishiMCAdapter(config)
    if "omron" in b or "fins" in protocol:
        return OmronFINSAdapter(config)
    raise PLCAdapterError(f"Unsupported PLC brand/protocol: {brand} / {config.get('plc_protocol', '')}")


# ---------------------------------------------------------------------------
# Backward-compatible connectivity helper
# ---------------------------------------------------------------------------
def _tcp_ping(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def check_plc_and_get_active(
    machine_or_brand,
    protocol: Optional[str] = None,
    ip: Optional[str] = None,
    slot: Optional[int] = None,
    timeout: float = 2.5,
) -> Tuple[bool, str]:
    """Preserve the original public helper API used elsewhere in EYRES."""
    if isinstance(machine_or_brand, dict):
        config = dict(machine_or_brand)
        brand = config.get("plc_brand")
        protocol = config.get("plc_protocol")
        ip = config.get("ip_address")
        slot = config.get("slot")
    else:
        brand = machine_or_brand
        config = {
            "plc_brand": brand,
            "plc_protocol": protocol,
            "ip_address": ip,
            "slot": slot,
        }

    if not ip and str(brand or "") != "Simulation":
        return False, "IP missing."

    profile = PLC_PROFILES.get(str(brand), {})
    config.setdefault("port", profile.get("default_port", 0))
    config.setdefault("rack", 0)
    config.setdefault("unit_id", 1)
    config.setdefault("timeout", timeout)

    if str(brand) == "Simulation":
        return True, "Simulation mode selected."

    try:
        adapter = create_plc_adapter(config)
        ok, message = adapter.connect()
        adapter.disconnect()
        if ok:
            return True, message
    except Exception as e:
        message = str(e)

    # Keep the original pragmatic TCP reachability fallback.
    port = int(config.get("port") or profile.get("default_port") or 0)
    if port and _tcp_ping(str(ip), port, timeout=timeout):
        return True, f"TCP port {port} is reachable for {brand}; protocol driver validation failed."

    return False, message if 'message' in locals() else "PLC not reachable."


__all__ = [
    "PLCAdapterError",
    "PLCCapabilityError",
    "PLCReadResult",
    "PLCAdapter",
    "AllenBradleyAdapter",
    "SiemensS7Adapter",
    "ModbusTCPAdapter",
    "MitsubishiMCAdapter",
    "OmronFINSAdapter",
    "PLC_PROFILES",
    "get_supported_plc_profiles",
    "create_plc_adapter",
    "check_plc_and_get_active",
]
