# ConfigMap Owner Dogfood Checklist v0.1

## 为什么需要这一步

本实验机器人 verifier 能确认 ConfigMap 值和 rollout restart 状态，但因为 `kubectl exec` 被安全策略禁止，机器无法直接读取容器内运行进程的环境变量值。也就是说，"ConfigMap 改了但运行中容器仍读到旧值"这个本实验最核心的教学语义，**verifier 只能间接证明（通过 rollout-restart 时序信号），无法直接观测到**。只有 Owner 亲自用 dogfood 账号走一遍、亲眼在终端里看到 old → new 的变化，才能确认这个核心学习语义对真实读者是成立的。

## 账号与访问

- 账号：`owner-test-01`（已存在的非 admin 普通测试账号，密码见 `/root/.k8s-netlab-admin-credentials`）
- 本次临时授权：仅此账号 + 仅此 lab_id（`ce793f9b-e416-44e2-9a32-c79b6488cfa2`）
- 已通过真实 API（非 admin bypass）验证：`owner-test-01` 视角 `GET /api/labs` 中该 lab `is_startable=true`
- 入口：登录后打开实验目录页，找到"ConfigMap 修改后不生效排查实验"，点击进入

## 操作步骤（照抄即可，命令与实验页面里的完全一致）

### A. 初始状态

1. 按页面 Step 1、Step 2 的指引依次执行两条命令，创建 ConfigMap 和 Deployment
2. 等 Pod 变成 `Running`
3. **需要记录**：Pod 是否真的 Running？（页面 verify 会自动确认，但请你自己也看一眼 `kubectl get pods` 的输出）

### B. 修改 ConfigMap

4. 按 Step 3、Step 4 的指引，先看一眼当前 ConfigMap 内容（应该是 `old`），再执行 patch 命令改成 `new`
5. 按 Step 5 的指引，重新查看当前 Pod（`kubectl get pods -l app=demo`）
6. **需要记录**：这一步是本实验最关键的一步——ConfigMap 现在已经确认是 `new` 了，但你看到的 Pod 名字和 Step 2 创建时是不是完全一样？AGE 是不是没有重置？

### C. 修复

7. 按 Step 6 的指引执行 `kubectl rollout restart`
8. 按 Step 7 的指引等待 rollout 完成，再看一眼 Pod 列表
9. **需要记录**：新 Pod 的名字是不是和之前不一样了？AGE 是不是从几秒重新开始计时？

### D. 收尾

10. 按 Step 8 的指引清理资源
11. 确认页面显示实验完成（session 应该会自动进入结束状态）

## 必须明确记录的四件事

请在测试完成后明确告诉我（哪怕只是简单的"是/否"）：

1. **Step A**：你是否真的看到 Pod 变成了 Running？应用（如果有办法观察）读到的是不是 `old`？
2. **Step B（核心）**：ConfigMap 更新之后，你是否确认看到"还是同一个 Pod，没有任何变化"？
3. **Step C**：`rollout restart` 之后，你是否确认看到一个全新的 Pod 出现？
4. **哪一步卡住了**（如果有）：具体是哪一步、报了什么错、命令是不是照着页面抄的就是抄不对（比如复制粘贴出了格式问题）
5. **命令本身顺不顺**：有没有哪条命令的提示文字看不懂、或者执行结果和页面预告的不一样
6. **严重程度分级**：如果发现问题，按 BLOCKER（完全走不下去）/ HIGH（能走完但体验很差或核心语义没confirm到）/ MEDIUM（小瑕疵不影响核心结论）/ LOW（文字措辞类）来标一下

## 测试期间我在做什么

我只会**只读监控**，不会替你操作任何实验步骤：
- 生产 health 端点
- 错误日志（journalctl）
- 你的 session 状态（是否正常推进、有没有卡在某一步）
- cleanup 是否正常完成
- 有没有 VM 被标记为 tainted

## 测试结束后

无论结果如何，测试完成后我会：
1. 从 `LABGEN_ENABLED_LAB_IDS` 移除这个 lab_id
2. 从 `data/labgen_invites.json` 移除这条临时邀请
3. 重启服务，验证 `owner-test-01` 和其它任意账号重新回到 403 / `is_startable=false`
4. 不删除 lab draft 或 article draft（内容本身保留，只关闭访问）

如果测试中发现 BLOCKER/HIGH 级别问题：
- 保留问题现场的具体证据（session_id、报错文本、卡住的 step_id）
- 立即执行上面的关闭步骤
- 不会启动 DNS Service Discovery Sprint
- 只会建议一个针对性的 fix 方案，不会自作主张展开修复
