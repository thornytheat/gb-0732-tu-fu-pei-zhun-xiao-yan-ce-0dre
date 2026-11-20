import unicodedata
from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.manifest import canonical_json
from app.modules.baseline.service import build_baseline
from app.reasons import REASONS

router = APIRouter(prefix='/api/baseline')
RulingId = Annotated[str, Path(pattern=r'^[0-9a-f]{64}$')]


class BaselineOptions(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    seam_limit_m: Annotated[float, Field(ge=0.01, le=25)] = 1.5


class RulingSignatureInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    sheet: Annotated[str, Field(pattern=r'^[A-Z0-9][A-Z0-9-]{0,23}$')]
    reviewer: Annotated[str, Field(min_length=1, max_length=30)]
    expected_version: Annotated[int, Field(ge=0)] = 0

    @field_validator('reviewer', mode='before')
    @classmethod
    def reviewer_name(cls, name):
        if not isinstance(name, str):
            return name
        if any(unicodedata.category(char).startswith('C') for char in name):
            raise ValueError('签审员姓名包含控制字符')
        return name.strip()


@router.post('/rulings')
def create_ruling(request: Request, options: BaselineOptions):
    snapshot, reused = build_baseline(request.app.state.settings, request.app.state.store, options)
    return {'reused': reused, **snapshot}


@router.get('/rulings/{ruling_id}')
def get_ruling(request: Request, ruling_id: RulingId):
    return request.app.state.store.get_ruling(ruling_id)


@router.post('/rulings/{ruling_id}/signatures')
def sign_ruling(request: Request, ruling_id: RulingId, form: RulingSignatureInput):
    return request.app.state.store.sign_ruling(ruling_id, form.sheet, form.reviewer, form.expected_version)


@router.get('/rulings/{ruling_id}/export')
def export_ruling(request: Request, ruling_id: RulingId):
    snapshot = request.app.state.store.get_ruling(ruling_id)
    evidence = {'format': 'map-register/baseline-ruling-1', **snapshot, 'reason_dictionary': REASONS}
    return Response(canonical_json(evidence) + '\n', media_type='application/json',
                    headers={'Content-Disposition':
                             f'attachment; filename="baseline-ruling-{ruling_id[:12]}.json"'})
