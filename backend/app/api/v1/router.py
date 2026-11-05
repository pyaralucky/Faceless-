from fastapi import APIRouter

from app.api.v1 import (
    agents,
    analytics,
    api_config,
    approvals,
    auth,
    channels,
    dashboard,
    media,
    organizations,
    projects,
    publishing,
    renders,
    social,
    users,
)

api_router = APIRouter()
for module in (
    auth,
    users,
    organizations,
    channels,
    projects,
    api_config,
    agents,
    renders,
    social,
    publishing,
    approvals,
    analytics,
    dashboard,
    media,
):
    api_router.include_router(module.router)
