"""裁定基准卷的拼缝验核。

裁定卷逐幅取自两个来源，但拼缝见证仍用外业原件那一份独立尺量（两版见证同
名同像素，校准副本仅删去未登记边）。训练复用判定按各幅采用版的控制点重建，
再把外业见证逐边投影到两侧被采用的重估模型上测距。
"""

from app.modules.seams.service import inspect_edge
from app.modules.seams.witnesses import TrainingIndex, read_witnesses, split_by_edge


class MosaicTrainingIndex:
    """按图幅分别指向采用版的控制点集合，其余行为与单册训练索引一致。"""

    def __init__(self, adopted):
        self._index = {}
        for code, survey in adopted.items():
            self._index[code] = TrainingIndex(survey.coordinates['pixels'], survey.pairing['aliases'])

    def reused(self, sheet, name, pixel):
        return self._index[sheet].reused(sheet, name, pixel)


def mosaic_seams(field, reference, rulings, seam_limit_m):
    adopted = {}
    edition_by_code = {}
    for ruling in rulings:
        survey = field if ruling['adopted']['edition'] == 'field' else reference
        adopted[ruling['code']] = survey
        edition_by_code[ruling['code']] = ruling['adopted']['edition']
    intake = field.intake
    catalog = intake['catalog']
    sheets = {sheet['code']: sheet for sheet in catalog['sheets']}
    models = {code: adopted[code].refit['sheets'][code] for code in sheets}
    by_edge, issues = split_by_edge(intake['tables']['witness.csv'], catalog)
    training = MosaicTrainingIndex(adopted)
    edges = []
    for edge in catalog['edges']:
        rows, rejected = read_witnesses(by_edge[edge['code']], edge, sheets[edge['a']],
                                        sheets[edge['b']], training)
        issues[edge['code']].extend(rejected)
        checked = inspect_edge(edge, rows, issues[edge['code']], sheets[edge['a']], sheets[edge['b']],
                               models, seam_limit_m)
        edges.append({**checked,
                      'a_edition': edition_by_code[edge['a']],
                      'b_edition': edition_by_code[edge['b']]})
    quarantine = sorted((row for group in issues.values() for row in group),
                        key=lambda row: row['source']['line'])
    return {'edges': edges, 'quarantine': quarantine,
            'witness_edition': field.dataset,
            'input_count': intake['tables']['witness.csv']['records']}
