import {element, pretty} from './client.js';

const labels = {READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓',
  CARRIED:'沿用原结论', REAUDITED:'重新审核'};
const headers = ['业务分组', '输入行', '计算值', '参考值', '判定', '来源'];

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

function originBadge(row) {
  const origin = row.provenance?.origin;
  const node = element('span', labels[origin] || origin || '—',
    {class:'badge', 'data-origin':origin || '', title: origin ? `来源批次 ${row.provenance.source?.run_id?.slice(0,10) ?? '更正片段'}` : ''});
  if (row.provenance?.blocked) node.dataset.blocked = 'true';
  return node;
}

export function snapshot(report, selected, stage) {
  const stats = report.intake;
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent = report.cases?.length ?? '—';
  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line,item.record,item.case,item.reason].map(value=>element('td',value)));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
  } else {
    head.append(...headers.map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button',row.case,{type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
      tr.insertCell().append(originBadge(row));
    }
  }
  table.createTHead().append(head);
  const picked = report.cases?.find(row=>row.case===selected);
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case}` : '采信摘要';
  let shown;
  if (picked) {
    shown = {
      判定: picked.measure?.evidence ?? picked.prep?.details ?? {原因:picked.status},
      来源: picked.provenance ? {
        类型: labels[picked.provenance.origin] || picked.provenance.origin,
        来源批次: picked.provenance.source?.run_id ? picked.provenance.source.run_id.slice(0,12) : '更正片段',
        来源指纹: picked.provenance.source?.source_sha256?.slice(0,16),
        阻断: picked.provenance.blocked?.reasons ?? null,
      } : null,
    };
  } else {
    shown = report.blocks?.length ? {阻断: report.blocks, 采信: stats.reasons} : stats.reasons;
  }
  document.querySelector('#detail').textContent = pretty(shown);
  const blockers = report.balance?.blockers ?? 0;
  const blocking = blockers ? ` · 阻断 ${blockers}` : '';
  document.querySelector('#counts').textContent = report.balance
    ? `行数 ${report.balance.accounted ?? report.balance.correction_input ?? '—'}/${report.balance.input ?? report.balance.correction_input ?? '—'} · ${report.balance.ready} 组通过${blocking}`
    : `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行`;
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    const mark = run.effective ? element('span','有效',{class:'badge','data-result':'APPROVED',title:'当前有效批次'}) : null;
    item.append(button, badge(run.status), mark);
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
