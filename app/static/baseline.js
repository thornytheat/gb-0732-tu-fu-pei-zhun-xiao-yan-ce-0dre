import {badge, el, fmt, reason, table} from './ledgers.js';

const EDITION = {field: '外业原件', reference: '校准副本'};
const state = {snapshot: null, busy: false, edgeId: null};

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error('服务暂不可达，请重试。');
  }
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(error?.detail?.message || `请求失败，请重试。${response.status}`);
  }
  return response.json();
}

const post = (url, payload) => request(url, {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
});

function feedback(node, message) {
  node.textContent = message || '';
  node.hidden = !message;
}

function editionTag(edition) {
  const node = el('span', EDITION[edition] || edition, 'status');
  node.dataset.status = edition === 'field' ? 'FIT' : 'BLOCKED';
  return node;
}

function policyPanel(root, snapshot) {
  const policy = snapshot.policy;
  const panel = el('div', null, 'ruling-policy');
  const items = [
    ['裁定铁律', policy.rule],
    ['逐点拼合', policy.mixing_allowed ? '允许' : '禁止 · 拼合会把两版来源混成一册，整幅采用单一来源'],
    ['拼缝见证', `${EDITION[policy.witness_source]}独立尺量，逐站投影到各采用模型测距`],
  ];
  for (const [label, text] of items) {
    const row = el('p');
    row.append(el('strong', label), el('span', text));
    panel.append(row);
  }
  root.append(panel);
}

function rulingsTable(root, snapshot) {
  root.append(el('h3', '逐幅基准对照裁定'));
  root.append(table(
    [['图幅'], ['采用基准'], ['数据版本'], ['采信点', 'num'], ['均方根 m', 'num'], ['采用理由'],
     ['放弃版本'], ['放弃理由'], ['拼合']],
    snapshot.rulings.map(row => [
      `${row.code} ${row.title}`,
      editionTag(row.adopted.edition),
      row.adopted.data_version,
      row.adopted.control_count,
      fmt(row.adopted.rms_m),
      reason(row.adopted_reason),
      EDITION[row.rejected.edition],
      reason(row.rejected_reason),
      row.mixing_allowed ? '允许' : '禁止',
    ])));
}

function edgeStations(root, edge) {
  if (!edge) return;
  root.append(el('h3', `${edge.code} 拼缝逐站结论（${EDITION[edge.a_edition]} → ${EDITION[edge.b_edition]}）`));
  if (!edge.stations.length) {
    root.append(el('p', '该拼缝无可用见证点。', 'feedback'));
    return;
  }
  root.append(table(
    [['证点'], ['甲侧像素'], ['乙侧像素'], ['法向 m', 'num'], ['切向 m', 'num'], ['平面偏差 m', 'num'], ['源行']],
    edge.stations.map(station => [
      station.name, station.a_pixel.join(' / '), station.b_pixel.join(' / '),
      fmt(station.normal_m), fmt(station.tangent_m), fmt(station.gap_m),
      `${station.source.file} #${station.source.line}`,
    ])));
}

function seamsTable(root, snapshot) {
  root.append(el('h3', '拼缝结论'));
  const edges = snapshot.mosaic.edges;
  root.append(table(
    [['拼缝'], ['相邻图幅'], ['甲侧基准'], ['乙侧基准'], ['状态'], ['见证点', 'num'],
     ['最大 m', 'num'], ['中位 m', 'num'], ['理由']],
    edges.map(edge => [
      edge.code, `${edge.a} · ${edge.b}`, EDITION[edge.a_edition], EDITION[edge.b_edition],
      badge(edge.status), edge.count, fmt(edge.max_m), fmt(edge.median_m),
      edge.reasons.length ? edge.reasons.map(reason).join(' / ') : '—',
    ])));
  const active = edges.find(edge => edge.code === state.edgeId) || edges[0];
  edgeStations(root, active);
  const buttons = el('div', null, 'seam-switch');
  for (const edge of edges) {
    const button = el('button', edge.code, 'text-action');
    button.type = 'button';
    button.setAttribute('aria-pressed', String(edge.code === active.code));
    button.addEventListener('click', () => {
      state.edgeId = edge.code;
      render(root);
    });
    buttons.append(button);
  }
  root.append(buttons);
  if (snapshot.mosaic.quarantine.length) {
    root.append(el('h3', '见证隔离'));
    root.append(table([['拼缝'], ['点名'], ['原因码'], ['判定'], ['源行']],
      snapshot.mosaic.quarantine.map(row => [row.edge || '—', row.name, row.reason, reason(row.reason),
        `${row.source.file} #${row.source.line}`])));
  }
}

