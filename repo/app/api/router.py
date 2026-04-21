from fastapi import APIRouter

from app.api.v1 import audit, auth, data_governance, export, files, metrics, process, users, hospital

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(process.router, prefix="/process", tags=["process"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
api_router.include_router(export.router, prefix="/export", tags=["export"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(data_governance.router, prefix="/data-governance", tags=["data-governance"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(hospital.router, prefix="/hospital", tags=["hospital"])
