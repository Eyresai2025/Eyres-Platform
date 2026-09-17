from bson.objectid import ObjectId
from datetime import datetime
from db import mongo
 
 
class Machines:
    """MongoDB model for machines."""
 
    coll = mongo.collection("machines")
 
    # -----------------------------------------------------------
    @staticmethod
    def list_machines():
        return list(Machines.coll.find({}))
 
    # -----------------------------------------------------------
    @staticmethod
    def get_machine(machine_id):
        try:
            oid = ObjectId(machine_id)
        except Exception:
            return None
        return Machines.coll.find_one({"_id": oid})
 
    # -----------------------------------------------------------
    @staticmethod
    def create_machine(payload: dict):
        """
        Payload should be a FLAT dict with:
        {
            name, ip_address, slot,
            plc_brand, plc_model, plc_protocol, active
        }

        """
        try:
            doc = payload.copy()
            # active comes from UI after real PLC check
            doc.setdefault("active", False)
            doc.setdefault("created_at", datetime.utcnow())
            doc.setdefault("updated_at", datetime.utcnow())
 
            res = Machines.coll.insert_one(doc)
            doc["_id"] = res.inserted_id
 
            return {"success": True, "machine": doc}
 
        except Exception as e:
            return {"success": False, "error": str(e)}
 
    # -----------------------------------------------------------
    @staticmethod
    def update_machine(machine_id, data: dict):
        try:
            oid = ObjectId(machine_id)
        except Exception:
            return False
 
        data["updated_at"] = datetime.utcnow()
 
        try:
            Machines.coll.update_one({"_id": oid}, {"$set": data})
            return True
        except Exception:
            return False
 
    # -----------------------------------------------------------
    @staticmethod
    def delete_machine(machine_id):
        try:
            oid = ObjectId(machine_id)
        except Exception:
            return False
 
        try:
            Machines.coll.delete_one({"_id": oid})
            return True
        except Exception:
            return False