"""
Web Demo API Server
支援：
- 多個 Excel 檔案上傳
- PowerPoint 模板上傳
- 自訂提示詞輸入
- 背景處理 + 進度查詢
- 結果下載
"""

import os
import uuid
import json
import warnings
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.pipeline import Pipeline, PipelineConfig

app = FastAPI(
    title="LLM 驅動之 Excel 報表轉簡報自動化系統",
    description="上傳多個 Excel + 模板 + 提示詞，自動產出 16 頁策略簡報",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# State
tasks: dict[str, dict] = {}
UPLOAD_DIR = "uploads"
OUTPUT_BASE = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Serve frontend
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend."""
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>LLM Excel-to-PPT System</h1><p>Frontend not found.</p>")


@app.post("/api/upload")
async def upload_and_process(
    background_tasks: BackgroundTasks,
    excel_files: list[UploadFile] = File(...),
    template_file: Optional[UploadFile] = File(None),
    prompt_text: str = Form(""),
    use_llm: bool = Form(True),
    target_institution: str = Form("台新銀行"),
    model_id: str = Form("us.anthropic.claude-sonnet-4-20250514-v1:0"),
    region: str = Form("us-east-1"),
):
    """上傳多個 Excel + 模板 + 提示詞，啟動處理。"""
    task_id = str(uuid.uuid4())
    task_dir = os.path.join(UPLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)

    # 儲存多個 Excel 檔案
    excel_paths = []
    for ef in excel_files:
        path = os.path.join(task_dir, ef.filename)
        with open(path, "wb") as f:
            content = await ef.read()
            f.write(content)
        excel_paths.append(path)

    # 儲存模板
    template_path = None
    if template_file and template_file.filename:
        template_path = os.path.join(task_dir, template_file.filename)
        with open(template_path, "wb") as f:
            content = await template_file.read()
            f.write(content)

    # 儲存提示詞
    prompt_path = None
    if prompt_text.strip():
        prompt_path = os.path.join(task_dir, "user_prompt.txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt_text)

    # 初始化任務
    tasks[task_id] = {
        "status": "processing",
        "progress": 5,
        "current_step": "上傳完成",
        "steps_completed": ["upload"],
        "result": None,
        "error": None,
    }

    # 背景處理
    output_dir = os.path.join(OUTPUT_BASE, task_id)
    background_tasks.add_task(
        _run_pipeline,
        task_id=task_id,
        excel_paths=excel_paths,
        template_path=template_path,
        prompt_path=prompt_path,
        output_dir=output_dir,
        use_llm=use_llm,
        target_institution=target_institution,
        model_id=model_id,
        region=region,
    )

    return {"task_id": task_id, "status": "processing", "files_uploaded": len(excel_paths)}


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """查詢任務進度。"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]


@app.get("/api/download/{task_id}/{file_type}")
async def download_file(task_id: str, file_type: str):
    """下載結果（ppt, excel, lineage, qa_report, slide_spec）。"""
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
        raise HTTPException(status_code=404, detail=f"File '{file_type}' not found")

    return FileResponse(file_path, filename=os.path.basename(file_path))


async def _run_pipeline(
    task_id: str,
    excel_paths: list[str],
    template_path: Optional[str],
    prompt_path: Optional[str],
    output_dir: str,
    use_llm: bool,
    target_institution: str,
    model_id: str,
    region: str,
):
    """背景執行 Pipeline（支援多個 Excel）。"""
    try:
        # 用第一個 Excel 作為主要輸入，其餘合併
        primary_excel = excel_paths[0]

        config = PipelineConfig(
            excel_path=primary_excel,
            template_path=template_path,
            output_dir=output_dir,
            use_llm=use_llm,
            model_id=model_id,
            region=region,
            target_institution=target_institution,
        )

        pipeline = Pipeline(config)

        # 如果有多個 Excel，額外載入
        if len(excel_paths) > 1:
            pipeline.extra_excel_paths = excel_paths[1:]

        # 如果有自訂提示詞
        if prompt_path:
            pipeline.user_prompt_path = prompt_path

        # 執行
        tasks[task_id]["progress"] = 10
        tasks[task_id]["current_step"] = "解析 Excel"

        result = pipeline.run()

        # 更新步驟
        tasks[task_id]["steps_completed"] = ["upload"] + result.steps_completed
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
