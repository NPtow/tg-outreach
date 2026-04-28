from pydantic import BaseModel
from fastapi import APIRouter

from backend.evals import DEFAULT_EVAL_CASES, run_local_eval_cases

router = APIRouter(prefix="/api/evals", tags=["evals"])


class EvalRunRequest(BaseModel):
    cases: list[dict] | None = None


@router.post("/run")
def run_evals(data: EvalRunRequest):
    return run_local_eval_cases(data.cases or DEFAULT_EVAL_CASES)
