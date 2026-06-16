"""
EPF/ESIC Document Extractor - Production Ready v3
Supports: PDF, PNG, JPG, JPEG, Screenshots, Photos, Scanned, DOCX
Uses: Groq vision + text models with smart merge strategy
"""
import json, base64, re, time, logging, requests, io
from pathlib import Path

logger = logging.getLogger("extractor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

EXPECTED_KEYS = [
    "employee_name","father_husband_name","gender","marital_status",
    "date_of_birth","date_of_joining","aadhaar_number","mobile_number",
    "pan_number","present_address","permanent_address","bank_name",
    "bank_account_number","ifsc_code","branch_name","uan_number",
    "esic_number","pf_basic_wages","gross_salary","pf_eligibility",
    "nominee_name","nominee_relationship","nominee_dob","family_members",
    "esic_dispensary","insurance_details"
]

# ── Validation ──────────────────────────────────────────────────────────────
def validate_fields(fields):
    issues = {}
    a = re.sub(r"[\s\-]","", fields.get("aadhaar_number",""))
    if a and (not a.isdigit() or len(a) != 12):
        issues["aadhaar_number"] = f"Should be 12 digits, got: {a}"
    p = fields.get("pan_number","").strip().upper()
    if p and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", p):
        issues["pan_number"] = f"Should be like ABCDE1234F, got: {p}"
    i = fields.get("ifsc_code","").strip().upper()
    if i and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", i):
        issues["ifsc_code"] = f"Should be like HDFC0001703, got: {i}"
    m = re.sub(r"[\s\-]","", fields.get("mobile_number",""))
    if m and (not m.isdigit() or len(m) != 10 or m[0] not in "6789"):
        issues["mobile_number"] = f"Should be 10 digits starting 6-9, got: {m}"
    return issues

def score_confidence(fields, issues):
    scores = {}
    key_fields = {"employee_name","aadhaar_number","pan_number","bank_account_number",
                  "date_of_birth","ifsc_code","bank_name"}
    for k in EXPECTED_KEYS:
        v = fields.get(k,"")
        if not v:
            scores[k] = "low"
        elif k in issues:
            scores[k] = "low"
        elif k in key_fields:
            scores[k] = "high"
        else:
            scores[k] = "medium"
    return scores

# ── File Processing ──────────────────────────────────────────────────────────
def extract_pdf_text(data):
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(p.get_text() for p in doc).strip()
        doc.close()
        if text:
            logger.info(f"PDF text extracted: {len(text)} chars")
            return text
    except Exception as e:
        logger.warning(f"PyMuPDF text: {e}")
    return ""

def pdf_to_images(data):
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        imgs = [p.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).tobytes("jpeg") for p in doc]
        doc.close()
        logger.info(f"PDF->images: {len(imgs)} pages")
        return imgs
    except Exception as e:
        logger.warning(f"PDF->images: {e}")
    return []

def read_docx(data):
    try:
        import mammoth
        result = mammoth.extract_raw_text(io.BytesIO(data))
        logger.info(f"DOCX text: {len(result.value)} chars")
        return result.value
    except Exception as e:
        logger.warning(f"DOCX: {e}")
    return ""

