#!/usr/bin/env python3
"""
T2-2 + T2-3: Create Directus schema and import experiment content.

Usage:
    source .env.directus
    python3 scripts/setup_directus.py

Or:
    DIRECTUS_URL=http://127.0.0.1:8055 \
    DIRECTUS_ADMIN_EMAIL=admin@cloudnetops.tech \
    DIRECTUS_ADMIN_PASSWORD=<pass> \
    python3 scripts/setup_directus.py
"""

import json
import os
import sys
from pathlib import Path

import httpx

BASE_URL = os.environ.get("DIRECTUS_URL", "http://127.0.0.1:8055")
ADMIN_EMAIL = os.environ["DIRECTUS_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["DIRECTUS_ADMIN_PASSWORD"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = PROJECT_ROOT / "docs" / "experiments"
DEPLOYMENTS_DIR = PROJECT_ROOT / "docs" / "deployments"

# ── metadata from routes ──────────────────────────────────────────────────────

NETWORK_EXPERIMENTS = [
    {"slug": "01", "filename": "01-kubernetes-network-basics.md", "title": "Kubernetes 网络基础", "difficulty": 2, "duration": "30-35 分钟", "phase": 1},
    {"slug": "02", "filename": "02-pod-network-deep-dive.md",     "title": "Pod 网络深入探索",     "difficulty": 3, "duration": "35-40 分钟", "phase": 1},
    {"slug": "03", "filename": "03-service-loadbalancing.md",     "title": "Service 负载均衡",      "difficulty": 3, "duration": "35-40 分钟", "phase": 1},
    {"slug": "04", "filename": "04-ingress-controller.md",        "title": "Ingress 控制器详解",    "difficulty": 4, "duration": "45-50 分钟", "phase": 2},
    {"slug": "05", "filename": "05-network-policy.md",            "title": "NetworkPolicy 网络策略","difficulty": 3, "duration": "35-40 分钟", "phase": 2},
    {"slug": "06", "filename": "06-dns-service-discovery.md",     "title": "DNS 服务发现",          "difficulty": 3, "duration": "35-40 分钟", "phase": 2},
    {"slug": "07", "filename": "07-persistent-storage.md",        "title": "持久化存储 PV/PVC",     "difficulty": 3, "duration": "40-45 分钟", "phase": 3},
    {"slug": "08", "filename": "08-configmap-secret.md",          "title": "ConfigMap 和 Secret",   "difficulty": 3, "duration": "35-40 分钟", "phase": 3},
    {"slug": "09", "filename": "09-statefulset.md",               "title": "StatefulSet 有状态应用","difficulty": 4, "duration": "45-50 分钟", "phase": 4},
    {"slug": "10", "filename": "10-monitoring-logging.md",        "title": "监控和日志管理",        "difficulty": 3, "duration": "35-40 分钟", "phase": 4},
    {"slug": "11", "filename": "11-comprehensive-practice.md",    "title": "综合实战项目",          "difficulty": 4, "duration": "50-60 分钟", "phase": 5},
]

DEPLOYMENT_CASES = [
    {"slug": "D01", "filename": "D01-guestbook.md",       "title": "留言板应用（Guestbook）",       "difficulty": 3, "duration": "30 分钟", "phase": 1},
    {"slug": "D02", "filename": "D02-wordpress-mysql.md", "title": "有状态应用：MySQL + 持久化存储", "difficulty": 4, "duration": "45 分钟", "phase": 2},
    {"slug": "D03", "filename": "D03-blue-green-deploy.md","title": "蓝绿部署与滚动更新",           "difficulty": 3, "duration": "35 分钟", "phase": 1},
    {"slug": "D04", "filename": "D04-cronjob.md",          "title": "CronJob 定时任务系统",         "difficulty": 3, "duration": "30 分钟", "phase": 2},
    {"slug": "D05", "filename": "D05-multi-namespace.md",  "title": "多命名空间微服务隔离",         "difficulty": 4, "duration": "40 分钟", "phase": 3},
]

# Background text is long — pull it from the route source rather than duplicate here.
# We import the actual Python module to get it.
sys.path.insert(0, str(PROJECT_ROOT))


def get_background(slug: str) -> str:
    try:
        if slug.startswith("D"):
            from backend.deployments_routes import DEPLOYMENT_CASES as DC
            item = next((c for c in DC if c["id"] == slug), None)
        else:
            from backend.docs_routes import EXPERIMENTS as EX
            item = next((e for e in EX if e["id"] == slug), None)
        return item["background"] if item else ""
    except Exception:
        return ""


# ── helpers ───────────────────────────────────────────────────────────────────

def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(label: str) -> None:
    print(f"  ✓ {label}")


# ── Directus API client ───────────────────────────────────────────────────────

class DirectusClient:
    def __init__(self, base_url: str, email: str, password: str):
        self.base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30)
        self._token = self._login(email, password)
        self._headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _login(self, email: str, password: str) -> str:
        r = self._client.post(f"{self.base}/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            die(f"Login failed: {r.text}")
        return r.json()["data"]["access_token"]

    def get(self, path: str) -> dict:
        r = self._client.get(f"{self.base}{path}", headers=self._headers)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict) -> dict:
        r = self._client.post(f"{self.base}{path}", headers=self._headers, json=body)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"POST {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    def patch(self, path: str, body: dict) -> dict:
        r = self._client.patch(f"{self.base}{path}", headers=self._headers, json=body)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"PATCH {path} → {r.status_code}: {r.text[:300]}")
        return r.json()

    def collection_exists(self, name: str) -> bool:
        r = self._client.get(f"{self.base}/collections/{name}", headers=self._headers)
        return r.status_code == 200

    def field_exists(self, collection: str, field: str) -> bool:
        r = self._client.get(f"{self.base}/fields/{collection}/{field}", headers=self._headers)
        return r.status_code == 200


