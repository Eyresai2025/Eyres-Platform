# src/models/project.py

from datetime import datetime
from bson.objectid import ObjectId
from db import mongo
from utils.project_paths import get_project_folder
# IMPORTANT: Model layer should NEVER import ProjectDB or MachineDB from db.py
# This would create a circular import: db.py → Projects → ProjectDB → db.py
# Only import: datetime, bson, and db.mongo (the MongoDB singleton)



class ProjectModel:
    """
    Handles project creation, update, delete, and retrieval.
    Each project belongs to a machine (PLC) and contains multiple cameras.
    """

    def __init__(self):
        self.collection = mongo.collection("projects")

    # --------------------------------------------------------
    # Create a new project
    # --------------------------------------------------------
    def create_project(self, name, machine_id, description="", type=None, folder_path=None):
        if folder_path is None:
            folder_path = str(get_project_folder(name))
        project = {
            "name": name,
            "machine_id": ObjectId(machine_id),
            "description": description,
            "type": type,
            "folder_path": folder_path,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }


        result = self.collection.insert_one(project)
        project["_id"] = result.inserted_id

        return {"success": True, "project": project}

    # --------------------------------------------------------
    # Add camera to project
    # --------------------------------------------------------
    def add_camera(self, project_id, camera_id):
        try:
            pid = ObjectId(project_id)
            cid = ObjectId(camera_id)
        except:
            return {"success": False, "error": "Invalid project or camera ID"}

        self.collection.update_one(
            {"_id": pid},
            {"$addToSet": {"cameras": cid}, "$set": {"updated_at": datetime.utcnow()}}
        )

        return {"success": True}

    # --------------------------------------------------------
    # Remove camera from project
    # --------------------------------------------------------
    def remove_camera(self, project_id, camera_id):
        self.collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$pull": {"cameras": ObjectId(camera_id)}}
        )
        return {"success": True}

    # --------------------------------------------------------
    # Update project info
    # --------------------------------------------------------
    def update_project(self, project_id, data: dict):
        data["updated_at"] = datetime.utcnow()

        result = self.collection.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": data}
        )

        return result.modified_count > 0

    # --------------------------------------------------------
    # Get project by ID
    # --------------------------------------------------------
    def get_project(self, project_id):
        return self.collection.find_one({"_id": ObjectId(project_id)})

    # --------------------------------------------------------
    # List all projects
    # --------------------------------------------------------
    def list_projects(self):
        return list(self.collection.find())

    # --------------------------------------------------------
    # List projects for a specific machine
    # --------------------------------------------------------
    def list_projects_for_machine(self, machine_id):
        return list(self.collection.find({"machine_id": ObjectId(machine_id)}))

    # --------------------------------------------------------
    # Delete project
    # --------------------------------------------------------
    def delete_project(self, project_id):
        result = self.collection.delete_one({"_id": ObjectId(project_id)})
        return result.deleted_count > 0


# ------------------------------------------------------------
# Export instance
# ------------------------------------------------------------
Projects = ProjectModel()

