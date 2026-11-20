from time import perf_counter

from app.config import RunOptions
from app.modules.baseline.decisions import sheet_decisions
from app.modules.baseline.manifest import ruling_manifest
from app.modules.baseline.mosaic import mosaic_seams
from app.modules.baseline.policy import adjudicate
from app.pipeline import Survey


def build_baseline(settings, store, options):
    """同一对照重跑不新增裁定。

    裁定编号只由两版输入字节、拼缝阈值与规则版本决定：同对照重跑先按编号回
    读旧册并原样返回（含已录签审），不再写入；新对照才整册插入，插入在单个
    事务内完成，失败即回滚，上一册完整保留。
    """
    started = perf_counter()
    field = Survey(settings, RunOptions(dataset='field', seam_limit_m=options.seam_limit_m))
    reference = Survey(settings, RunOptions(dataset='reference', seam_limit_m=options.seam_limit_m))
    manifest = ruling_manifest(field, reference, options.seam_limit_m)
    existing = store.get_ruling(manifest['ruling_id'], required=False)
    if existing is not None:
        return existing, True
    rulings = adjudicate(field.catalog, field, reference)
    mosaic = mosaic_seams(field, reference, rulings, options.seam_limit_m)
    decisions = sheet_decisions(rulings, mosaic)
    manifest['processing_ms'] = round((perf_counter() - started) * 1000, 3)
    snapshot = {
        'manifest': manifest,
        'policy': {
            'rule': '整幅单一来源，禁止逐点拼合；外业原件可拟合时优先沿用其唯一现场修正',
            'mixing_allowed': False,
            'witness_source': 'field',
        },
        'rulings': rulings,
        'mosaic': mosaic,
        'decisions': decisions,
    }
    saved, reused = store.insert_ruling(snapshot)
    return saved, reused
