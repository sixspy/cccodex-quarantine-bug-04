import { api } from '../api.js';

export async function renderReconcile(el) {
  const [data, pin] = await Promise.all([
    api('/api/reports'),
    api('/api/pin_batch/snap'),
  ]);
  const reasons = pin.misalign_reasons || [];
  const gate = pin.gate_allows
    ? '<span class="chip ok">闸已放行</span>'
    : '<span class="chip bad">闸已挡</span>';
  el.innerHTML = `
    <div class="card">
      <h2>隔离对账 ${gate}</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">钉批芯片</span><b><span class="chip ${pin.chip === '钉批已亮' ? 'ok' : 'bad'}">${pin.chip}</span></b></div>
        <div class="stat"><span class="muted">对账批次号</span><b>${pin.batch_code || '无落点'}</b></div>
        <div class="stat"><span class="muted">钉批落点</span><b>${pin.pinned_fingerprint || '无'}</b></div>
        <div class="stat"><span class="muted">坏件数 / 快照行</span><b>${pin.bad_count}</b></div>
      </div>
      ${reasons.length ? `<div class="hint-box">钉批与落点对不齐，清洗编排已挡：${reasons.join('；')}</div>` : ''}
      <div class="row"><button id="run">生成对账报告</button></div>
    </div>
    <div class="card">
      <h3>钉批落点行（只读）</h3>
      <table>
        <thead><tr><th>批次号</th><th>坏件指纹</th><th>坏件数</th><th>读轨</th><th>拒回刷</th></tr></thead>
        <tbody>
          ${pin.ledger_present ? `
            <tr>
              <td>${pin.batch_code}</td>
              <td>${pin.pinned_fingerprint}</td>
              <td>${pin.bad_count}</td>
              <td>${pin.active_read}</td>
              <td>${pin.reject_refresh ? '是' : '否'}</td>
            </tr>` : '<tr><td colspan="5" class="muted">库无钉批落点</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>时间</th><th>摘要</th><th>待复核</th><th>放行</th><th>回炉</th><th>废弃</th><th>错位</th><th>指纹</th></tr></thead>
        <tbody>
          ${(data.items || []).map((r) => `
            <tr>
              <td>${r.created_at}</td>
              <td>${r.summary}</td>
              <td>${r.open_rows}</td>
              <td>${r.released}</td>
              <td>${r.reworking}</td>
              <td>${r.abandoned}</td>
              <td><span class="chip ${r.mismatch ? 'bad' : 'ok'}">${r.mismatch}</span></td>
              <td><span class="chip ${r.fingerprint_match ? 'ok' : 'bad'}">${r.fingerprint_match ? '对齐' : '拧花'}</span></td>
            </tr>`).join('') || '<tr><td colspan="8" class="muted">暂无报告</td></tr>'}
        </tbody>
      </table>
    </div>`;
  el.querySelector('#run').onclick = async () => {
    try {
      await api('/api/reports/run', { method: 'POST', body: '{}' });
    } catch (e) {
      alert(e.message);
    }
    await renderReconcile(el);
  };
}
