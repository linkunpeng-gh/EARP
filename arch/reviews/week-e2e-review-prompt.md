# 本周工作评审 Prompt

> 一刀。改动集中 4 个文件。输出 `arch/reviews/week-e2e-review.md`。

```bash
cd /Users/linkunpeng/work/EARP && codex exec "本周工作代码评审。

评审对象：
- apps/earp-server/tests/test_e2e.py (126行，全链路 e2e 测试)
- apps/earp-server/Makefile (加 make e2e 目标)
- apps/earp-server/src/earp_server/main.py (EventBus test-mode 回退 + test lifespan 空权限 capability)
- apps/earp-server/src/earp_server/capability/registry.py (demo:echo → demo.echo 避 psycopg 冲突)

已知限制：e2e 测试 PolicyLayer 权限经 lifespan test-mode 绕过（空 required_permissions），不在测试中做 DB 种子数据。psycopg3 async 引擎不支持 exec_driver_sql 稳定种子。

检查项：

1. test_e2e.py：
   - session→plan→invoke 链是否覆盖完整？（M1 会话/M3 规划/M1+2+5 调用）
   - DB 验证（audit/checkpoint/blobs/execution）断言是否有效？
   - asyncio.run() + 内部 async 函数在 TestClient 同步上下文中是否可靠？
   - 测试依赖 lifespan 注册的 cap-demo-echo——如果 lifespan 失败测试是否直接 crash？

2. Makefile：
   - make e2e 命令语法是否正确？
   - .PHONY 声明是否包含 e2e？

3. main.py：
   - EventBus test-mode 回退逻辑是否正确？（test/dev→进程内，prod→RedisStreams）
   - test lifespan 中 ON CONFLICT DO UPDATE SET required_permissions='{}'——是否每次测试覆盖会修改 dev 数据？
   - exec_driver_sql 在 async lifespan 中是否可靠？（已知坑）

4. registry.py：
   - demo:echo→demo.echo 的变更是否影响已有引用？（Business Dictionary/M2 PolicyLayer 匹配）
   - 向下兼容性：cap-demo-echo 已在 DB 中的旧 required_permissions 是否会造成不匹配？

输出：逐项 PASS/ISSUE + P0/P1/P2 + file:line。中文。" > arch/reviews/week-e2e-review.md 2>&1
```
