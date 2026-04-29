"""
FHIR MCP Server - Bài tập nhóm
=================================
5 công cụ mcp.tool() truy vấn dữ liệu FHIR từ HAPI FHIR Server:

  1. get_patient_gender_statistics   - Thống kê tỷ lệ % nam/nữ (Patient)
  2. get_medications_by_patient_id   - Thuốc được kê cho bệnh nhân theo ID (MedicationRequest)
  3. get_procedures_by_patient_id    - Thủ thuật/phẫu thuật theo ID bệnh nhân (Procedure)
  4. get_observations_by_patient_id  - Quan sát lâm sàng theo ID bệnh nhân (Observation)
  5. get_conditions_by_patient_id    - Chẩn đoán bệnh theo ID bệnh nhân (Condition)

Cách chạy:
    python fhir_assignment_server.py

Biến môi trường (tuỳ chọn):
    FHIR_SERVER_BASE_URL  - URL gốc của FHIR server (mặc định: http://localhost:8081/fhir)
"""

import asyncio
import os
from typing import Any, Dict, List

import httpx
from mcp.server.fastmcp import FastMCP

# --------------------------------------------------------------------------- #
# Cấu hình kết nối FHIR server
# --------------------------------------------------------------------------- #
FHIR_BASE_URL: str = os.getenv("FHIR_SERVER_BASE_URL", "http://localhost:8081/fhir")
FHIR_HEADERS: Dict[str, str] = {
    "Accept": "application/fhir+json",
    "Content-Type": "application/fhir+json",
}

# --------------------------------------------------------------------------- #
# Khởi tạo MCP server
# --------------------------------------------------------------------------- #
mcp = FastMCP(
    name="FHIR Assignment MCP Server",
    instructions=(
        "Server MCP cho bài tập nhóm. Cung cấp 5 công cụ truy vấn dữ liệu FHIR: "
        "thống kê giới tính bệnh nhân, thuốc kê đơn, thủ thuật, quan sát lâm sàng, "
        "và chẩn đoán bệnh."
    ),
)


# --------------------------------------------------------------------------- #
# Hàm trợ giúp nội bộ
# --------------------------------------------------------------------------- #
async def _fhir_get(resource_type: str, params: Dict[str, str] | None = None) -> Dict[str, Any]:
    """Gửi HTTP GET đến FHIR server và trả về JSON bundle."""
    url = f"{FHIR_BASE_URL}/{resource_type}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=FHIR_HEADERS, params=params)
        response.raise_for_status()
        return response.json()