function decisionsTable(root, snapshot) {
  const signed = new Map(snapshot.signatures.map(item => [item.sheet, item]));
  root.append(el('h3', '签审裁定（签审只认本裁定册）'));
  root.append(table(
    [['图幅'], ['沿用基准'], ['裁定结论'], ['理由'], ['关联拼缝'], ['签审员'], ['签审时间']],
    snapshot.decisions.map(row => {
      const signature = signed.get(row.code);
      return [`${row.code} ${row.title}`, EDITION[row.baseline_edition],
        badge(signature ? 'SIGNED' : row.status), reason(row.reason),
        row.edges.join(' / '), signature?.reviewer, signature?.signed_at];
    })));
}

function signatureForm(root, snapshot) {
  const eligible = snapshot.decisions.filter(row => row.status === 'READY' &&
    !snapshot.signatures.some(signature => signature.sheet === row.code));
  if (!eligible.length) return;
  const form = el('form', null, 'signature-form ruling-sign');
  const sheetSelect = el('select');
  sheetSelect.name = 'sheet';
  sheetSelect.append(...eligible.map(row => new Option(`${row.code} ${row.title}`, row.code)));
  const reviewer = el('input');
  reviewer.name = 'reviewer';
  reviewer.required = true;
  reviewer.maxLength = 30;
  reviewer.autocomplete = 'name';
  const button = el('button', '签审入册', 'button primary');
  button.type = 'submit';
  const error = el('p', null, 'feedback');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  form.append(el('label', '签审图幅 ', null), sheetSelect, el('label', '签审员 ', null), reviewer, button, error);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    try {
      const rulingId = snapshot.manifest.ruling_id;
      await post(`/api/baseline/rulings/${rulingId}/signatures`,
        {sheet: sheetSelect.value, reviewer: reviewer.value, expected_version: 0});
      state.snapshot = await request(`/api/baseline/rulings/${rulingId}`);
      render(root);
    } catch (err) {
      feedback(error, err.message);
    } finally {
      state.busy = false;
      button.disabled = false;
    }
  });
  root.append(form);
}

function header(root, snapshot) {
  const manifest = snapshot.manifest;
  const head = el('div', null, 'ruling-head');
  head.append(el('p', `裁定编号 ${manifest.ruling_id.slice(0, 16)}…`, 'num'));
  head.append(el('p', `外业版 ${manifest.field_version} · 校准版 ${manifest.reference_version} · 拼缝阈值 ${manifest.parameters.seam_limit_m} m`));
  const exportLink = el('a', '导出裁定证据', 'button outline');
  exportLink.href = `/api/baseline/rulings/${manifest.ruling_id}/export`;
  head.append(exportLink);
  root.append(head);
}

function triggerForm(root) {
  const form = el('form', null, 'settings ruling-trigger');
  const limit = el('input');
  limit.name = 'seam_limit_m';
  limit.type = 'number';
  limit.min = '0.01';
  limit.max = '25';
  limit.step = '0.01';
  limit.value = '1.50';
  limit.required = true;
  const button = el('button', '形成基准对照裁定', 'button primary');
  button.type = 'submit';
  const error = el('p', null, 'feedback');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  form.append(el('label', '拼缝偏差 m ', null), limit, button, error);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    button.disabled = true;
    try {
      state.snapshot = await post('/api/baseline/rulings', {seam_limit_m: Number(limit.value)});
      render(root);
    } catch (err) {
      feedback(error, err.message);
    } finally {
      state.busy = false;
      button.disabled = false;
    }
  });
  root.append(form);
}

export function renderBaseline(root) {
  root.replaceChildren();
  const snapshot = state.snapshot;
  if (!snapshot) {
    root.append(el('p', '在外业原件与校准副本之间逐幅裁定唯一沿用基准。整幅采用单一来源，禁止逐点拼合。', 'ruling-intro'));
    triggerForm(root);
    return;
  }
  header(root, snapshot);
  policyPanel(root, snapshot);
  rulingsTable(root, snapshot);
  seamsTable(root, snapshot);
  decisionsTable(root, snapshot);
  signatureForm(root, snapshot);
}