# ── schema creation ───────────────────────────────────────────────────────────

FIELDS = [
    {"field": "slug",       "type": "string",  "meta": {"interface": "input", "note": "唯一标识，如 01 D01"}, "schema": {"is_unique": True, "is_nullable": False, "max_length": 20}},
    {"field": "category",   "type": "string",  "meta": {"interface": "select-dropdown", "options": {"choices": [{"text": "网络实验", "value": "network"}, {"text": "部署案例", "value": "deployment"}]}}, "schema": {"is_nullable": False, "max_length": 20}},
    {"field": "title",      "type": "string",  "meta": {"interface": "input"}, "schema": {"is_nullable": False}},
    {"field": "difficulty", "type": "integer", "meta": {"interface": "input", "note": "1-5"}, "schema": {"is_nullable": True}},
    {"field": "duration",   "type": "string",  "meta": {"interface": "input"}, "schema": {"is_nullable": True}},
    {"field": "phase",      "type": "integer", "meta": {"interface": "input"}, "schema": {"is_nullable": True}},
    {"field": "sort_order", "type": "integer", "meta": {"interface": "input", "sort": 1}, "schema": {"is_nullable": True}},
    {"field": "status",     "type": "string",  "meta": {"interface": "select-dropdown", "options": {"choices": [{"text": "已发布", "value": "published"}, {"text": "草稿", "value": "draft"}]}}, "schema": {"is_nullable": False, "default_value": "published", "max_length": 20}},
    {"field": "content",    "type": "text",    "meta": {"interface": "input-multiline", "note": "实验步骤 Markdown"}},
    {"field": "background", "type": "text",    "meta": {"interface": "input-multiline", "note": "实验背景 Markdown"}},
]


def setup_schema(dc: DirectusClient) -> None:
    print("\n── T2-2: Schema ─────────────────────────────────────────")
    if dc.collection_exists("experiments"):
        print("  collection 'experiments' already exists, skipping creation")
    else:
        dc.post("/collections", {
            "collection": "experiments",
            "meta": {"icon": "science", "note": "K8s 网络实验 + 部署案例内容"},
            "schema": {"name": "experiments"},
        })
        ok("created collection 'experiments'")

    for f in FIELDS:
        if dc.field_exists("experiments", f["field"]):
            print(f"  field '{f['field']}' already exists, skipping")
        else:
            dc.post(f"/fields/experiments", f)
            ok(f"created field '{f['field']}'")


def setup_public_permissions(dc: DirectusClient) -> None:
    print("\n── Public read permissions ──────────────────────────────")
    # Directus 11 uses policies. Find the public policy (name starts with $t:public_label or "Public").
    policies = dc.get("/policies")["data"]
    public_policy = next(
        (p for p in policies if "public" in p.get("name", "").lower() or p.get("name", "") == "$t:public_label"),
        None
    )
    if not public_policy:
        print("  public policy not found, skipping")
        return
    policy_id = public_policy["id"]

    # Check if permission already exists for this policy + collection
    existing = dc.get(
        f"/permissions?filter[policy][_eq]={policy_id}&filter[collection][_eq]=experiments&filter[action][_eq]=read"
    )["data"]
    if existing:
        print("  public read permission already exists")
        return

    dc.post("/permissions", {
        "policy": policy_id,
        "collection": "experiments",
        "action": "read",
        "fields": ["*"],
        "permissions": {"status": {"_eq": "published"}},
    })
    ok(f"granted public read on experiments via policy '{public_policy['name']}'")


