"""
EPF/ESIC Document Extractor - Final optimized version
- Sends ALL documents in ONE API call (faster + more accurate)
- Uses text extraction for PDFs first (instant, no vision needed)
- Vision as backup for image-only PDFs
"""
import json, base64, re, time, logging, requests, io
from pathlib import Path

logger = logging.getLogger("extractor")
logging.basicConfig(level=logging.INFO)

EXPECTED_KEYS = [
    "employee_name","father_husband_name","gender","marital_status",
    "date_of_birth","date_of_joining","aadhaar_number","mobile_number",
    "pan_number","present_address","permanent_address","bank_name",
    "bank_account_number","ifsc_code","branch_name","uan_number",
    "esic_number","pf_basic_wages","gross_salary","pf_eligibility",
    "nominee_name","nominee_relationship","nominee_dob","family_members",
    "esic_dispensary","insurance_details"
]

def extract_pdf_text(data):
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc).strip()
        doc.close()
        if len(text) > 20:
            logger.info(f"PDF text OK: {len(text)} chars")
            return text
    except Exception as e:
        logger.warning(f"PDF text: {e}")
    return ""

def pdf_to_image(data):
    """Convert first 2 pages of PDF to compressed JPEG."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        images = []
        for i, page in enumerate(doc):
            if i >= 2: break
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))  # Higher res for scanned docs
            images.append(pix.tobytes("jpeg"))
        doc.close()
        return images
    except Exception as e:
        logger.warning(f"PDF->image: {e}")
    return []

def compress_image(data, max_px=1400, quality=88):
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(data))
        try: img = ImageOps.exif_transpose(img)
        except: pass
        if max(img.size) > max_px:
            r = max_px / max(img.size)
            img = img.resize((int(img.width*r), int(img.height*r)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()
    except:
        return data

def parse_json(text):
    if not text: return None
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try: return json.loads(text)
    except: pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try: return json.loads(m.group())
        except: pass
    return None

def clean_fields(fields, doj):
    for k in EXPECTED_KEYS:
        v = fields.get(k)
        if not v or str(v).strip() in ("null","None","N/A","undefined",""):
            fields[k] = ""
        else:
            fields[k] = str(v).strip()
    # Fix Aadhaar spacing
    a = re.sub(r"\D", "", fields.get("aadhaar_number", ""))
    if len(a) == 12:
        fields["aadhaar_number"] = f"{a[:4]} {a[4:8]} {a[8:]}"
    # Fix PAN & IFSC uppercase
    for k in ["pan_number", "ifsc_code"]:
        if fields.get(k): fields[k] = fields[k].upper()
    # Set defaults
    if doj and not fields.get("date_of_joining"):
        fields["date_of_joining"] = doj
    if not fields.get("pf_eligibility"):
        fields["pf_eligibility"] = "ESIC"
    return fields

def validate(fields):
    issues = {}
    a = re.sub(r"\D", "", fields.get("aadhaar_number", ""))
    if a and len(a) != 12: issues["aadhaar_number"] = f"Must be 12 digits (got {len(a)})"
    p = fields.get("pan_number", "")
    if p and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", p):
        issues["pan_number"] = f"Invalid PAN: {p}"
    i = fields.get("ifsc_code", "")
    if i and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", i):
        issues["ifsc_code"] = f"Invalid IFSC: {i}"
    m = re.sub(r"\D", "", fields.get("mobile_number", ""))
    if m and (len(m) != 10 or m[0] not in "6789"):
        issues["mobile_number"] = f"Invalid mobile: {m}"
    return issues

def call_groq_text_only(key, all_text, hint, doj):
    """Fast: use text model only when we have good PDF text."""
    prompt = f"""Extract employee registration data from these Indian HR document texts.
Employee name hint: {hint}
Date of joining: {doj}

DOCUMENT TEXTS:
{all_text[:6000]}

