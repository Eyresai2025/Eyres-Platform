# db.py
"""
Unified database module for EYRES QC.

Includes:
    - MongoDB singleton (connection, collections, indexes, default admin)
    - Database: auth / user management (login, create, forgot password)
    - ProjectDB, MachineDB wrappers for dashboard_models.*
    - Camera overrides helpers (load/save) for camera_app
"""

from typing import Dict, Tuple
import pymongo
import hashlib
import base64
import hmac
import logging
import os
import secrets
import atexit
from datetime import datetime, time, timedelta
from collections import defaultdict
from app_core.config import get_config
from app_core.rbac import ADMIN, OPERATOR, ROLES, normalize_role

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when the configured database cannot be reached in time."""


_PASSWORD_ITERATIONS = 600_000


def hash_secret(value: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, _PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PASSWORD_ITERATIONS, base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_secret(value: str, encoded: str) -> tuple[bool, bool]:
    if encoded.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, expected = encoded.split("$", 3)
            actual = hashlib.pbkdf2_hmac(
                "sha256", value.encode("utf-8"), base64.b64decode(salt), int(iterations)
            )
            return hmac.compare_digest(actual, base64.b64decode(expected)), False
        except (ValueError, TypeError):
            return False, False
    legacy = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, encoded), True


# ----------------------------------------------------------------------
# MongoDB singleton
# ----------------------------------------------------------------------
class MongoDB:
    """
    Industrial-grade MongoDB singleton.
    Handles:
        - DB connection
        - Automatic collection creation
        - Automatic index creation
        - Automatic default admin user
    """

    _instance = None

    @staticmethod
    def get_instance():
        if MongoDB._instance is None:
            MongoDB._instance = MongoDB()
        return MongoDB._instance

    def __init__(self):
        # Prevent re-init if called directly
        if hasattr(self, "_initialized") and self._initialized:
            return

        config = get_config()
        self.available = False
        try:
            self.client = pymongo.MongoClient(
                config.mongodb_uri,
                serverSelectionTimeoutMS=config.service_timeout_ms,
                connectTimeoutMS=config.service_timeout_ms,
                socketTimeoutMS=config.service_timeout_ms,
                retryWrites=True,
                appname="eyres-ai-platform",
            )
            self.db = self.client[config.mongodb_database]
            self.client.admin.command("ping")

            self._create_collections()
            self._create_indexes()
            self._create_default_users()
            self._repair_corrupted_machine_records()

            self.available = True

        except Exception as e:
            logger.error("MongoDB is unavailable: %s", e)
        finally:
            self._initialized = True

    def require_available(self) -> None:
        try:
            self.client.admin.command("ping")
            self.available = True
        except Exception as exc:
            self.available = False
            raise DatabaseUnavailableError(
                "Database service is unavailable. Start MongoDB and try again."
            ) from exc

    # ------------ collections ------------

    def _create_collections(self):
        required = [
            "users",
            "projects",
            "machines",
            "system_logs",
            "camera_overrides",  # added for camera settings
            "live",
        ]

        existing = set(self.db.list_collection_names())
        for name in required:
            if name not in existing:
                self.db.create_collection(name)

    # ------------ indexes ------------

    def _create_indexes(self):
        # Users
        self.db.users.create_index("username", unique=True)
        self.db.users.create_index("email")
        self.db.users.create_index("role")
        # Phase 1 authentication preparation: Google identity is linked by
        # provider + provider_user_id. Sparse/partial indexing keeps existing
        # local-password users valid while preventing duplicate Google links.
        self.db.users.create_index(
            [("auth_provider", 1), ("provider_user_id", 1)],
            unique=True,
            partialFilterExpression={"provider_user_id": {"$exists": True, "$type": "string"}},
            name="auth_provider_identity_unique",
        )

        # Projects
        self.db.projects.create_index("name")   # NOT unique
        self.db.projects.create_index("machine_id")

        # Machines
        self.db.machines.create_index("name", unique=True)

        # Camera overrides
        self.db.camera_overrides.create_index(
            [("type", 1), ("key", 1)],
            unique=True,
        )
        # Live inspection logs
        self.db.live.create_index("inspection_datetime")
        self.db.live.create_index("inspection_type")
        self.db.live.create_index("cam_index")


    # ------------ default admin ------------

    def _create_default_users(self):
        admin_exists = self.db.users.find_one({"username": "admin"})
        if admin_exists:
            self.db.users.update_one(
                {"_id": admin_exists["_id"]},
                {"$set": {"role": ADMIN, "active": True, "updated_at": datetime.utcnow()}},
            )
            return

        configured_password = os.getenv("EYRES_BOOTSTRAP_ADMIN_PASSWORD")
        if not configured_password:
            logger.warning("Bootstrap admin skipped: set EYRES_BOOTSTRAP_ADMIN_PASSWORD on first run")
            return
        default_password = hash_secret(configured_password)

        admin_user = {
            "username": "admin",
            "password": default_password,
            "role": "admin",
            "active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        self.db.users.insert_one(admin_user)
        logger.info("Bootstrap administrator account created")

    # ------------ utils ------------

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def collection(self, name: str):
        return self.db[name]

    def _backup_machines_collection(self, path="/tmp/machines_backup.json"):
        """Optional: one-time quick backup snippet (not required, but safe)."""
        try:
            coll = self.db["machines"]
            docs = list(coll.find({}))
            import json
            from bson import json_util
            with open(path, "w", encoding="utf-8") as f:
                f.write(json_util.dumps(docs))
        except Exception as e:
            print(f"⚠️  Backup failed: {e}")

    def _repair_corrupted_machine_records(self):
        """
        Idempotent: find machines where `name` is a dict and flatten them.
        Safe to run on every app start.
        """
        try:
            coll = self.db["machines"]
        except Exception:
            return

        fixed = 0
        for doc in coll.find({}):
            name_field = doc.get("name")
            if isinstance(name_field, dict):
                # flatten nested dict into top-level fields, preserve _id
                nested = name_field.copy()
                update_fields = {}
                for k, v in nested.items():
                    # avoid accidental overwrite of _id
                    if k == "_id":
                        continue
                    update_fields[k] = v

                # pick canonical name
                canonical_name = nested.get("name") or nested.get("machine_name") or str(nested)
                update_fields["name"] = canonical_name

                # update document
                try:
                    coll.update_one({"_id": doc["_id"]}, {"$set": update_fields})
                    fixed += 1
                except Exception:
                    continue

        if fixed:
            print(f"Repaired {fixed} corrupted machine records.")


# Global singleton accessor
mongo = MongoDB.get_instance()
def _close_mongo_client():
    client = getattr(mongo, "client", None)
    if client is not None:
        client.close()
atexit.register(_close_mongo_client)

# ----------------------------------------------------------------------
# Auth / user management
# ----------------------------------------------------------------------


class Database:
    """
    Auth wrapper used by Login / Forgot Password UI.

    Uses MongoDB singleton above instead of creating a new client.
    """

    def __init__(self, uri="mongodb://localhost:27017", db_name="eyres_qc"):
        # Keep signature for backward compatibility, but use `mongo`
        self.db = mongo.db
        self.users = self.db["users"]

    def _hash(self, value: str) -> str:
        return hash_secret(value)

    # ----------------------- AUTH FUNCTIONS -----------------------

    def find_user(self, username: str, password: str):
        """Used by Login Window."""
        mongo.require_available()
        user = self.users.find_one({"username": username})
        if not user:
            return None
        if not user.get("active", True):
            return None
        now = datetime.utcnow()
        locked_until = user.get("locked_until")
        if locked_until and locked_until > now:
            return None
        if locked_until:
            self.users.update_one({"_id": user["_id"]}, {"$unset": {"locked_until": ""},
                "$set": {"failed_login_count": 0, "updated_at": now}})
        valid, needs_upgrade = verify_secret(password, user.get("password", ""))
        if not valid:
            config = get_config()
            attempts = int(user.get("failed_login_count", 0)) + 1
            update = {"failed_login_count": attempts, "updated_at": now}
            if attempts >= config.max_login_attempts:
                update["locked_until"] = now + timedelta(minutes=config.lockout_minutes)
            self.users.update_one({"_id": user["_id"]}, {"$set": update})
            return None
        if needs_upgrade:
            self.users.update_one({"_id": user["_id"]}, {"$set": {
                "password": hash_secret(password), "updated_at": datetime.utcnow()}})
        user["role"] = normalize_role(user.get("role"))
        user["active"] = bool(user.get("active", True))
        self.users.update_one({"_id": user["_id"]}, {"$set": {
            "failed_login_count": 0, "last_login_at": now, "updated_at": now},
            "$unset": {"locked_until": ""}})
        return user

    def user_exists(self, username: str) -> bool:
        mongo.require_available()
        return self.users.find_one({"username": username}) is not None

    def create_user(
        self, username: str, password: str, email: str,
        sec_question: str, sec_answer: str
    ):
        if self.user_exists(username):
            raise ValueError("Username already exists")

        self.users.insert_one({
            "username": username,
            "email": email,
            "password": hash_secret(password),
            # Authentication metadata. Existing accounts remain local/password users.
            "auth_provider": "local",
            "security_question": sec_question,
            "security_answer": hash_secret(sec_answer),
            "role": OPERATOR,
            "active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })

    def create_managed_user(self, username: str, password: str, email: str = "",
                            role: str = OPERATOR, active: bool = True):
        """Administrator-facing account provisioning API."""
        mongo.require_available()
        username = username.strip()
        if not username or len(password) < 8:
            raise ValueError("Username is required and password must have at least 8 characters")
        role = normalize_role(role)
        if role not in ROLES or self.user_exists(username):
            raise ValueError("Invalid role or username already exists")
        self.users.insert_one({
            "username": username, "email": email.strip(),
            "password": hash_secret(password),
            "auth_provider": "local",
            "role": role,
            "active": bool(active), "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })

    # ---------------- Google authentication ----------------

    def create_google_user(self, email: str, name: str, provider_user_id: str):
        """Create a default operator account for a verified Google identity."""
        mongo.require_available()
        import re
        import secrets

        email = (email or "").strip().lower()
        name = (name or "").strip()
        provider_user_id = (provider_user_id or "").strip()
        if not email or not provider_user_id:
            raise ValueError("Google email and provider identity are required")

        existing = self.get_user_by_provider_identity("google", provider_user_id)
        if existing:
            return existing

        # Prefer the email local-part for the platform username, then make it unique.
        base = re.sub(r"[^a-zA-Z0-9_.-]", "_", email.split("@", 1)[0] or "google_user").strip("._-") or "google_user"
        username = base[:48]
        candidate = username
        counter = 1
        while self.user_exists(candidate):
            counter += 1
            candidate = f"{username[:43]}_{counter}"

        now = datetime.utcnow()
        # Random local secret: Google users authenticate through Google, never this value.
        random_secret = secrets.token_urlsafe(48)
        self.users.insert_one({
            "username": candidate,
            "email": email,
            "password": hash_secret(random_secret),
            "auth_provider": "google",
            "provider_user_id": provider_user_id,
            "security_question": "",
            "security_answer": hash_secret(secrets.token_urlsafe(32)),
            "role": OPERATOR,
            "active": True,
            "display_name": name,
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        })
        return self.users.find_one({"username": candidate})

    # ---------------- Phase 1: authentication identity helpers ----------------

    def get_user_by_email(self, email: str):
        """Return a user by normalized email, without exposing password fields."""
        mongo.require_available()
        email = (email or "").strip().lower()
        if not email:
            return None
        return self.users.find_one({"email": email})

    def get_user_by_provider_identity(self, provider: str, provider_user_id: str):
        """Return a user linked to an external identity (used by Phase 2 Google OAuth)."""
        mongo.require_available()
        provider = (provider or "").strip().lower()
        provider_user_id = (provider_user_id or "").strip()
        if not provider or not provider_user_id:
            return None
        return self.users.find_one({
            "auth_provider": provider,
            "provider_user_id": provider_user_id,
        })

    def link_provider_identity(self, username: str, provider: str, provider_user_id: str, email: str = ""):
        """Link an external identity to an existing user. OAuth flow is added in Phase 2."""
        mongo.require_available()
        provider = (provider or "").strip().lower()
        provider_user_id = (provider_user_id or "").strip()
        if not provider or not provider_user_id:
            raise ValueError("Provider and provider user ID are required")
        user = self.users.find_one({"username": username})
        if not user:
            raise ValueError("User not found")
        existing = self.get_user_by_provider_identity(provider, provider_user_id)
        if existing and existing.get("_id") != user.get("_id"):
            raise ValueError("This external account is already linked to another user")
        update = {
            "auth_provider": provider,
            "provider_user_id": provider_user_id,
            "updated_at": datetime.utcnow(),
        }
        if email and not user.get("email"):
            update["email"] = email.strip().lower()
        self.users.update_one({"_id": user["_id"]}, {"$set": update})

    def list_users(self):
        mongo.require_available()
        return list(self.users.find({}, {"password": 0, "security_answer": 0}).sort("username", 1))

    def set_user_role(self, username: str, role: str):
        mongo.require_available()
        role = normalize_role(role)
        if username == "admin" and role != ADMIN:
            raise ValueError("The bootstrap administrator cannot be demoted")
        result = self.users.update_one({"username": username}, {"$set": {
            "role": role, "updated_at": datetime.utcnow()}})
        if not result.matched_count:
            raise ValueError("User not found")

    def set_user_active(self, username: str, active: bool):
        mongo.require_available()
        if username == "admin" and not active:
            raise ValueError("The bootstrap administrator cannot be disabled")
        result = self.users.update_one({"username": username}, {"$set": {
            "active": bool(active), "updated_at": datetime.utcnow()}})
        if not result.matched_count:
            raise ValueError("User not found")

    def get_security_question(self, username: str):
        user = self.users.find_one({"username": username})
        if user:
            return user.get("security_question")
        return None

    def verify_security_answer(self, username: str, answer: str) -> bool:
        mongo.require_available()
        user = self.users.find_one({"username": username})
        if not user:
            return False
        valid, needs_upgrade = verify_secret(answer, user.get("security_answer", ""))
        if valid and needs_upgrade:
            self.users.update_one({"_id": user["_id"]}, {"$set": {
                "security_answer": hash_secret(answer), "updated_at": datetime.utcnow()}})
        return valid

    def update_password(self, username: str, new_password: str):
        self.users.update_one(
            {"username": username},
            {
                "$set": {
                    "password": hash_secret(new_password),
                    "updated_at": datetime.utcnow(),
                    "failed_login_count": 0,
                }
                , "$unset": {"locked_until": ""}
            }
        )

    def admin_reset_password(self, username: str, new_password: str):
        mongo.require_available()
        if len(new_password) < 8:
            raise ValueError("Password must contain at least 8 characters")
        result = self.users.update_one({"username": username}, {"$set": {
            "password": hash_secret(new_password), "failed_login_count": 0,
            "updated_at": datetime.utcnow()}, "$unset": {"locked_until": ""}})
        if not result.matched_count:
            raise ValueError("User not found")

    def clear_user_lockout(self, username: str):
        """Clear failed authentication attempts without changing the password."""
        mongo.require_available()
        result = self.users.update_one(
            {"username": username},
            {
                "$set": {"failed_login_count": 0, "updated_at": datetime.utcnow()},
                "$unset": {"locked_until": ""},
            },
        )
        if not result.matched_count:
            raise ValueError("User not found")


# ----------------------------------------------------------------------
# Project / Machine wrappers
# ----------------------------------------------------------------------

# NOTE: using dashboard_models instead of models
from dashboard_models.project import Projects
from dashboard_models.machine import Machines


class ProjectDB:
    """Database wrapper for project operations."""

    def __init__(self):
        self.model = Projects

    def get_all_projects(self):
        """Get all projects from database."""
        return self.model.list_projects()

    def add_project(self, name, machine_id, description="", type=None, folder_path=None):
        result = self.model.create_project(
            name, machine_id,
            description=description,
            type=type,
            folder_path=folder_path
        )
        if result.get("success"):
            return result["project"]
        return None

    def delete_project(self, project_id):
        """Delete a project by ID."""
        return self.model.delete_project(project_id)

    def get_project(self, project_id):
        """Get a project by ID."""
        return self.model.get_project(project_id)

    def update_project(self, project_id, name=None, machine_id=None,
                   description=None, type=None, folder_path=None):
        data = {}
        if name is not None:
            data["name"] = name
        if machine_id is not None:
            from bson.objectid import ObjectId
            data["machine_id"] = ObjectId(machine_id)
        if description is not None:
            data["description"] = description
        if type is not None:
            data["type"] = type
        if folder_path is not None:
            data["folder_path"] = folder_path

        return self.model.update_project(project_id, data)



class MachineDB:
    """Database wrapper for machine operations."""

    def __init__(self):
        self.model = Machines
        self._coll = mongo.collection("machines")

    def get_all_machines(self):
        return self.model.list_machines()

    def _normalize_payload(self, payload: dict) -> dict:
        """
        Ensure payload is a flat dict with consistent field names.
        Accepts payloads created either by old UI or new UI.
        """
        p = {}
        # prefer explicit keys if present
        p["name"] = payload.get("name") or payload.get("machine_name") or payload.get("label") or None
        p["description"] = payload.get("description") or payload.get("desc") or None
        p["ip_address"] = payload.get("ip_address") or payload.get("plc_ip") or None
        p["plc_brand"] = payload.get("plc_brand") or None
        p["plc_model"] = payload.get("plc_model") or None
        p["plc_protocol"] = payload.get("plc_protocol") or None
        # default flags
        if "active" in payload:
            p["active"] = payload["active"]
        else:
            p.setdefault("active", True)
        # remove None values so model layer can fill defaults
        return {k: v for k, v in p.items() if v is not None}

    def add_machine(self, *args, **kwargs):
        """
        Accept either:
          - add_machine(name_str, plc_ip='', description='')
          - add_machine(payload_dict)
        and always write a flattened document via model.create_machine(payload).
        """
        # If first arg is a dict, treat it as payload
        if len(args) == 1 and isinstance(args[0], dict):
            payload = self._normalize_payload(args[0])
        else:
            # old signature: name, plc_ip, description (positional or kwargs)
            name = kwargs.get("name") if "name" in kwargs else (args[0] if len(args) > 0 else None)
            plc_ip = kwargs.get("plc_ip") or (args[1] if len(args) > 1 else None)
            description = kwargs.get("description") or (args[2] if len(args) > 2 else None)
            payload = self._normalize_payload({
                "name": name,
                "ip_address": plc_ip,
                "description": description
            })

        if not payload.get("name"):
            raise ValueError("Machine name is required")

        # call model layer (expects a dict payload)
        result = self.model.create_machine(payload)
        if result.get("success"):
            return result["machine"]
        return None

    def update_machine(self, machine_id, data: dict):
        """Update expects a dict payload with fields to change."""
        return self.model.update_machine(machine_id, data)

    def delete_machine(self, machine_id):
        return self.model.delete_machine(machine_id)

    def get_machine(self, machine_id):
        return self.model.get_machine(machine_id)


# ----------------------------------------------------------------------
# Camera overrides API (Arena + MVS)
# ----------------------------------------------------------------------
def ensure_mongo_connected() -> bool:
    """
    Simple ping using the shared MongoDB singleton.
    Returns True if MongoDB responds, False otherwise.
    """
    try:
        mongo.client.admin.command("ping")
        return True
    except Exception as e:
        print(f"[db] MongoDB ping failed: {e}")
        return False


def load_camera_overrides() -> Tuple[Dict[str, dict], Dict[int, dict]]:
    """
    Load all stored camera overrides from `camera_overrides` collection.

    Returns:
        (arena_overrides, mvs_overrides)
        arena_overrides: {serial(str): {...}}
        mvs_overrides:   {index(int): {...}}
    """
    arena_overrides: Dict[str, dict] = {}
    mvs_overrides: Dict[int, dict] = {}

    try:
        coll = mongo.collection("camera_overrides")
    except Exception as e:
        print(f"[db] load_camera_overrides: cannot access collection: {e}")
        return arena_overrides, mvs_overrides

    try:
        for doc in coll.find({}):
            t = doc.get("type")
            key = doc.get("key")
            ov = doc.get("overrides") or {}

            if t == "arena" and key is not None:
                arena_overrides[str(key)] = ov
            elif t == "mvs" and key is not None:
                try:
                    mvs_overrides[int(key)] = ov
                except (TypeError, ValueError):
                    continue
    except Exception as e:
        print(f"[db] load_camera_overrides: error while reading: {e}")

    return arena_overrides, mvs_overrides


def save_camera_overrides(
    arena_overrides: Dict[str, dict],
    mvs_overrides: Dict[int, dict],
) -> None:
    """
    Persist current overrides into MongoDB:

    Collection: `camera_overrides`
    Docs: {type: 'arena'|'mvs', key: serial|index, overrides: {...}, updated_at: datetime}
    """
    try:
        coll = mongo.collection("camera_overrides")
    except Exception as e:
        print(f"[db] save_camera_overrides: cannot access collection: {e}")
        return

    now = datetime.utcnow()

    # Save Arena overrides
    for serial, ov in (arena_overrides or {}).items():
        try:
            coll.update_one(
                {"type": "arena", "key": str(serial)},
                {"$set": {"overrides": ov, "updated_at": now}},
                upsert=True,
            )
        except Exception as e:
            print(f"[db] save_camera_overrides: arena[{serial}] failed: {e}")

    # Save MVS overrides
    for idx, ov in (mvs_overrides or {}).items():
        try:
            coll.update_one(
                {"type": "mvs", "key": str(idx)},
                {"$set": {"overrides": ov, "updated_at": now}},
                upsert=True,
            )
        except Exception as e:
            print(f"[db] save_camera_overrides: mvs[{idx}] failed: {e}")
def insert_live_record(doc: Dict) -> None:
    """
    Insert one document into `live` collection.

    Expected (but not strictly required) fields in `doc`:
      - good_count, bad_count, total_count, cycle
      - inspection_type
      - score_text, class_name
      - input_image, output_image
      - cam_index

    If `inspection_datetime` is missing, it will be added here.
    """
    try:
        coll = mongo.collection("live")
        if "inspection_datetime" not in doc:
            doc["inspection_datetime"] = datetime.utcnow()
        coll.insert_one(doc)
    except Exception as e:
        print(f"[db] insert_live_record: failed to insert: {e}")

def get_today_live_counts():
    """
    Aggregate today's live inspection results.
    
    Returns:
        {
            "good": int,
            "bad": int,
            "total": int
        }
    """
    mongo_inst = MongoDB.get_instance()
    db = mongo_inst.db
    coll = db["live"]

    # Use UTC here because insert_live_record uses datetime.utcnow()
    today = datetime.utcnow().date()
    start_dt = datetime.combine(today, time.min)

    # Get today's docs
    docs = list(coll.find({"inspection_datetime": {"$gte": start_dt}}))

    good = 0
    bad = 0

    for d in docs:
        is_ng = bool(d.get("is_ng", False))

        if is_ng:
            bad += 1
        else:
            good += 1

    total = good + bad

    return {
        "good": good,
        "bad": bad,
        "total": total,
    }


def get_recent_inspections(limit: int = 30):
    """
    Get the most recent inspection records with their output images.
    
    Args:
        limit: Maximum number of records to return
        
    Returns:
        List of documents with _id, inspection_datetime, cam_index, is_ng, 
        output_image, class_name, score_text, and inspection_type
    """
    try:
        coll = mongo.collection("live")
        
        # Get most recent records, sorted by datetime descending
        cursor = coll.find(
            {"output_image": {"$exists": True, "$ne": None}},
            {
                "_id": 1,
                "inspection_datetime": 1,
                "cam_index": 1,
                "is_ng": 1,
                "output_image": 1,
                "class_name": 1,
                "score_text": 1,
                "inspection_type": 1,
                "good_count": 1,
                "bad_count": 1,
                "total_count": 1
            }
        ).sort("inspection_datetime", -1).limit(limit)
        
        return list(cursor)
    except Exception as e:
        print(f"[db] get_recent_inspections error: {e}")
        return []