def _extract_entries(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Trích xuất danh sách resource từ FHIR Bundle."""
    entries = bundle.get("entry", [])
    return [entry["resource"] for entry in entries if "resource" in entry]


def _error_response(message: str) -> Dict[str, Any]:
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": "error", "code": "exception", "diagnostics": message}],
    }


# --------------------------------------------------------------------------- #
# Tool 1: Thống kê tỷ lệ nam/nữ (Patient)
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "Thống kê tỷ lệ phần trăm người bệnh nam, nữ trên tổng số người bệnh (Patient). "
        "Truy vấn FHIR server để đếm số lượng từng giới tính và tính tỷ lệ % tương ứng. "
        "Không cần tham số đầu vào."
    )
)
async def get_patient_gender_statistics() -> Dict[str, Any]:
    """
    Phương thức hoạt động:
      - Gửi 3 truy vấn song song đến FHIR endpoint /Patient với _summary=count:
          * Tổng tất cả bệnh nhân
          * Chỉ gender=male
          * Chỉ gender=female
      - Tính số lượng khác/không xác định = tổng - nam - nữ
      - Tính tỷ lệ % cho từng nhóm
    Trả về dict với các khoá: total, male, female, other_or_unknown.
    """
    try:
        total_bundle, male_bundle, female_bundle = await asyncio.gather(
            _fhir_get("Patient", {"_summary": "count"}),
            _fhir_get("Patient", {"gender": "male", "_summary": "count"}),
            _fhir_get("Patient", {"gender": "female", "_summary": "count"}),
        )

        total: int = total_bundle.get("total", 0)
        male_count: int = male_bundle.get("total", 0)
        female_count: int = female_bundle.get("total", 0)
        other_count: int = total - male_count - female_count

        def pct(n: int) -> float:
            return round(n / total * 100, 2) if total > 0 else 0.0

        return {
            "total": total,
            "male": {
                "count": male_count,
                "percentage": pct(male_count),
            },
            "female": {
                "count": female_count,
                "percentage": pct(female_count),
            },
            "other_or_unknown": {
                "count": other_count,
                "percentage": pct(other_count),
            },
        }
    except Exception as ex:
        return _error_response(f"Không thể truy vấn thống kê giới tính: {ex}")


# --------------------------------------------------------------------------- #
# Tool 2: Thuốc kê đơn theo ID bệnh nhân (MedicationRequest)
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "Lấy danh sách tất cả các thuốc được kê đơn (MedicationRequest) cho người bệnh theo ID. "
        "Tìm kiếm toàn bộ đơn thuốc liên kết với một bệnh nhân cụ thể trên FHIR server."
    )
)
async def get_medications_by_patient_id(patient_id: str) -> Dict[str, Any]:
    """
    Phương thức hoạt động:
      - Nhận patient_id là ID logic của tài nguyên Patient trên FHIR server.
      - Gửi truy vấn GET /MedicationRequest?patient={patient_id} đến FHIR server.
      - Trả về danh sách các MedicationRequest (đơn thuốc) dưới dạng JSON entries.
    Tham số:
      patient_id: ID của bệnh nhân (ví dụ: "123", "patient-456")
    """
    if not patient_id:
        return _error_response("Tham số patient_id là bắt buộc.")
    try:
        bundle = await _fhir_get("MedicationRequest", {"patient": patient_id})
        entries = _extract_entries(bundle)
        return {
            "patient_id": patient_id,
            "total": bundle.get("total", len(entries)),
            "medications": entries,
        }
    except Exception as ex:
        return _error_response(f"Không thể truy vấn MedicationRequest cho bệnh nhân {patient_id}: {ex}")


# --------------------------------------------------------------------------- #
# Tool 3: Thủ thuật/phẫu thuật theo ID bệnh nhân (Procedure)
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "Lấy danh sách tất cả các thủ thuật và phẫu thuật (Procedure) được thực hiện "
        "cho người bệnh theo ID. Tìm kiếm toàn bộ can thiệp lâm sàng liên kết với "
        "một bệnh nhân cụ thể trên FHIR server."
    )
)
async def get_procedures_by_patient_id(patient_id: str) -> Dict[str, Any]:
    """
    Phương thức hoạt động:
      - Nhận patient_id là ID logic của tài nguyên Patient trên FHIR server.
      - Gửi truy vấn GET /Procedure?patient={patient_id} đến FHIR server.
      - Trả về danh sách các Procedure (thủ thuật, phẫu thuật) dưới dạng JSON entries.
    Tham số:
      patient_id: ID của bệnh nhân (ví dụ: "123", "patient-456")
    """
    if not patient_id:
        return _error_response("Tham số patient_id là bắt buộc.")
    try:
        bundle = await _fhir_get("Procedure", {"patient": patient_id})
        entries = _extract_entries(bundle)
        return {
            "patient_id": patient_id,
            "total": bundle.get("total", len(entries)),
            "procedures": entries,
        }
    except Exception as ex:
        return _error_response(f"Không thể truy vấn Procedure cho bệnh nhân {patient_id}: {ex}")


# --------------------------------------------------------------------------- #
# Tool 4: Quan sát lâm sàng theo ID bệnh nhân (Observation)
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "Lấy tất cả quan sát lâm sàng (Observation) của người bệnh theo ID. "
        "Bao gồm kết quả xét nghiệm, dấu hiệu sinh tồn, và các chỉ số lâm sàng khác "
        "liên kết với một bệnh nhân cụ thể trên FHIR server."
    )
)
async def get_observations_by_patient_id(patient_id: str) -> Dict[str, Any]:
    """
    Phương thức hoạt động:
      - Nhận patient_id là ID logic của tài nguyên Patient trên FHIR server.
      - Gửi truy vấn GET /Observation?patient={patient_id} đến FHIR server.
      - Trả về danh sách các Observation (kết quả xét nghiệm, sinh hiệu, v.v.)
        dưới dạng JSON entries.
    Tham số:
      patient_id: ID của bệnh nhân (ví dụ: "123", "patient-456")
    """
    if not patient_id:
        return _error_response("Tham số patient_id là bắt buộc.")
    try:
        bundle = await _fhir_get("Observation", {"patient": patient_id})
        entries = _extract_entries(bundle)
        return {
            "patient_id": patient_id,
            "total": bundle.get("total", len(entries)),
            "observations": entries,
        }
    except Exception as ex:
        return _error_response(f"Không thể truy vấn Observation cho bệnh nhân {patient_id}: {ex}")


# --------------------------------------------------------------------------- #
# Tool 5: Chẩn đoán bệnh theo ID bệnh nhân (Condition)
# --------------------------------------------------------------------------- #
@mcp.tool(
    description=(
        "Lấy dữ liệu chẩn đoán bệnh (Condition) của người bệnh theo ID. "
        "Bao gồm tất cả các chẩn đoán và tình trạng bệnh lý được ghi nhận "
        "cho một bệnh nhân cụ thể trên FHIR server."
    )
)
async def get_conditions_by_patient_id(patient_id: str) -> Dict[str, Any]:
    """
    Phương thức hoạt động:
      - Nhận patient_id là ID logic của tài nguyên Patient trên FHIR server.
      - Gửi truy vấn GET /Condition?patient={patient_id} đến FHIR server.
      - Trả về danh sách các Condition (chẩn đoán, tình trạng bệnh lý)
        dưới dạng JSON entries.
    Tham số:
      patient_id: ID của bệnh nhân (ví dụ: "123", "patient-456")
    """
    if not patient_id:
        return _error_response("Tham số patient_id là bắt buộc.")
    try:
        bundle = await _fhir_get("Condition", {"patient": patient_id})
        entries = _extract_entries(bundle)
        return {
            "patient_id": patient_id,
            "total": bundle.get("total", len(entries)),
            "conditions": entries,
        }
    except Exception as ex:
        return _error_response(f"Không thể truy vấn Condition cho bệnh nhân {patient_id}: {ex}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print(f"[FHIR MCP] Kết nối đến FHIR server: {FHIR_BASE_URL}")
    print("[FHIR MCP] Khởi động server với transport=stdio ...")
    mcp.run(transport="stdio")
