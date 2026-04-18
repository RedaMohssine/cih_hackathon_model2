from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from classify_farm import classify

app = FastAPI(title="CIH Farm Stage Classifier")

class Report(BaseModel):
    model_config = {"extra": "allow"}

@app.get("/")
def health():
    return {"status": "ok", "service": "CIH Farm Stage Classifier"}

@app.post("/classify")
def classify_endpoint(report: Report):
    try:
        result = classify(report.model_dump())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
