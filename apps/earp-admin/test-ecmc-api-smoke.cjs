/* ECMC N01B — ecmc-api.js 冒烟/契约测试（无浏览器）
 * FE-ECMC-2026-0830 §15：Headers / 稳定错误映射 / ETag 更新 / Idempotency 重试 / 冲突停止
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, 'js', 'ecmc-api.js'), 'utf8');

let allOk = true;
async function check(name, fn) {
  try { await fn(); console.log('  ✓ ' + name); }
  catch (e) { allOk = false; console.error('  ✗ ' + name + ' — ' + (e && e.message)); }
}

function freshEnv(responses) {
  const calls = [];
  let idx = 0;
  global.fetch = async (url, opts) => {
    calls.push({ url, opts: opts || {}, headers: (opts && opts.headers) || {} });
    const canned = responses && responses[idx++];
    return {
      ok: !canned || canned.status < 400,
      status: canned ? canned.status : 200,
      headers: { get: (k) => {
        const key = k.toLowerCase();
        if (key === 'content-type') return (canned && canned.headers && canned.headers['content-type']) || 'application/json';
        return canned && canned.headers ? canned.headers[key] : '';
      } },
      text: async () => (canned ? JSON.stringify(canned.body) : '{}'),
    };
  };
  global.EARP = { apiBase: 'http://test', headers: () => ({ 'Content-Type': 'application/json' }) };
  global.window = {};
  eval(src);
  return { calls, api: global.window.ECMC.api };
}

(async function () {
  await check('Idempotency-Key 每次生成且唯一', () => {
    freshEnv();
    const api = global.window.ECMC.api;
    const a = api.idempotencyKey();
    const b = api.idempotencyKey();
    assert.ok(a && b && a !== b, 'keys must be unique');
    assert.ok(/^n01b-/.test(a), 'key must have n01b- prefix');
  });

  await check('写请求携带 If-Match "v<revision>" 与 Idempotency-Key', async () => {
    const env = freshEnv([{ status: 200, body: { model_version_id: 'cmv-1', node_key: 'n-1', revision: 3 } }]);
    const client = new env.api.VersionClient('cm-1', 'cmv-1', 2, () => {});
    await client.mutate('PUT', '/causal-models/cm-1/versions/cmv-1/nodes/n-1', { business_name: 'x' }, { idempotencyKey: 'k-1' });
    const req = env.calls[0];
    assert.ok(req, 'fetch must be called once');
    assert.strictEqual(req.headers['If-Match'], '"v2"', 'If-Match must be "v2"');
    assert.strictEqual(req.headers['Idempotency-Key'], 'k-1');
    assert.strictEqual(req.opts.method, 'PUT');
    assert.strictEqual(JSON.parse(req.opts.body).business_name, 'x');
  });

  await check('成功后用响应 revision 刷新 ETag（后续写入使用新 revision）', async () => {
    const env = freshEnv([
      { status: 200, body: { model_version_id: 'cmv-1', node_key: 'n-1', revision: 4 } },
      { status: 200, body: { model_version_id: 'cmv-1', node_key: 'n-2', revision: 5 } },
    ]);
    const client = new env.api.VersionClient('cm-1', 'cmv-1', 3, () => {});
    await client.mutate('PUT', '/x/n-1', {});
    await client.mutate('PUT', '/x/n-2', {});
    assert.strictEqual(env.calls[1].headers['If-Match'], '"v4"', 'second write must use refreshed revision 4');
    assert.strictEqual(client.revision, 5);
  });

  await check('409 VERSION_CONFLICT → 停止写队列 + onConflict 回调', async () => {
    let conflicted = null;
    const env = freshEnv([
      { status: 409, headers: { 'x-correlation-id': 'corr-1' }, body: { error: { code: 'VERSION_CONFLICT', message: 'stale', correlation_id: 'corr-1', details: { current_revision: 9 } } } },
      { status: 200, body: { revision: 10 } },
    ]);
    const client = new env.api.VersionClient('cm-1', 'cmv-1', 4, (e) => { conflicted = e; });
    await assert.rejects(client.mutate('PUT', '/x', {}), (e) => e.code === 'VERSION_CONFLICT');
    assert.strictEqual(conflicted.code, 'VERSION_CONFLICT');
    assert.strictEqual(conflicted.correlationId, 'corr-1');
    assert.strictEqual(client.stopped, true, 'client must stop after conflict');
    // 后续写入被本地拦截，不再发请求（禁止静默覆盖）
    await assert.rejects(client.mutate('PUT', '/x2', {}), (e) => e.localStopped === true);
    assert.strictEqual(env.calls.length, 1, 'no further requests after stop');
  });

  await check('稳定错误映射：403/404/409/422 → EcmcApiError{status,code,correlationId}', async () => {
    const cases = [
      { status: 403, code: 'PERMISSION_DENIED' },
      { status: 404, code: 'CAUSAL_MODEL_NOT_FOUND' },
      { status: 409, code: 'ACTIVE_VERSION_CHANGED' },
      { status: 422, code: 'MISSING_IF_MATCH' },
    ];
    for (const c of cases) {
      const env = freshEnv([{ status: c.status, body: { error: { code: c.code, message: 'm', correlation_id: 'corr-' + c.status, details: {} } } }]);
      await assert.rejects(env.api.get('/causal-models'), (e) => {
        return e.status === c.status && e.code === c.code && e.correlationId === 'corr-' + c.status;
      });
    }
  });

  await check('422 MODEL_VALIDATION_FAILED 携带 validation_result 供校验面板消费', async () => {
    const vr = { validation_run_id: 'cvr-1', result: 'failed', issues: [{ code: 'CAUSAL_DAG_CYCLE', severity: 'error', location: { resource_type: 'version' }, message: 'cycle' }] };
    const env = freshEnv([{ status: 422, body: { error: { code: 'MODEL_VALIDATION_FAILED', message: 'blocked', correlation_id: 'corr-v', details: { validation_result: vr } } } }]);
    try { await env.api.post('/x/validate', { mode: 'full' }, { idempotencyKey: 'k' }); assert.fail('should throw'); }
    catch (e) {
      assert.strictEqual(e.code, 'MODEL_VALIDATION_FAILED');
      assert.deepStrictEqual(e.details.validation_result, vr);
    }
  });

  await check('hydrateModels：列表无 versions 时补取模型详情与最新 Version 内容', async () => {
    global.window = {};
    const commonSrc = fs.readFileSync(path.join(__dirname, 'js', 'ecmc-common.js'), 'utf8');
    eval(commonSrc);
    eval(src);
    // Node eval 不会从 window.ECMC 创建全局 ECMC 标识符（浏览器会自动绑定）
    global.ECMC = global.window.ECMC;
    const routes = {
      '/causal-models': { status: 200, body: [
        { model_id: 'cm-1', name: 'M1', data_domain_id: 'production_data', active_pointer: { model_version_id: 'cmv-2', snapshot_id: 'cms-1' } },
      ]},
      '/causal-models/cm-1': { status: 200, body: { model_id: 'cm-1', name: 'M1', data_domain_id: 'production_data', active_pointer: { model_version_id: 'cmv-2', snapshot_id: 'cms-1' }, versions: [
        { model_version_id: 'cmv-2', version: '2', status: 'published', revision: 5 },
        { model_version_id: 'cmv-1', version: '1', status: 'draft', revision: 3 },
      ]}},
      '/causal-models/cm-1/versions/cmv-2': { status: 200, body: { model_version_id: 'cmv-2', diagnostic_target: { objective: 'diagnose', entry_point: 'production_output', direction: 'down' }, updated_at: '2026-08-30T10:00:00Z' } },
    };
    global.fetch = async (url) => {
      const canned = routes[url.replace('http://test/v1/ecmc', '')];
      return {
        ok: true, status: 200,
        headers: { get: () => 'application/json' },
        text: async () => JSON.stringify(canned.body),
      };
    };
    const hydrated = await global.window.ECMC.common.hydrateModels([{ model_id: 'cm-1', name: 'M1', data_domain_id: 'production_data', active_pointer: { model_version_id: 'cmv-2', snapshot_id: 'cms-1' } }]);
    assert.strictEqual(hydrated.length, 1);
    assert.strictEqual(hydrated[0].versions.length, 2, 'versions hydrated from model detail');
    assert.strictEqual(hydrated[0].latestVersion.model_version_id, 'cmv-2');
    assert.strictEqual(hydrated[0].latestDetail.diagnostic_target.entry_point, 'production_output');
    assert.ok(hydrated[0].latestDetail.updated_at, 'version updated_at captured');
  });

  process.exit(allOk ? 0 : 1);
})();