def compress(data, max_px=900, quality=75):
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        # Auto-rotate
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except: pass
        if max(img.size) > max_px:
            r = max_px / max(img.size)
            img = img.resize((int(img.width*r), int(img.height*r)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        out = buf.getvalue()
        logger.info(f"Compressed {len(data)}->{len(out)} bytes")
        return out
    except:
        return data

def process_file(fn, fd):
    """Convert any file into (list_of_jpeg_bytes, text_string)."""
    ext = Path(fn).suffix.lower()
    images, text = [], ""
    if ext == ".pdf":
        text = extract_pdf_text(fd)
        images = [compress(i) for i in pdf_to_images(fd)]
    elif ext in {".jpg",".jpeg",".png",".webp",".bmp",".heic",".tiff",".gif"}:
        images = [compress(fd)]
    elif ext in {".doc",".docx"}:
        text = read_docx(fd)
    else:
        logger.warning(f"Unsupported format: {fn}")
    logger.info(f"{fn}: {len(images)} images, {len(text)} text chars")
    return images, text

# ── Groq API ─────────────────────────────────────────────────────────────────
VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]
TEXT_MODELS = ["llama-3.3-70b-versatile", "llama3-70b-8192", "gemma2-9b-it"]

def groq_vision(key, img_data, hint, doj):
    """Call Groq vision on one image."""
    prompt = f"""You are an expert reading Indian HR documents (Aadhaar, PAN, bank cheque/passbook).
Carefully read ALL text visible in this image.
Employee hint: {hint}
Date of joining: {doj}

Extract every piece of information and return ONLY this JSON (use "" for missing fields):
{{
  "employee_name": "exact name as printed",
  "father_husband_name": "S/O or H/O name",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number with spaces",
  "mobile_number": "10 digit mobile",
  "pan_number": "like ABCDE1234F",
  "present_address": "complete address from Aadhaar",
  "permanent_address": "same as present if not specified",
  "bank_name": "full bank name",
  "bank_account_number": "complete account number",
  "ifsc_code": "like HDFC0001703",
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
    b64 = base64.standard_b64encode(img_data).decode()
    content = [
        {"type":"text","text":prompt},
        {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
    ]
    for model in VISION_MODELS:
        try:
            h = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
            p = {"model":model,"messages":[{"role":"user","content":content}],
                 "temperature":0.1,"max_tokens":2048}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              json=p, headers=h, timeout=60)
            logger.info(f"Vision {model}: HTTP {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                logger.warning("Vision rate limit, waiting 25s...")
                time.sleep(25)
        except Exception as e:
            logger.error(f"Vision error: {e}")
        time.sleep(3)
    return None

def groq_text(key, text, hint, doj):
    """Extract from text using Groq text model."""
    prompt = f"""Extract employee registration data from these Indian HR document texts.
Employee hint: {hint}  DOJ: {doj}

Document text:
{text[:5000]}

Return ONLY this JSON (use "" for missing, never null or None):
{{
  "employee_name": "full name",
  "father_husband_name": "father or husband name",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number",
  "mobile_number": "10 digit mobile",
  "pan_number": "PAN number",
  "present_address": "complete address",
  "permanent_address": "complete address",
  "bank_name": "bank name",
  "bank_account_number": "account number",
  "ifsc_code": "IFSC code",
  "branch_name": "branch",
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
    for model in TEXT_MODELS:
        try:
            h = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
            p = {"model":model,"messages":[{"role":"user","content":prompt}],
                 "temperature":0.1,"max_tokens":2048}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              json=p, headers=h, timeout=60)
            logger.info(f"Text {model}: HTTP {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(15)
        except Exception as e:
            logger.error(f"Text error: {e}")
        time.sleep(2)
    return None

# ── JSON & Field Utils ────────────────────────────────────────────────────────
def parse_json(text):
    if not text: return None
    text = re.sub(r"```(?:json)?","",text).replace("```","").strip()
    try: return json.loads(text)
    except: pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try: return json.loads(m.group())
        except: pass
    return None

def merge(base, update):
    """Merge fields — keep existing non-empty, fill blanks from update."""
    result = dict(base)
    for k, v in (update or {}).items():
        if v and str(v).strip() and str(v).strip() not in ("null","None","N/A") \
           and not result.get(k):
            result[k] = str(v).strip()
    return result

def clean(fields, doj):
    """Normalize all fields."""
    for k in EXPECTED_KEYS:
        v = fields.get(k)
        fields[k] = str(v).strip() if v and str(v).strip() not in ("null","None","N/A","") else ""
    # Aadhaar: ensure 12 digits with spaces
    a = re.sub(r"\D","", fields.get("aadhaar_number",""))
    if len(a) == 12:
        fields["aadhaar_number"] = f"{a[:4]} {a[4:8]} {a[8:]}"
    # PAN uppercase
    if fields.get("pan_number"):
        fields["pan_number"] = fields["pan_number"].upper().strip()
    # IFSC uppercase
    if fields.get("ifsc_code"):
        fields["ifsc_code"] = fields["ifsc_code"].upper().strip()
    # DOJ fallback
    if doj and not fields.get("date_of_joining"):
        fields["date_of_joining"] = doj
    # Default PF eligibility
    if not fields.get("pf_eligibility"):
        fields["pf_eligibility"] = "ESIC"
    return fields

def empty(msg):
    return {
        "fields": {k:"" for k in EXPECTED_KEYS},
        "field_confidence": {k:"low" for k in EXPECTED_KEYS},
        "validation": {},
        "confidence_summary": {"total_extracted":0,"high":0,"medium":0,"low":26,"review_needed":0},
        "documents_detected": [],
        "error": msg
    }

# ── Main Extractor Class ──────────────────────────────────────────────────────
class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key.strip()

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        t0 = time.time()
        all_images, all_texts = [], []

        # Step 1: Collect all files
        for fn, fd in files:
            try:
                imgs, txt = process_file(fn, fd)
                all_images.extend(imgs)
                if txt: all_texts.append(f"[{Path(fn).name}]:\n{txt}")
            except Exception as e:
                logger.error(f"File processing error {fn}: {e}")

        if not all_images and not all_texts:
            return empty("No readable files. Upload JPG, PNG, or PDF.")

        logger.info(f"Total: {len(all_images)} images, {len(all_texts)} text blocks")
        fields = {k:"" for k in EXPECTED_KEYS}
        hint = hint_name or "not specified"
        doj = date_of_joining or ""

        # Step 2: Vision on images (one at a time, max 4)
        for idx, img in enumerate(all_images[:4]):
            logger.info(f"Vision processing image {idx+1}/{min(len(all_images),4)}")
            raw = groq_vision(self.api_key, img, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    before = sum(1 for v in fields.values() if v)
                    fields = merge(fields, parsed)
                    after = sum(1 for v in fields.values() if v)
                    logger.info(f"Vision img {idx+1}: +{after-before} fields → total {after}")
            # Rate limit protection between images
            if idx < min(len(all_images),4) - 1:
                time.sleep(6)

        # Step 3: Text extraction from PDFs
        if all_texts:
            combined = "\n\n".join(all_texts)
            logger.info(f"Text extraction on {len(combined)} chars")
            raw = groq_text(self.api_key, combined, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    before = sum(1 for v in fields.values() if v)
                    fields = merge(fields, parsed)
                    after = sum(1 for v in fields.values() if v)
                    logger.info(f"Text extraction: +{after-before} fields → total {after}")

        # Step 4: Clean & validate
        fields = clean(fields, doj)
        validation = validate_fields(fields)
        conf = score_confidence(fields, validation)

        ex = sum(1 for v in fields.values() if v)
        high = sum(1 for c in conf.values() if c == "high")
        med  = sum(1 for c in conf.values() if c == "medium")
        low  = sum(1 for c in conf.values() if c == "low")

        docs = []
        if fields.get("aadhaar_number"): docs.append("Aadhaar Card")
        if fields.get("pan_number"):     docs.append("PAN Card")
        if fields.get("bank_account_number"): docs.append("Bank Document")
        if not docs: docs = ["Documents processed"]

        logger.info(f"Done in {time.time()-t0:.1f}s: {ex} fields, {len(validation)} issues")
        return {
            "fields": fields,
            "field_confidence": conf,
            "validation": validation,
            "confidence_summary": {
                "total_extracted": ex, "high": high,
                "medium": med, "low": low,
                "review_needed": len(validation)
            },
            "documents_detected": docs
        }
