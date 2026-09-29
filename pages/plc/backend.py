"""Backend for the EYRES PyQt6 PLC Live page.

Migrated from the existing PLC_GUI.py while keeping the production behavior:
- Allen-Bradley EtherNet/IP through pylogix.PLC
- fallback simulation mode
- PLC tag discovery
- batched continuous reads
- single-cycle reads
- predefined 300+ tag auto-mapping
- CSV / optional Mongo storage
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal


SPECIFIC_TAGS = ['ai_C_HydOil_LevelPV', 'ai_C_MainPanel_TempPV', 'ai_C_TBOPanel_TempPV', 'ai_Hydraulic_oil_Temp', 'ai_LH_Guide_Rod1_Pos', 'ai_LH_Guide_Rod2_Pos', 'ai_LH_Humidity_Sensor', 'ai_LH_Jacket_Drain_TempPV', 'ai_LH_Loader_LVDT', 'ai_LH_PCI_Bead_Lift', 'ai_LH_PCI_Green_Pressure', 'ai_LH_PCI_Yellow_Pressure', 'ai_LH_Platen_Drain_Temp_PV', 'ai_LH_Press_IntPressurePV', 'ai_LH_Press_IntTempPV', 'ai_LH_Press_LVDT', 'ai_LH_Press_ShapingPV', 'ai_LH_Pump_PressurePV', 'ai_LH_Rio_Box_Temp', 'ai_LH_SQ_PT', 'ai_LH_TBLBox_TempPV', 'ai_LH_TBPLBox_TempPV', 'ai_LH_UnLoader_LVDT', 'ai_RH_Guide_Rod1_Pos', 'ai_RH_Guide_Rod2_Pos', 'ai_RH_Humidity_Sensor', 'ai_RH_Jacket_Drain_TempPV', 'ai_RH_Loader_LVDT', 'ai_RH_PCI_Bead_Lift', 'ai_RH_PCI_Green_Pressure', 'ai_RH_PCI_Yellow_Pressure', 'ai_RH_Platen_Drain_Temp_PV', 'ai_RH_Press_IntPressurePV', 'ai_RH_Press_IntTempPV', 'ai_RH_Press_LVDT', 'ai_RH_Press_ShapingPV', 'ai_RH_Pump_PressurePV', 'ai_RH_Rio_Box_Temp', 'ai_RH_SQ_PT', 'ai_RH_TBLBox_TempPV', 'ai_RH_TBPLBox_TempPV', 'ai_RH_UnLoader_LVDT', 'ao_LH_BSP_Platen', 'ao_LH_HydPumpPressure_CV', 'ao_LH_Internal_HPS_CV', 'ao_LH_JacketHeatingSteam_CV', 'ao_LH_Loader_UpDown_CV', 'ao_LH_PlatenHeatingSteam_CV', 'ao_LH_Platen_Bottom', 'ao_LH_Press_UpDown_CV', 'ao_LH_Shaping_CV', 'ao_LH_TopRing_UpDown_CV', 'ao_LH_Unloader_UpDown_CV', 'ao_RH_BSP_Platen', 'ao_RH_HydPumpPressure_CV', 'ao_RH_Internal_HPS_CV', 'ao_RH_JacketHeatingSteam_CV', 'ao_RH_Loader_UpDown_CV', 'ao_RH_PlatenHeatingSteam_CV', 'ao_RH_Platen_Bottom', 'ao_RH_Press_UpDown_CV', 'ao_RH_Shaping_CV', 'ao_RH_TopRing_UpDown_CV', 'ao_RH_Unloader_UpDown_CV', 'di_C_24DC_MCB_trip', 'di_C_Auto_Shaping', 'di_C_Auto_Vaccum', 'di_C_CoolingOil_Filter', 'di_C_EStop_Enable_FB', 'di_C_LampAndFan_MCB_Trip', 'di_C_LampAndFan_RCCB_MCB_Trip', 'di_C_OilCoolingPump_MPCB_Trip', 'di_C_PanelDoorSwitchOn', 'di_C_PhaseSequnece_and_Loss_Detector', 'di_C_PumpMotor_MPCB_Trip', 'di_C_Reset', 'di_LH_Bayonut_Unlock_SSW', 'di_LH_Bayonut_lock_SSW', 'di_LH_BeadWidth_adj_Dec_SSW', 'di_LH_BeadWidth_adj_Homing', 'di_LH_BeadWidth_adj_Inc_SSW', 'di_LH_BeadWidth_adj_Over_Travel', 'di_LH_BeadWidth_adj_Teeth_Counter', 'di_LH_C_PressureLine_Filter', 'di_LH_C_ReturnLine_Filter', 'di_LH_Conveyor_Motor_MPCB_Trip', 'di_LH_Conveyor_On', 'di_LH_CureEnable_FB', 'di_LH_GTH_InPosition_FB', 'di_LH_GTH_TyreSensor', 'di_LH_LoaderChuck_Close_FB', 'di_LH_LoaderChuck_Open_FB', 'di_LH_LoaderChuck_Open_PS', 'di_LH_Loader_Enable_FB', 'di_LH_Loader_GT_Sensor', 'di_LH_Loader_Inside_Press_FB', 'di_LH_Loader_Outside_Press_FB', 'di_LH_Loader_Overtravel', 'di_LH_Loader_Tyre_Sensing_2', 'di_LH_LowerRing_Down_FB', 'di_LH_LowerRing_Up_FB', 'di_LH_MainInletAirOn_PS', 'di_LH_PCI_Auto_SSW', 'di_LH_PCI_Bayonut_Lock', 'di_LH_PCI_Bayonut_Lock1_MovingPart', 'di_LH_PCI_Bayonut_UnLock1_MovingPart', 'di_LH_PCI_Bayonut_Unlock', 'di_LH_PCI_Deflation_Green_SSW', 'di_LH_PCI_Deflation_Yellow_SSW', 'di_LH_PCI_Enable_FB', 'di_LH_PCI_FaultReset_PB', 'di_LH_PCI_Inflation_Green_SSW', 'di_LH_PCI_Inflation_Yellow_SSW', 'di_LH_PCI_Manual_SSW', 'di_LH_PCI_RimClose_SSW', 'di_LH_PCI_RimOpen_SSW', 'di_LH_PCI_Rotation_Green', 'di_LH_PCI_Rotation_Green_SSW', 'di_LH_PCI_Rotation_Yellow', 'di_LH_PCI_Rotation_Yellow_SSW', 'di_LH_PCI_Tire_Detect_PHS', 'di_LH_PciRim_BeadWidth_adj_Motor_Trip', 'di_LH_Press_Auto_Mode', 'di_LH_Press_Enable_FB', 'di_LH_Press_MC_Mode', 'di_LH_Press_Manual_Mode', 'di_LH_Press_Unlocked_FB1', 'di_LH_Press_Unlocked_FB2', 'di_LH_RimFullup_Lock_Unlock', 'di_LH_Rotation_Manual_lock', 'di_LH_SMO_Extend_FB', 'di_LH_SMO_Lock_FB', 'di_LH_SMO_Retract_FB', 'di_LH_SMO_Unlock_FB', 'di_LH_TBL24DC_MCB_Trip', 'di_LH_UnLoader_Intermediate', 'di_LH_UnloaderChuck_Close_FB', 'di_LH_UnloaderChuck_Open_FB', 'di_LH_UnloaderChuck_Open_PS', 'di_LH_Unloader_Close_Ssw', 'di_LH_Unloader_Down_SSW', 'di_LH_Unloader_Enable_FB', 'di_LH_Unloader_In_Ssw', 'di_LH_Unloader_Open_SSW', 'di_LH_Unloader_Out_Ssw', 'di_LH_Unloader_PCI_In_FB', 'di_LH_Unloader_Pci_SSW', 'di_LH_Unloader_PressIn_FB', 'di_LH_Unloader_PressOut_FB', 'di_LH_Unloader_Press_SSW', 'di_LH_Unloader_TyreSensor', 'di_LH_Unloader_Up_SSW', 'di_Load_Enable', 'di_RH_Bayonut_Lock_SSW', 'di_RH_Bayonut_Unlock_SSW', 'di_RH_BeadWidth_adj_Homing', 'di_RH_BeadWidth_adj_Over_travel', 'di_RH_BeadWidth_adj_teeth_counter', 'di_RH_C_PressureLine_Filter', 'di_RH_C_ReturnLine_Filter', 'di_RH_Conveyor_On', 'di_RH_CureEnable_FB', 'di_RH_GTH_InPosition_FB', 'di_RH_GTH_TyreSensor', 'di_RH_LoaderChuck_Close_FB', 'di_RH_LoaderChuck_Open_FB', 'di_RH_LoaderChuck_Open_PS', 'di_RH_Loader_Enable_FB', 'di_RH_Loader_GT_Sensor', 'di_RH_Loader_Inside_Press_FB', 'di_RH_Loader_Outside_Press_FB', 'di_RH_Loader_Overtravel', 'di_RH_Loader_Tyre_Sensing_2', 'di_RH_LowerRing_Down_FB', 'di_RH_LowerRing_Up_FB', 'di_RH_MainInletAirOn_PS', 'di_RH_PCI_Auto_SSW', 'di_RH_PCI_Bayonut_Lock', 'di_RH_PCI_Bayonut_UnLock', 'di_RH_PCI_Bayonut_Lock1_MovingPart', 'di_RH_PCI_Bayonut_UnLock1_MovingPart', 'di_RH_PCI_Deflation_Green_SSW', 'di_RH_PCI_Deflation_Yellow_SSW', 'di_RH_PCI_Enable_FB', 'di_RH_PCI_FaultReset_PB', 'di_RH_PCI_Inflation_Green_SSW', 'di_RH_PCI_Inflation_Yellow_SSW', 'di_RH_PCI_Manual_SSW', 'di_RH_PCI_RimClose_SSW', 'di_RH_PCI_RimFullUp_Lock_Unlock', 'di_RH_PCI_RimOpen_SSW', 'di_RH_PCI_Rotation_Green', 'di_RH_PCI_Rotation_Green_SSW', 'di_RH_PCI_Rotation_Yellow', 'di_RH_PCI_Rotation_Yellow_SSW', 'di_RH_PCI_Tire_Detect_PHS', 'di_RH_PciRim_BeadWidth_adj_Dec_SSW', 'di_RH_PciRim_BeadWidth_adj_Inc_SSW', 'di_RH_PciRim_BeadWidth_adj_Motor_Trip', 'di_RH_Press_Auto_Mode', 'di_RH_Press_Enable_FB', 'di_RH_Press_MC_Mode', 'di_RH_Press_Manual_Mode', 'di_RH_Press_Unlocked_FB1', 'di_RH_Press_Unlocked_FB2', 'di_RH_Rotation_Manual_Lock', 'di_RH_SMO_Extend_FB', 'di_RH_SMO_Lock_FB', 'di_RH_SMO_Retract_FB', 'di_RH_SMO_Unlock_FB', 'di_RH_TBR_24DC_MCB_Trip', 'di_RH_UnLoader_Intermediate', 'di_RH_UnloaderChuck_Close_FB', 'di_RH_UnloaderChuck_Open_FB', 'di_RH_UnloaderChuck_Open_PS', 'di_RH_Unloader_Close_SSW', 'di_RH_Unloader_Down_SSW', 'di_RH_Unloader_Enable_FB', 'di_RH_Unloader_In_SSW', 'di_RH_Unloader_Open_SSW', 'di_RH_Unloader_Out_SSW', 'di_RH_Unloader_PCI_In_FB', 'di_RH_Unloader_PCI_SSW', 'di_RH_Unloader_PressIn_FB', 'di_RH_Unloader_PressOut_FB', 'di_RH_Unloader_Press_SSW', 'di_RH_Unloader_TyreSensor', 'di_RH_Unloader_Up_SSW', 'di_Softstarter_Bypassed', 'di_Softstarter_Overload', 'di_Softstarter_Run', 'do_C_AC_Lamp_On', 'do_C_E_Stop_Lamp', 'do_C_OilCooling_Motor_On', 'do_C_Pump_ON', 'do_C_SoftStarter_ON', 'do_LH_BlockOff_On', 'do_LH_C_CureAir_Off', 'do_LH_Circulation_Drain_On', 'do_LH_Deflation_Green', 'do_LH_Deflation_Yellow', 'do_LH_Green_Tower_Lamp', 'do_LH_HPS_On', 'do_LH_Hooter_Tower_Lamp', 'do_LH_Internal_PS_Lamp', 'do_LH_LoaderChuck_Close', 'do_LH_LoaderChuck_Open', 'do_LH_Loader_Down', 'do_LH_Loader_Press_In', 'do_LH_Loader_Press_Out', 'do_LH_Loader_Up', 'do_LH_LowerRing_Down', 'do_LH_LowerRing_Up', 'do_LH_MD_On', 'do_LH_Mould_Blow_Out', 'do_LH_N2_Leak_Test_Valve_Off', 'do_LH_N2_Leak_Test_Valve_On', 'do_LH_N2_Purging_On', 'do_LH_OpenVacuum_On', 'do_LH_PCI_Bayonut_lock', 'do_LH_PCI_Green_Inflation', 'do_LH_PCI_Green_Inflation_Lamp', 'do_LH_PCI_Lifter_Down', 'do_LH_PCI_Lifter_SlowSpeed', 'do_LH_PCI_Lifter_UP', 'do_LH_PCI_Pos1Arm_In', 'do_LH_PCI_Pos1Arm_Out', 'do_LH_PCI_Pos1Deflate', 'do_LH_PCI_Pos1TyreStripper', 'do_LH_PCI_Pos2Arm_In', 'do_LH_PCI_Pos2Arm_Out', 'do_LH_PCI_Reset_Lamp', 'do_LH_PCI_Rotation_Green', 'do_LH_PCI_Rotation_Yellow', 'do_LH_PCI_Saf_Lock1', 'do_LH_PCI_Unloader_In', 'do_LH_PCI_Unloader_Out', 'do_LH_PCI_Yellow_Inflation', 'do_LH_PCI_Yellow_Inflation_Lamp', 'do_LH_PressCV_Enable', 'do_LH_Press_Close_Lock', 'do_LH_Press_Lock1', 'do_LH_Press_Lock2', 'do_LH_Red_Tower_Lamp', 'do_LH_Return_MD_On', 'do_LH_SMO_Extend', 'do_LH_SMO_Lock', 'do_LH_SMO_Retract', 'do_LH_SMO_UnLock', 'do_LH_SQBooster_Enable', 'do_LH_SQ_Disable_1', 'do_LH_SQ_Disable_2', 'do_LH_SQ_PneumaticBooster', 'do_LH_SQ_PumpBooster', 'do_LH_SQ_SlowSpeed', 'do_LH_Shapping_On', 'do_LH_Squeeze_Extend', 'do_LH_Squeeze_Retract', 'do_LH_TBI_Cooler_On', 'do_LH_TBLCooler_On', 'do_LH_TBPLCooler_On', 'do_LH_TopRing_Down', 'do_LH_TopRing_Slow_Speed', 'do_LH_TopRing_Up', 'do_LH_UnloaderChuck_Close', 'do_LH_UnloaderChuck_Open', 'do_LH_Unloader_Down', 'do_LH_Unloader_SlowSpeed', 'do_LH_Unloader_SwingIn', 'do_LH_Unloader_SwingOut', 'do_LH_Unloader_Up', 'do_LH_Vacuum_On', 'do_LH_Vent_On', 'do_LH_Yellow_Tower_Lamp', 'do_LH_loader_SlowSpeed', 'do_Oil_Cooling_On', 'do_Pump_On', 'do_RH_BlockOff_On', 'do_RH_C_CureAir_Off', 'do_RH_C_Pump_ON', 'do_RH_Circulation_Drain_On', 'do_RH_Deflation_Green', 'do_RH_Deflation_Yellow', 'do_RH_Green_Tower_Lamp', 'do_RH_HPS_On', 'do_RH_Hooter_Tower_Lamp', 'do_RH_Internal_PS_Lamp', 'do_RH_LoaderChuck_Close', 'do_RH_LoaderChuck_Open', 'do_RH_Loader_Down', 'do_RH_Loader_Press_In', 'do_RH_Loader_Press_Out', 'do_RH_Loader_SlowSpeed', 'do_RH_Loader_Up', 'do_RH_LowerRing_Down', 'do_RH_LowerRing_Up', 'do_RH_MD_On', 'do_RH_Mould_Blow_Out', 'do_RH_N2_Leak_Test_Valve_Off', 'do_RH_N2_Leak_Test_Valve_On', 'do_RH_N2_Purging_On', 'do_RH_OpenVacuum_On', 'do_RH_PCI_Bayonut_lock', 'do_RH_PCI_Green_Inflation', 'do_RH_PCI_Green_Inflation_Lamp', 'do_RH_PCI_Lifter_Down', 'do_RH_PCI_Lifter_SlowSpeed', 'do_RH_PCI_Lifter_Up', 'do_RH_PCI_Pos1Arm_In', 'do_RH_PCI_Pos1Arm_Out', 'do_RH_PCI_Pos1Deflate', 'do_RH_PCI_Pos1TyreStripper', 'do_RH_PCI_Pos2Arm_In', 'do_RH_PCI_Pos2Arm_Out', 'do_RH_PCI_Reset_Lamp', 'do_RH_PCI_Rotation_Green', 'do_RH_PCI_Rotation_Yellow', 'do_RH_PCI_Saf_Lock1', 'do_RH_PCI_Unloader_In', 'do_RH_PCI_Unloader_Out', 'do_RH_PCI_Yellow_Inflation', 'do_RH_PCI_Yellow_Inflation_Lamp', 'do_RH_PressCV_Enable', 'do_RH_Press_Close_Lock', 'do_RH_Press_Lock1', 'do_RH_Press_Lock2', 'do_RH_Red_Tower_Lamp', 'do_RH_Return_MD_On', 'do_RH_SMO_Extend', 'do_RH_SMO_Lock', 'do_RH_SMO_Retract', 'do_RH_SMO_UnLock', 'do_RH_SQBooster_Enable', 'do_RH_SQ_Disable_1', 'do_RH_SQ_Disable_2', 'do_RH_SQ_PneumaticBooster', 'do_RH_SQ_PumpBooster', 'do_RH_SQ_SlowSpeed', 'do_RH_Shapping_On', 'do_RH_Squeeze_Extend', 'do_RH_Squeeze_Retract', 'do_RH_TBI_Cooler_On', 'do_RH_TBLCooler_On', 'do_RH_TBPLCooler_On', 'do_RH_TopRing_Down', 'do_RH_TopRing_Slow_Speed', 'do_RH_TopRing_Up', 'do_RH_UnloaderChuck_Close', 'do_RH_UnloaderChuck_Open', 'do_RH_Unloader_Down', 'do_RH_Unloader_SlowSpeed', 'do_RH_Unloader_SwingIn', 'do_RH_Unloader_SwingOut', 'do_RH_Unloader_Up', 'do_RH_Vacuum_On', 'do_RH_Vent_On', 'do_RH_Yellow_Tower_Lamp', 'do_Reset', 'do_S_C_ControlPower_On', 'EP1_Step[1].X', 'EP1_Step[2].X', 'EP1_Step[3].X', 'EP1_Step[4].X', 'EP1_Step[5].X', 'EP1_Step[6].X', 'EP1_Step[7].X', 'EP1_Step[8].X', 'EP1_Step[9].X', 'EP1_Step[10].X', 'EP2_Step[0].X', 'EP2_Step[1].X', 'EP2_Step[2].X', 'EP2_Step[3].X', 'EP2_Step[4].X', 'EP2_Step[5].X', 'EP2_Step[6].X', 'EP2_Step[7].X', 'EP2_Step[8].X', 'EP2_Step[9].X', 'EP2_Step[10].X', 'EP2_Step[11].X', 'EP2_Step[12].X', 'EP2_Step[13].X', 'EP2_Step[14].X', 'EP2_Step[15].X', 'EP2_Step[16].X', 'EP2_Step[17].X', 'EP2_Step[18].X', 'EP2_Step[19].X', 'EP2_Step[20].X', 'EP3_Step[0].X', 'EP3_Step[1].X', 'EP3_Step[2].X', 'EP3_Step[3].X', 'EP3_Step[4].X', 'EP3_Step[5].X', 'EP3_Step[6].X', 'EP3_Step[7].X', 'EP3_Step[8].X', 'EP3_Step[9].X', 'EP3_Step[10].X', 'EP3_Step[11].X', 'EP3_Step[12].X', 'EP3_Step[13].X', 'EP3_Step[14].X', 'EP3_Step[15].X', 'EP3_Step[16].X', 'EP3_Step[17].X', 'EP3_Step[18].X', 'EP3_Step[19].X', 'EP3_Step[20].X', 'EP3_Step[21].X', 'EP3_Step[22].X', 'EP3_Step[23].X', 'EP3_Step[24].X', 'EP3_Step[25].X', 'EP3_Step[26].X', 'EP3_Step[27].X', 'EP3_Step[28].X', 'EP3_Step[29].X', 'EP3_Step[30].X', 'EP3_Step[31].X', 'EP3_Step[32].X', 'EP3_Step[33].X', 'EP3_Step[34].X', 'EP3_Step[35].X', 'EP3_Step[36].X', 'LH.Curing.Step_No', 'LH.Curing_Interlock_Ok', 'LH.Initiate_Curing', 'LH.Curing.Completed', 'LH.Machine_Idle', 'LH_Curing.Active']


class PLCWorker(QThread):
    data_received = pyqtSignal(dict)
    status_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    tags_retrieved = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plc = None
        self.ip_address = "192.168.1.1"
        self.slot = 0
        self.tags_to_read: List[str] = []
        self.is_reading = False
        self.read_interval = 1000
        self.batch_size = 50
        self.simulation = False
        self.sim_counter = 0
        self._shutdown_requested = False

    def _fake_value_for_tag(self, tag: str, step: int):
        lower = tag.lower()
        if lower.startswith(("di_", "do_")) or lower.endswith(".x"):
            return step % 2
        base = hash(tag) % 100
        return base + (step % 10)

    def connect_plc(self, ip: str, slot: int):
        try:
            from pylogix import PLC

            self.ip_address = str(ip)
            self.slot = int(slot)

            plc = PLC()
            plc.IPAddress = self.ip_address
            plc.ProcessorSlot = self.slot

            result = plc.GetPLCTime()
            if getattr(result, "Status", "") == "Success":
                self.plc = plc
                self.simulation = False
                self.status_signal.emit(f"Connected to PLC at {self.ip_address}")
                return True

            self.plc = None
            self.simulation = True
            self.error_signal.emit(f"PLC connection failed: {getattr(result, 'Status', 'Unknown')}")
            self.status_signal.emit("Switching to SIMULATION mode (dummy PLC data).")
            return False

        except Exception as exc:
            self.plc = None
            self.simulation = True
            self.error_signal.emit(f"Connection error: {exc}")
            self.status_signal.emit("Switching to SIMULATION mode (dummy PLC data).")
            return False

    def disconnect_plc(self):
        self.stop_reading()
        plc = self.plc
        self.plc = None
        self.simulation = False
        try:
            if plc is not None and hasattr(plc, "Close"):
                plc.Close()
        except Exception:
            pass
        self.status_signal.emit("Disconnected from PLC")

    def get_all_tags(self):
        try:
            if self.simulation:
                tags = [f"SimTag{i}" for i in range(1, 51)]
                self.tags_retrieved.emit(tags)
                self.status_signal.emit(f"SIM: generated {len(tags)} fake tags")
                return

            if self.plc is None:
                self.error_signal.emit("Not connected to PLC")
                return

            response = self.plc.GetTagList()
            if getattr(response, "Status", "") == "Success":
                tags = [tag.TagName for tag in response.Value]
                self.tags_retrieved.emit(tags)
                self.status_signal.emit(f"Retrieved {len(tags)} tags")
            else:
                self.error_signal.emit(f"Failed to get tags: {getattr(response, 'Status', 'Unknown')}")
        except Exception as exc:
            self.error_signal.emit(f"Error getting tags: {exc}")

    def start_reading(self, tags: List[str], interval: int, batch_size: int):
        self.tags_to_read = list(tags)
        self.read_interval = max(100, int(interval))
        self.batch_size = max(1, int(batch_size))
        self.is_reading = True
        self.status_signal.emit(
            f"Started reading {len(tags)} tags every {self.read_interval}ms "
            f"(batch={self.batch_size})"
        )

    def stop_reading(self):
        self.is_reading = False
        self.status_signal.emit("Stopped reading")

    def read_one(self, tag: str):
        try:
            if self.simulation:
                self.sim_counter += 1
                return SimpleNamespace(
                    TagName=tag,
                    Value=self._fake_value_for_tag(tag, self.sim_counter),
                    Status="Success",
                )
            if self.plc is None:
                return None
            return self.plc.Read(tag)
        except Exception:
            return None

    def read_single_cycle(self, tags: List[str]):
        try:
            if self.simulation:
                self.sim_counter += 1
                data = {"timestamp": datetime.now(), "values": {}}
                for tag in tags:
                    data["values"][tag] = self._fake_value_for_tag(tag, self.sim_counter)
                self.data_received.emit(data)
                return

            if self.plc is None:
                self.error_signal.emit("Not connected to PLC")
                return

            data = {"timestamp": datetime.now(), "values": {}}
            batch = max(1, int(self.batch_size))

            for index in range(0, len(tags), batch):
                chunk = tags[index:index + batch]
                try:
                    results = self.plc.Read(chunk)
                    if not isinstance(results, list):
                        results = [results]
                    for response in results:
                        tag_name = getattr(response, "TagName", None)
                        if not tag_name:
                            continue
                        if getattr(response, "Status", "") == "Success":
                            data["values"][tag_name] = response.Value
                        else:
                            data["values"][tag_name] = f"Error:{getattr(response, 'Status', 'Unknown')}"
                except Exception as exc:
                    for tag in chunk:
                        data["values"][tag] = f"Error:{type(exc).__name__}"

            self.data_received.emit(data)

        except Exception as exc:
            self.error_signal.emit(f"Read error: {exc}")

    def read_sim_cycle(self, tags: List[str]):
        import random

        self.sim_counter += 1
        data = {"timestamp": datetime.now(), "values": {}}

        for tag in tags:
            lower = tag.lower()
            if lower.startswith(("di_", "do_")) or lower.endswith(".x"):
                value = random.choice([0, 1])
            elif lower.startswith("ai_") or any(word in lower for word in ("temp", "pressure", "level")):
                value = round(10 + random.random() * 90, 2)
            else:
                value = random.randint(0, 100)
            data["values"][tag] = value

        self.data_received.emit(data)

    def run(self):
        while not self._shutdown_requested:
            if self.is_reading and self.tags_to_read:
                if self.simulation or self.plc is None:
                    self.read_sim_cycle(self.tags_to_read)
                else:
                    self.read_single_cycle(self.tags_to_read)
                self.msleep(self.read_interval)
            else:
                self.msleep(100)

    def shutdown(self):
        self.is_reading = False
        self._shutdown_requested = True
        self.disconnect_plc()


class MongoDBHandler:
    def __init__(self, connection_string: str = "mongodb://localhost:27017/"):
        self.connection_string = connection_string
        self.client = None
        self.db = None
        self.collection = None

    def connect(self, db_name: str = "plc_data", collection_name: str = "readings"):
        try:
            import pymongo
            self.client = pymongo.MongoClient(self.connection_string)
            self.db = self.client[db_name]
            self.collection = self.db[collection_name]
            return True
        except Exception as exc:
            print(f"MongoDB connection error: {exc}")
            return False

    def insert_data(self, data: Dict):
        try:
            if self.collection is not None:
                doc = dict(data)
                if isinstance(doc.get("timestamp"), datetime):
                    doc["timestamp"] = doc["timestamp"].isoformat()
                self.collection.insert_one(doc)
                return True
        except Exception as exc:
            print(f"MongoDB insert error: {exc}")
        return False

    def close(self):
        try:
            if self.client is not None:
                self.client.close()
        except Exception:
            pass
        self.client = None
        self.collection = None


class DataStorage:
    def __init__(self):
        self.csv_file = None
        self.csv_writer = None
        self.mongo_handler = None
        self.use_csv = True
        self.use_mongo = False
        self.current_display_tags: List[str] = []
        self.display_to_plc: Dict[str, Optional[str]] = {}

    def setup_csv(self, filename: str):
        self.close_csv()
        try:
            path = Path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.csv_file = path.open("w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(
                self.csv_file,
                quoting=csv.QUOTE_ALL,
                escapechar="\\",
            )
            return True
        except Exception as exc:
            print(f"CSV setup error: {exc}")
            self.csv_file = None
            self.csv_writer = None
            return False

    def setup_mongo(self, connection_string: str, db_name: str, collection_name: str):
        self.mongo_handler = MongoDBHandler(connection_string)
        return self.mongo_handler.connect(db_name, collection_name)

    def write_headers(self):
        if self.csv_writer is not None and self.csv_file is not None:
            self.csv_writer.writerow(["timestamp"] + self.current_display_tags)
            self.csv_file.flush()

    def store_data(self, timestamp: datetime, values_by_plc: Dict[str, object]):
        if self.use_csv and self.csv_writer is not None:
            try:
                row = [timestamp.isoformat()]
                for display in self.current_display_tags:
                    plc_name = self.display_to_plc.get(display)
                    value = "" if plc_name is None else values_by_plc.get(plc_name, "")
                    row.append(self._clean_for_csv(value))
                self.csv_writer.writerow(row)
                self.csv_file.flush()
            except Exception as exc:
                print(f"CSV write error: {exc}")

        if self.use_mongo and self.mongo_handler is not None:
            doc = {"timestamp": timestamp}
            for display in self.current_display_tags:
                plc_name = self.display_to_plc.get(display)
                doc[display] = None if plc_name is None else values_by_plc.get(plc_name)
            self.mongo_handler.insert_data(doc)

    @staticmethod
    def _clean_for_csv(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="ignore").strip()
            except Exception:
                return value.hex()

        text = str(value)
        for old, new in {
            ",": ";",
            '"': "'",
            "\n": " ",
            "\r": " ",
            "\t": " ",
            "\0": "",
            "\\": "/",
        }.items():
            text = text.replace(old, new)
        if len(text) > 1000:
            text = text[:1000] + "...(truncated)"
        return text

    def close_csv(self):
        try:
            if self.csv_file is not None:
                self.csv_file.close()
        except Exception:
            pass
        self.csv_file = None
        self.csv_writer = None

    def close(self):
        self.close_csv()
        if self.mongo_handler is not None:
            self.mongo_handler.close()
        self.mongo_handler = None


class TagMapper:
    """Preserves the predefined-tag mapping behavior from the previous PLC GUI."""

    def __init__(self, worker: PLCWorker, available_tags: List[str]):
        self.worker = worker
        self.available_tags = list(available_tags or [])

    @staticmethod
    def _tok(value: str) -> List[str]:
        return [token for token in re.split(r"[^0-9a-zA-Z]+", value.lower()) if token]

    @staticmethod
    def _ep_desired_parts(tag: str) -> Optional[Tuple[int, int, str]]:
        match = re.match(r"^(EP)([1-3])_Step\[(\d+)\]\.(X)$", tag, re.IGNORECASE)
        if not match:
            return None
        _, ep_text, index_text, member = match.groups()
        return int(ep_text), int(index_text), member.lower()

    @staticmethod
    def _generate_ep_patterns(ep: int, index: int, member: str):
        index2 = f"{index:02d}"
        patterns = [
            rf"^EP{ep}[_]?Step\[{index}\][\._]{member}$",
            rf"^EP{ep}[_]?Step\[{index}\]{member}$",
            rf"^EP{ep}[_]?Step{index}[\._]{member}$",
            rf"^EP{ep}[_]?Step_{index}[\._]{member}$",
            rf"^EP{ep}[_]?Step{index2}[\._]{member}$",
            rf"^EP{ep}[_]?Step_{index2}[\._]{member}$",
            rf"^EP{ep}[_]?Step\[{index}\]_{member}$",
            rf"^EP{ep}[_]?Step_{index}_{member}$",
        ]
        return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]

    @classmethod
    def _generate_lh_patterns(cls, tag: str):
        tokens = cls._tok(tag)
        if not tokens or tokens[0] != "lh":
            tokens = ["lh"] + tokens
        pattern = r".*".join(map(re.escape, tokens))
        return [re.compile(pattern, re.IGNORECASE)]

    def _probe_candidate(self, name: str) -> bool:
        result = self.worker.read_one(name)
        return result is not None and getattr(result, "Status", "") == "Success"

    def _best_match_from_available(self, patterns, startswith: Optional[str] = None):
        pool = self.available_tags
        if startswith:
            prefix = startswith.lower()
            pool = [tag for tag in pool if tag.lower().startswith(prefix)]

        candidates = []
        for tag in pool:
            if any(pattern.search(tag) for pattern in patterns):
                candidates.append(tag)

        if not candidates:
            return None

        candidates.sort(key=lambda value: (len(value), value.lower()))
        return candidates[0]

    def map_specific_tags(self, desired: List[str]):
        mapping: Dict[str, Optional[str]] = {}
        fixes: List[Tuple[str, str]] = []
        unresolved: List[str] = []

        for display in desired:
            if self._probe_candidate(display):
                mapping[display] = display
                continue

            chosen = None
            ep_parts = self._ep_desired_parts(display)
            if ep_parts:
                ep, index, member = ep_parts
                candidate = self._best_match_from_available(
                    self._generate_ep_patterns(ep, index, member),
                    startswith=f"ep{ep}",
                )
                if candidate and self._probe_candidate(candidate):
                    chosen = candidate

            if chosen is None and display.lower().startswith("lh."):
                candidate = self._best_match_from_available(
                    self._generate_lh_patterns(display),
                    startswith="lh",
                )
                if candidate and self._probe_candidate(candidate):
                    chosen = candidate

            if chosen is None:
                variants = set()
                if "." in display:
                    left, right = display.split(".", 1)
                    variants.add(f"{left}_{right}")
                if "_" in display:
                    parts = display.split("_", 1)
                    if len(parts) == 2:
                        variants.add(f"{parts[0]}.{parts[1]}")

                for variant in variants:
                    if self._probe_candidate(variant):
                        chosen = variant
                        break

            if chosen:
                mapping[display] = chosen
                if chosen != display:
                    fixes.append((display, chosen))
            else:
                mapping[display] = None
                unresolved.append(display)

        return mapping, fixes, unresolved
