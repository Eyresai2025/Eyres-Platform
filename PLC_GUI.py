# plc_data_monitor.py
import sys, csv, re, threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QLineEdit, QSpinBox, QGroupBox, QTextEdit, QProgressBar,
    QHeaderView, QSplitter, QFileDialog, QMessageBox, QTabWidget, QCheckBox, QScrollArea,
    QListWidget, QAbstractItemView, QStackedWidget, QFrame, QToolButton, QComboBox,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect
)
from PyQt5.QtGui import QFont, QColor, QFontDatabase
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread, QPropertyAnimation, QEasingCurve, QEvent
import pymongo
import random
from plc_connection import (
    PLCAdapterError,
    PLCCapabilityError,
    PLCReadResult,
    create_plc_adapter,
    get_supported_plc_profiles,
)



# ----------------------- PLC Worker -----------------------
class PLCWorker(QThread):
    data_received   = pyqtSignal(dict)
    status_signal   = pyqtSignal(str)
    error_signal    = pyqtSignal(str)
    tags_retrieved  = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.adapter = None
        # ``plc`` is kept as a compatibility alias for older code paths.
        self.plc = None

        self.ip_address = "192.168.1.1"
        self.slot = 0
        self.rack = 0
        self.port = 44818
        self.unit_id = 1
        self.brand = "Allen-Bradley"
        self.protocol = "EtherNet/IP (CIP)"

        self.tags_to_read: List[str] = []
        self.is_reading = False
        self.read_interval = 1000
        self.batch_size = 50

        self.simulation = False
        self.sim_counter = 0
        self.supports_tag_browse = True
        self.supports_read = True
        self.supports_symbolic_tags = True
        self.driver_message = ""

    def _fake_value_for_tag(self, tag: str, step: int):
        tl = tag.lower()
        if tl.startswith(("di_", "do_")) or tl.endswith(".x"):
            return step % 2
        base = hash(tag) % 100
        return base + (step % 10)

    def _set_simulation_capabilities(self):
        self.simulation = True
        self.adapter = None
        self.plc = None
        self.supports_tag_browse = True
        self.supports_read = True
        self.supports_symbolic_tags = True
        self.sim_counter = 0

    def connect_plc(self, config: Dict[str, object]):
        """Connect using the selected PLC brand/protocol adapter.

        Physical connection failures keep the application's existing behaviour:
        the worker falls back to simulation so the UI can still be exercised.
        """
        self.disconnect_plc(emit_status=False)

        self.brand = str(config.get("plc_brand") or "Allen-Bradley")
        self.protocol = str(config.get("plc_protocol") or "")
        self.ip_address = str(config.get("ip_address") or "").strip()
        self.slot = int(config.get("slot") or 0)
        self.rack = int(config.get("rack") or 0)
        self.port = int(config.get("port") or 0)
        self.unit_id = int(config.get("unit_id") or 1)

        if self.brand == "Simulation" or self.protocol.lower() == "simulation":
            self._set_simulation_capabilities()
            self.driver_message = "Simulation mode selected."
            self.status_signal.emit("Simulation PLC session ready.")
            return True

        try:
            self.adapter = create_plc_adapter(config)
            ok, message = self.adapter.connect()
            self.driver_message = message

            if ok:
                self.simulation = False
                self.plc = self.adapter
                self.supports_tag_browse = bool(getattr(self.adapter, "supports_tag_browse", False))
                self.supports_read = bool(getattr(self.adapter, "supports_read", True))
                self.supports_symbolic_tags = bool(getattr(self.adapter, "supports_symbolic_tags", False))
                self.status_signal.emit(message)
                return True

            self._set_simulation_capabilities()
            self.error_signal.emit(f"PLC connection failed: {message}")
            self.status_signal.emit(
                f"{self.brand} connection failed. Switching to SIMULATION mode (dummy PLC data)."
            )
            return False

        except Exception as e:
            self.driver_message = str(e)
            self._set_simulation_capabilities()
            self.error_signal.emit(f"PLC connection failed: {e}")
            self.status_signal.emit(
                f"{self.brand} driver error. Switching to SIMULATION mode (dummy PLC data)."
            )
            return False

    def disconnect_plc(self, emit_status: bool = True):
        self.is_reading = False
        try:
            if self.adapter is not None:
                self.adapter.disconnect()
        except Exception:
            pass
        self.adapter = None
        self.plc = None
        self.simulation = False
        if emit_status:
            self.status_signal.emit("Disconnected from PLC")

    def get_all_tags(self):
        try:
            if self.simulation:
                fake_tags = [f"SimTag{i}" for i in range(1, 51)]
                self.tags_retrieved.emit(fake_tags)
                self.status_signal.emit(f"SIM: generated {len(fake_tags)} fake tags")
                return

            if not self.adapter:
                self.error_signal.emit("Not connected to PLC")
                return

            if not self.supports_tag_browse:
                self.tags_retrieved.emit([])
                self.status_signal.emit(
                    f"Automatic tag discovery is not supported for {self.brand}. "
                    "Use Manual address / tag entry."
                )
                return

            tags = self.adapter.get_all_tags()
            self.tags_retrieved.emit(list(tags))
            self.status_signal.emit(f"Retrieved {len(tags)} tags from {self.brand} PLC")
        except PLCCapabilityError as e:
            self.tags_retrieved.emit([])
            self.status_signal.emit(str(e))
        except Exception as e:
            self.error_signal.emit(f"Error getting tags: {e}")

    def start_reading(self, tags: List[str], interval: int, batch_size: int):
        self.tags_to_read = list(tags)
        self.read_interval = interval
        self.batch_size = max(1, int(batch_size))
        self.is_reading = True
        self.status_signal.emit(
            f"Started reading {len(tags)} tags every {interval}ms (batch={self.batch_size})"
        )

    def stop_reading(self):
        self.is_reading = False
        self.status_signal.emit("Stopped reading")

    def read_one(self, tag: str):
        try:
            if self.simulation:
                self.sim_counter += 1
                return PLCReadResult(
                    TagName=tag,
                    Value=self._fake_value_for_tag(tag, self.sim_counter),
                    Status="Success",
                )
            if not self.adapter or not self.supports_read:
                return PLCReadResult(tag, None, "Unsupported")
            return self.adapter.read_one(tag)
        except Exception as e:
            return PLCReadResult(tag, None, f"Error:{type(e).__name__}:{e}")

    def read_single_cycle(self, tags: List[str]):
        try:
            if self.simulation:
                self.sim_counter += 1
                data = {'timestamp': datetime.now(), 'values': {}}
                for t in tags:
                    data['values'][t] = self._fake_value_for_tag(t, self.sim_counter)
                self.data_received.emit(data)
                return

            if not self.adapter:
                self.error_signal.emit("Not connected to PLC")
                return

            if not self.supports_read:
                self.error_signal.emit(
                    f"Generic live reads are not enabled for {self.brand} / {self.protocol}."
                )
                return

            data = {'timestamp': datetime.now(), 'values': {}}
            bs = max(1, int(self.batch_size))
            for i in range(0, len(tags), bs):
                chunk = tags[i:i + bs]
                try:
                    results = self.adapter.read_many(chunk)
                    by_name = {str(r.TagName): r for r in results}
                    for requested in chunk:
                        r = by_name.get(requested)
                        if r is None:
                            data['values'][requested] = "Error:NoResult"
                        elif str(r.Status) == "Success":
                            data['values'][requested] = r.Value
                        else:
                            data['values'][requested] = f"Error:{r.Status}"
                except Exception as e:
                    for t in chunk:
                        data['values'][t] = f"Error:{type(e).__name__}"
            self.data_received.emit(data)
        except Exception as e:
            self.error_signal.emit(f"Read error: {e}")

    def read_sim_cycle(self, tags: List[str]):
        from random import random, randint, choice
        self.sim_counter += 1
        data = {'timestamp': datetime.now(), 'values': {}}
        for t in tags:
            tl = t.lower()
            if tl.startswith("di_") or tl.startswith("do_") or tl.endswith(".x"):
                val = choice([0, 1])
            elif tl.startswith("ai_") or "temp" in tl or "pressure" in tl or "level" in tl:
                val = round(10 + random() * 90, 2)
            else:
                val = randint(0, 100)
            data['values'][t] = val
        self.data_received.emit(data)

    def run(self):
        while True:
            if self.is_reading and self.tags_to_read:
                if self.simulation:
                    self.read_sim_cycle(self.tags_to_read)
                elif self.adapter is not None:
                    self.read_single_cycle(self.tags_to_read)
                self.msleep(self.read_interval)
            else:
                self.msleep(100)

# ----------------------- Mongo / Storage -----------------------
class MongoDBHandler:
    def __init__(self, connection_string: str = "mongodb://localhost:27017/"):
        self.connection_string = connection_string
        self.client = None
        self.db = None
        self.collection = None

    def connect(self, db_name: str = "plc_data", collection_name: str = "readings"):
        try:
            self.client = pymongo.MongoClient(self.connection_string)
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            return True
        except Exception as e:
            print(f"MongoDB connection error: {e}")
            return False

    def insert_data(self, data: Dict):
        try:
            if self.collection:
                d = data.copy()
                d['timestamp'] = data['timestamp'].isoformat()
                self.collection.insert_one(d)
                return True
        except Exception as e:
            print(f"MongoDB insert error: {e}")
            return False

    def close(self):
        if self.client:
            self.client.close()


class DataStorage:
    def __init__(self):
        self.csv_file = None
        self.csv_writer = None
        self.mongo_handler = None
        self.use_csv = True
        self.use_mongo = False
        self.current_display_tags: List[str] = []  # display headers
        self.display_to_plc: Dict[str, Optional[str]] = {}

    def setup_csv(self, filename: str):
        try:
            self.csv_file = open(filename, 'w', newline='', encoding='utf-8')
            self.csv_writer = csv.writer(self.csv_file, quoting=csv.QUOTE_ALL, escapechar='\\')
            return True
        except Exception as e:
            print(f"CSV setup error: {e}")
            return False

    def setup_mongo(self, connection_string: str, db_name: str, collection_name: str):
        self.mongo_handler = MongoDBHandler(connection_string)
        return self.mongo_handler.connect(db_name, collection_name)

    def write_headers(self):
        if self.csv_writer and self.csv_file:
            headers = ['timestamp'] + self.current_display_tags
            self.csv_writer.writerow(headers)
            self.csv_file.flush()

    def store_data(self, timestamp: datetime, values_by_plc: Dict[str, object]):
        if self.use_csv and self.csv_writer:
            try:
                row = [timestamp.isoformat()]
                for disp in self.current_display_tags:
                    plc = self.display_to_plc.get(disp)
                    val = '' if plc is None else values_by_plc.get(plc, '')
                    row.append(self._clean_for_csv(val))
                self.csv_writer.writerow(row)
                self.csv_file.flush()
            except Exception as e:
                print(f"CSV write error: {e}")

        if self.use_mongo and self.mongo_handler:
            try:
                doc = {'timestamp': timestamp.isoformat()}
                for disp in self.current_display_tags:
                    plc = self.display_to_plc.get(disp)
                    doc[disp] = None if plc is None else values_by_plc.get(plc, None)
                self.mongo_handler.insert_data(doc)
            except Exception as e:
                print(f"MongoDB insert error: {e}")

    def _clean_for_csv(self, value):
        if value is None:
            return ''
        if isinstance(value, bytes):
            try:
                try: return value.decode('utf-8', errors='ignore').strip()
                except: return value.hex()
            except:
                return 'BINARY_DATA'
        try:
            s = str(value)
            repl = {',': ';','"': "'",'\n': ' ','\r': ' ','\t':' ','\0':'','\\':'/'}
            for a,b in repl.items(): s = s.replace(a,b)
            if len(s) > 1000: s = s[:1000] + "...(truncated)"
            return s
        except Exception:
            return f"ERROR:{type(value).__name__}"

    def close(self):
        if self.csv_file:
            try:
                self.csv_file.close()
            except Exception:
                pass
        self.csv_file = None
        self.csv_writer = None
        if self.mongo_handler:
            try:
                self.mongo_handler.close()
            except Exception:
                pass
        self.mongo_handler = None


