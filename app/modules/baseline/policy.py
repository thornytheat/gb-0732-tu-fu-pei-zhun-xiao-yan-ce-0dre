"""基准裁定策略：逐幅在外业原件与校准副本之间裁定唯一沿用基准。

铁律：只允许整幅采用一个来源，禁止逐点拼合（混源）。外业原件的现场修正是
孤本，凡原件可拟合的图幅一律沿用原件；原件模型不可用的图幅才整幅改用副本。
"""


def _edition_summary(survey, code):
    fit = survey.refit['sheets'][code]
    return {
        'edition': survey.dataset,
        'data_version': survey.catalog['version'],
        'fit_status': fit['status'],
        'reason': fit.get('reason'),
        'control_count': fit.get('count'),
        'rms_m': fit.get('rms_m'),
        'accepted': sum(1 for point in survey.refit['accepted'] if point['sheet'] == code),
        'outliers': sum(1 for point in survey.refit['outliers'] if point['sheet'] == code),
        'isolated': sum(1 for mark in survey.refit['quarantine'] if mark.get('sheet') == code),
    }


def rule_sheet(specification, field, reference):
    """裁定单幅图幅的基准，返回裁定行与采用/放弃两版摘要。"""
    code = specification['code']
    field_summary = _edition_summary(field, code)
    reference_summary = _edition_summary(reference, code)
    field_fit = field.refit['sheets'][code]
    if field_fit['status'] == 'FIT':
        adopted, rejected = field_summary, reference_summary
        adopted_reason = 'FIELD_CORRECTION_PRIORITY'
        rejected_reason = 'REFERENCE_SOURCE_MIX'
    else:
        adopted, rejected = reference_summary, field_summary
        adopted_reason = 'FIELD_MODEL_BLOCKED'
        rejected_reason = field_fit.get('reason') or 'FIELD_MODEL_BLOCKED'
    return {
        'code': code,
        'title': specification['title'],
        'adopted': adopted,
        'rejected': rejected,
        'adopted_reason': adopted_reason,
        'rejected_reason': rejected_reason,
        'mixing_allowed': False,
    }


def adjudicate(catalog, field, reference):
    return [rule_sheet(specification, field, reference) for specification in catalog['sheets']]
