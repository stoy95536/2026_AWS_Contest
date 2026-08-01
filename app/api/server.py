"""
Web Demo API Server
使用 FastAPI 建立 Web 介面：
- 上傳 Excel、模板及提示詞
- 顯示處理進度
- 預覽分析摘要
- 下載 PPT、Excel 及 QA 報告
"""

import os
import uuid
import json
import shutil
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.pipeline import Pipeline, PipelineConfig, PipelineResult

app = FastAPI(
    title="LLM 驅動之 Excel 報表轉簡報自動化系統",
    description="讀取信用卡業務 Excel 資料，自動產出 16 頁策略簡報",
    version="1.0.0",
)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 任務狀態儲存
tasks: dict[str, dict] = {}

# 上傳暫存目錄
UPLOAD_DIR = "uploads"
OUTPUT_BASE = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/")
async def root():
    """系統首頁。"""
    return {"message": "LLM Excel-to-PPT Automation System", "status": "running"}


@app.post("/api/upload")
async def upload_and_process(
    background_tasks: BackgroundTasks,
    excel_file: UploadFile = File(...),
    template_file: Optional[UploadFile] = File(None),
    use_llm: bool = Form(True),
    target_institution: str = Form("台新銀行"),
    model_id: str = Form("anthropic.claude-sonnet-4-20250514-v1:0"),
    region: str = Form("us-east-1"),
):
    """
    上傳檔案並啟動處理流程。

    Returns:
        task_id 用於查詢進度
    """
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(UPLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    # 儲存上傳的 Excel
    excel_path = os.path.join(task_dir, excel_file.filename)
    with open(excel_path, "wb") as f:
        content = await excel_file.read()
        f.write(content)

    # 儲存模板（如有）
    template_path = None
    if template_file:
        template_path = os.path.join(task_dir, template_file.filename)
        with open(template_path, "wb") as f:
            content = await template_file.read()
            f.write(content)

    # 初始化任務狀態
    tasks[task_id] = {
        "status": "processing",
        "progress": 0,
        "current_step": "初始化",
        "result": None,
        "error": None,
    }

    # 背景執行
    output_dir = os.path.join(OUTPUT_BASE, task_id)
    background_tasks.add_task(
        _run_pipeline,
        task_id=task_id,
        excel_path=excel_path,
        template_path=template_path,
        output_dir=output_dir,
        use_llm=use_llm,
        target_institution=target_institution,
        model_id=model_id,
        region=region,
    )

    return {"task_id": task_id, "status": "processing"}


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """查詢任務進度。"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]


@app.get("/api/download/{task_id}/{file_type}")
async def download_file(task_id: str, file_type: str):
    """
    下載結果檔案。

    file_type: ppt, excel, lineage, qa_report, slide_spec
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed")

    result = task["result"]
    file_map = {
        "ppt": result.get("ppt_path"),
        "excel": result.get("excel_path"),
        "lineage": result.get("lineage_path"),
        "qa_report": result.get("qa_report_path"),
        "slide_spec": result.get("slide_spec_path"),
    }

    file_path = file_map.get(file_type)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File type '{file_type}' not found")

    return FileResponse(file_path, filename=os.path.basename(file_path))


@app.get("/api/preview/{task_id}")
async def preview_summary(task_id: str):
    """預覽分析摘要。"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = tasks[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed")

    result = task["result"]
    spec_path = result.get("slide_spec_path")

    if spec_path and os.path.exists(spec_path):
        with open(spec_path, "r", encoding="utf-8") as f:
            slide_specs = json.load(f)
        return {"slides": slide_specs}

    return {"slides": []}


async def _run_pipeline(
    task_id: str,
    excel_path: str,
    template_path: Optional[str],
    output_dir: str,
    use_llm: bool,
    target_institution: str,
    model_id: str,
    region: str,
):
    """背景執行 Pipeline。"""
    try:
        config = PipelineConfig(
            excel_path=excel_path,
            template_path=template_path,
            output_dir=output_dir,
            use_llm=use_llm,
            model_id=model_id,
            region=region,
            target_institution=target_institution,
        )

        pipeline = Pipeline(config)

        # 更新進度
        tasks[task_id]["current_step"] = "執行中"
        tasks[task_id]["progress"] = 10

        result = pipeline.run()

        tasks[task_id]["progress"] = 100

        if result.success:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["result"] = {
                "ppt_path": result.ppt_path,
                "excel_path": result.excel_path,
                "lineage_path": result.lineage_path,
                "qa_report_path": result.qa_report_path,
                "slide_spec_path": result.slide_spec_path,
                "duration_seconds": result.duration_seconds,
                "steps_completed": result.steps_completed,
            }
        else:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = result.errors

    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = [str(e)]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