# ── data import ───────────────────────────────────────────────────────────────

def import_item(dc: DirectusClient, meta: dict, directory: Path, category: str, sort_offset: int) -> None:
    slug = meta["slug"]
    filepath = directory / meta["filename"]
    content = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    background = get_background(slug)

    # Check if item already imported
    existing = dc.get(f"/items/experiments?filter[slug][_eq]={slug}")["data"]
    if existing:
        print(f"  {slug}: already exists, updating content")
        dc.patch(f"/items/experiments/{existing[0]['id']}", {
            "content": content,
            "background": background,
        })
        return

    dc.post("/items/experiments", {
        "slug": slug,
        "category": category,
        "title": meta["title"],
        "difficulty": meta["difficulty"],
        "duration": meta["duration"],
        "phase": meta["phase"],
        "sort_order": sort_offset + int(meta["slug"].replace("D", "0")),
        "status": "published",
        "content": content,
        "background": background,
    })
    ok(f"imported {slug}: {meta['title']}")


def import_data(dc: DirectusClient) -> None:
    print("\n── T2-3: Data import ────────────────────────────────────")
    for i, meta in enumerate(NETWORK_EXPERIMENTS):
        import_item(dc, meta, EXPERIMENTS_DIR, "network", 0)
    for i, meta in enumerate(DEPLOYMENT_CASES):
        import_item(dc, meta, DEPLOYMENTS_DIR, "deployment", 100)
    print(f"\n  Total: {len(NETWORK_EXPERIMENTS)} network + {len(DEPLOYMENT_CASES)} deployment cases")


# ── users import ──────────────────────────────────────────────────────────────

def import_users(dc: DirectusClient) -> None:
    print("\n── T2-3: Users import ───────────────────────────────────")
    users_file = PROJECT_ROOT / "data" / "users.json"
    if not users_file.exists():
        print("  data/users.json not found, skipping")
        return

    users = json.loads(users_file.read_text())
    if not users:
        print("  no users found")
        return

    # Find student and admin roles
    roles_resp = dc.get("/roles")["data"]
    admin_role = next((r for r in roles_resp if r["name"] == "Administrator"), None)
    # Create a Student role if it doesn't exist
    student_role_resp = dc.get("/roles?filter[name][_eq]=Student")["data"]
    if student_role_resp:
        student_role_id = student_role_resp[0]["id"]
    else:
        result = dc.post("/roles", {"name": "Student", "icon": "person", "description": "Platform student"})
        student_role_id = result["data"]["id"]
        ok("created Student role")

    admin_usernames = set(os.environ.get("ADMIN_USERNAMES", "admin").split(","))
    imported = 0
    skipped = 0

    for username, user_data in users.items():
        email = f"{username}@lab.cloudnetops.tech"
        # Check if user already exists in Directus
        existing = dc.get(f"/users?filter[email][_eq]={email}")["data"]
        if existing:
            skipped += 1
            continue

        is_admin = username in admin_usernames
        role_id = admin_role["id"] if (is_admin and admin_role) else student_role_id

        # Directus stores passwords as bcrypt — we can pass existing bcrypt hash
        password_hash = user_data.get("password_hash", "")

        try:
            dc.post("/users", {
                "email": email,
                "first_name": username,
                "role": role_id,
                "status": "active",
                "password": password_hash or "CHANGE_ME_ON_FIRST_LOGIN",
            })
            ok(f"imported user '{username}' ({email})")
            imported += 1
        except Exception as e:
            print(f"  WARN: failed to import user '{username}': {e}")

    print(f"\n  Users: {imported} imported, {skipped} already existed")
    print("  NOTE: Users login with email = {username}@lab.cloudnetops.tech")


# ── entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Connecting to Directus at {BASE_URL}...")
    dc = DirectusClient(BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD)
    ok("authenticated as admin")

    setup_schema(dc)
    setup_public_permissions(dc)
    import_data(dc)
    import_users(dc)

    print("\n✓ Setup complete.")
    print(f"  Admin UI: {BASE_URL}/admin")


if __name__ == "__main__":
    main()