# ----------------------- Main Window -----------------------
class ModernPLCWindow(QMainWindow):
    connection_result = pyqtSignal(bool, bool, str)

    def __init__(self):
        super().__init__()
        self.plc_worker = PLCWorker()
        self.plc_profiles = get_supported_plc_profiles()
        self.data_storage = DataStorage()
        self.cached_all_tags = [] 

        # UI state
        self.available_tags: List[str] = []               # from PLC
        self.display_tags: List[str] = []                 # what you asked for (headers)
        self.display_to_plc: Dict[str, Optional[str]] = {}# display -> real plc name or None
        self.read_tags: List[str] = []                    # dedup list actually read
        self.is_connected = False
        self.is_reading = False
        self.is_paused = False
        self.records_count = 0
        self.current_step = 1
        self.csv_directory: Optional[Path] = None
        self.current_csv_path: Optional[Path] = None
        self._fade_anim = None

        # ---- SPECIFIC TAGS (your list) ----
        # ---- SPECIFIC TAGS (full list) ----
        self.specific_tags = [
            # --------- AI ---------
            "ai_C_HydOil_LevelPV","ai_C_MainPanel_TempPV","ai_C_TBOPanel_TempPV","ai_Hydraulic_oil_Temp",
            "ai_LH_Guide_Rod1_Pos","ai_LH_Guide_Rod2_Pos","ai_LH_Humidity_Sensor","ai_LH_Jacket_Drain_TempPV",
            "ai_LH_Loader_LVDT","ai_LH_PCI_Bead_Lift","ai_LH_PCI_Green_Pressure","ai_LH_PCI_Yellow_Pressure",
            "ai_LH_Platen_Drain_Temp_PV","ai_LH_Press_IntPressurePV","ai_LH_Press_IntTempPV","ai_LH_Press_LVDT",
            "ai_LH_Press_ShapingPV","ai_LH_Pump_PressurePV","ai_LH_Rio_Box_Temp","ai_LH_SQ_PT",
            "ai_LH_TBLBox_TempPV","ai_LH_TBPLBox_TempPV","ai_LH_UnLoader_LVDT","ai_RH_Guide_Rod1_Pos",
            "ai_RH_Guide_Rod2_Pos","ai_RH_Humidity_Sensor","ai_RH_Jacket_Drain_TempPV","ai_RH_Loader_LVDT",
            "ai_RH_PCI_Bead_Lift","ai_RH_PCI_Green_Pressure","ai_RH_PCI_Yellow_Pressure","ai_RH_Platen_Drain_Temp_PV",
            "ai_RH_Press_IntPressurePV","ai_RH_Press_IntTempPV","ai_RH_Press_LVDT","ai_RH_Press_ShapingPV",
            "ai_RH_Pump_PressurePV","ai_RH_Rio_Box_Temp","ai_RH_SQ_PT","ai_RH_TBLBox_TempPV",
            "ai_RH_TBPLBox_TempPV","ai_RH_UnLoader_LVDT",
            # --------- AO ---------
            "ao_LH_BSP_Platen","ao_LH_HydPumpPressure_CV","ao_LH_Internal_HPS_CV","ao_LH_JacketHeatingSteam_CV",
            "ao_LH_Loader_UpDown_CV","ao_LH_PlatenHeatingSteam_CV","ao_LH_Platen_Bottom","ao_LH_Press_UpDown_CV",
            "ao_LH_Shaping_CV","ao_LH_TopRing_UpDown_CV","ao_LH_Unloader_UpDown_CV","ao_RH_BSP_Platen",
            "ao_RH_HydPumpPressure_CV","ao_RH_Internal_HPS_CV","ao_RH_JacketHeatingSteam_CV","ao_RH_Loader_UpDown_CV",
            "ao_RH_PlatenHeatingSteam_CV","ao_RH_Platen_Bottom","ao_RH_Press_UpDown_CV","ao_RH_Shaping_CV",
            "ao_RH_TopRing_UpDown_CV","ao_RH_Unloader_UpDown_CV",
            # --------- DI ---------
            "di_C_24DC_MCB_trip","di_C_Auto_Shaping","di_C_Auto_Vaccum","di_C_CoolingOil_Filter",
            "di_C_EStop_Enable_FB","di_C_LampAndFan_MCB_Trip","di_C_LampAndFan_RCCB_MCB_Trip","di_C_OilCoolingPump_MPCB_Trip",
            "di_C_PanelDoorSwitchOn","di_C_PhaseSequnece_and_Loss_Detector","di_C_PumpMotor_MPCB_Trip","di_C_Reset",
            "di_LH_Bayonut_Unlock_SSW","di_LH_Bayonut_lock_SSW","di_LH_BeadWidth_adj_Dec_SSW","di_LH_BeadWidth_adj_Homing",
            "di_LH_BeadWidth_adj_Inc_SSW","di_LH_BeadWidth_adj_Over_Travel","di_LH_BeadWidth_adj_Teeth_Counter",
            "di_LH_C_PressureLine_Filter","di_LH_C_ReturnLine_Filter","di_LH_Conveyor_Motor_MPCB_Trip","di_LH_Conveyor_On",
            "di_LH_CureEnable_FB","di_LH_GTH_InPosition_FB","di_LH_GTH_TyreSensor","di_LH_LoaderChuck_Close_FB",
            "di_LH_LoaderChuck_Open_FB","di_LH_LoaderChuck_Open_PS","di_LH_Loader_Enable_FB","di_LH_Loader_GT_Sensor",
            "di_LH_Loader_Inside_Press_FB","di_LH_Loader_Outside_Press_FB","di_LH_Loader_Overtravel","di_LH_Loader_Tyre_Sensing_2",
            "di_LH_LowerRing_Down_FB","di_LH_LowerRing_Up_FB","di_LH_MainInletAirOn_PS","di_LH_PCI_Auto_SSW",
            "di_LH_PCI_Bayonut_Lock","di_LH_PCI_Bayonut_Lock1_MovingPart","di_LH_PCI_Bayonut_UnLock1_MovingPart","di_LH_PCI_Bayonut_Unlock",
            "di_LH_PCI_Deflation_Green_SSW","di_LH_PCI_Deflation_Yellow_SSW","di_LH_PCI_Enable_FB","di_LH_PCI_FaultReset_PB",
            "di_LH_PCI_Inflation_Green_SSW","di_LH_PCI_Inflation_Yellow_SSW","di_LH_PCI_Manual_SSW","di_LH_PCI_RimClose_SSW",
            "di_LH_PCI_RimOpen_SSW","di_LH_PCI_Rotation_Green","di_LH_PCI_Rotation_Green_SSW","di_LH_PCI_Rotation_Yellow",
            "di_LH_PCI_Rotation_Yellow_SSW","di_LH_PCI_Tire_Detect_PHS","di_LH_PciRim_BeadWidth_adj_Motor_Trip","di_LH_Press_Auto_Mode",
            "di_LH_Press_Enable_FB","di_LH_Press_MC_Mode","di_LH_Press_Manual_Mode","di_LH_Press_Unlocked_FB1",
            "di_LH_Press_Unlocked_FB2","di_LH_RimFullup_Lock_Unlock","di_LH_Rotation_Manual_lock","di_LH_SMO_Extend_FB",
            "di_LH_SMO_Lock_FB","di_LH_SMO_Retract_FB","di_LH_SMO_Unlock_FB","di_LH_TBL24DC_MCB_Trip",
            "di_LH_UnLoader_Intermediate","di_LH_UnloaderChuck_Close_FB","di_LH_UnloaderChuck_Open_FB","di_LH_UnloaderChuck_Open_PS",
            "di_LH_Unloader_Close_Ssw","di_LH_Unloader_Down_SSW","di_LH_Unloader_Enable_FB","di_LH_Unloader_In_Ssw",
            "di_LH_Unloader_Open_SSW","di_LH_Unloader_Out_Ssw","di_LH_Unloader_PCI_In_FB","di_LH_Unloader_Pci_SSW",
            "di_LH_Unloader_PressIn_FB","di_LH_Unloader_PressOut_FB","di_LH_Unloader_Press_SSW","di_LH_Unloader_TyreSensor",
            "di_LH_Unloader_Up_SSW","di_Load_Enable","di_RH_Bayonut_Lock_SSW","di_RH_Bayonut_Unlock_SSW",
            "di_RH_BeadWidth_adj_Homing","di_RH_BeadWidth_adj_Over_travel","di_RH_BeadWidth_adj_teeth_counter","di_RH_C_PressureLine_Filter",
            "di_RH_C_ReturnLine_Filter","di_RH_Conveyor_On","di_RH_CureEnable_FB","di_RH_GTH_InPosition_FB",
            "di_RH_GTH_TyreSensor","di_RH_LoaderChuck_Close_FB","di_RH_LoaderChuck_Open_FB","di_RH_LoaderChuck_Open_PS",
            "di_RH_Loader_Enable_FB","di_RH_Loader_GT_Sensor","di_RH_Loader_Inside_Press_FB","di_RH_Loader_Outside_Press_FB",
            "di_RH_Loader_Overtravel","di_RH_Loader_Tyre_Sensing_2","di_RH_LowerRing_Down_FB","di_RH_LowerRing_Up_FB",
            "di_RH_MainInletAirOn_PS","di_RH_PCI_Auto_SSW","di_RH_PCI_Bayonut_Lock","di_RH_PCI_Bayonut_UnLock",
            "di_RH_PCI_Bayonut_Lock1_MovingPart","di_RH_PCI_Bayonut_UnLock1_MovingPart","di_RH_PCI_Deflation_Green_SSW","di_RH_PCI_Deflation_Yellow_SSW",
            "di_RH_PCI_Enable_FB","di_RH_PCI_FaultReset_PB","di_RH_PCI_Inflation_Green_SSW","di_RH_PCI_Inflation_Yellow_SSW",
            "di_RH_PCI_Manual_SSW","di_RH_PCI_RimClose_SSW","di_RH_PCI_RimFullUp_Lock_Unlock","di_RH_PCI_RimOpen_SSW",
            "di_RH_PCI_Rotation_Green","di_RH_PCI_Rotation_Green_SSW","di_RH_PCI_Rotation_Yellow","di_RH_PCI_Rotation_Yellow_SSW",
            "di_RH_PCI_Tire_Detect_PHS","di_RH_PciRim_BeadWidth_adj_Dec_SSW","di_RH_PciRim_BeadWidth_adj_Inc_SSW","di_RH_PciRim_BeadWidth_adj_Motor_Trip",
            "di_RH_Press_Auto_Mode","di_RH_Press_Enable_FB","di_RH_Press_MC_Mode","di_RH_Press_Manual_Mode",
            "di_RH_Press_Unlocked_FB1","di_RH_Press_Unlocked_FB2","di_RH_Rotation_Manual_Lock","di_RH_SMO_Extend_FB",
            "di_RH_SMO_Lock_FB","di_RH_SMO_Retract_FB","di_RH_SMO_Unlock_FB","di_RH_TBR_24DC_MCB_Trip",
            "di_RH_UnLoader_Intermediate","di_RH_UnloaderChuck_Close_FB","di_RH_UnloaderChuck_Open_FB","di_RH_UnloaderChuck_Open_PS",
            "di_RH_Unloader_Close_SSW","di_RH_Unloader_Down_SSW","di_RH_Unloader_Enable_FB","di_RH_Unloader_In_SSW",
            "di_RH_Unloader_Open_SSW","di_RH_Unloader_Out_SSW","di_RH_Unloader_PCI_In_FB","di_RH_Unloader_PCI_SSW",
            "di_RH_Unloader_PressIn_FB","di_RH_Unloader_PressOut_FB","di_RH_Unloader_Press_SSW","di_RH_Unloader_TyreSensor",
            "di_RH_Unloader_Up_SSW","di_Softstarter_Bypassed","di_Softstarter_Overload","di_Softstarter_Run",
            # --------- DO ---------
            "do_C_AC_Lamp_On","do_C_E_Stop_Lamp","do_C_OilCooling_Motor_On","do_C_Pump_ON","do_C_SoftStarter_ON",
            "do_LH_BlockOff_On","do_LH_C_CureAir_Off","do_LH_Circulation_Drain_On","do_LH_Deflation_Green","do_LH_Deflation_Yellow",
            "do_LH_Green_Tower_Lamp","do_LH_HPS_On","do_LH_Hooter_Tower_Lamp","do_LH_Internal_PS_Lamp","do_LH_LoaderChuck_Close",
            "do_LH_LoaderChuck_Open","do_LH_Loader_Down","do_LH_Loader_Press_In","do_LH_Loader_Press_Out","do_LH_Loader_Up",
            "do_LH_LowerRing_Down","do_LH_LowerRing_Up","do_LH_MD_On","do_LH_Mould_Blow_Out","do_LH_N2_Leak_Test_Valve_Off",
            "do_LH_N2_Leak_Test_Valve_On","do_LH_N2_Purging_On","do_LH_OpenVacuum_On","do_LH_PCI_Bayonut_lock","do_LH_PCI_Green_Inflation",
            "do_LH_PCI_Green_Inflation_Lamp","do_LH_PCI_Lifter_Down","do_LH_PCI_Lifter_SlowSpeed","do_LH_PCI_Lifter_UP","do_LH_PCI_Pos1Arm_In",
            "do_LH_PCI_Pos1Arm_Out","do_LH_PCI_Pos1Deflate","do_LH_PCI_Pos1TyreStripper","do_LH_PCI_Pos2Arm_In","do_LH_PCI_Pos2Arm_Out",
            "do_LH_PCI_Reset_Lamp","do_LH_PCI_Rotation_Green","do_LH_PCI_Rotation_Yellow","do_LH_PCI_Saf_Lock1","do_LH_PCI_Unloader_In",
            "do_LH_PCI_Unloader_Out","do_LH_PCI_Yellow_Inflation","do_LH_PCI_Yellow_Inflation_Lamp","do_LH_PressCV_Enable",
            "do_LH_Press_Close_Lock","do_LH_Press_Lock1","do_LH_Press_Lock2","do_LH_Red_Tower_Lamp","do_LH_Return_MD_On",
            "do_LH_SMO_Extend","do_LH_SMO_Lock","do_LH_SMO_Retract","do_LH_SMO_UnLock","do_LH_SQBooster_Enable",
            "do_LH_SQ_Disable_1","do_LH_SQ_Disable_2","do_LH_SQ_PneumaticBooster","do_LH_SQ_PumpBooster","do_LH_SQ_SlowSpeed",
            "do_LH_Shapping_On","do_LH_Squeeze_Extend","do_LH_Squeeze_Retract","do_LH_TBI_Cooler_On","do_LH_TBLCooler_On",
            "do_LH_TBPLCooler_On","do_LH_TopRing_Down","do_LH_TopRing_Slow_Speed","do_LH_TopRing_Up","do_LH_UnloaderChuck_Close",
            "do_LH_UnloaderChuck_Open","do_LH_Unloader_Down","do_LH_Unloader_SlowSpeed","do_LH_Unloader_SwingIn","do_LH_Unloader_SwingOut",
            "do_LH_Unloader_Up","do_LH_Vacuum_On","do_LH_Vent_On","do_LH_Yellow_Tower_Lamp","do_LH_loader_SlowSpeed",
            "do_Oil_Cooling_On","do_Pump_On","do_RH_BlockOff_On","do_RH_C_CureAir_Off","do_RH_C_Pump_ON",
            "do_RH_Circulation_Drain_On","do_RH_Deflation_Green","do_RH_Deflation_Yellow","do_RH_Green_Tower_Lamp","do_RH_HPS_On",
            "do_RH_Hooter_Tower_Lamp","do_RH_Internal_PS_Lamp","do_RH_LoaderChuck_Close","do_RH_LoaderChuck_Open","do_RH_Loader_Down",
            "do_RH_Loader_Press_In","do_RH_Loader_Press_Out","do_RH_Loader_SlowSpeed","do_RH_Loader_Up","do_RH_LowerRing_Down",
            "do_RH_LowerRing_Up","do_RH_MD_On","do_RH_Mould_Blow_Out","do_RH_N2_Leak_Test_Valve_Off","do_RH_N2_Leak_Test_Valve_On",
            "do_RH_N2_Purging_On","do_RH_OpenVacuum_On","do_RH_PCI_Bayonut_lock","do_RH_PCI_Green_Inflation","do_RH_PCI_Green_Inflation_Lamp",
            "do_RH_PCI_Lifter_Down","do_RH_PCI_Lifter_SlowSpeed","do_RH_PCI_Lifter_Up","do_RH_PCI_Pos1Arm_In","do_RH_PCI_Pos1Arm_Out",
            "do_RH_PCI_Pos1Deflate","do_RH_PCI_Pos1TyreStripper","do_RH_PCI_Pos2Arm_In","do_RH_PCI_Pos2Arm_Out","do_RH_PCI_Reset_Lamp",
            "do_RH_PCI_Rotation_Green","do_RH_PCI_Rotation_Yellow","do_RH_PCI_Saf_Lock1","do_RH_PCI_Unloader_In","do_RH_PCI_Unloader_Out",
            "do_RH_PCI_Yellow_Inflation","do_RH_PCI_Yellow_Inflation_Lamp","do_RH_PressCV_Enable","do_RH_Press_Close_Lock","do_RH_Press_Lock1",
            "do_RH_Press_Lock2","do_RH_Red_Tower_Lamp","do_RH_Return_MD_On","do_RH_SMO_Extend","do_RH_SMO_Lock","do_RH_SMO_Retract",
            "do_RH_SMO_UnLock","do_RH_SQBooster_Enable","do_RH_SQ_Disable_1","do_RH_SQ_Disable_2","do_RH_SQ_PneumaticBooster",
            "do_RH_SQ_PumpBooster","do_RH_SQ_SlowSpeed","do_RH_Shapping_On","do_RH_Squeeze_Extend","do_RH_Squeeze_Retract",
            "do_RH_TBI_Cooler_On","do_RH_TBLCooler_On","do_RH_TBPLCooler_On","do_RH_TopRing_Down","do_RH_TopRing_Slow_Speed",
            "do_RH_TopRing_Up","do_RH_UnloaderChuck_Close","do_RH_UnloaderChuck_Open","do_RH_Unloader_Down","do_RH_Unloader_SlowSpeed",
            "do_RH_Unloader_SwingIn","do_RH_Unloader_SwingOut","do_RH_Unloader_Up","do_RH_Vacuum_On","do_RH_Vent_On",
            "do_RH_Yellow_Tower_Lamp","do_Reset","do_S_C_ControlPower_On",

            # --------- EP1/EP2/EP3 step bits (original forms; auto-fix will resolve) ---------
            "EP1_Step[1].X","EP1_Step[2].X","EP1_Step[3].X","EP1_Step[4].X","EP1_Step[5].X",
            "EP1_Step[6].X","EP1_Step[7].X","EP1_Step[8].X","EP1_Step[9].X","EP1_Step[10].X",

            "EP2_Step[0].X","EP2_Step[1].X","EP2_Step[2].X","EP2_Step[3].X","EP2_Step[4].X",
            "EP2_Step[5].X","EP2_Step[6].X","EP2_Step[7].X","EP2_Step[8].X","EP2_Step[9].X",
            "EP2_Step[10].X","EP2_Step[11].X","EP2_Step[12].X","EP2_Step[13].X","EP2_Step[14].X",
            "EP2_Step[15].X","EP2_Step[16].X","EP2_Step[17].X","EP2_Step[18].X","EP2_Step[19].X",
            "EP2_Step[20].X",

            "EP3_Step[0].X","EP3_Step[1].X","EP3_Step[2].X","EP3_Step[3].X","EP3_Step[4].X",
            "EP3_Step[5].X","EP3_Step[6].X","EP3_Step[7].X","EP3_Step[8].X","EP3_Step[9].X",
            "EP3_Step[10].X","EP3_Step[11].X","EP3_Step[12].X","EP3_Step[13].X","EP3_Step[14].X",
            "EP3_Step[15].X","EP3_Step[16].X","EP3_Step[17].X","EP3_Step[18].X","EP3_Step[19].X",
            "EP3_Step[20].X","EP3_Step[21].X","EP3_Step[22].X","EP3_Step[23].X","EP3_Step[24].X",
            "EP3_Step[25].X","EP3_Step[26].X","EP3_Step[27].X","EP3_Step[28].X","EP3_Step[29].X",
            "EP3_Step[30].X","EP3_Step[31].X","EP3_Step[32].X","EP3_Step[33].X","EP3_Step[34].X",
            "EP3_Step[35].X","EP3_Step[36].X",

            # --------- LH group (note: underscore vs dot) ---------
            "LH.Curing.Step_No",
            "LH.Curing_Interlock_Ok",
            "LH.Initiate_Curing",
            "LH.Curing.Completed",
            "LH.Machine_Idle",
            "LH_Curing.Active",
        ]

        self.setup_ui()
        self.setup_connections()
        # Keep this page's Figma theme local when the EYRES shell embeds/reparents
        # the PLC widget and applies the application-wide stylesheet.
        self._install_embedded_style_guard()
        # Guided workflow starts at Step 1. Connection is an explicit operator action.
        QTimer.singleShot(0, lambda: self._show_step(1, animate=False))

    # ---------- Mapping helpers ----------
    def _tok(self, s: str) -> List[str]:
        return [t for t in re.split(r'[^0-9a-zA-Z]+', s.lower()) if t]

    def _ep_desired_parts(self, tag: str) -> Optional[Tuple[int,int,str]]:
        m = re.match(r'^(EP)([1-3])_Step\[(\d+)\]\.(X)$', tag, re.IGNORECASE)
        if not m: return None
        _, epn_s, idx_s, member = m.groups()
        return (int(epn_s), int(idx_s), member.lower())

    def _generate_ep_patterns(self, ep: int, idx: int, member: str) -> List[re.Pattern]:
        # Try common real PLC spellings: underscores, zero-padding, flattened names, etc.
        idx2 = f"{idx:02d}"
        pats = [
            rf"^EP{ep}[_]?Step\[{idx}\][\._]{member}$",
            rf"^EP{ep}[_]?Step\[{idx}\]{member}$",
            rf"^EP{ep}[_]?Step{idx}[\._]{member}$",
            rf"^EP{ep}[_]?Step_{idx}[\._]{member}$",
            rf"^EP{ep}[_]?Step{idx2}[\._]{member}$",
            rf"^EP{ep}[_]?Step_{idx2}[\._]{member}$",
            rf"^EP{ep}[_]?Step\[{idx}\]_{member}$",
            rf"^EP{ep}[_]?Step_{idx}_{member}$",
        ]
        return [re.compile(p, re.IGNORECASE) for p in pats]

    def _generate_lh_patterns(self, tag: str) -> List[re.Pattern]:
        # Accept LH.Curing.Step_No, LH.Curing_Interlock_Ok, LH.Initiate_Curing, LH.Machine_Idle etc.
        # Convert tokens into fuzzy underscore/dot-insensitive regex.
        toks = self._tok(tag)
        if not toks or toks[0] != 'lh':
            toks = ['lh'] + toks  # ensure 'lh' prefix
        pat = r".*".join(map(re.escape, toks))
        return [re.compile(pat, re.IGNORECASE)]

    def _probe_candidate(self, name: str) -> bool:
        res = self.plc_worker.read_one(name)
        return (res is not None) and getattr(res, "Status", "") == "Success"

    def _best_match_from_available(self, patterns: List[re.Pattern], startswith: Optional[str]=None) -> Optional[str]:
        cands: List[str] = []
        pool = self.available_tags if not startswith else [t for t in self.available_tags if t.lower().startswith(startswith)]
        for t in pool:
            for p in patterns:
                if p.search(t):
                    cands.append(t)
                    break
        if not cands:
            return None
        # Prefer shortest, then alphabetical
        cands.sort(key=lambda s: (len(s), s.lower()))
        return cands[0]

    def _map_specific_tags(self, desired: List[str]) -> Tuple[Dict[str, Optional[str]], List[Tuple[str,str]], List[str]]:
        """
        Returns (display->plc map, fixes list, unresolved list).
        We use:
          1) direct probe
          2) EP-pattern search in available list + probe
          3) LH-pattern search in available list + probe
          4) simple underscore/dot replacement variants + probe
        """
        mapping: Dict[str, Optional[str]] = {}
        fixes: List[Tuple[str,str]] = []
        unresolved: List[str] = []

        # precompute lowercase available for cheap contains checks
        self.available_tags = self.available_tags or []

        for disp in desired:
            # 1) direct
            if self._probe_candidate(disp):
                mapping[disp] = disp
                continue

            # 2) EP family
            ep_parts = self._ep_desired_parts(disp)
            chosen: Optional[str] = None
            if ep_parts:
                ep, idx, member = ep_parts
                pats = self._generate_ep_patterns(ep, idx, member)
                candidate = self._best_match_from_available(pats, startswith=f"ep{ep}")
                if candidate and self._probe_candidate(candidate):
                    chosen = candidate

            # 3) LH family
            if (not chosen) and (disp.lower().startswith('lh.')):
                pats = self._generate_lh_patterns(disp)
                candidate = self._best_match_from_available(pats, startswith="lh")
                if candidate and self._probe_candidate(candidate):
                    chosen = candidate

            # 4) simple underscore/dot swaps
            if not chosen:
                variants = set()
                if '.' in disp:
                    a,b = disp.split('.',1)
                    variants.add(f"{a}_{b}")
                if '_':  # also try replacing first '_' with '.'
                    parts = disp.split('_',1)
                    if len(parts)==2:
                        variants.add(f"{parts[0]}.{parts[1]}")
                for v in list(variants):
                    if self._probe_candidate(v):
                        chosen = v
                        break

            if chosen:
                mapping[disp] = chosen
                if chosen != disp:
                    fixes.append((disp, chosen))
            else:
                mapping[disp] = None
                unresolved.append(disp)

        return mapping, fixes, unresolved


    def setup_ui(self):
        self.setWindowTitle("PLC Data Monitor")
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.availableGeometry())
        self.setWindowFlags(Qt.Window)

        # Figma uses Inter. Fall back to Segoe UI on Windows if Inter is unavailable.
        families = set(QFontDatabase().families())
        self._ui_font = "Inter" if "Inter" in families else "Segoe UI"

        central = QWidget()
        central.setObjectName("plcRoot")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(12)

        # ---------------- Header ----------------
        header = QFrame()
        header.setObjectName("pageHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(12)

        htxt = QVBoxLayout()
        htxt.setSpacing(2)
        title = QLabel("PLC Data Monitor")
        title.setObjectName("pageTitle")
        subtitle = QLabel("A guided setup that follows the operator sequence from connection to live monitoring.")
        subtitle.setObjectName("pageSubtitle")
        htxt.addWidget(title)
        htxt.addWidget(subtitle)
        hl.addLayout(htxt)
        hl.addStretch(1)

        self.mode_badge = QLabel("PLC OFFLINE")
        self.mode_badge.setObjectName("modeBadge")
        self.mode_badge.setAlignment(Qt.AlignCenter)
        self.mode_badge.setMinimumWidth(120)
        self.mode_badge.setFixedHeight(30)
        hl.addWidget(self.mode_badge)

        self.help_btn = QToolButton()
        self.help_btn.setObjectName("helpButton")
        self.help_btn.setText("?")
        self.help_btn.setFixedSize(30, 30)
        self.help_btn.setToolTip("PLC data monitor help")
        self.help_btn.setCursor(Qt.PointingHandCursor)
        # Styling is provided by the page-level QSS (QToolButton#helpButton).
        # Keeping this widget free of a second ad-hoc stylesheet avoids the
        # repeated Qt "Could not parse stylesheet" warning during restyles.
        self.help_btn.clicked.connect(self._show_help)
        hl.addWidget(self.help_btn)
        root.addWidget(header)

        # ---------------- Main workspace ----------------
        workspace = QFrame()
        workspace.setObjectName("workspaceCard")
        self.workspace = workspace
        wl = QVBoxLayout(workspace)
        wl.setContentsMargins(24, 20, 24, 20)
        wl.setSpacing(16)
        root.addWidget(workspace, 1)

        # Guided workflow ribbon
        steps_row = QHBoxLayout()
        steps_row.setSpacing(16)
        self.step_cards = []
        self.step_number_labels = []
        self.step_title_labels = []
        self.step_subtitle_labels = []
        step_defs = [
            ("Connect PLC", "Controller session"),
            ("Select tags", "Choose monitoring tags"),
            ("Storage & collection", "CSV + read settings"),
            ("Live monitor", "Run and observe"),
        ]
        for i, (st, ss) in enumerate(step_defs, 1):
            card = QFrame()
            card.setObjectName("flowStep")
            card.setProperty("state", "future")
            card.setProperty("stepIndex", i)
            card.setMinimumHeight(64)
            card.setCursor(Qt.PointingHandCursor)
            card.setToolTip("Open this workflow step for UI preview. Operational actions remain safety-gated.")
            sl = QHBoxLayout(card)
            sl.setContentsMargins(14, 10, 14, 10)
            sl.setSpacing(10)

            num = QLabel(str(i))
            num.setObjectName("flowStepNumber")
            num.setAlignment(Qt.AlignCenter)
            num.setFixedSize(28, 28)
            sl.addWidget(num, 0, Qt.AlignVCenter)

            tc = QVBoxLayout()
            tc.setSpacing(1)
            st_lbl = QLabel(st)
            st_lbl.setObjectName("flowStepTitle")
            ss_lbl = QLabel(ss)
            ss_lbl.setObjectName("flowStepSubtitle")
            tc.addWidget(st_lbl)
            tc.addWidget(ss_lbl)
            sl.addLayout(tc, 1)
            steps_row.addWidget(card, 1)

            self.step_cards.append(card)
            self.step_number_labels.append(num)
            self.step_title_labels.append(st_lbl)
            self.step_subtitle_labels.append(ss_lbl)

        wl.addLayout(steps_row)

        # Pages
        self.flow_stack = QStackedWidget()
        self.flow_stack.setObjectName("flowStack")
        self.flow_stack.addWidget(self._build_connect_page())
        self.flow_stack.addWidget(self._build_tags_page())
        self.flow_stack.addWidget(self._build_storage_page())
        self.flow_stack.addWidget(self._build_live_page())
        wl.addWidget(self.flow_stack, 1)

        self.apply_dark_theme()
        self._update_step_bar()
        self._sync_connection_readiness()
        self._update_start_readiness()
        self._sync_live_summary()

        # Subtle Figma-like card shadow.
        shadow = QGraphicsDropShadowEffect(workspace)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(10, 20, 41, 18))
        workspace.setGraphicsEffect(shadow)

    def _section_panel(self, title_text: str, subtitle_text: str = ""):
        card = QFrame()
        card.setObjectName("sectionCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        if subtitle_text:
            sub = QLabel(subtitle_text)
            sub.setObjectName("sectionSubtitle")
            sub.setWordWrap(True)
            lay.addWidget(sub)

        return card, lay

    def _field_caption(self, text: str):
        lbl = QLabel(text)
        lbl.setObjectName("fieldCaption")
        return lbl

    def _make_status_row(self, label_text: str, initial_text: str = "Locked"):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label_text)
        lbl.setObjectName("readinessLabel")
        chip = QLabel(initial_text)
        chip.setObjectName("statusChip")
        chip.setProperty("tone", "neutral")
        chip.setAlignment(Qt.AlignCenter)
        chip.setMinimumWidth(92)
        chip.setFixedHeight(24)
        row.addWidget(lbl)
        row.addStretch(1)
        row.addWidget(chip)
        return row, chip

    def _set_chip(self, chip: QLabel, text: str, tone: str):
        chip.setText(text)
        chip.setProperty("tone", tone)
        chip.style().unpolish(chip)
        chip.style().polish(chip)
        chip.update()

    def _build_connect_page(self):
        page = QWidget()
        page.setObjectName("flowPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        eyebrow = QLabel("STEP 1 OF 4")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        title = QLabel("Connect to the PLC")
        title.setObjectName("flowTitle")
        layout.addWidget(title)

        sub = QLabel("Start by establishing a controller session. Tag discovery stays locked until the connection is ready.")
        sub.setObjectName("flowSubtitle")
        layout.addWidget(sub)

        body = QHBoxLayout()
        body.setSpacing(18)

        conn, cl = self._section_panel("Controller connection", "PLC type and network details")

        profile_row = QHBoxLayout()
        profile_row.setSpacing(10)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(6)
        brand_col.addWidget(self._field_caption("PLC brand / type"))
        self.plc_brand_combo = QComboBox()
        self.plc_brand_combo.setObjectName("modernCombo")
        self.plc_brand_combo.setMinimumHeight(40)
        self.plc_brand_combo.addItems(list(self.plc_profiles.keys()))
        self.plc_brand_combo.setCurrentText("Allen-Bradley")
        brand_col.addWidget(self.plc_brand_combo)
        profile_row.addLayout(brand_col, 1)

        protocol_col = QVBoxLayout()
        protocol_col.setSpacing(6)
        protocol_col.addWidget(self._field_caption("Protocol"))
        self.protocol_combo = QComboBox()
        self.protocol_combo.setObjectName("modernCombo")
        self.protocol_combo.setMinimumHeight(40)
        self.protocol_combo.setEnabled(False)
        protocol_col.addWidget(self.protocol_combo)
        profile_row.addLayout(protocol_col, 1)
        cl.addLayout(profile_row)

        network_row = QHBoxLayout()
        network_row.setSpacing(10)

        ip_wrap = QWidget()
        ip_l = QVBoxLayout(ip_wrap)
        ip_l.setContentsMargins(0, 0, 0, 0)
        ip_l.setSpacing(6)
        ip_l.addWidget(self._field_caption("IP address"))
        self.ip_edit = QLineEdit("192.168.1.1")
        self.ip_edit.setObjectName("modernField")
        self.ip_edit.setMinimumHeight(40)
        ip_l.addWidget(self.ip_edit)
        network_row.addWidget(ip_wrap, 2)

        def _spin_field(label, minimum, maximum, value):
            wrap = QWidget()
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            lay.addWidget(self._field_caption(label))
            spin = QSpinBox()
            spin.setObjectName("modernSpin")
            spin.setRange(minimum, maximum)
            spin.setValue(value)
            spin.setButtonSymbols(QSpinBox.NoButtons)
            spin.setMinimumHeight(40)
            lay.addWidget(spin)
            return wrap, spin

        self.rack_field, self.rack_spin = _spin_field("Rack", 0, 10, 0)
        self.slot_field, self.slot_spin = _spin_field("Slot", 0, 31, 0)
        self.port_field, self.port_spin = _spin_field("Port", 1, 65535, 44818)
        self.unit_field, self.unit_spin = _spin_field("Unit ID", 0, 255, 1)

        network_row.addWidget(self.rack_field, 0)
        network_row.addWidget(self.slot_field, 0)
        network_row.addWidget(self.port_field, 0)
        network_row.addWidget(self.unit_field, 0)
        cl.addLayout(network_row)

        protocol = QFrame()
        protocol.setObjectName("infoStrip")
        pl = QVBoxLayout(protocol)
        pl.setContentsMargins(12, 8, 12, 8)
        pl.setSpacing(2)
        self.protocol_info_title = QLabel("Allen-Bradley · EtherNet/IP (CIP)")
        self.protocol_info_title.setObjectName("infoStripTitle")
        self.protocol_info_text = QLabel("Controller symbolic tags are discovered automatically.")
        self.protocol_info_text.setObjectName("infoStripText")
        self.protocol_info_text.setWordWrap(True)
        pl.addWidget(self.protocol_info_title)
        pl.addWidget(self.protocol_info_text)
        cl.addWidget(protocol)

        action = QHBoxLayout()
        action.setSpacing(8)
        self.connect_btn = QPushButton("Connect to PLC")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.setMinimumHeight(40)
        self.disconnect_btn = QPushButton("Cancel")
        self.disconnect_btn.setObjectName("secondaryButton")
        self.disconnect_btn.setMinimumHeight(40)
        action.addWidget(self.connect_btn)
        action.addWidget(self.disconnect_btn)
        action.addStretch(1)
        cl.addLayout(action)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("modernProgress")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setVisible(False)
        cl.addWidget(self.progress_bar)
        cl.addStretch(1)

        ready, rl = self._section_panel("Connection readiness", "Live readiness checks")
        lead = QHBoxLayout()
        lead.setSpacing(12)
        icon = QLabel("PLC")
        icon.setObjectName("plcIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(48, 48)
        lead.addWidget(icon)
        lead_text = QVBoxLayout()
        lead_text.setSpacing(2)
        self.connection_state_title = QLabel("Waiting for connection")
        self.connection_state_title.setObjectName("readinessTitle")
        self.connection_state_sub = QLabel("Enter the PLC address and connect to unlock tag discovery.")
        self.connection_state_sub.setObjectName("readinessText")
        self.connection_state_sub.setWordWrap(True)
        lead_text.addWidget(self.connection_state_title)
        lead_text.addWidget(self.connection_state_sub)
        lead.addLayout(lead_text, 1)
        rl.addLayout(lead)

        r, self.ready_network_chip = self._make_status_row("Network address configured", "Ready")
        rl.addLayout(r)
        r, self.ready_session_chip = self._make_status_row("PLC session", "Not connected")
        rl.addLayout(r)
        r, self.ready_tags_chip = self._make_status_row("Tag discovery", "Locked")
        rl.addLayout(r)

        self.status_label = QLabel("Next step opens automatically after a successful connection.")
        self.status_label.setObjectName("statusStrip")
        self.status_label.setWordWrap(True)
        rl.addStretch(1)
        rl.addWidget(self.status_label)

        body.addWidget(conn, 3)
        body.addWidget(ready, 2)
        layout.addLayout(body, 1)

        # Apply the default Allen-Bradley profile after all readiness widgets exist.
        QTimer.singleShot(0, lambda: self._on_plc_brand_changed(self.plc_brand_combo.currentText()))
        return page

    def _build_tags_page(self):
        page = QWidget()
        page.setObjectName("flowPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        eyebrow = QLabel("STEP 2 OF 4")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        title = QLabel("Choose monitoring tags")
        title.setObjectName("flowTitle")
        layout.addWidget(title)

        sub = QLabel("Discover PLC tags, filter them, and build the clean monitoring set used by this session.")
        sub.setObjectName("flowSubtitle")
        layout.addWidget(sub)

        body = QHBoxLayout()
        body.setSpacing(18)

        available, al = self._section_panel("Available PLC tags", "Retrieved from the active controller session")

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.tag_search_edit = QLineEdit()
        self.tag_search_edit.setObjectName("modernField")
        self.tag_search_edit.setPlaceholderText("Search tag name…")
        self.tag_search_edit.setMinimumHeight(38)
        toolbar.addWidget(self.tag_search_edit, 1)

        self.get_tags_btn = QPushButton("Refresh tags")
        self.get_tags_btn.setObjectName("secondaryButton")
        self.get_tags_btn.setMinimumHeight(38)
        toolbar.addWidget(self.get_tags_btn)

        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.setObjectName("secondaryButton")
        self.select_all_btn.setMinimumHeight(38)
        self.select_all_btn.setEnabled(False)
        toolbar.addWidget(self.select_all_btn)
        al.addLayout(toolbar)

        self.tag_found_badge = QLabel("0 FOUND")
        self.tag_found_badge.setObjectName("countBadge")
        al.addWidget(self.tag_found_badge, 0, Qt.AlignRight)

        self.tag_capability_note = QLabel("Connect to a PLC to see its tag-discovery capability.")
        self.tag_capability_note.setObjectName("mutedText")
        self.tag_capability_note.setWordWrap(True)
        al.addWidget(self.tag_capability_note)

        manual_row = QHBoxLayout()
        manual_row.setSpacing(8)
        self.manual_tag_edit = QLineEdit()
        self.manual_tag_edit.setObjectName("modernField")
        self.manual_tag_edit.setPlaceholderText("Manual PLC tag / address  (comma separated supported)")
        self.manual_tag_edit.setMinimumHeight(38)
        self.add_manual_tag_btn = QPushButton("Add address")
        self.add_manual_tag_btn.setObjectName("secondaryButton")
        self.add_manual_tag_btn.setMinimumHeight(38)
        manual_row.addWidget(self.manual_tag_edit, 1)
        manual_row.addWidget(self.add_manual_tag_btn)
        al.addLayout(manual_row)

        self.tags_list_widget = QListWidget()
        self.tags_list_widget.setObjectName("tagList")
        self.tags_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tags_list_widget.setAlternatingRowColors(False)
        al.addWidget(self.tags_list_widget, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.clear_selection_btn = QPushButton("Clear selection")
        self.clear_selection_btn.setObjectName("ghostButton")
        self.clear_selection_btn.setEnabled(False)
        self.add_selected_btn = QPushButton("Add selected")
        self.add_selected_btn.setObjectName("primaryButton")
        self.add_selected_btn.setEnabled(False)
        self.add_all_btn = QPushButton("Add all")
        self.add_all_btn.setObjectName("secondaryButton")
        self.add_all_btn.setEnabled(False)
        action_row.addWidget(self.clear_selection_btn)
        action_row.addStretch(1)
        action_row.addWidget(self.add_all_btn)
        action_row.addWidget(self.add_selected_btn)
        al.addLayout(action_row)

        advanced = QHBoxLayout()
        advanced.setSpacing(8)
        self.add_specific_btn = QPushButton("Auto-map predefined 300+ tags")
        self.add_specific_btn.setObjectName("purpleButton")
        self.add_specific_btn.setEnabled(False)
        advanced.addWidget(self.add_specific_btn)

        self.save_taglist_btn = QPushButton("Export tag list")
        self.save_taglist_btn.setObjectName("ghostButton")
        self.save_taglist_btn.setEnabled(False)
        advanced.addWidget(self.save_taglist_btn)

        self.auto_save_taglist_check = QCheckBox("Auto-save discovered tag list")
        self.auto_save_taglist_check.setObjectName("modernCheck")
        self.auto_save_taglist_check.setChecked(False)
        advanced.addWidget(self.auto_save_taglist_check)
        al.addLayout(advanced)

        self.taglist_csv_path_label = QLabel("Tag-list export not created")
        self.taglist_csv_path_label.setObjectName("mutedText")
        al.addWidget(self.taglist_csv_path_label)

        selected, sl = self._section_panel("Selected for monitoring", "Only selected tags are read during the live session")

        self.selected_count_label = QLabel("0 TAGS")
        self.selected_count_label.setObjectName("successBadge")
        sl.addWidget(self.selected_count_label, 0, Qt.AlignRight)

        self.selected_tags_list = QListWidget()
        self.selected_tags_list.setObjectName("selectedTagList")
        self.selected_tags_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        sl.addWidget(self.selected_tags_list, 1)

        sel_actions = QHBoxLayout()
        self.remove_tag_btn = QPushButton("Remove selected")
        self.remove_tag_btn.setObjectName("ghostButton")
        self.remove_tag_btn.setEnabled(False)
        self.clear_all_btn = QPushButton("Clear all")
        self.clear_all_btn.setObjectName("ghostButton")
        sel_actions.addWidget(self.remove_tag_btn)
        sel_actions.addWidget(self.clear_all_btn)
        sel_actions.addStretch(1)
        sl.addLayout(sel_actions)

        ready = QFrame()
        ready.setObjectName("blueInfo")
        ril = QVBoxLayout(ready)
        ril.setContentsMargins(12, 9, 12, 9)
        ril.setSpacing(2)
        self.tag_ready_title = QLabel("Select one or more tags")
        self.tag_ready_title.setObjectName("blueInfoTitle")
        self.tag_ready_sub = QLabel("The storage step unlocks after the monitoring set is ready.")
        self.tag_ready_sub.setObjectName("blueInfoText")
        ril.addWidget(self.tag_ready_title)
        ril.addWidget(self.tag_ready_sub)
        sl.addWidget(ready)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.tags_back_btn = QPushButton("Back")
        self.tags_back_btn.setObjectName("secondaryButton")
        self.tags_continue_btn = QPushButton("Continue to storage")
        self.tags_continue_btn.setObjectName("primaryButton")
        self.tags_continue_btn.setEnabled(False)
        nav.addWidget(self.tags_back_btn)
        nav.addWidget(self.tags_continue_btn)
        sl.addLayout(nav)

        body.addWidget(available, 3)
        body.addWidget(selected, 2)
        layout.addLayout(body, 1)

        return page

    def _build_storage_page(self):
        page = QWidget()
        page.setObjectName("flowPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        eyebrow = QLabel("STEP 3 OF 4")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)

        title = QLabel("Storage & collection setup")
        title.setObjectName("flowTitle")
        layout.addWidget(title)

        sub = QLabel("Select the save destination, confirm sampling settings, then start the live reading session.")
        sub.setObjectName("flowSubtitle")
        layout.addWidget(sub)

        body = QHBoxLayout()
        body.setSpacing(18)

        storage, sl = self._section_panel("CSV destination", "Required before Start Reading becomes available")

        # Kept for the existing storage logic, but the workflow always stores to CSV.
        self.csv_check = QCheckBox("Save to CSV")
        self.csv_check.setChecked(True)
        self.csv_check.hide()

        sl.addWidget(self._field_caption("Save folder"))
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.csv_folder_edit = QLineEdit()
        self.csv_folder_edit.setObjectName("modernField")
        self.csv_folder_edit.setPlaceholderText("Choose a folder…")
        self.csv_folder_edit.setReadOnly(True)
        self.csv_folder_edit.setMinimumHeight(40)
        self.csv_browse_btn = QPushButton("Browse…")
        self.csv_browse_btn.setObjectName("secondaryButton")
        self.csv_browse_btn.setMinimumHeight(40)
        folder_row.addWidget(self.csv_folder_edit, 1)
        folder_row.addWidget(self.csv_browse_btn)
        sl.addLayout(folder_row)

        self.auto_csv_check = QCheckBox("Auto-generate CSV filename")
        self.auto_csv_check.setObjectName("switchCheck")
        self.auto_csv_check.setChecked(True)
        sl.addWidget(self.auto_csv_check)

        self.manual_filename_edit = QLineEdit("plc_data.csv")
        self.manual_filename_edit.setObjectName("modernField")
        self.manual_filename_edit.setPlaceholderText("CSV filename")
        self.manual_filename_edit.setMinimumHeight(40)
        self.manual_filename_edit.setVisible(False)
        sl.addWidget(self.manual_filename_edit)

        preview = QFrame()
        preview.setObjectName("blueInfo")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(12, 9, 12, 9)
        pl.setSpacing(2)
        ptitle = QLabel("OUTPUT PREVIEW")
        ptitle.setObjectName("blueInfoKicker")
        self.csv_path_label = QLabel("Choose a destination folder to preview the output file.")
        self.csv_path_label.setObjectName("blueInfoTitle")
        self.csv_path_label.setWordWrap(True)
        pl.addWidget(ptitle)
        pl.addWidget(self.csv_path_label)
        sl.addWidget(preview)
        sl.addStretch(1)

        collect, cl = self._section_panel("Collection settings", "Sampling behavior for this run")

        fields = QHBoxLayout()
        fields.setSpacing(12)

        int_col = QVBoxLayout()
        int_col.setSpacing(6)
        int_col.addWidget(self._field_caption("Read interval"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setObjectName("modernSpin")
        self.interval_spin.setRange(100, 30000)
        self.interval_spin.setValue(1000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.interval_spin.setMinimumHeight(40)
        int_col.addWidget(self.interval_spin)

        batch_col = QVBoxLayout()
        batch_col.setSpacing(6)
        batch_col.addWidget(self._field_caption("Batch size"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setObjectName("modernSpin")
        self.batch_spin.setRange(1, 100)
        self.batch_spin.setValue(50)
        self.batch_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.batch_spin.setMinimumHeight(40)
        batch_col.addWidget(self.batch_spin)

        fields.addLayout(int_col, 1)
        fields.addLayout(batch_col, 1)
        cl.addLayout(fields)

        summary = QFrame()
        summary.setObjectName("summaryCard")
        sm = QVBoxLayout(summary)
        sm.setContentsMargins(12, 10, 12, 10)
        sm.setSpacing(6)

        top = QHBoxLayout()
        kicker = QLabel("RUN SUMMARY")
        kicker.setObjectName("summaryKicker")
        self.storage_ready_badge = QLabel("NOT READY")
        self.storage_ready_badge.setObjectName("statusChip")
        self.storage_ready_badge.setProperty("tone", "neutral")
        top.addWidget(kicker)
        top.addStretch(1)
        top.addWidget(self.storage_ready_badge)
        sm.addLayout(top)

        self.storage_summary_label = QLabel("PLC disconnected · 0 monitoring tags · CSV folder not selected")
        self.storage_summary_label.setObjectName("summaryText")
        self.storage_summary_label.setWordWrap(True)
        sm.addWidget(self.storage_summary_label)
        cl.addWidget(summary)
        cl.addStretch(1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.storage_back_btn = QPushButton("Back")
        self.storage_back_btn.setObjectName("secondaryButton")
        self.start_btn = QPushButton("Start Reading")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setEnabled(False)
        nav.addWidget(self.storage_back_btn)
        nav.addWidget(self.start_btn)
        cl.addLayout(nav)

        body.addWidget(storage, 3)
        body.addWidget(collect, 2)
        layout.addLayout(body, 1)

        ready_strip = QLabel("All required data is complete. Starting reading opens the Live Monitor workspace.")
        ready_strip.setObjectName("successStrip")
        layout.addWidget(ready_strip)

        return page

    def _build_live_page(self):
        page = QWidget()
        page.setObjectName("flowPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        eyebrow = QLabel("LIVE MONITOR")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("PLC data stream")
        title.setObjectName("flowTitle")
        title_col.addWidget(eyebrow)
        title_col.addWidget(title)
        head.addLayout(title_col)

        self.live_state_badge = QLabel("READY")
        self.live_state_badge.setObjectName("statusChip")
        self.live_state_badge.setProperty("tone", "success")
        self.live_state_badge.setAlignment(Qt.AlignCenter)
        self.live_state_badge.setFixedHeight(26)
        head.addWidget(self.live_state_badge, 0, Qt.AlignBottom)
        head.addStretch(1)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.connection_metric = self._metric_card("CONNECTION", "Not connected", "green")
        self.tags_metric = self._metric_card("MONITORING", "0 tags", "blue")
        self.records_metric = self._metric_card("RECORDS", "0", "neutral")
        self.interval_metric = self._metric_card("INTERVAL", "1000 ms", "purple")
        metrics.addWidget(self.connection_metric[0])
        metrics.addWidget(self.tags_metric[0])
        metrics.addWidget(self.records_metric[0])
        metrics.addWidget(self.interval_metric[0])
        head.addLayout(metrics)

        layout.addLayout(head)

        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("monitorTabs")

        # Real-time tab
        realtime_tab = QWidget()
        rt = QVBoxLayout(realtime_tab)
        rt.setContentsMargins(0, 10, 0, 0)
        rt.setSpacing(8)

        self.data_table = QTableWidget()
        self.data_table.setObjectName("dataTable")
        self.data_table.setColumnCount(3)
        self.data_table.setHorizontalHeaderLabels(["Display Tag", "Current Value", "Timestamp"])
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.setShowGrid(False)
        self.data_table.setAlternatingRowColors(False)
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.data_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.data_table.setMinimumHeight(260)
        rt.addWidget(self.data_table, 1)

        self.tab_widget.addTab(realtime_tab, "Real-time Data")

        # System log tab
        log_tab = QWidget()
        lt = QVBoxLayout(log_tab)
        lt.setContentsMargins(0, 10, 0, 0)
        lt.setSpacing(8)

        self.log_text = QTextEdit()
        self.log_text.setObjectName("logConsole")
        self.log_text.setReadOnly(True)
        lt.addWidget(self.log_text, 1)

        log_actions = QHBoxLayout()
        self.clear_log_btn = QPushButton("Clear log")
        self.clear_log_btn.setObjectName("secondaryButton")
        self.save_log_btn = QPushButton("Save log")
        self.save_log_btn.setObjectName("secondaryButton")
        log_actions.addWidget(self.clear_log_btn)
        log_actions.addWidget(self.save_log_btn)
        log_actions.addStretch(1)
        lt.addLayout(log_actions)

        self.tab_widget.addTab(log_tab, "System Log")
        layout.addWidget(self.tab_widget, 1)

        footer = QFrame()
        footer.setObjectName("liveFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 8, 12, 8)
        fl.setSpacing(8)

        self.live_csv_label = QLabel("CSV destination not configured")
        self.live_csv_label.setObjectName("mutedText")
        fl.addWidget(self.live_csv_label, 1)

        self.clear_data_btn = QPushButton("Clear data")
        self.clear_data_btn.setObjectName("ghostButton")
        self.single_read_btn = QPushButton("Single read")
        self.single_read_btn.setObjectName("secondaryButton")
        self.pause_btn = QPushButton("Pause reading")
        self.pause_btn.setObjectName("secondaryButton")
        self.stop_btn = QPushButton("Stop session")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.setEnabled(False)

        fl.addWidget(self.clear_data_btn)
        fl.addWidget(self.single_read_btn)
        fl.addWidget(self.pause_btn)
        fl.addWidget(self.stop_btn)
        layout.addWidget(footer)

        # Compatibility labels used by the existing data update code.
        self.records_count_label = QLabel("0")
        self.records_count_label.hide()
        self.tags_count_label = QLabel("0")
        self.tags_count_label.hide()

        return page

    def _metric_card(self, title_text: str, value_text: str, tone: str):
        card = QFrame()
        card.setObjectName("metricCard")
        card.setProperty("tone", tone)
        card.setFixedSize(126, 54)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        t = QLabel(title_text)
        t.setObjectName("metricTitle")
        v = QLabel(value_text)
        v.setObjectName("metricValue")
        lay.addWidget(t)
        lay.addWidget(v)
        return card, v

    def _show_help(self):
        QMessageBox.information(
            self,
            "PLC Data Monitor",
            "Guided workflow:\\n\\n"
            "1. Connect to the PLC.\\n"
            "2. Discover and select monitoring tags.\\n"
            "3. Choose the CSV save folder and collection settings.\\n"
            "4. Start Reading to open the live monitor.\\n\\n"
            "Simulation mode remains available when the PLC connection cannot be established."
        )

    def _show_step(self, step: int, animate: bool = True):
        step = max(1, min(4, int(step)))
        self.current_step = step
        self.flow_stack.setCurrentIndex(step - 1)
        self._update_step_bar()
        QTimer.singleShot(0, self._force_local_plc_theme)

        if animate:
            effect = QGraphicsOpacityEffect(self.flow_stack.currentWidget())
            self.flow_stack.currentWidget().setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(160)
            anim.setStartValue(0.25)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            def cleanup():
                w = self.flow_stack.currentWidget()
                if w:
                    w.setGraphicsEffect(None)
            anim.finished.connect(cleanup)
            self._fade_anim = anim
            anim.start()

    def _update_step_bar(self):
        for idx, card in enumerate(self.step_cards, 1):
            if idx < self.current_step:
                state = "complete"
            elif idx == self.current_step:
                state = "active"
            else:
                state = "future"
            card.setProperty("state", state)
            for w in [card, self.step_number_labels[idx-1], self.step_title_labels[idx-1], self.step_subtitle_labels[idx-1]]:
                w.style().unpolish(w)
                w.style().polish(w)
                w.update()

    def _current_plc_config(self) -> Dict[str, object]:
        brand = self.plc_brand_combo.currentText() if hasattr(self, "plc_brand_combo") else "Allen-Bradley"
        protocol = self.protocol_combo.currentText() if hasattr(self, "protocol_combo") else "EtherNet/IP (CIP)"
        return {
            "plc_brand": brand,
            "plc_protocol": protocol,
            "ip_address": self.ip_edit.text().strip() if hasattr(self, "ip_edit") else "",
            "rack": self.rack_spin.value() if hasattr(self, "rack_spin") else 0,
            "slot": self.slot_spin.value() if hasattr(self, "slot_spin") else 0,
            "port": self.port_spin.value() if hasattr(self, "port_spin") else 0,
            "unit_id": self.unit_spin.value() if hasattr(self, "unit_spin") else 1,
            "timeout": 2.5,
        }

    def _on_plc_brand_changed(self, brand: str):
        profile = self.plc_profiles.get(str(brand), self.plc_profiles.get("Allen-Bradley", {}))
        protocol = str(profile.get("protocol", ""))

        if hasattr(self, "protocol_combo"):
            self.protocol_combo.blockSignals(True)
            self.protocol_combo.clear()
            self.protocol_combo.addItem(protocol)
            self.protocol_combo.setCurrentIndex(0)
            self.protocol_combo.blockSignals(False)

        if hasattr(self, "port_spin"):
            default_port = int(profile.get("default_port") or 0)
            if default_port > 0:
                self.port_spin.setValue(default_port)

        if hasattr(self, "rack_field"):
            self.rack_field.setVisible(bool(profile.get("uses_rack")))
        if hasattr(self, "slot_field"):
            self.slot_field.setVisible(bool(profile.get("uses_slot")))
        if hasattr(self, "port_field"):
            self.port_field.setVisible(str(brand) not in ("Simulation",))
        if hasattr(self, "unit_field"):
            self.unit_field.setVisible(bool(profile.get("uses_unit_id")))

        if hasattr(self, "ip_edit"):
            simulation = str(brand) == "Simulation"
            self.ip_edit.setEnabled(not simulation)
            self.ip_edit.setPlaceholderText("Not required in simulation" if simulation else "PLC IPv4 address")

        if hasattr(self, "protocol_info_title"):
            self.protocol_info_title.setText(f"{brand} · {protocol}")
        if hasattr(self, "protocol_info_text"):
            self.protocol_info_text.setText(str(profile.get("address_help", "")))

        self._sync_connection_readiness()
        self._sync_tag_capability_ui()

    def _sync_tag_capability_ui(self):
        if not hasattr(self, "tag_capability_note"):
            return

        brand = self.plc_worker.brand if self.is_connected else (
            self.plc_brand_combo.currentText() if hasattr(self, "plc_brand_combo") else "Allen-Bradley"
        )
        profile = self.plc_profiles.get(brand, {})
        browse = self.plc_worker.supports_tag_browse if self.is_connected else bool(profile.get("supports_tag_browse"))
        read_ok = self.plc_worker.supports_read if self.is_connected else bool(profile.get("supports_read", True))
        symbolic = self.plc_worker.supports_symbolic_tags if self.is_connected else bool(profile.get("supports_symbolic_tags"))

        if self.is_connected and browse:
            self.tag_capability_note.setText(
                f"{brand}: automatic PLC tag discovery is available. You can also enter a tag manually."
            )
        elif self.is_connected:
            self.tag_capability_note.setText(
                f"{brand}: automatic tag discovery is not available through this generic driver. "
                f"{profile.get('address_help', 'Enter PLC addresses manually below.')}"
            )
        else:
            self.tag_capability_note.setText(
                f"{brand}: {profile.get('address_help', 'Connect the PLC or enter manual addresses.') }"
            )

        if hasattr(self, "get_tags_btn"):
            self.get_tags_btn.setEnabled(self.is_connected and browse)
        if hasattr(self, "add_specific_btn"):
            self.add_specific_btn.setEnabled(self.is_connected and symbolic)
        if hasattr(self, "add_manual_tag_btn"):
            self.add_manual_tag_btn.setEnabled(read_ok or not self.is_connected)

    def add_manual_tags(self):
        raw = self.manual_tag_edit.text().strip() if hasattr(self, "manual_tag_edit") else ""
        if not raw:
            QMessageBox.information(self, "Manual PLC address", "Enter one or more PLC tags/addresses first.")
            return

        parts = [p.strip() for p in re.split(r"[,;]+", raw) if p.strip()]
        added = 0
        for tag in parts:
            if tag not in self.display_tags:
                self.display_tags.append(tag)
                self.display_to_plc[tag] = tag
                self.selected_tags_list.addItem(tag)
                added += 1

        if added:
            self.manual_tag_edit.clear()
            self.update_tags_count()
            self.log_message(f"Added {added} manual PLC tag/address item(s)")
        else:
            QMessageBox.information(self, "Manual PLC address", "Those tags/addresses are already selected.")

    def _sync_connection_readiness(self):
        brand = self.plc_brand_combo.currentText() if hasattr(self, "plc_brand_combo") else "Allen-Bradley"
        profile = self.plc_profiles.get(brand, {})
        simulation_selected = brand == "Simulation"
        ip_ok = simulation_selected or (bool(self.ip_edit.text().strip()) if hasattr(self, "ip_edit") else False)
        self._set_chip(self.ready_network_chip, "Ready" if ip_ok else "Missing", "success" if ip_ok else "warning")

        if self.is_connected:
            self._set_chip(self.ready_session_chip, "Connected", "success")
            if self.plc_worker.supports_tag_browse:
                self._set_chip(self.ready_tags_chip, "Available", "success")
            else:
                self._set_chip(self.ready_tags_chip, "Manual", "warning")
            self.connection_state_title.setText(f"{self.plc_worker.brand} session ready")
            if self.plc_worker.simulation:
                self.connection_state_sub.setText("Simulation session is active. Generated tags and values are available.")
            elif self.plc_worker.supports_tag_browse:
                self.connection_state_sub.setText(
                    f"{self.plc_worker.protocol} session is active and automatic tag discovery is available."
                )
            else:
                self.connection_state_sub.setText(
                    f"{self.plc_worker.protocol} session is active. Enter PLC addresses manually on Step 2."
                )
        else:
            self._set_chip(self.ready_session_chip, "Not connected", "neutral")
            self._set_chip(self.ready_tags_chip, "Locked", "neutral")
            self.connection_state_title.setText("Waiting for connection")
            self.connection_state_sub.setText(
                f"Select the PLC type, enter its connection details, and connect. {profile.get('address_help', '')}"
            )

    def _filter_tags(self, query: str):
        q = (query or "").strip().lower()
        for i in range(self.tags_list_widget.count()):
            item = self.tags_list_widget.item(i)
            item.setHidden(bool(q) and q not in item.text().lower())

    def _update_storage_preview(self):
        folder = self.csv_directory
        auto = self.auto_csv_check.isChecked() if hasattr(self, "auto_csv_check") else True
        if hasattr(self, "manual_filename_edit"):
            self.manual_filename_edit.setVisible(not auto)

        if not folder:
            if hasattr(self, "csv_path_label"):
                self.csv_path_label.setText("Choose a destination folder to preview the output file.")
            self._update_start_readiness()
            return

        if auto:
            filename = f"plc_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        else:
            filename = (self.manual_filename_edit.text() or "plc_data.csv").strip()
            if not filename.lower().endswith(".csv"):
                filename += ".csv"

        preview = folder / filename
        self.csv_path_label.setText(str(preview))
        self._update_start_readiness()

    def _update_start_readiness(self):
        if not hasattr(self, "start_btn"):
            return

        tags_ok = len(self.display_tags) > 0
        folder_ok = self.csv_directory is not None
        connected_ok = self.is_connected
        read_ok = bool(self.plc_worker.supports_read or self.plc_worker.simulation)
        ready = connected_ok and read_ok and tags_ok and folder_ok and not self.is_reading
        self.start_btn.setEnabled(ready)

        if connected_ok and not read_ok:
            conn_text = f"{self.plc_worker.brand} connected · generic read not configured"
        else:
            conn_text = f"{self.plc_worker.brand} connected" if connected_ok else "PLC disconnected"
        tag_text = f"{len(self.display_tags)} monitoring tag{'s' if len(self.display_tags) != 1 else ''}"
        csv_text = "CSV folder configured" if folder_ok else "CSV folder not selected"
        if hasattr(self, "storage_summary_label"):
            self.storage_summary_label.setText(f"{conn_text} · {tag_text} · {csv_text}")

        if hasattr(self, "storage_ready_badge"):
            self._set_chip(self.storage_ready_badge, "READY" if ready else "NOT READY", "success" if ready else "neutral")

    def _sync_live_summary(self):
        if not hasattr(self, "connection_metric"):
            return

        if self.is_connected:
            self.connection_metric[1].setText("Simulation" if self.plc_worker.simulation else self.plc_worker.brand)
        else:
            self.connection_metric[1].setText("Not connected")

        self.tags_metric[1].setText(f"{len(self.display_tags)} tags")
        self.records_metric[1].setText(f"{self.records_count:,}")
        self.interval_metric[1].setText(f"{self.interval_spin.value()} ms" if hasattr(self, "interval_spin") else "—")

        if self.current_csv_path:
            self.live_csv_label.setText(f"Saving to  {self.current_csv_path.name}")
        elif self.csv_directory:
            self.live_csv_label.setText(f"CSV folder  {self.csv_directory}")
        else:
            self.live_csv_label.setText("CSV destination not configured")

        if self.is_reading:
            self._set_chip(self.live_state_badge, "READING", "success")
        elif self.is_paused:
            self._set_chip(self.live_state_badge, "PAUSED", "warning")
        else:
            self._set_chip(self.live_state_badge, "READY", "success")

    def pause_reading(self):
        if self.is_reading:
            self.plc_worker.stop_reading()
            self.is_reading = False
            self.is_paused = True
            self.pause_btn.setText("Resume reading")
            self.stop_btn.setEnabled(True)
            self.single_read_btn.setEnabled(True)
            self.log_message("Paused data collection")
        elif self.is_paused and self.read_tags:
            self.plc_worker.start_reading(
                self.read_tags,
                self.interval_spin.value(),
                self.batch_spin.value()
            )
            self.is_reading = True
            self.is_paused = False
            self.pause_btn.setText("Pause reading")
            self.stop_btn.setEnabled(True)
            self.single_read_btn.setEnabled(False)
            self.log_message("Resumed data collection")
        self._sync_live_summary()


    def apply_dark_theme(self):
        # Kept under the original method name for compatibility; this is the finalized
        # light EYRES / Figma visual system.
        fam = getattr(self, "_ui_font", "Segoe UI")
        qss = f"""
            QWidget#plcRoot {{
                background:#F6F9FD;
                color:#0E1729;
                font-family:"{fam}";
                font-size:12px;
            }}
            QFrame#pageHeader {{
                background:transparent;
                border:0;
            }}
            QLabel#pageTitle {{
                background:transparent;
                border:0;
                color:#0E1729;
                font-size:20px;
                font-weight:700;
            }}
            QLabel#pageSubtitle {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:11px;
            }}
            QLabel#modeBadge {{
                background:#F1F4F9;
                color:#61708A;
                border:0;
                border-radius:9px;
                padding:0 12px;
                font-size:10px;
                font-weight:700;
            }}
            QToolButton#helpButton {{
                background:#ECF2FF;
                color:#255CED;
                border:0;
                border-radius:15px;
                font-weight:700;
                font-size:13px;
            }}
            QToolButton#helpButton:hover {{
                background:#DCE7FF;
            }}
            QFrame#workspaceCard {{
                background:#FFFFFF;
                border:1px solid #DBE3F0;
                border-radius:18px;
            }}
            QFrame#flowStep {{
                background:#F9FBFE;
                border:1px solid #DBE3F0;
                border-radius:10px;
            }}
            QFrame#flowStep[state="active"] {{
                background:#ECF2FF;
                border:1px solid #255CED;
            }}
            QFrame#flowStep[state="complete"] {{
                background:#EAF8F1;
                border:1px solid #B8E6CD;
            }}
            QLabel#flowStepNumber {{
                background:#E8EDF7;
                color:#61708A;
                border-radius:14px;
                font-weight:700;
            }}
            QFrame#flowStep[state="active"] QLabel#flowStepNumber {{
                background:#255CED;
                color:#FFFFFF;
            }}
            QFrame#flowStep[state="complete"] QLabel#flowStepNumber {{
                background:#089957;
                color:#FFFFFF;
            }}
            QLabel#flowStepTitle {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:11px;
                font-weight:600;
            }}
            QFrame#flowStep[state="active"] QLabel#flowStepTitle,
            QFrame#flowStep[state="complete"] QLabel#flowStepTitle {{
                color:#0E1729;
            }}
            QLabel#flowStepSubtitle {{
                background:transparent;
                border:0;
                color:#91A0B8;
                font-size:9px;
            }}
            QWidget#flowPage {{
                background:#FBFCFF;
                border:1px solid #E3E9F3;
                border-radius:14px;
            }}
            QLabel#eyebrow {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:9px;
                font-weight:700;
            }}
            QLabel#flowTitle {{
                background:transparent;
                border:0;
                color:#0E1729;
                font-size:20px;
                font-weight:700;
            }}
            QLabel#flowSubtitle {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:11px;
            }}
            QFrame#sectionCard {{
                background:#FFFFFF;
                border:1px solid #DBE3F0;
                border-radius:12px;
            }}
            QLabel#sectionTitle {{
                background:transparent;
                border:0;
                color:#0E1729;
                font-size:13px;
                font-weight:700;
            }}
            QLabel#sectionSubtitle {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:10px;
            }}
            QLabel#fieldCaption {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:10px;
                font-weight:600;
            }}
            QLineEdit#modernField,
            QSpinBox#modernSpin,
            QComboBox#modernCombo {{
                background:#FFFFFF;
                color:#0E1729;
                border:1px solid #C9D6EB;
                border-radius:8px;
                padding:0 11px;
                selection-background-color:#DCE7FF;
                selection-color:#0E1729;
            }}
            QLineEdit#modernField:focus,
            QSpinBox#modernSpin:focus,
            QComboBox#modernCombo:focus {{
                border:1px solid #255CED;
            }}
            QComboBox#modernCombo {{
                padding-right:28px;
            }}
            QComboBox#modernCombo::drop-down {{
                border:0;
                width:28px;
            }}
            QComboBox#modernCombo:disabled {{
                background:#F5F8FC;
                color:#61708A;
                border:1px solid #D8E1EE;
            }}
            QComboBox#modernCombo QAbstractItemView {{
                background:#FFFFFF;
                color:#0E1729;
                border:1px solid #C9D6EB;
                selection-background-color:#ECF2FF;
                selection-color:#0E1729;
                outline:0;
            }}
            QSpinBox#modernSpin::up-button,
            QSpinBox#modernSpin::down-button {{
                width:0px;
                height:0px;
                border:0;
            }}
            QPushButton {{
                min-height:34px;
                border-radius:8px;
                padding:0 14px;
                font-weight:600;
                font-size:11px;
            }}
            QPushButton#primaryButton {{
                background:#1268ED;
                color:#FFFFFF;
                border:1px solid #1268ED;
            }}
            QPushButton#primaryButton:hover {{
                background:#0D5DDB;
                border-color:#0D5DDB;
            }}
            QPushButton#primaryButton:pressed {{
                background:#0A50BF;
            }}
            QPushButton#primaryButton:disabled {{
                background:#E8EDF7;
                color:#91A0B8;
                border:1px solid #E1E7F1;
            }}
            QPushButton#secondaryButton {{
                background:#FFFFFF;
                color:#255CED;
                border:1px solid #BFD0EE;
            }}
            QPushButton#secondaryButton:hover {{
                background:#F6F9FF;
                border-color:#86A7E6;
            }}
            QPushButton#ghostButton {{
                background:transparent;
                color:#61708A;
                border:1px solid #DBE3F0;
            }}
            QPushButton#ghostButton:hover {{
                background:#F6F9FD;
                color:#255CED;
            }}
            QPushButton#purpleButton {{
                background:#F2EDFF;
                color:#6B40E5;
                border:1px solid #D9CDFE;
            }}
            QPushButton#purpleButton:hover {{
                background:#EAE1FF;
            }}
            QPushButton#dangerButton {{
                background:#FFF1F2;
                color:#C53E4C;
                border:1px solid #F2C9CE;
            }}
            QPushButton#dangerButton:hover {{
                background:#FFE7E9;
            }}
            QProgressBar#modernProgress {{
                background:#EEF3FA;
                border:0;
                border-radius:2px;
            }}
            QProgressBar#modernProgress::chunk {{
                background:#255CED;
                border-radius:2px;
            }}
            QFrame#infoStrip {{
                background:#F8FAFD;
                border:1px solid #E2E8F1;
                border-radius:8px;
            }}
            QLabel#infoStripTitle {{
                background:transparent;
                border:0;
                color:#0E1729;
                font-size:10px;
                font-weight:600;
            }}
            QLabel#infoStripText {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:9px;
            }}
            QLabel#plcIcon {{
                background:#ECF2FF;
                color:#255CED;
                border-radius:10px;
                font-weight:700;
            }}
            QLabel#readinessTitle {{
                background:transparent;
                border:0;
                color:#0E1729;
                font-size:12px;
                font-weight:700;
            }}
            QLabel#readinessText {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:10px;
            }}
            QLabel#readinessLabel {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:10px;
            }}
            QLabel#statusChip {{
                border-radius:7px;
                padding:2px 8px;
                font-size:9px;
                font-weight:700;
            }}
            QLabel#statusChip[tone="neutral"] {{
                background:#F1F4F9;
                color:#61708A;
            }}
            QLabel#statusChip[tone="success"] {{
                background:#E8FAF0;
                color:#089957;
            }}
            QLabel#statusChip[tone="warning"] {{
                background:#FFF6DD;
                color:#9A6A05;
            }}
            QLabel#statusStrip {{
                background:#ECF2FF;
                color:#255CED;
                border-radius:7px;
                padding:9px 10px;
                font-size:9px;
            }}
            QLabel#countBadge {{
                background:#ECF2FF;
                color:#255CED;
                border-radius:8px;
                padding:4px 8px;
                font-size:9px;
                font-weight:700;
            }}
            QLabel#successBadge {{
                background:#E8FAF0;
                color:#089957;
                border-radius:8px;
                padding:4px 8px;
                font-size:9px;
                font-weight:700;
            }}
            QListWidget#tagList,
            QListWidget#selectedTagList {{
                background:#FFFFFF;
                color:#0E1729;
                border:1px solid #DBE3F0;
                border-radius:9px;
                outline:0;
                padding:4px;
            }}
            QListWidget#tagList::item,
            QListWidget#selectedTagList::item {{
                min-height:30px;
                border-bottom:1px solid #EEF2F7;
                padding:0 8px;
            }}
            QListWidget#tagList::item:selected {{
                background:#ECF2FF;
                color:#0E1729;
                border-radius:6px;
            }}
            QListWidget#selectedTagList::item:selected {{
                background:#F2EDFF;
                color:#0E1729;
                border-radius:6px;
            }}
            QLabel#mutedText {{
                background:transparent;
                border:0;
                color:#61708A;
                font-size:9px;
            }}
            QCheckBox#modernCheck,
            QCheckBox#switchCheck {{
                color:#61708A;
                font-size:10px;
                spacing:7px;
            }}
            QCheckBox#modernCheck::indicator,
            QCheckBox#switchCheck::indicator {{
                width:15px;
                height:15px;
            }}
            QFrame#blueInfo {{
                background:#ECF2FF;
                border:0;
                border-radius:8px;
            }}
            QLabel#blueInfoKicker {{
                background:transparent;
                border:0;
                color:#255CED;
                font-size:8px;
                font-weight:700;
            }}
            QLabel#blueInfoTitle {{
                background:transparent;
                border:0;
                color:#0E1729;
                font-size:10px;
                font-weight:600;
            }}
            QLabel#blueInfoText {{
                color:#61708A;
                font-size:9px;
            }}
            QFrame#summaryCard {{
                background:#F8FAFD;
                border:1px solid #E2E8F1;
                border-radius:8px;
            }}
            QLabel#summaryKicker {{
                color:#61708A;
                font-size:8px;
                font-weight:700;
            }}
            QLabel#summaryText {{
                color:#61708A;
                font-size:9px;
            }}
            QLabel#successStrip {{
                background:#E8FAF0;
                color:#087E4B;
                border-radius:7px;
                padding:8px 10px;
                font-size:9px;
            }}
            QFrame#metricCard {{
                border:0;
                border-radius:8px;
            }}
            QFrame#metricCard[tone="green"] {{
                background:#E8FAF0;
            }}
            QFrame#metricCard[tone="blue"] {{
                background:#ECF2FF;
            }}
            QFrame#metricCard[tone="purple"] {{
                background:#F2EDFF;
            }}
            QFrame#metricCard[tone="neutral"] {{
                background:#F1F4F9;
            }}
            QLabel#metricTitle {{
                color:#61708A;
                font-size:7px;
                font-weight:700;
            }}
            QLabel#metricValue {{
                color:#0E1729;
                font-size:10px;
                font-weight:700;
            }}
            QTabWidget#monitorTabs::pane {{
                border:1px solid #DBE3F0;
                border-radius:10px;
                background:#FFFFFF;
                top:-1px;
            }}
            QTabBar::tab {{
                background:#F5F8FC;
                color:#61708A;
                border:0;
                padding:9px 18px;
                margin-right:2px;
                font-size:10px;
            }}
            QTabBar::tab:selected {{
                background:#FFFFFF;
                color:#255CED;
                border-bottom:2px solid #255CED;
                font-weight:700;
            }}
            QTableWidget#dataTable {{
                background:#FFFFFF;
                color:#0E1729;
                border:0;
                gridline-color:#EEF2F7;
                selection-background-color:#ECF2FF;
                selection-color:#0E1729;
            }}
            QTableWidget#dataTable::item {{
                padding:8px 10px;
                border-bottom:1px solid #EEF2F7;
            }}
            QHeaderView::section {{
                background:#F5F8FC;
                color:#61708A;
                border:0;
                border-bottom:1px solid #DBE3F0;
                padding:8px 10px;
                font-size:9px;
                font-weight:700;
            }}
            QTextEdit#logConsole {{
                background:#0A1020;
                color:#C8D6F0;
                border:0;
                border-radius:8px;
                padding:10px;
                font-family:"Consolas";
                font-size:10px;
            }}
            QFrame#liveFooter {{
                background:#F8FAFD;
                border:1px solid #E2E8F1;
                border-radius:9px;
            }}
            QScrollBar:vertical {{
                background:transparent;
                width:8px;
                margin:2px;
            }}
            QScrollBar::handle:vertical {{
                background:#C9D6EB;
                min-height:28px;
                border-radius:4px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height:0;
            }}
        """
        self._plc_figma_qss = qss
        self._force_local_plc_theme()


    def _force_local_plc_theme(self):
        """Apply the PLC Figma theme directly to embedded page roots.

        The host application has a global stylesheet. When this QMainWindow's
        central widget is embedded into the host, that global theme can flatten
        the page unless the PLC stylesheet is also owned by the embedded roots.
        """
        qss = getattr(self, "_plc_figma_qss", "")
        if not qss:
            return

        self.setStyleSheet(qss)

        roots = []
        central = self.centralWidget()
        if central is not None:
            roots.append(central)

        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            roots.append(workspace)

        stack = getattr(self, "flow_stack", None)
        if stack is not None:
            roots.append(stack)
            for i in range(stack.count()):
                page = stack.widget(i)
                if page is not None:
                    roots.append(page)

        roots.extend(getattr(self, "step_cards", []))

        seen = set()
        for widget in roots:
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget))
            widget.setStyleSheet(qss)
            try:
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
            except Exception:
                pass

        # Help-button styling comes from QToolButton#helpButton in the local
        # page QSS above. Do not assign another stylesheet directly to the
        # button here; repeated direct assignment was the source of the Qt
        # stylesheet parser warnings seen at startup.

        # Dynamic properties such as active/complete must be polished again.
        if hasattr(self, "step_cards"):
            self._update_step_bar()


    def _install_embedded_style_guard(self):
        """Restore local styling after host re-parent/show operations."""
        watched = []

        central = self.centralWidget()
        if central is not None:
            watched.append(central)

        workspace = getattr(self, "workspace", None)
        if workspace is not None:
            watched.append(workspace)

        stack = getattr(self, "flow_stack", None)
        if stack is not None:
            watched.append(stack)
            for i in range(stack.count()):
                page = stack.widget(i)
                if page is not None:
                    watched.append(page)

        # Workflow cards are also watched so they can act as safe UI-preview
        # navigation. This lets the operator/reviewer inspect every page without
        # a live PLC connection, while actual PLC actions remain validated.
        for card in getattr(self, "step_cards", []):
            watched.append(card)

        for widget in watched:
            widget.installEventFilter(self)

        # The main page loader can apply the global QSS shortly after insertion.
        # These delayed passes intentionally run after that loader sequence.
        for delay in (0, 50, 150, 350, 750, 1200):
            QTimer.singleShot(delay, self._force_local_plc_theme)


    def eventFilter(self, obj, event):
        if event.type() in (QEvent.ParentChange, QEvent.Show):
            QTimer.singleShot(0, self._force_local_plc_theme)
            QTimer.singleShot(100, self._force_local_plc_theme)

        # UI preview navigation: allow opening any of the four pages directly
        # from the workflow ribbon, even when no PLC is connected.
        #
        # This does NOT bypass operational validation. Connect / tag discovery /
        # storage / start-reading actions still use their existing readiness checks.
        if event.type() == QEvent.MouseButtonRelease and obj in getattr(self, "step_cards", []):
            try:
                if event.button() == Qt.LeftButton:
                    step = self.step_cards.index(obj) + 1
                    self._show_step(step)
                    return True
            except Exception:
                pass

        return super().eventFilter(obj, event)


    # ---------- Connections / handlers ----------
    def setup_connections(self):
        self.plc_worker.data_received.connect(self.on_data_received)
        self.plc_worker.status_signal.connect(self.on_status_update)
        self.plc_worker.error_signal.connect(self.on_error)
        self.plc_worker.tags_retrieved.connect(self.on_tags_retrieved)
        self.connection_result.connect(self._handle_connection_result)

        self.connect_btn.clicked.connect(self.connect_to_plc)
        self.disconnect_btn.clicked.connect(self.disconnect_from_plc)

        self.get_tags_btn.clicked.connect(self.get_all_tags)
        self.select_all_btn.clicked.connect(self.select_all_tags)
        self.clear_selection_btn.clicked.connect(self.clear_tags_selection)
        self.add_selected_btn.clicked.connect(self.add_selected_tags)
        self.add_all_btn.clicked.connect(self.add_all_tags)
        self.add_specific_btn.clicked.connect(self.add_specific_tags_automap)
        self.save_taglist_btn.clicked.connect(self.save_taglist_dialog)

        self.remove_tag_btn.clicked.connect(self.remove_selected_tag)
        self.clear_all_btn.clicked.connect(self.clear_all_tags)

        self.tags_back_btn.clicked.connect(lambda: self._show_step(1))
        self.tags_continue_btn.clicked.connect(lambda: self._show_step(3))
        self.storage_back_btn.clicked.connect(lambda: self._show_step(2))

        self.start_btn.clicked.connect(self.start_reading)
        self.stop_btn.clicked.connect(self.stop_reading)
        self.pause_btn.clicked.connect(self.pause_reading)
        self.single_read_btn.clicked.connect(self.single_read)

        self.csv_browse_btn.clicked.connect(self.browse_csv_file)
        self.auto_csv_check.toggled.connect(self._update_storage_preview)
        self.manual_filename_edit.textChanged.connect(self._update_storage_preview)
        self.interval_spin.valueChanged.connect(lambda _=None: (self._update_start_readiness(), self._sync_live_summary()))
        self.batch_spin.valueChanged.connect(lambda _=None: self._update_start_readiness())

        self.clear_data_btn.clicked.connect(self.clear_data)
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.save_log_btn.clicked.connect(self.save_log)

        self.tags_list_widget.itemSelectionChanged.connect(self.on_tags_selection_changed)
        self.selected_tags_list.itemSelectionChanged.connect(self.on_selected_tags_selection_changed)
        self.tag_search_edit.textChanged.connect(self._filter_tags)
        self.add_manual_tag_btn.clicked.connect(self.add_manual_tags)
        self.manual_tag_edit.returnPressed.connect(self.add_manual_tags)

        self.ip_edit.textChanged.connect(lambda _=None: self._sync_connection_readiness())
        self.plc_brand_combo.currentTextChanged.connect(self._on_plc_brand_changed)
        self.rack_spin.valueChanged.connect(lambda _=None: self._sync_connection_readiness())
        self.slot_spin.valueChanged.connect(lambda _=None: self._sync_connection_readiness())
        self.port_spin.valueChanged.connect(lambda _=None: self._sync_connection_readiness())
        self.unit_spin.valueChanged.connect(lambda _=None: self._sync_connection_readiness())

        self._on_plc_brand_changed(self.plc_brand_combo.currentText())
        self.plc_worker.start()

    def auto_connect(self):
        self.connect_to_plc()


    def connect_to_plc(self):
        config = self._current_plc_config()
        brand = str(config.get("plc_brand") or "Allen-Bradley")
        ip = str(config.get("ip_address") or "").strip()

        if brand != "Simulation" and not ip:
            QMessageBox.warning(self, "Input Error", "Please enter PLC IP address")
            return

        self.progress_bar.setVisible(True)
        target = "simulation" if brand == "Simulation" else f"{brand} at {ip}"
        self.status_label.setText(f"Connecting to {target}…")
        self.connection_state_title.setText("Connecting…")
        self.connection_state_sub.setText(
            f"Opening a {config.get('plc_protocol', '')} session and validating communication."
        )
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)

        def do_connect():
            success = self.plc_worker.connect_plc(config)
            display_target = "Simulation" if brand == "Simulation" else ip
            self.connection_result.emit(bool(success), bool(self.plc_worker.simulation), display_target)

        threading.Thread(target=do_connect, daemon=True).start()

    def _handle_connection_result(self, success: bool, simulation: bool, ip: str):
        self.progress_bar.setVisible(False)
        self.is_connected = bool(success or simulation)

        if self.is_connected:
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.disconnect_btn.setText("Disconnect")

            # Driver capabilities decide which tag-selection actions are valid.
            self.get_tags_btn.setEnabled(self.plc_worker.supports_tag_browse)
            self.add_selected_btn.setEnabled(self.plc_worker.supports_tag_browse)
            self.add_all_btn.setEnabled(self.plc_worker.supports_tag_browse)
            self.add_specific_btn.setEnabled(self.plc_worker.supports_symbolic_tags)
            self.add_manual_tag_btn.setEnabled(self.plc_worker.supports_read or simulation)

            if simulation:
                self.mode_badge.setText("SIMULATION MODE")
                self.mode_badge.setStyleSheet(
                    "background:#FFF6DD;color:#9A6A05;border-radius:9px;padding:0 12px;font-weight:700;font-size:10px;"
                )
                self.status_label.setText("Simulation session ready. Opening tag selection…")
            else:
                self.mode_badge.setText(f"{self.plc_worker.brand.upper()} CONNECTED")
                self.mode_badge.setStyleSheet(
                    "background:#E8FAF0;color:#089957;border-radius:9px;padding:0 12px;font-weight:700;font-size:10px;"
                )
                self.status_label.setText(
                    f"{self.plc_worker.brand} connected at {ip}. Opening tag selection…"
                )

            self._sync_connection_readiness()
            self._sync_tag_capability_ui()
            self._update_start_readiness()
            self._sync_live_summary()

            self._show_step(2)
            if self.plc_worker.supports_tag_browse:
                self.get_all_tags()
            else:
                self.status_label.setText(
                    f"{self.plc_worker.brand} connected. Automatic tag browsing is unavailable; "
                    "enter PLC addresses manually."
                )
        else:
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.disconnect_btn.setText("Cancel")
            self.mode_badge.setText("PLC OFFLINE")
            self.mode_badge.setStyleSheet("")
            self.status_label.setText("Connection failed. Verify the PLC type/address and retry.")
            self._sync_connection_readiness()
            self._sync_tag_capability_ui()
            self._update_start_readiness()
            self._sync_live_summary()


    def disconnect_from_plc(self):
        self.plc_worker.stop_reading()
        self.plc_worker.disconnect_plc(emit_status=False)
        self.is_connected = False
        self.is_reading = False
        self.is_paused = False

        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setText("Cancel")

        self.get_tags_btn.setEnabled(False)
        self.select_all_btn.setEnabled(False)
        self.clear_selection_btn.setEnabled(False)
        self.add_selected_btn.setEnabled(False)
        self.add_all_btn.setEnabled(False)
        self.add_specific_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.single_read_btn.setEnabled(False)

        self.mode_badge.setText("PLC OFFLINE")
        self.mode_badge.setStyleSheet("")
        self.status_label.setText("Disconnected from PLC")
        self.log_message("Disconnected from PLC")
        self._sync_connection_readiness()
        self._sync_tag_capability_ui()
        self._update_start_readiness()
        self._sync_live_summary()
        self._show_step(1)


    def get_all_tags(self):
        if not self.is_connected:
            QMessageBox.warning(self, "PLC", "Connect to the PLC before discovering tags.")
            return
        if not self.plc_worker.supports_tag_browse:
            profile = self.plc_profiles.get(self.plc_worker.brand, {})
            QMessageBox.information(
                self,
                "Manual PLC addressing",
                f"Automatic tag discovery is not available for {self.plc_worker.brand}.\n\n"
                f"{profile.get('address_help', 'Enter PLC addresses manually on this page.')}",
            )
            self._sync_tag_capability_ui()
            return
        self.progress_bar.setVisible(True)
        self.status_label.setText(f"Retrieving tags from {self.plc_worker.brand} PLC…")
        self.get_tags_btn.setEnabled(False)
        self.plc_worker.get_all_tags()


    def on_tags_retrieved(self, tags: List[str]):
        """Handle retrieved tags and keep the guided tag-selection state in sync."""
        self.progress_bar.setVisible(False)
        self.get_tags_btn.setEnabled(self.is_connected)
        self.tags_list_widget.clear()

        if tags:
            tags_sorted = sorted(tags)
            self.available_tags = tags_sorted[:]
            self.tags_list_widget.addItems(tags_sorted)
            self.cached_all_tags = tags_sorted
            self.save_taglist_btn.setEnabled(True)

            self.tag_found_badge.setText(f"{len(tags_sorted)} FOUND")
            self.status_label.setText(f"Retrieved {len(tags_sorted)} tags from PLC")
            self.log_message(f"Successfully retrieved {len(tags_sorted)} tags from PLC")
            self.select_all_btn.setEnabled(True)
            self.clear_selection_btn.setEnabled(True)
            self.add_all_btn.setEnabled(True)

            if self.auto_save_taglist_check.isChecked():
                path = self.save_taglist_csv(self.cached_all_tags)
                self.taglist_csv_path_label.setText(Path(path).name)
                self.log_message(f"Auto-saved tag list to: {path}")
        else:
            self.available_tags = []
            self.cached_all_tags = []
            self.save_taglist_btn.setEnabled(False)
            self.tag_found_badge.setText("0 FOUND")
            self.status_label.setText("No tags found in PLC")
            self.log_message("No tags found in PLC")

        self._sync_tag_capability_ui()
        self._filter_tags(self.tag_search_edit.text())

    def select_all_tags(self):
        self.tags_list_widget.selectAll()
        self.log_message(f"Selected all {self.tags_list_widget.count()} tags")

    def clear_tags_selection(self):
        self.tags_list_widget.clearSelection()
        self.log_message("Cleared tag selection")

    def add_selected_tags(self):
        selected_items = self.tags_list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Information", "Please select tags to add")
            return
        added = 0
        for it in selected_items:
            tag = it.text()
            if tag not in self.display_tags:
                self.selected_tags_list.addItem(tag)
                self.display_tags.append(tag)
                self.display_to_plc[tag] = tag
                added += 1
        self.read_tags.clear()
        self.update_tags_count()
        self.log_message(f"Added {added} tags to monitoring list")

    def add_all_tags(self):
        if self.tags_list_widget.count() == 0:
            QMessageBox.information(self, "Information", "No tags available to add")
            return
        self.selected_tags_list.clear()
        self.display_tags.clear()
        self.display_to_plc.clear()
        for i in range(self.tags_list_widget.count()):
            tag = self.tags_list_widget.item(i).text()
            self.selected_tags_list.addItem(tag)
            self.display_tags.append(tag)
            self.display_to_plc[tag] = tag
        self.read_tags.clear()
        self.update_tags_count()
        self.log_message(f"Added all {len(self.display_tags)} tags to monitoring list")

    def add_specific_tags_automap(self):
        if not self.is_connected:
            QMessageBox.warning(self, "Warning", "Please connect to PLC first")
            return
        if not (self.plc_worker.supports_symbolic_tags or self.plc_worker.simulation):
            QMessageBox.information(
                self,
                "Predefined symbolic tags",
                f"The 300+ predefined list contains Allen-Bradley-style symbolic tag names and cannot be "
                f"auto-mapped generically on {self.plc_worker.brand}.\n\n"
                "Use Manual PLC tag / address for this controller type.",
            )
            return

        if self.is_reading:
            self.stop_reading()

        self.selected_tags_list.clear()
        self.display_tags = list(self.specific_tags)  # keep your labels
        self.update_tags_count()
        self.log_message(f"Loaded {len(self.display_tags)} predefined tags. Auto-mapping to real PLC names...")

        self.progress_bar.setVisible(True); QApplication.processEvents()

        # Build mapping
        self.display_to_plc, fixes, unresolved = self._map_specific_tags(self.display_tags)

        # Fill UI with display names
        self.selected_tags_list.addItems(self.display_tags)
        self.update_tags_count()

        # Prepare actual read set (skip unresolved)
        mapped = [p for p in self.display_to_plc.values() if p]
        # Deduplicate but keep order
        seen = set(); self.read_tags = []
        for t in mapped:
            if t not in seen:
                self.read_tags.append(t); seen.add(t)

        # Log
        for old, new in fixes:
            self.log_message(f"✓ Fixed tag: {old}  →  {new}")
        for bad in unresolved:
            self.log_message(f"✗ Could not resolve (skipped from read): {bad}")

        self.status_label.setText(f"Specific tags mapped. Readable: {len(self.read_tags)}, unresolved: {len(unresolved)}")
        self.progress_bar.setVisible(False)

    def remove_selected_tag(self):
        items = self.selected_tags_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Information", "Please select tags to remove")
            return
        for it in items:
            disp = it.text()
            self.selected_tags_list.takeItem(self.selected_tags_list.row(it))
            if disp in self.display_tags:
                self.display_tags.remove(disp)
            if disp in self.display_to_plc:
                self.display_to_plc.pop(disp, None)
        self.read_tags.clear()
        self.update_tags_count()
        self.log_message(f"Removed {len(items)} tags from monitoring list")

    def clear_all_tags(self):
        self.selected_tags_list.clear()
        self.display_tags.clear()
        self.display_to_plc.clear()
        self.read_tags.clear()
        self.update_tags_count()
        self.log_message("Cleared all selected tags")

    def on_tags_selection_changed(self):
        cnt = len(self.tags_list_widget.selectedItems())
        self.add_selected_btn.setText(f"Add selected ({cnt})" if cnt else "Add selected")
        self.add_selected_btn.setEnabled(cnt > 0 and self.is_connected)

    def on_selected_tags_selection_changed(self):
        self.remove_tag_btn.setEnabled(len(self.selected_tags_list.selectedItems()) > 0)


    def update_tags_count(self):
        count = len(self.display_tags)
        self.tags_count_label.setText(str(count))
        self.selected_count_label.setText(f"{count} TAG{'S' if count != 1 else ''}")

        if count > 0:
            self.tag_ready_title.setText("Ready for storage setup")
            self.tag_ready_sub.setText(f"{count} tag{'s' if count != 1 else ''} will be monitored.")
            self.tags_continue_btn.setEnabled(True)
        else:
            self.tag_ready_title.setText("Select one or more tags")
            self.tag_ready_sub.setText("The storage step unlocks after the monitoring set is ready.")
            self.tags_continue_btn.setEnabled(False)

        self.single_read_btn.setEnabled(count > 0 and self.is_connected and not self.is_reading)
        self._update_start_readiness()
        self._sync_live_summary()


    def start_reading(self):
        if not self.is_connected:
            QMessageBox.warning(self, "Warning", "Connect to the PLC before starting a reading session.")
            self._show_step(1)
            return

        if not self.display_tags:
            QMessageBox.warning(self, "Warning", "No tags selected for monitoring. Please select tags first.")
            self._show_step(2)
            return

        if not self.display_to_plc:
            self.add_specific_tags_automap()

        if not self._setup_storage():
            self._show_step(3)
            return

        if not self.read_tags:
            mapped = [p for p in self.display_to_plc.values() if p]
            seen = set()
            self.read_tags = []
            for t in mapped:
                if t not in seen:
                    self.read_tags.append(t)
                    seen.add(t)

        if not self.read_tags:
            QMessageBox.warning(self, "Warning", "No resolvable tags to read. Check the System Log for unmapped names.")
            return

        self.is_reading = True
        self.is_paused = False
        self.plc_worker.start_reading(
            self.read_tags,
            self.interval_spin.value(),
            self.batch_spin.value()
        )

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Pause reading")
        self.single_read_btn.setEnabled(False)

        self.records_count = 0
        self._update_records_count()
        self.log_message(
            f"Started continuous reading of {len(self.read_tags)} PLC tags "
            f"(display columns: {len(self.display_tags)})"
        )

        self._show_step(4)
        self._sync_live_summary()


    def stop_reading(self):
        self.is_reading = False
        self.is_paused = False
        self.plc_worker.stop_reading()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause reading")
        self.single_read_btn.setEnabled(bool(self.display_tags) and self.is_connected)

        self.data_storage.close()
        self.current_csv_path = None
        self.log_message("Stopped data collection")
        self._sync_live_summary()
        self._update_start_readiness()


    def single_read(self):
        if not self.display_tags:
            QMessageBox.warning(self, "Warning", "No tags selected for monitoring")
            return

        if not self.display_to_plc:
            self.add_specific_tags_automap()

        if not self._setup_storage():
            return

        if not self.read_tags:
            mapped = [p for p in self.display_to_plc.values() if p]
            seen = set()
            self.read_tags = []
            for t in mapped:
                if t not in seen:
                    self.read_tags.append(t)
                    seen.add(t)

        if not self.read_tags:
            QMessageBox.warning(self, "Warning", "No resolvable tags to read. Check the System Log for unmapped names.")
            return

        self.plc_worker.batch_size = self.batch_spin.value()
        self.plc_worker.read_single_cycle(self.read_tags)
        self.log_message("Performed single read operation")


    def _setup_storage(self):
        try:
            if not self.csv_check.isChecked():
                return True

            if self.data_storage.csv_file:
                return True

            if self.csv_directory is None:
                QMessageBox.warning(self, "CSV Folder Required", "Choose the CSV save folder before starting the reading session.")
                return False

            folder = Path(self.csv_directory)
            folder.mkdir(parents=True, exist_ok=True)

            if self.auto_csv_check.isChecked():
                filename = folder / f"plc_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            else:
                name = (self.manual_filename_edit.text() or "plc_data.csv").strip()
                if not name.lower().endswith(".csv"):
                    name += ".csv"
                filename = folder / name

            if not self.data_storage.setup_csv(str(filename)):
                QMessageBox.critical(self, "Error", "Failed to create CSV file")
                return False

            self.current_csv_path = filename
            self.csv_path_label.setText(str(filename))
            self.data_storage.use_csv = True
            self.data_storage.current_display_tags = list(self.display_tags)
            self.data_storage.display_to_plc = dict(self.display_to_plc)
            self.data_storage.write_headers()
            self.log_message(f"CSV storage setup: {filename}")
            self._sync_live_summary()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Storage setup failed: {str(e)}")
            return False


    def on_data_received(self, data: Dict):
        try:
            ts = data['timestamp']
            values_plc = data['values']
            self.data_storage.store_data(ts, values_plc)
            self._update_table(ts, values_plc)
            self.records_count += 1
            self._update_records_count()
            self._sync_live_summary()
        except Exception as e:
            self.log_message(f"Error processing data: {str(e)}")


    def _update_table(self, timestamp: datetime, values_plc: Dict[str, object]):
        tstr = timestamp.strftime("%H:%M:%S.%f")[:-3]
        if self.data_table.rowCount() != len(self.display_tags):
            self.data_table.setRowCount(len(self.display_tags))

        for i, disp in enumerate(self.display_tags):
            plc = self.display_to_plc.get(disp)
            val = 'N/A' if plc is None else values_plc.get(plc, 'N/A')

            if self.data_table.item(i, 0) is None:
                self.data_table.setItem(i, 0, QTableWidgetItem(disp))
            else:
                self.data_table.item(i, 0).setText(disp)

            if self.data_table.item(i, 1) is None:
                self.data_table.setItem(i, 1, QTableWidgetItem(str(val)))
            else:
                self.data_table.item(i, 1).setText(str(val))

            value_item = self.data_table.item(i, 1)
            if 'Error' in str(val):
                value_item.setBackground(QColor("#FFF0F1"))
                value_item.setForeground(QColor("#B42335"))
            else:
                value_item.setBackground(QColor("#FFFFFF"))
                value_item.setForeground(QColor("#0E1729"))

            if self.data_table.item(i, 2) is None:
                self.data_table.setItem(i, 2, QTableWidgetItem(tstr))
            else:
                self.data_table.item(i, 2).setText(tstr)

        self.data_table.resizeRowsToContents()


    def _update_records_count(self):
        self.records_count_label.setText(str(self.records_count))
        if hasattr(self, "records_metric"):
            self.records_metric[1].setText(f"{self.records_count:,}")


    def on_status_update(self, message: str):
        self.status_label.setText(message)
        self.log_message(f"INFO: {message}")
        self._sync_live_summary()

    def on_error(self, message: str):
        # If we are in simulation, connection errors are not fatal -> no popup
        if self.plc_worker.simulation and ("connection failed" in message.lower() or "timed out" in message.lower()):
            self.status_label.setText(f"SIM MODE: {message}")
            self.log_message(f"SIM INFO: {message}")
            return

        self.status_label.setText(f"Error: {message}")
        self.log_message(f"ERROR: {message}")
        QMessageBox.critical(self, "Error", message)


    def log_message(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {message}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def clear_data(self):
        self.data_table.setRowCount(0)
        self.records_count = 0
        self._update_records_count()
        self.log_message("Cleared data display")

    def clear_log(self):
        self.log_text.clear()
        self.log_message("Log cleared")

    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Log File", f"plc_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", "Text Files (*.txt)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                self.log_message(f"Log saved to {filename}")
                QMessageBox.information(self, "Success", f"Log saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save log: {str(e)}")


    def browse_csv_file(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose CSV Save Folder",
            str(self.csv_directory or Path.cwd())
        )
        if folder:
            self.csv_directory = Path(folder)
            self.csv_folder_edit.setText(str(self.csv_directory))
            self._update_storage_preview()
            self._update_start_readiness()

    def save_taglist_csv(self, tags: List[str], filename: str = None) -> str:
        """Save the full PLC tag list to a CSV (1 tag per line, with 'tag' header). Returns path."""
        from pathlib import Path
        import csv
        from datetime import datetime

        if filename is None:
            filename = str(Path.cwd() / f"plc_taglist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['tag'])
                for t in tags:
                    w.writerow([t])
            return filename
        except Exception as e:
            self.log_message(f"Failed to save tag list CSV: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save tag list CSV:\n{e}")
            return filename

    def save_taglist_dialog(self):
        """Manual Save As… for the full PLC tag list CSV."""
        if not self.cached_all_tags:
            QMessageBox.information(self, "No Tags", "No tags loaded yet. Click 'Get All Tags' first.")
            return
        from datetime import datetime
        from pathlib import Path

        default_name = f"plc_taglist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Tag List CSV", default_name, "CSV Files (*.csv)"
        )
        if filename:
            path = self.save_taglist_csv(self.cached_all_tags, filename)
            self.taglist_csv_path_label.setText(Path(path).name)
            self.log_message(f"Tag list saved to: {path}")
            QMessageBox.information(self, "Saved", f"Saved {len(self.cached_all_tags)} tags to:\n{path}")


    def closeEvent(self, event):
        if self.is_reading or self.is_paused:
            self.stop_reading()
        if self.is_connected:
            self.disconnect_from_plc()
        else:
            self.plc_worker.disconnect_plc(emit_status=False)
        self.plc_worker.wait(1000)
        self.data_storage.close()
        self.log_message("Application closed")
        event.accept()


def main():
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("PLC Data Monitor")
    app.setApplicationVersion("2.2.0")
    app.setOrganizationName("Industrial Automation")
    app.setStyle('Fusion')
    app.setFont(QFont("Segoe UI", 9)) 
    window = ModernPLCWindow()
    window.setWindowFlags(Qt.Window)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
