import { api } from '../api.js';

export async function renderReview(el) {
  const [data, pin] = await Promise.all([
    api('/api/tickets'),
    api('/api/pin_batch/snap'),
  ]);
  const pinChip = pin.chip === '钉批已亮' ? 'ok' : 'bad';
  el.innerHTML = `
    <div class="card">
      <h2>复核放行</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">钉批芯片</span><b><span class="chip ${pinChip}">${pin.chip}</span></b></div>
        <div class="stat"><span class="muted">对账批次号</span><b>${pin.batch_code || '无落点'}</b></div>
        <div class="stat"><span class="muted">钉批落点</span><b>${pin.pinned_fingerprint || '无'}</b></div>
      </div>
      ${pin.gate_allows
        ? '<div class="hint-box">钉批落点对齐，放行闸已开。</div>'
        : `<div class="hint-box">钉批落点未对齐，放行已挡：${(pin.misalign_reasons || []).join('；')}</div>`}
      <table>
        <thead><tr><th>单号</th><th>条目</th><th>舱</th><th>裁决</th><th>操作</th></tr></thead>
        <tbody>
          ${(data.items || []).map((t) => `
            <tr>
              <td>${t.ticket_code}</td>
              <td>${t.item_key}</td>
              <td>${t.bin_code}</td>
              <td><span class="chip">${t.decision}</span></td>
              <td class="row">
                ${t.decision === '待决' ? `
                  <button data-d="放行" data-id="${t.id}" ${pin.gate_allows ? '' : 'disabled'}>放行</button>
                  <button data-d="驳回回炉" data-id="${t.id}">驳回回炉</button>
                  <button data-d="废弃" data-id="${t.id}">废弃</button>
                ` : (t.comment || '')}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('button[data-d]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/tickets/${btn.dataset.id}/decide`, {
          method: 'POST',
          body: JSON.stringify({ decision: btn.dataset.d, comment: '台上裁决' }),
        });
      } catch (e) { alert(e.message); }
      await renderReview(el);
    };
  });
}
