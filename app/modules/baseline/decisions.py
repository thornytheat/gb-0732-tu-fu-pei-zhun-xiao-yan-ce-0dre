"""基准卷逐幅签审判定：签审只认基准对照裁定，不再认单册校验结论。"""

from collections import defaultdict


def sheet_decisions(rulings, mosaic):
    incident = defaultdict(list)
    for edge in mosaic['edges']:
        incident[edge['a']].append(edge)
        incident[edge['b']].append(edge)
    decisions = []
    for ruling in rulings:
        code = ruling['code']
        edges = incident[code]
        failed = [edge['code'] for edge in edges if edge['status'] == 'FAIL']
        blocked = [edge['code'] for edge in edges if edge['status'] == 'BLOCKED']
        adopted_model_ok = ruling['adopted']['fit_status'] == 'FIT'
        if not adopted_model_ok:
            status, reason = 'HOLD', ruling['adopted_reason']
        elif failed:
            status, reason = 'RETURN', 'MOSAIC_GAP'
        elif blocked:
            status, reason = 'HOLD', 'MOSAIC_BLOCKED'
        elif not edges:
            status, reason = 'HOLD', 'NO_EDGE_REGISTERED'
        else:
            status, reason = 'READY', None
        decisions.append({
            'code': code,
            'title': ruling['title'],
            'status': status,
            'reason': reason,
            'baseline_edition': ruling['adopted']['edition'],
            'fit_rms_m': ruling['adopted']['rms_m'],
            'edges': [edge['code'] for edge in edges],
            'failed_edges': failed,
            'blocked_edges': blocked,
        })
    return decisions
