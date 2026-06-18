"""
EPF/ESIC Document Extractor - Final Production Version
Supports ALL formats: PDF, PNG, JPG, JPEG, Screenshots, Photos, Scanned, DOCX
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

# Supported formats
IMAGE_FORMATS = {".jpg",".jpeg",".png",".webp",".bmp",".gif",".tiff",".tif",".heic",".heif"}
PDF_FORMATS   = {".pdf"}
WORD_FORMATS  = {".doc",".docx"}
ALL_SUPPORTED = IMAGE_FORMATS | PDF_FORMATS | WORD_FORMATS

def read_docx(data):
    """Extract text from Word documents."""
    try:
        import mammoth
        result = mammoth.extract_raw_text(io.BytesIO(data))
        logger.info(f"DOCX text: {len(result.value)} chars")
        return result.value
    except Exception as e:
        logger.warning(f"DOCX read failed: {e}")
    # Fallback: try python-docx
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs)
        logger.info(f"python-docx text: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"python-docx failed: {e}")
    return ""

def extract_pdf_text(data):
    """Extract text layer from PDF (works for digital PDFs)."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc).strip()
        doc.close()
        if len(text) > 30:
            logger.info(f"PDF text extracted: {len(text)} chars")
            return text
    except Exception as e:
        logger.warning(f"PDF text extract: {e}")
    return ""

def pdf_to_images(data, dpi_scale=2.5):
    """Convert PDF pages to high-res JPEG images (for scanned PDFs)."""
    images = []
    # Method 1: PyMuPDF (best quality)
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi_scale, dpi_scale))
            images.append(pix.tobytes("jpeg"))
        doc.close()
        logger.info(f"PDF->images via PyMuPDF: {len(images)} pages at {dpi_scale}x")
        return images
    except Exception as e:
        logger.warning(f"PyMuPDF: {e}")
    # Method 2: Pillow fallback
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        for i in range(getattr(img,"n_frames",1)):
            try: img.seek(i)
            except EOFError: break
            buf = io.BytesIO()
            img.convert("RGB").save(buf,"JPEG",quality=90)
            images.append(buf.getvalue())
        if images:
            logger.info(f"PDF->images via Pillow: {len(images)} pages")
            return images
    except Exception as e:
        logger.warning(f"Pillow PDF: {e}")
    return []

def process_image_file(data, fmt):
    """Process any image file — handles all formats including screenshots and phone photos."""
    try:
        from PIL import Image, ImageOps, ImageEnhance
        img = Image.open(io.BytesIO(data))
        # Auto-rotate based on EXIF (fixes phone photos)
        try:
            img = ImageOps.exif_transpose(img)
        except: pass
        # Convert to RGB (handles PNG transparency, HEIC, etc.)
        img = img.convert("RGB")
        # Resize if too large (keep quality, reduce size)
        max_px = 1400
        if max(img.size) > max_px:
            r = max_px / max(img.size)
            img = img.resize((int(img.width*r), int(img.height*r)), Image.LANCZOS)
        # Enhance contrast slightly for scanned documents
        if fmt in {".tiff",".tif",".bmp"}:
            img = ImageEnhance.Contrast(img).enhance(1.2)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        result = buf.getvalue()
        logger.info(f"{fmt} -> JPEG: {len(data)}->{len(result)} bytes, size={img.size}")
        return result
    except Exception as e:
        logger.error(f"Image process {fmt}: {e}")
        return data

def process_file(fn, fd):
    """
    Convert ANY file format to (list_of_jpeg_bytes, text_string).
    Supports: PDF, PNG, JPG, JPEG, Screenshots, Photos, Scanned, DOCX, DOC
    """
    ext = Path(fn).suffix.lower()
    images, text = [], ""

    if ext in PDF_FORMATS:
        # Try text extraction first (fast, accurate for digital PDFs)
        text = extract_pdf_text(fd)
        # Always also convert to images (catches scanned PDFs)
        imgs = pdf_to_images(fd)
        images = [process_image_file(i, ".jpg") for i in imgs]
        logger.info(f"PDF {fn}: {len(text)} text chars, {len(images)} images")

    elif ext in IMAGE_FORMATS:
        # All image formats: JPG, PNG, JPEG, Screenshots, Phone photos, Scanned
        img = process_image_file(fd, ext)
        images = [img]
        logger.info(f"Image {fn} ({ext}): processed to JPEG")

    elif ext in WORD_FORMATS:
        # Word documents
        text = read_docx(fd)
        logger.info(f"Word {fn}: {len(text)} text chars")

    else:
        logger.warning(f"Unsupported format: {fn} ({ext})")

    return images, text

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
    result = dict(base)
    for k, v in (update or {}).items():
        v = str(v).strip() if v else ""
        if v and v not in ("null","None","N/A","undefined","n/a") and not result.get(k):
            result[k] = v
    return result

