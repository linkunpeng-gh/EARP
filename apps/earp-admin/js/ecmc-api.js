/* ════════════════════════════════════════════════════════════════════════
 * ECMC N01B — 统一 API 客户端（ecmc-api.js）
 *
 * 设计: arch/design/2026-08-30-ecmc-frontend-information-architecture-and-page-template.md
 *   §15 HTTP 与错误处理规范、§19 API 映射、§13 公共组件契约
 * 合同: api/2026-08-30-n01a-causal-model-management-api-contract.md
 *
 * 职责（业务页面不得复制 fetch 封装）：
 *   - 统一 headers（Idempotency-Key / If-Match / ETag）
 *   - 稳定错误映射（403/404/409/422 → EcmcApiError，携带 correlation_id）
 *   - VersionClient：同一 Version 的写入串行执行、成功后用响应 revision 刷新 ETag、
 *     409 VERSION_CONFLICT 停止写队列并要求重新加载（禁止静默覆盖）
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var BASE = '/v1/ecmc';

  /* ── 稳定错误 ── */
  function EcmcApiError(status, code, message, correlationId, details) {
    var err = new Error((code || 'HTTP_' + status) + ': ' + (message || '请求失败'));
    err.name = 'EcmcApiError';
    err.status = status;
    err.code = code || ('HTTP_' + status);
    err.correlationId = correlationId || '';
    err.details = details || {};
    return err;
  }

  /* 每个业务操作生成唯一 Idempotency-Key；同一用户操作的网络重试复用原 key，
   * 不同用户操作不得复用。调用方用 EcmcApi.idempotencyKey() 生成一次并在重试间复用。 */
  function newIdempotencyKey() {
    return 'n01b-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10) + '-' + Math.random().toString(36).slice(2, 6);
  }

  function parsePayload(res, text) {
    var ct = res.headers.get('content-type') || '';
    if (!text) return null;
    if (ct.indexOf('json') !== -1) {
      try { return JSON.parse(text); } catch (_) { /* fallthrough */ }
    }
    return { raw: text };
  }

  async function request(method, path, options) {
    options = options || {};
    var headers = Object.assign({}, EARP.headers(), options.headers || {});
    if (options.body !== undefined && options.body !== null) {
      headers['Content-Type'] = 'application/json';
    }
    if (options.ifMatch) headers['If-Match'] = '"v' + options.ifMatch + '"';
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;

    var fetchOpts = { method: method, headers: headers, signal: options.signal };
    if (options.body !== undefined && options.body !== null) {
      fetchOpts.body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
    }

    var res = await fetch(EARP.apiBase + BASE + path, fetchOpts);
    var text = await res.text().catch(function () { return ''; });
    var payload = parsePayload(res, text);
    var etag = res.headers.get('ETag') || '';

    if (!res.ok) {
      var e = payload && payload.error ? payload.error : {};
      var err = EcmcApiError(res.status, e.code, e.message, e.correlation_id, e.details);
      err.payload = payload;
      throw err;
    }
    return { status: res.status, body: payload, etag: etag, headers: res.headers };
  }

  function parseEtag(etag) {
    if (!etag) return null;
    var m = /^"?v(\d+)"?$/.exec(etag.trim());
    return m ? parseInt(m[1], 10) : null;
  }

  /* ── VersionClient：串行写队列 + ETag 刷新 + 冲突停止 ── */
  function VersionClient(modelId, versionId, revision, onConflict) {
    this.modelId = modelId;
    this.versionId = versionId;
    this.revision = revision;
    this.stopped = false;
    this.onConflict = onConflict || function () {};
    this._queue = Promise.resolve();
  }

  VersionClient.prototype.refresh = function (revision) {
    this.revision = revision;
    this.stopped = false;
  };

  VersionClient.prototype.stop = function () {
    this.stopped = true;
  };

  VersionClient.prototype._enqueue = function (task) {
    var run = this._queue.then(task, task); // 前序失败不阻塞后续（但冲突后 stopped 会拦截）
    // 让队列继续推进，即使本条失败
    this._queue = run.catch(function () {});
    return run;
  };

  /* 业务写：同一 Version 的写入串行执行，不允许并发发送多个旧 revision 请求 */
  VersionClient.prototype.mutate = function (method, path, body, options) {
    var self = this;
    options = options || {};
    return this._enqueue(function () {
      if (self.stopped) {
        var err = EcmcApiError(409, 'VERSION_CONFLICT', '版本已被其他用户更新，请重新加载后再编辑。', '');
        err.localStopped = true;
        throw err;
      }
      return request(method, path, {
        body: body,
        ifMatch: self.revision,
        idempotencyKey: options.idempotencyKey || newIdempotencyKey(),
        signal: options.signal,
      }).then(function (res) {
        var rev = res.body && typeof res.body.revision === 'number' ? res.body.revision : parseEtag(res.etag);
        if (rev != null) self.revision = rev;
        self._lastResponse = res;
        return res;
      }).catch(function (err) {
        if (err && err.code === 'VERSION_CONFLICT' && !err.localStopped) {
          self.stopped = true;
          self.onConflict(err);
        }
        throw err;
      });
    });
  };

  /* ── 对外 API ── */
  window.ECMC = window.ECMC || {};
  window.ECMC.api = {
    BASE: BASE,
    EcmcApiError: EcmcApiError,
    idempotencyKey: newIdempotencyKey,
    parseEtag: parseEtag,
    get: function (path, options) { return request('GET', path, options); },
    post: function (path, body, options) { return request('POST', path, Object.assign({ body: body }, options)); },
    put: function (path, body, options) { return request('PUT', path, Object.assign({ body: body }, options)); },
    patch: function (path, body, options) { return request('PATCH', path, Object.assign({ body: body }, options)); },
    del: function (path, options) { return request('DELETE', path, options); },
    VersionClient: VersionClient,
  };
})();
