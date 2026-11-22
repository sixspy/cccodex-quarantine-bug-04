import { api } from '../api.js';

export async function renderBins(el) {
  const [bins, rows, pin] = await Promise.all([
    api('/api/bins'),
    api('/api/rows'),
    api('/api/pin_batch/snap'),
  ]);
  const pinChip = pin.chip === '钉批已亮' ? 'ok' : 'bad';
  const pinnedBatch = pin.batch_code;
  el.innerHTML = `
    <div class="card">
      <h2>隔离舱</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">钉批芯片</span><b><span class="chip ${pinChip}">${pin.chip}</span></b></div>
        <div class="stat"><span class="muted">对账批次号</span><b>${pinnedBatch || '无落点'}</b></div>
      </div>
      <table>
        <thead><tr><th>舱号</th><th>标题</th><th>状态</th><th>占用/容量</th><th>复核条</th></tr></thead>
        <tbody>
          ${(bins.items || []).map((b) => `
            <tr>
              <td>${b.bin_code}</td>
              <td>${b.title}</td>
              <td><span class="chip">${b.status}</span></td>
              <td>${b.row_count}/${b.capacity}</td>
              <td>${b.pending_count > 0
                ? `<span class="chip bad">待复核 ${b.pending_count}</span>`
                : '<span class="chip ok">复核已清</span>'}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>舱内行</h2>
      <table>
        <thead><tr><th>舱</th><th>条目键</th><th>质量</th><th>原因</th><th>状态</th><th>复核条</th></tr></thead>
        <tbody>
          ${(rows.items || []).map((r) => `
            <tr>
              <td>${r.bin_code}</td>
              <td>${r.item_key}</td>
              <td>${r.quality}</td>
              <td>${r.reason}</td>
              <td><span class="chip">${r.status}</span></td>
              <td>${r.status === '待复核'
                ? '<span class="chip bad">挂复核条</span>'
                : `<span class="chip">${r.status === '已放行' ? '放行已走' : '不在复核'}</span>`}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}
