from datetime import datetime, timezone
from hashlib import sha256

from app.config import RULE_VERSION
from app.manifest import canonical_json


def ruling_manifest(field, reference, seam_limit_m):
    """裁定编号只取决于两版输入字节、拼缝阈值与规则版本，同对照重跑得到同编号。"""
    inputs = {}
    for edition, survey in (('field', field), ('reference', reference)):
        for name, raw in survey.bundle.items():
            inputs[f'{edition}/{name}'] = sha256(raw).hexdigest()
    fingerprint = {
        'inputs': inputs,
        'parameters': {'seam_limit_m': seam_limit_m},
        'rule_version': RULE_VERSION,
        'scope': 'baseline-adjudication',
    }
    ruling_id = sha256(canonical_json(fingerprint).encode()).hexdigest()
    return {
        'ruling_id': ruling_id,
        **fingerprint,
        'field_version': field.catalog['version'],
        'reference_version': reference.catalog['version'],
        'created_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
    }
