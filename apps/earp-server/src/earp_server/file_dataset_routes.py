"""Admin APIs for file scenario datasets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from earp_server import file_dataset
from earp_server.policy import roles_service

router = APIRouter(prefix="/v1/file-datasets", tags=["file-datasets"])


async def _require_admin(req: Request) -> None:
    if not await roles_service.is_admin_role(req.app.state.engine, req.state.tenant_id, req.state.role_id):
        raise HTTPException(status_code=403, detail="仅 Admin 角色可管理文件场景数据集")


def _limits(req: Request) -> tuple[int, int, int]:
    settings = req.app.state.settings
    return (
        settings.file_dataset_max_files,
        settings.file_dataset_max_file_bytes,
        settings.file_dataset_max_total_bytes,
    )


async def _read_uploads(req: Request, manifest: UploadFile, files: list[UploadFile]) -> tuple[bytes, dict[str, bytes]]:
    max_files, max_file_bytes, max_total_bytes = _limits(req)
    if len(files) > max_files:
        raise HTTPException(status_code=400, detail=f"文件数超过限制（{max_files}）")
    manifest_bytes = await manifest.read()
    if len(manifest_bytes) > max_file_bytes:
        raise HTTPException(status_code=400, detail="manifest 超过单文件限制")
    total = len(manifest_bytes)
    result: dict[str, bytes] = {}
    for upload in files:
        name = upload.filename or ""
        if name in result:
            raise HTTPException(status_code=400, detail=f"文件名重复: {name}")
        content = await upload.read()
        if len(content) > max_file_bytes:
            raise HTTPException(status_code=400, detail=f"{name} 超过单文件限制")
        total += len(content)
        result[name] = content
    if total > max_total_bytes:
        raise HTTPException(status_code=400, detail="数据集总大小超过限制")
    return manifest_bytes, result


@router.post("", status_code=201, dependencies=[Depends(_require_admin)])
async def upload_dataset(
    req: Request,
    manifest: UploadFile = File(...),
    files: list[UploadFile] = File(...),
) -> dict:
    manifest_bytes, contents = await _read_uploads(req, manifest, files)
    try:
        max_files, max_file_bytes, max_total_bytes = _limits(req)
        return await file_dataset.stage_dataset(
            req.app.state.engine,
            req.state.tenant_id,
            req.app.state.settings.file_data_root,
            manifest_bytes,
            contents,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )
    except file_dataset.FileDatasetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class DirectoryDatasetIn(BaseModel):
    relative_path: str = Field(min_length=1, max_length=512)


@router.post("/from-directory", status_code=201, dependencies=[Depends(_require_admin)])
async def register_directory(body: DirectoryDatasetIn, req: Request) -> dict:
    try:
        max_files, max_file_bytes, max_total_bytes = _limits(req)
        return await file_dataset.stage_directory(
            req.app.state.engine,
            req.state.tenant_id,
            req.app.state.settings.file_data_root,
            body.relative_path,
            max_files=max_files,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        )
    except file_dataset.FileDatasetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("")
async def list_file_datasets(req: Request) -> dict:
    return {"items": await file_dataset.list_datasets(req.app.state.engine, req.state.tenant_id)}


@router.get("/{dataset_id}")
async def get_file_dataset(dataset_id: str, req: Request) -> dict:
    result = await file_dataset.get_dataset(req.app.state.engine, req.state.tenant_id, dataset_id)
    if result is None:
        raise HTTPException(status_code=404, detail="File dataset not found")
    return result


@router.post("/{dataset_id}/publish", dependencies=[Depends(_require_admin)])
async def publish_file_dataset(dataset_id: str, req: Request) -> dict:
    try:
        return await file_dataset.publish_dataset(
            req.app.state.engine,
            req.state.tenant_id,
            req.app.state.settings.file_data_root,
            dataset_id,
        )
    except file_dataset.FileDatasetError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
