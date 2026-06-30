"""
E2E 测试：模拟真实用户的完整业务流程。

每个 Journey 跨越多个路由，验证端到端行为一致。
Proxmox 调用全部 mock，无需实体基础设施。
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import AuthManager
from backend.auth_routes import router as auth_router
from backend.api_routes import router as api_router
from backend.docs_routes import router as docs_router
from backend.auth_deps import get_current_user


# ============================================================
# 共享 App Fixture（包含 auth + api + docs 所有路由）
# ============================================================

@pytest.fixture
def full_app(tmp_path):
    """包含全部路由的 TestClient，Proxmox 操作已 mock。"""
    users_file = tmp_path / "users.json"
    sessions_file = tmp_path / "sessions.json"
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    for i in range(1, 4):
        (exp_dir / f"0{i}-kubernetes-network-basics.md").write_text(
            f"# 实验 {i}\n内容", encoding="utf-8"
        )

    mock_rl = MagicMock()
    mock_rl.is_over_limit.return_value = False
    mock_rl.retry_after.return_value = 30

    with patch("backend.auth.USERS_FILE", users_file), \
         patch("backend.auth.SESSIONS_FILE", sessions_file), \
         patch("backend.auth.DATA_DIR", tmp_path):
        mgr = AuthManager()

        with patch("backend.auth_routes.auth_manager", mgr), \
             patch("backend.auth_routes.rate_limiter", mock_rl), \
             patch("backend.docs_routes.EXPERIMENTS_DIR", exp_dir):
            app = FastAPI()
            app.include_router(auth_router)
            app.include_router(api_router)
            app.include_router(docs_router)
            yield TestClient(app, raise_server_exceptions=True), mgr, mock_rl


def _vm_mock(vm_id=500):
    """标准 VM mock：创建/删除均成功，tracker 配合响应。"""
    mock_tracker = MagicMock()
    mock_tracker.get_user_vms.return_value = []
    mock_tracker.get_all_tracked_vms.return_value = []
    mock_tracker.is_owner.return_value = True
    mock_rl = MagicMock()
    mock_rl.is_allowed.return_value = True
    return mock_tracker, mock_rl


# ============================================================
# Journey 1 — 主路径：注册 → 登录 → 读实验 → 登出
# ============================================================

def test_e2e_main_user_journey(full_app):
    """
    用户完整旅程：
    注册 → 登录（获得 cookie）→ 查实验列表 → 读实验内容 → /me 验证身份 → 登出
    """
    client, mgr, _ = full_app

    # 1. 注册
    resp = client.post("/api/auth/register",
                       json={"username": "alice", "password": "secret1", "email": "alice@example.com"})
    assert resp.status_code == 201, resp.text

    # 2. 登录
    resp = client.post("/api/auth/login",
                       json={"username": "alice", "password": "secret1"})
    assert resp.status_code == 200
    assert "set-cookie" in resp.headers

    # 3. 确认身份
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"

    # 4. 查实验列表
    resp = client.get("/api/experiments")
    assert resp.status_code == 200
    experiments = resp.json()["experiments"]
    assert len(experiments) > 0

    # 5. 读实验内容
    exp_id = experiments[0]["id"]
    resp = client.get(f"/api/experiments/{exp_id}")
    assert resp.status_code == 200
    assert "content" in resp.json()

    # 6. 登出
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200

    # 7. 登出后 /me 应返回 401
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# ============================================================
# Journey 2 — VM 生命周期：创建 → 查配额 → 删除 → 配额归零
# ============================================================

def test_e2e_vm_lifecycle(full_app):
    """
    VM 完整生命周期：
    登录 → 创建 VM（配额+1）→ 查配额验证 → 删除 VM → 配额归零
    """
    client, mgr, _ = full_app

    # 准备用户和 session
    mgr.register_user("bob", "secret1")
    token = mgr.create_session("bob")
    client.cookies.set("session_token", token)

    mock_tracker = MagicMock()
    mock_tracker.get_user_vms.return_value = []
    mock_tracker.get_all_tracked_vms.return_value = []
    mock_tracker.is_owner.return_value = True
    mock_rl = MagicMock()
    mock_rl.is_allowed.return_value = True

    # 创建 VM
    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes.list_vms",
               return_value={"success": True, "data": []}), \
         patch("backend.api_routes.create_vm",
               return_value={"success": True, "data": {"vm_id": 500}}), \
         patch("backend.api_routes.rate_limiter", mock_rl):
        resp = client.post("/api/vms/create", json={"template_id": 100})
    assert resp.status_code == 201
    assert resp.json()["success"] is True

    # 查配额（模拟创建后 tracker 已记录）
    mock_tracker.get_user_vms.return_value = [500]
    mock_tracker.get_all_tracked_vms.return_value = [500]
    with patch("backend.api_routes.vm_tracker", mock_tracker):
        resp = client.get("/api/quota")
    assert resp.status_code == 200
    quota = resp.json()
    assert quota["user"]["current"] == 1
    assert quota["system"]["current"] == 1

    # 删除 VM
    _mock_repo_e2e1 = MagicMock()
    _mock_repo_e2e1.has_active_session_for_vm.return_value = False
    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes._get_lab_session_repo", return_value=_mock_repo_e2e1), \
         patch("backend.api_routes.delete_vm",
               return_value={"success": True, "data": {}}):
        resp = client.delete("/api/vms/500")
    assert resp.status_code == 200

    # 配额归零
    mock_tracker.get_user_vms.return_value = []
    mock_tracker.get_all_tracked_vms.return_value = []
    with patch("backend.api_routes.vm_tracker", mock_tracker):
        resp = client.get("/api/quota")
    assert resp.json()["user"]["current"] == 0
    assert resp.json()["system"]["current"] == 0


# ============================================================
# Journey 3 — 多用户隔离：A 的 VM，B 无法删除
# ============================================================

def test_e2e_multi_user_isolation(full_app):
    """
    用户 A 创建 VM → 用户 B 删除被拒（403）→ 用户 A 自己可以删除（200）
    """
    client, mgr, _ = full_app

    mgr.register_user("userA", "secret1")
    mgr.register_user("userB", "secret1")

    # 以用户 B 身份访问
    token_b = mgr.create_session("userB")
    client.cookies.set("session_token", token_b)

    mock_tracker = MagicMock()
    # is_owner: userB 不是 500 的 owner
    mock_tracker.is_owner.return_value = False

    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes.delete_vm",
               return_value={"success": True, "data": {}}):
        resp = client.delete("/api/vms/500")
    assert resp.status_code == 403, "用户 B 不能删除用户 A 的 VM"

    # 切换到用户 A
    token_a = mgr.create_session("userA")
    client.cookies.set("session_token", token_a)
    mock_tracker.is_owner.return_value = True

    _mock_repo_e2e2 = MagicMock()
    _mock_repo_e2e2.has_active_session_for_vm.return_value = False
    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes._get_lab_session_repo", return_value=_mock_repo_e2e2), \
         patch("backend.api_routes.delete_vm",
               return_value={"success": True, "data": {}}):
        resp = client.delete("/api/vms/500")
    assert resp.status_code == 200, "用户 A 可以删除自己的 VM"


# ============================================================
# Journey 4 — 速率限制端到端：触发 429 → Retry-After
# ============================================================

def test_e2e_rate_limit_login(full_app):
    """
    反复登录失败触发速率限制 → 429 + Retry-After 头 → 速率恢复后可正常登录
    """
    client, mgr, mock_rl = full_app
    mgr.register_user("charlie", "secret1")

    # 前 5 次正常放行，第 6 次触发限制
    call_count = [0]

    def rate_side_effect(key, max_requests, window_seconds):
        call_count[0] += 1
        return call_count[0] > 5  # True = over limit = blocked

    mock_rl.is_over_limit.side_effect = rate_side_effect
    mock_rl.retry_after.return_value = 45

    # 消耗配额（5 次失败登录）
    for _ in range(5):
        client.post("/api/auth/login",
                    json={"username": "charlie", "password": "wrongpass"})

    # 第 6 次应被限速
    resp = client.post("/api/auth/login",
                       json={"username": "charlie", "password": "wrongpass"})
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) > 0

    # 速率恢复后正常登录
    mock_rl.is_over_limit.side_effect = None
    mock_rl.is_over_limit.return_value = False
    resp = client.post("/api/auth/login",
                       json={"username": "charlie", "password": "secret1"})
    assert resp.status_code == 200


# ============================================================
# Journey 5 — 配额耗尽：创建至上限 → 再创建被拒
# ============================================================

def test_e2e_quota_exhausted_then_freed(full_app):
    """
    配额耗尽（per-user limit）→ 再创建 429 → 删除一个 → 重新可创建
    """
    client, mgr, _ = full_app
    mgr.register_user("dave", "secret1")
    token = mgr.create_session("dave")
    client.cookies.set("session_token", token)

    mock_tracker = MagicMock()
    mock_rl = MagicMock()
    mock_rl.is_allowed.return_value = True

    # 模拟已达到 per-user 上限
    mock_tracker.get_user_vms.return_value = [500]
    mock_tracker.get_all_tracked_vms.return_value = [500]

    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes.list_vms",
               return_value={"success": True, "data": []}), \
         patch("backend.api_routes.rate_limiter", mock_rl):
        resp = client.post("/api/vms/create", json={"template_id": 100})
    assert resp.status_code == 429, "达到配额上限时应返回 429"

    # 删除一个 VM 后可以重新创建
    mock_tracker.is_owner.return_value = True
    _mock_repo_e2e3 = MagicMock()
    _mock_repo_e2e3.has_active_session_for_vm.return_value = False
    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes._get_lab_session_repo", return_value=_mock_repo_e2e3), \
         patch("backend.api_routes.delete_vm",
               return_value={"success": True, "data": {}}):
        resp = client.delete("/api/vms/500")
    assert resp.status_code == 200

    # 清空配额后再创建
    mock_tracker.get_user_vms.return_value = []
    mock_tracker.get_all_tracked_vms.return_value = []
    with patch("backend.api_routes.vm_tracker", mock_tracker), \
         patch("backend.api_routes.list_vms",
               return_value={"success": True, "data": []}), \
         patch("backend.api_routes.create_vm",
               return_value={"success": True, "data": {"vm_id": 501}}), \
         patch("backend.api_routes.rate_limiter", mock_rl):
        resp = client.post("/api/vms/create", json={"template_id": 100})
    assert resp.status_code == 201, "删除后配额释放，应可创建新 VM"


# ============================================================
# Journey 6 — 实验活动追踪：读实验 → session activity 更新
# ============================================================

def test_e2e_experiment_activity_tracking(full_app):
    """
    用户登录后读实验 → session 的 current_experiment 被更新 → 可被 admin 观察到
    """
    client, mgr, _ = full_app
    mgr.register_user("eve", "secret1")
    token = mgr.create_session("eve")
    client.cookies.set("session_token", token)

    # 读第一个实验
    resp = client.get("/api/experiments")
    assert resp.status_code == 200
    first_id = resp.json()["experiments"][0]["id"]

    resp = client.get(f"/api/experiments/{first_id}")
    assert resp.status_code == 200

    # 验证 session 中 current_experiment 已更新
    sessions = mgr.get_active_sessions()
    eve_session = next((s for s in sessions if s["username"] == "eve"), None)
    assert eve_session is not None
    assert eve_session.get("current_experiment") == first_id, \
        "读实验后 session.current_experiment 应被更新"
