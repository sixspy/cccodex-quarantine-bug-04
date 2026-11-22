import { api } from '../api.js';

export async function renderSettings(el) {
  const [data, pin] = await Promise.all([
    api('/api/settings'),
    api('/api/pin_batch/snap'),
  ]);
  const pinChip = pin.chip === '钉批已亮' ? 'ok' : 'bad';
  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <table>
        <thead><tr><th>项</th><th>说明</th><th>值</th><th></th></tr></thead>
        <tbody>
          ${(data.items || []).map((s) => `
            <tr>
              <td>${s.key}</td>
              <td>${s.label}</td>
              <td><input data-key="${s.key}" value="${s.value}" /></td>
              <td><button data-save="${s.key}">保存</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>钉批钉点口径</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">钉批芯片</span><b><span class="chip ${pinChip}">${pin.chip}</span></b></div>
        <div class="stat"><span class="muted">对账批次号</span><b>${pin.batch_code || '无落点'}</b></div>
        <div class="stat"><span class="muted">钉批落点</span><b>${pin.pinned_fingerprint || '无'}</b></div>
        <div class="stat"><span class="muted">读轨</span><b>${pin.active_read}</b></div>
      </div>
      <p class="muted">单读轨口径：切流账册钉住当刻批次号与坏件指纹，供对账只读引用并拒回刷；双写两轨禁止双开。</p>
      ${pin.gate_allows
        ? '<p class="muted">钉批芯片 · 批次号 · 落点三项一致。</p>'
        : `<div class="hint-box">对不齐：${(pin.misalign_reasons || []).join('；')}</div>`}
    </div>`;
  el.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      const input = el.querySelector(`input[data-key="${btn.dataset.save}"]`);
      try {
        await api('/api/settings/update', {
          method: 'POST',
          body: JSON.stringify({ key: btn.dataset.save, value: input.value }),
        });
      } catch (e) { alert(e.message); }
      await renderSettings(el);
    };
  });
}