def clean_fields(fields, doj):
    for k in EXPECTED_KEYS:
        v = fields.get(k,"")
        if not v or str(v).strip() in ("null","None","N/A","undefined"):
            fields[k] = ""
        else:
            fields[k] = str(v).strip()

    # Fix IFSC: position 4 must be digit 0, not letter O (common OCR error)
    ifsc = fields.get("ifsc_code","").upper().strip()
    if len(ifsc) >= 5:
        ifsc = ifsc[:4] + ifsc[4:].replace("O","0",1)
    fields["ifsc_code"] = ifsc

    # Fix PAN: correct O/0 confusion in specific positions
    pan = fields.get("pan_number","").upper().strip()
    if pan and len(pan) == 10:
        pan_list = list(pan)
        for i in [5,6,7,8]:   # must be digits
            if pan_list[i] == "O": pan_list[i] = "0"
        for i in [0,1,2,3,4,9]: # must be letters
            if pan_list[i] == "0": pan_list[i] = "O"
        pan = "".join(pan_list)
    fields["pan_number"] = pan

    # Fix Aadhaar: normalize digits only
    a = re.sub(r"\D","", fields.get("aadhaar_number",""))
    if len(a) == 12:
        fields["aadhaar_number"] = f"{a[:4]} {a[4:8]} {a[8:]}"
    elif len(a) == 11:
        # Keep for manual correction, mark clearly
        fields["aadhaar_number"] = a
        logger.warning(f"Aadhaar 11 digits - manual check needed: {a}")
    else:
        fields["aadhaar_number"] = fields.get("aadhaar_number","")

    # DOJ fallback
    if doj and not fields.get("date_of_joining"):
        fields["date_of_joining"] = doj
    # Default PF eligibility
    if not fields.get("pf_eligibility"):
        fields["pf_eligibility"] = "ESIC"
    return fields

def validate_fields(fields):
    issues = {}
    a = re.sub(r"\D","", fields.get("aadhaar_number",""))
    if a and len(a) != 12:
        issues["aadhaar_number"] = f"Must be 12 digits, got {len(a)}"
    p = fields.get("pan_number","").upper()
    if p and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", p):
        issues["pan_number"] = f"Invalid format: {p}"
    i = fields.get("ifsc_code","").upper()
    if i and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", i):
        issues["ifsc_code"] = f"Invalid format: {i}"
    m = re.sub(r"\D","", fields.get("mobile_number",""))
    if m and (len(m)!=10 or m[0] not in "6789"):
        issues["mobile_number"] = f"Invalid: {m}"
    return issues

def groq_vision(key, images, hint, doj):
    """Send ALL images in ONE call to Groq vision."""
    prompt = f"""You are an expert OCR system for Indian government documents.
I am sending {len(images)} document image(s) for employee: {hint}
Date of joining: {doj}

READ EVERY IMAGE CAREFULLY. Extract ALL visible text and data.

WHAT TO LOOK FOR:
- AADHAAR CARD FRONT: Name (large bold text), S/O or W/O or D/O (father/husband), DOB (DD/MM/YYYY), Male/Female, 12-digit number at bottom
- AADHAAR CARD BACK: Complete address with PIN code, Mobile number
- PAN CARD: Name, Father name, DOB, PAN number (10 chars: ABCDE1234F format)
- BANK CHEQUE: Bank name, Account number, IFSC code (11 chars), Branch name
- BANK PASSBOOK: Same as cheque
- SCREENSHOT/PHOTO: Read as-is, same rules apply

CRITICAL RULES:
- Extract EXACT text as printed - do not paraphrase or modify names
- Aadhaar number = 12 digits (e.g. 7626 8151 1496)
- PAN = exactly 10 characters (e.g. HHMPP0103B)
- IFSC = exactly 11 characters (e.g. HDFC0001703)
- If text is unclear or garbled, leave that field EMPTY
- Do NOT guess or fill in unclear text

Return ONLY this JSON (no explanation, no markdown):
{{
  "employee_name": "exact name from Aadhaar front",
  "father_husband_name": "name after S/O or W/O on Aadhaar",
  "gender": "Male or Female",
  "marital_status": "Unmarried or Married",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number e.g. 7626 8151 1496",
  "mobile_number": "10 digit mobile if clearly visible",
  "pan_number": "PAN number e.g. HHMPP0103B",
  "present_address": "complete address from Aadhaar back",
  "permanent_address": "same as present if not separately shown",
  "bank_name": "bank name e.g. HDFC Bank",
  "bank_account_number": "account number",
  "ifsc_code": "IFSC e.g. HDFC0001703",
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

    content = [{"type":"text","text":prompt}]
    for img in images[:4]:
        b64 = base64.standard_b64encode(img).decode()
        content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}})

    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={"model":model,"messages":[{"role":"user","content":content}],
                      "temperature":0.1,"max_tokens":2048},
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                timeout=60
            )
            logger.info(f"Vision {model}: HTTP {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                logger.warning("Rate limited, waiting 25s...")
                time.sleep(25)
        except Exception as e:
            logger.error(f"Vision error: {e}")
        time.sleep(3)
    return None

def groq_text(key, text, hint, doj):
    """Extract fields from PDF/Word text using Groq text model."""
    prompt = f"""Extract employee registration data from these Indian HR document texts.
