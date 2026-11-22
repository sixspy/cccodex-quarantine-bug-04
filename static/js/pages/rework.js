import { api } from '../api.js';

export async function renderRework(el) {
  const [data, pin] = await Promise.all([
    api('/api/rework/jobs'),
    api('/api/pin_batch/snap'),
  ]);
  const pinChip = pin.chip === '钉批已亮' ? 'ok' : 'bad';
  el.innerHTML = `
    <div class="card">
      <h2>回炉队列</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">钉批芯片</span><b><span class="chip ${pinChip}">${pin.chip}</span></b></div>
        <div class="stat"><span class="muted">对账批次号</span><b>${pin.batch_code || '无落点'}</b></div>
      </div>
      ${pin.gate_allows
        ? ''
        : `<div class="hint-box">回炉成功会放回合格流，钉批未对齐已挡：${(pin.misalign_reasons || []).join('；')}</div>`}
      <table>
        <thead><tr><th>任务</th><th>条目</th><th>舱</th><th>状态</th><th>次数</th><th>操作</th></tr></thead>
        <tbody>
          ${(data.items || []).map((j) => `
            <tr>
              <td>${j.job_code}</td>
              <td>${j.item_key}</td>
              <td>${j.bin_code}</td>
              <td><span class="chip">${j.status}</span></td>
              <td>${j.attempt}</td>
              <td class="row">
                ${['排队','失败'].includes(j.status) ? `
                  <button data-ok="${j.id}" ${pin.gate_allows ? '' : 'disabled'}>执行成功</button>
                  <button data-bad="${j.id}">执行失败</button>
                ` : (j.message || '')}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('[data-ok]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/rework/jobs/${btn.dataset.ok}/run`, {
          method: 'POST', body: JSON.stringify({ succeed: true }),
        });
      } catch (e) { alert(e.message); }
      await renderRework(el);
    };
  });
  el.querySelectorAll('[data-bad]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/rework/jobs/${btn.dataset.bad}/run`, {
          method: 'POST', body: JSON.stringify({ succeed: false }),
        });
      } catch (e) { alert(e.message); }
      await renderRework(el);
    };
  });
}