Return ONLY this JSON (no explanation, no markdown):
{{
  "employee_name": "exact name from Aadhaar",
  "father_husband_name": "father name from Aadhaar (S/O field)",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number",
  "mobile_number": "10 digit mobile",
  "pan_number": "like ABCDE1234F",
  "present_address": "complete address from Aadhaar",
  "permanent_address": "same as present if not separate",
  "bank_name": "bank name from cheque",
  "bank_account_number": "account number",
  "ifsc_code": "IFSC code",
  "branch_name": "branch name",
  "uan_number": "",
  "esic_number": "",
  "pf_basic_wages": "",
  "gross_salary": "",
  "pf_eligibility": "ESIC",
  "nominee_name": "",
  "nominee_relationship": "",
  "nominee_dob": "",
  "family_members": "",
  "esic_dispensary": "",
  "insurance_details": ""
}}"""
    for model in ["llama-3.3-70b-versatile", "llama3-70b-8192"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={"model": model, "messages": [{"role":"user","content":prompt}],
                      "temperature": 0.1, "max_tokens": 2048},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=30
            )
            logger.info(f"Text {model}: {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(10)
        except Exception as e:
            logger.error(f"Text model error: {e}")
    return None

def call_groq_vision_all(key, images, hint, doj):
    """Send up to 4 images in ONE call for speed."""
    prompt = f"""You are an expert OCR system for Indian government documents.
I am sending {len(images)} document image(s) for employee: {hint}
Date of joining: {doj}

CAREFULLY read EVERY image and extract ALL visible text.

AADHAAR CARD contains:
- Front: Full name (large text), S/O or W/O or D/O (father/husband name), Date of Birth (DD/MM/YYYY), Gender (Male/Female), 12-digit Aadhaar number at bottom
- Back: Full address with PIN code, sometimes mobile number

PAN CARD contains:
- Name, Father's name, Date of Birth, PAN number (format: 5 letters + 4 digits + 1 letter, e.g. HHMPP0103B)

BANK CHEQUE/PASSBOOK contains:
- Account holder name, Bank name, Branch name, Account number (long number), IFSC code (format: 4 letters + 0 + 6 chars, e.g. HDFC0001703)

IMPORTANT RULES:
- Extract name EXACTLY as printed, do not guess or modify
- Aadhaar number is 12 digits, often shown as XXXX XXXX XXXX
- PAN is always 10 characters: ABCDE1234F format
- IFSC is always 11 characters starting with 4 bank letters
- If you cannot read something clearly, leave it empty - do NOT guess garbled text
- For address, write the complete readable address only

