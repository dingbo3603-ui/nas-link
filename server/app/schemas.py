from pydantic import BaseModel, Field


class DeviceRegistration(BaseModel):
    id: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    platform: str = Field(min_length=1, max_length=50)
    app_version: str = Field(default="0.1.0", max_length=30)


class ClipboardCreate(BaseModel):
    source_device: str = Field(min_length=3, max_length=100)
    content: str = Field(min_length=1, max_length=200_000)


class BackupFile(BaseModel):
    path: str = Field(min_length=1, max_length=2_000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)


class BackupPlan(BaseModel):
    device_id: str = Field(min_length=3, max_length=100)
    root_name: str = Field(min_length=1, max_length=200)
    files: list[BackupFile] = Field(max_length=500_000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=20, ge=1, le=50)


class OrganizeDecision(BaseModel):
    category: str
    subcategory: str
    tags: list[str]
    summary: str
    confidence: float

