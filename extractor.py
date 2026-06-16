"""
Document Extractor — uses Gemini 1.5 Flash (free tier)
"""

import json
import base64
import re
import time
import logging
import requests
from pathlib import Path

logging.basicConfig(level=logging.INFO)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

EXPECTED_KEYS = [
    "employee_name", "father_husband_name", "gender", "marital_status",
    "date_of_birth", "date_of_joining", "aadhaar_number", "mobile_number",
    "pan_number", "present_address", "permanent_address", "bank_name",
    "bank_account_number", "ifsc_code", "branch_name", "uan_number",
    "esic_number", "pf_basic_wages", "gross_salary", "pf_eligibility",
    "nominee_name", "nominee_relationship", "nominee_dob", "family_members",
    "esic_dispensary", "insurance_details"
]

def call_gemini(api_key, prompt, images):
    parts = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": img})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096}
    }
    for attempt in range(3):
        try:
            resp = requests.post(f"{GEMINI_URL}?key={api_key}", json=payload, timeout=60)
            if resp.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(5)
    return ""

def encode_file(file_bytes, filename):
    ext = Path(filename).suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}
    mime = mime_map.get(ext)
    if not mime:
        return None
    return {"mime_type": mime, "data": base64.standard_b64encode(file_bytes).decode("utf-8")}

def parse_json_response(text):
    if not text:
        return None
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass
    return None

def validate_fields(fields):
    validation = {}
    aadhaar = fields.get("aadhaar_number", "").replace(" ", "")
    if aadhaar and not re.fullmatch(r"\d{12}", aadhaar):
        validation["aadhaar_number"] = {"error": True, "message": f"Invalid Aadhaar: expected 12 digits"}
    pan = fields.get("pan_number", "").strip().upper()
    if pan and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
        validation["pan_number"] = {"error": True, "message": f"Invalid PAN format"}
    ifsc = fields.get("ifsc_code", "").strip().upper()
    if ifsc and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
        validation["ifsc_code"] = {"error": True, "message": f"Invalid IFSC format"}
    mobile = fields.get("mobile_number", "").replace(" ", "").replace("-", "")
    if mobile and not re.fullmatch(r"[6-9]\d{9}", mobile):
        validation["mobile_number"] = {"error": True, "message": f"Invalid mobile number"}
    for field in ["employee_name", "aadhaar_number"]:
        if not fields.get(field):
            validation[field] = {"error": True, "message": "Required field missing"}
    return validation

def empty_result(reason):
    return {
        "fields": {k: "" for k in EXPECTED_KEYS},
        "field_confidence": {},
        "validation": {"_error": {"error": True, "message": reason}},
        "confidence_summary": {"total_extracted": 0, "high": 0, "medium": 0, "low": 0, "review_needed": 1},
        "documents_detected": [],
        "error": reason
    }

class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        images = []
        for fname, fdata in files:
            encoded = encode_file(fdata, fname)
            if encoded:
                images.append(encoded)

        if not images:
            return empty_result("No supported documents found")

        prompt = f"""You are an expert at extracting data from Indian government documents for EPF/ESIC employee registration.

Extract ALL available information from the provided documents and return ONLY a valid JSON object with exactly these fields.
Use empty string "" for any field not found.

{{
  "employee_name": "",
  "father_husband_name": "",
  "gender": "",
  "marital_status": "",
  "date_of_birth": "",
  "date_of_joining": "",
  "aadhaar_number": "",
  "mobile_number": "",
  "pan_number": "",
  "present_address": "",
  "permanent_address": "",
  "bank_name": "",
  "bank_account_number": "",
  "ifsc_code": "",
  "branch_name": "",
  "uan_number": "",
  "esic_number": "",
  "pf_basic_wages": "",
  "gross_salary": "",
  "pf_eligibility": "",
  "nominee_name": "",
  "nominee_relationship": "",
  "nominee_dob": "",
  "family_members": "",
  "esic_dispensary": "",
  "insurance_details": ""
}}

Rules:
- Employee name exactly as on Aadhaar
- Aadhaar: 12 digits like XXXX XXXX XXXX
- PAN: like ABCDE1234F (uppercase)
- IFSC: like SBIN0001234 (uppercase)
- Dates: DD/MM/YYYY format
- Gender: Male / Female / Other
- Marital Status: Married / Unmarried
- Employee name hint: {hint_name or 'not provided'}
- Date of joining: {date_of_joining or 'not provided'}

Return ONLY the JSON. No explanation. No markdown."""

        try:
            raw = call_gemini(self.api_key, prompt, images[:10])
        except Exception as e:
            return empty_result(f"API error: {e}")

        fields = parse_json_response(raw)
        if not fields:
            return empty_result("Could not parse AI response")

        # Ensure ALL expected keys exist
        for key in EXPECTED_KEYS:
            if key not in fields:
                fields[key] = ""

        # Set date of joining if provided but not extracted
        if date_of_joining and not fields.get("date_of_joining"):
            fields["date_of_joining"] = date_of_joining

        # Simple confidence: any non-empty field = high
        field_confidence = {k: "high" if v else "low" for k, v in fields.items()}
        validation = validate_fields(fields)

        extracted_count = sum(1 for v in fields.values() if v)
        confidence_summary = {
            "total_extracted": extracted_count,
            "high": extracted_count,
            "medium": 0,
            "low": len(EXPECTED_KEYS) - extracted_count,
            "review_needed": sum(1 for v in validation.values() if v.get("error"))
        }

        return {
            "fields": fields,
            "field_confidence": field_confidence,
            "validation": validation,
            "confidence_summary": confidence_summary,
            "documents_detected": ["Documents processed successfully"],
        }