Employee: {hint}  DOJ: {doj}

DOCUMENT TEXT:
{text[:6000]}

Return ONLY this JSON (empty string for missing fields):
{{
  "employee_name": "name from document",
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
    for model in ["llama-3.3-70b-versatile","llama3-70b-8192"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={"model":model,"messages":[{"role":"user","content":prompt}],
                      "temperature":0.1,"max_tokens":2048},
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                timeout=30
            )
            logger.info(f"Text {model}: HTTP {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(10)
        except Exception as e:
            logger.error(f"Text model: {e}")
        time.sleep(2)
    return None

def empty(msg):
    return {
        "fields":{k:"" for k in EXPECTED_KEYS},
        "field_confidence":{k:"low" for k in EXPECTED_KEYS},
        "validation":{},
        "confidence_summary":{"total_extracted":0,"high":0,"medium":0,"low":26,"review_needed":0},
        "documents_detected":[],
        "error":msg
    }

class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key.strip()

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        t0 = time.time()
        hint = hint_name or "not specified"
        doj  = date_of_joining or ""

        all_images = []
        all_texts  = []

        # Sort: images first (JPG/PNG), then PDFs, then Word
        sorted_files = sorted(files, key=lambda x: (
            0 if Path(x[0]).suffix.lower() in IMAGE_FORMATS else
            1 if Path(x[0]).suffix.lower() in PDF_FORMATS else 2
        ))

        for fn, fd in sorted_files:
            try:
                imgs, txt = process_file(fn, fd)
                all_images.extend(imgs)
                if txt:
                    all_texts.append(f"=== {Path(fn).name} ===\n{txt}")
            except Exception as e:
                logger.error(f"File error {fn}: {e}")

        logger.info(f"Total: {len(all_images)} images, {len(all_texts)} text blocks")

        if not all_images and not all_texts:
            return empty("No readable files. Supported: PDF, JPG, PNG, JPEG, Screenshots, DOCX")

        fields = {k:"" for k in EXPECTED_KEYS}

        # Step 1: Text extraction (fast, accurate for digital docs)
        if all_texts:
            combined = "\n\n".join(all_texts)
            raw = groq_text(self.api_key, combined, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    fields = merge(fields, parsed)
                    logger.info(f"Text: {sum(1 for v in fields.values() if v)} fields")

        # Step 2: Vision on all images in ONE call
        if all_images:
            raw = groq_vision(self.api_key, all_images, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    before = sum(1 for v in fields.values() if v)
                    fields = merge(fields, parsed)
                    after  = sum(1 for v in fields.values() if v)
                    logger.info(f"Vision: +{after-before} fields, total={after}")

        # Clean and validate
        fields = clean_fields(fields, doj)
        val    = validate_fields(fields)
        ex     = sum(1 for v in fields.values() if v)

        if ex == 0:
            return empty("No data extracted. Use clear JPG photos for best results.")

        key_fields = {"employee_name","aadhaar_number","pan_number",
                      "bank_account_number","date_of_birth","ifsc_code"}
        conf = {k: ("high" if fields.get(k) and k in key_fields else
                    "medium" if fields.get(k) else "low")
                for k in EXPECTED_KEYS}

        docs = []
        if fields.get("aadhaar_number"): docs.append("Aadhaar Card")
        if fields.get("pan_number"):     docs.append("PAN Card")
        if fields.get("bank_account_number"): docs.append("Bank Document")
        if not docs: docs = ["Documents processed"]

        logger.info(f"Done in {time.time()-t0:.1f}s: {ex} fields, issues={len(val)}")
        return {
            "fields": fields,
            "field_confidence": conf,
            "validation": val,
            "confidence_summary": {
                "total_extracted": ex,
                "high":   sum(1 for c in conf.values() if c=="high"),
                "medium": sum(1 for c in conf.values() if c=="medium"),
                "low":    sum(1 for c in conf.values() if c=="low"),
                "review_needed": len(val)
            },
            "documents_detected": docs
        }