Return ONLY this JSON (empty string for anything unclear or missing):
{{
  "employee_name": "name exactly as on Aadhaar front",
  "father_husband_name": "name after S/O or W/O on Aadhaar",
  "gender": "Male or Female from Aadhaar",
  "marital_status": "Unmarried or Married",
  "date_of_birth": "DD/MM/YYYY from Aadhaar",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digits from Aadhaar e.g. 7626 8151 1496",
  "mobile_number": "10 digit mobile number if clearly visible",
  "pan_number": "PAN from PAN card e.g. HHMPP0103B",
  "present_address": "complete clear address from Aadhaar back",
  "permanent_address": "same as present address if not separately shown",
  "bank_name": "bank name e.g. HDFC Bank",
  "bank_account_number": "account number from cheque",
  "ifsc_code": "IFSC code e.g. HDFC0001703",
  "branch_name": "branch location",
  "uan_number": "",
  "esic_number": "",
  "pf_basic_wages": "",
  "gross_salary": "",
  "pf_eligibility": "ESIC",
  "nominee_name": "",
  "nominee_relationship": "",
  "nominee_dob": "",
  "family_members": "",
  "esic_dispensary": "",
  "insurance_details": ""
}}"""

    content = [{"type": "text", "text": prompt}]
    for img in images[:4]:
        b64 = base64.standard_b64encode(img).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={"model": model, "messages": [{"role":"user","content":content}],
                      "temperature": 0.1, "max_tokens": 2048},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=60
            )
            logger.info(f"Vision {model}: {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                logger.warning("Vision rate limited, waiting 20s...")
                time.sleep(20)
        except Exception as e:
            logger.error(f"Vision error: {e}")
        time.sleep(2)
    return None

def merge(base, update):
    result = dict(base)
    for k, v in (update or {}).items():
        if v and str(v).strip() not in ("","null","None","N/A") and not result.get(k):
            result[k] = str(v).strip()
    return result

def empty(msg):
    return {
        "fields": {k:"" for k in EXPECTED_KEYS},
        "field_confidence": {k:"low" for k in EXPECTED_KEYS},
        "validation": {},
        "confidence_summary": {"total_extracted":0,"high":0,"medium":0,"low":26,"review_needed":0},
        "documents_detected": [],
        "error": msg
    }

class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key.strip()

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        t0 = time.time()
        all_images = []
        all_texts = []
        hint = hint_name or "not specified"
        doj = date_of_joining or ""

        # ── Collect all files (JPG first for better vision) ─────────────
        # Sort: images first, then PDFs
        sorted_files = sorted(files, key=lambda x: (
            0 if Path(x[0]).suffix.lower() in {'.jpg','.jpeg','.png'} else 1
        ))
        for fn, fd in sorted_files:
            ext = Path(fn).suffix.lower()
            logger.info(f"Processing {fn} ({len(fd)} bytes)")

            if ext == ".pdf":
                # Try text first (fast)
                text = extract_pdf_text(fd)
                if text:
                    all_texts.append(f"=== {fn} ===\n{text}")
                # Also get images (for scanned PDFs)
                imgs = pdf_to_image(fd)
                all_images.extend([compress_image(i) for i in imgs])

            elif ext in {".jpg",".jpeg",".png",".webp",".bmp",".heic",".tiff",".gif"}:
                all_images.append(compress_image(fd))

        logger.info(f"Collected: {len(all_images)} images, {len(all_texts)} text blocks")

        if not all_images and not all_texts:
            return empty("No readable files. Upload JPG, PNG or PDF.")

        fields = {k:"" for k in EXPECTED_KEYS}

        # ── Strategy 1: If we have good text, use text model (fast) ───
        if all_texts:
            combined = "\n\n".join(all_texts)
            logger.info(f"Text extraction: {len(combined)} chars")
            raw = call_groq_text_only(self.api_key, combined, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    fields = merge(fields, parsed)
                    ex = sum(1 for v in fields.values() if v)
                    logger.info(f"Text got {ex} fields")

        # ── Strategy 2: Vision on ALL images in ONE call ───────────────
        if all_images:
            # Check if we still have missing important fields
            missing_key = not fields.get("aadhaar_number") or not fields.get("pan_number") \
                          or not fields.get("employee_name") or not fields.get("bank_account_number")

            if missing_key or not all_texts:
                logger.info(f"Vision on {len(all_images)} images (one call)")
                raw = call_groq_vision_all(self.api_key, all_images, hint, doj)
                if raw:
                    parsed = parse_json(raw)
                    if parsed:
                        before = sum(1 for v in fields.values() if v)
                        fields = merge(fields, parsed)
                        after = sum(1 for v in fields.values() if v)
                        logger.info(f"Vision added +{after-before} fields → total {after}")

        # ── Clean, validate, score ─────────────────────────────────────
        fields = clean_fields(fields, doj)
        val_issues = validate(fields)
        ex = sum(1 for v in fields.values() if v)

        if ex == 0:
            return empty("No data extracted. Check document quality.")

        key_fields = {"employee_name","aadhaar_number","pan_number","bank_account_number",
                      "date_of_birth","ifsc_code","bank_name","father_husband_name"}
        conf = {}
        for k in EXPECTED_KEYS:
            v = fields.get(k,"")
            if not v: conf[k] = "low"
            elif k in val_issues: conf[k] = "low"
            elif k in key_fields: conf[k] = "high"
            else: conf[k] = "medium"

        high = sum(1 for c in conf.values() if c=="high")
        med  = sum(1 for c in conf.values() if c=="medium")

        docs = []
        if fields.get("aadhaar_number"): docs.append("Aadhaar Card")
        if fields.get("pan_number"): docs.append("PAN Card")
        if fields.get("bank_account_number"): docs.append("Bank Document")
        if not docs: docs = ["Documents processed"]

        logger.info(f"Done in {time.time()-t0:.1f}s: {ex} fields, docs={docs}")
        return {
            "fields": fields,
            "field_confidence": conf,
            "validation": val_issues,
            "confidence_summary": {"total_extracted":ex,"high":high,"medium":med,
                                   "low":ex-high-med,"review_needed":len(val_issues)},
            "documents_detected": docs
        }
