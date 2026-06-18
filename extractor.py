"""
EPF/ESIC Document Extractor - Maximum Quality Version
Handles scanned PDFs, photos, screenshots with highest accuracy
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

IMAGE_FORMATS = {".jpg",".jpeg",".png",".webp",".bmp",".gif",
                 ".tiff",".tif",".heic",".heif"}

def extract_pdf_text(data):
    """Extract text from digital PDFs."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc).strip()
        doc.close()
        if len(text) > 30:
            logger.info(f"PDF text: {len(text)} chars")
            return text
    except Exception as e:
        logger.warning(f"PDF text: {e}")
    return ""

def pdf_to_images_highres(data):
    """Convert scanned PDF to HIGH resolution images for better OCR."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        images = []
        for page in doc:
            # Use 3x scale for maximum quality on scanned documents
            pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
            images.append(pix.tobytes("jpeg"))
        doc.close()
        logger.info(f"PDF->highres images: {len(images)} pages at 3x")
        return images
    except Exception as e:
        logger.warning(f"PDF->images: {e}")
    return []

def prepare_image(data, max_px=1600, quality=92):
    """Prepare image at high quality — auto-rotate, enhance, resize."""
    try:
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
        img = Image.open(io.BytesIO(data))
        # Fix rotation from EXIF
        try:
            img = ImageOps.exif_transpose(img)
        except: pass
        img = img.convert("RGB")
        # Sharpen slightly for better text recognition
        img = img.filter(ImageFilter.SHARPEN)
        # Resize keeping high quality
        if max(img.size) > max_px:
            r = max_px / max(img.size)
            new_size = (int(img.width*r), int(img.height*r))
            img = img.resize(new_size, Image.LANCZOS)
        elif max(img.size) < 800:
            # Upscale small images
            r = 800 / max(img.size)
            new_size = (int(img.width*r), int(img.height*r))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        result = buf.getvalue()
        logger.info(f"Image prepared: {img.size}, {len(data)}->{len(result)} bytes")
        return result
    except Exception as e:
        logger.warning(f"Image prepare: {e}")
        return data

def process_file(fn, fd):
    """Convert any file to (images, text)."""
    ext = Path(fn).suffix.lower()
    images, text = [], ""

    if ext == ".pdf":
        text = extract_pdf_text(fd)
        imgs = pdf_to_images_highres(fd)
        images = [prepare_image(i, max_px=1600, quality=92) for i in imgs]
        logger.info(f"PDF {fn}: text={len(text)}, images={len(images)}")

    elif ext in IMAGE_FORMATS:
        images = [prepare_image(fd, max_px=1600, quality=92)]
        logger.info(f"Image {fn}: prepared")

    elif ext in {".doc",".docx"}:
        try:
            import mammoth
            text = mammoth.extract_raw_text(io.BytesIO(fd)).value
        except:
            try:
                from docx import Document
                text = "\n".join(p.text for p in Document(io.BytesIO(fd)).paragraphs)
            except: pass
        logger.info(f"Word {fn}: {len(text)} chars")

    return images, text

def call_groq_vision(key, images, hint, doj):
    """Send all images in ONE call with detailed extraction prompt."""
    n = len(images)
    prompt = f"""You are a highly accurate OCR system specialized in Indian government documents.
I am sending {n} high-resolution document image(s) for employee: {hint}

CAREFULLY READ EVERY SINGLE IMAGE and extract ALL text visible.

DOCUMENT TYPES AND WHAT TO EXTRACT:

1. AADHAAR CARD FRONT (blue/white card with photo):
   - Employee name (large bold text, usually ALL CAPS)
   - Father name: look for "S/O" (Son of) or "D/O" (Daughter of) or "W/O" (Wife of)
   - Date of Birth: DD/MM/YYYY format
   - Gender: Male or Female
   - Aadhaar number: 12 digits at bottom (format: XXXX XXXX XXXX)

2. AADHAAR CARD BACK:
   - Complete address with PIN code
   - Mobile number if shown

3. PAN CARD (white card):
   - PAN number: 10 characters like ABCDE1234F
   - Name on PAN
   - Father name on PAN
   - Date of Birth

4. BANK CANCELLED CHEQUE or PASSBOOK:
   - Bank name (e.g. HDFC Bank, SBI, ICICI)
   - Account number (long number)
   - IFSC code (11 chars, e.g. HDFC0001703)
   - Branch name

IMPORTANT:
- Extract EXACT text as printed
- For Aadhaar number: it is ALWAYS 12 digits, look carefully at bottom of card
- For PAN: exactly 10 characters
- For IFSC: exactly 11 characters, 5th character is always digit 0 (zero)
- If you see partial text, extract what you can read clearly
- Do NOT guess unclear text - leave field empty

Return ONLY this JSON (no explanation):
{{
  "employee_name": "EXACT name from Aadhaar front in CAPITALS",
  "father_husband_name": "name after S/O or D/O or W/O",
  "gender": "Male or Female",
  "marital_status": "Unmarried or Married",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number e.g. 7626 8151 1496",
  "mobile_number": "10 digit mobile",
  "pan_number": "10 char PAN e.g. HHMPP0103B",
  "present_address": "complete address from Aadhaar back",
  "permanent_address": "same as present if not separately shown",
  "bank_name": "bank name",
  "bank_account_number": "account number",
  "ifsc_code": "IFSC code e.g. HDFC0001703",
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

    content = [{"type": "text", "text": prompt}]
    for img in images[:4]:
        b64 = base64.standard_b64encode(img).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={"model": model,
                      "messages": [{"role": "user", "content": content}],
                      "temperature": 0.05,
                      "max_tokens": 2048},
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                timeout=90
            )
            logger.info(f"Vision {model}: HTTP {r.status_code}")
            if r.status_code == 200:
                resp = r.json()["choices"][0]["message"]["content"]
                logger.info(f"Vision response: {resp[:300]}")
                return resp
            if r.status_code == 429:
                logger.warning("Rate limited, waiting 30s...")
                time.sleep(30)
                # Try once more
                r2 = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json={"model": model,
                          "messages": [{"role": "user", "content": content}],
                          "temperature": 0.05, "max_tokens": 2048},
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    timeout=90
                )
                if r2.status_code == 200:
                    return r2.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Vision {model}: {e}")
        time.sleep(3)
    return None

def call_groq_text(key, text, hint, doj):
    """Extract from PDF text using text model."""
    prompt = f"""Extract employee data from these Indian HR documents.
Employee: {hint}  DOJ: {doj}

TEXT:
{text[:6000]}

Return ONLY JSON with these keys (empty string for missing):
employee_name, father_husband_name, gender, marital_status, date_of_birth,
date_of_joining, aadhaar_number, mobile_number, pan_number,
present_address, permanent_address, bank_name, bank_account_number,
ifsc_code, branch_name, uan_number, esic_number, pf_basic_wages,
gross_salary, pf_eligibility(=ESIC), nominee_name, nominee_relationship,
nominee_dob, family_members, esic_dispensary, insurance_details"""

    for model in ["llama-3.3-70b-versatile", "llama3-70b-8192"]:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json={"model": model,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.05, "max_tokens": 2048},
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                timeout=30
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(10)
        except Exception as e:
            logger.error(f"Text {model}: {e}")
        time.sleep(2)
    return None

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

def merge(base, update):
    result = dict(base)
    for k, v in (update or {}).items():
        v = str(v).strip() if v else ""
        if v and v not in ("null","None","N/A","undefined","n/a","") \
           and not result.get(k):
            result[k] = v
    return result

def clean_and_fix(fields, doj):
    """Clean fields and auto-fix common OCR errors."""
    for k in EXPECTED_KEYS:
        v = fields.get(k, "")
        if not v or str(v).strip() in ("null","None","N/A","undefined"):
            fields[k] = ""
        else:
            fields[k] = str(v).strip()

    # Auto-fix IFSC: position 4 must be 0 (zero) not O (letter)
    ifsc = fields.get("ifsc_code", "").upper()
    if len(ifsc) >= 5:
        ifsc_list = list(ifsc)
        if ifsc_list[4] == 'O':
            ifsc_list[4] = '0'
        fields["ifsc_code"] = "".join(ifsc_list)

    # Auto-fix PAN: positions 5-8 must be digits, 0,1,2,3,4,9 must be letters
    pan = fields.get("pan_number", "").upper()
    if len(pan) == 10:
        pan_list = list(pan)
        for i in [5, 6, 7, 8]:
            if pan_list[i] == 'O': pan_list[i] = '0'
        for i in [0, 1, 2, 3, 4, 9]:
            if pan_list[i] == '0': pan_list[i] = 'O'
        fields["pan_number"] = "".join(pan_list)

    # Normalize Aadhaar
    a = re.sub(r"\D", "", fields.get("aadhaar_number", ""))
    if len(a) == 12:
        fields["aadhaar_number"] = f"{a[:4]} {a[4:8]} {a[8:]}"
    elif len(a) == 11:
        fields["aadhaar_number"] = a  # Keep for manual fix

    # Defaults
    if doj and not fields.get("date_of_joining"):
        fields["date_of_joining"] = doj
    if not fields.get("pf_eligibility"):
        fields["pf_eligibility"] = "ESIC"

    return fields

def validate(fields):
    issues = {}
    a = re.sub(r"\D", "", fields.get("aadhaar_number", ""))
    if a and len(a) != 12:
        issues["aadhaar_number"] = f"Must be 12 digits, got {len(a)} — please correct manually"
    p = fields.get("pan_number", "").upper()
    if p and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", p):
        issues["pan_number"] = f"Invalid PAN: {p}"
    i = fields.get("ifsc_code", "").upper()
    if i and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", i):
        issues["ifsc_code"] = f"Invalid IFSC: {i}"
    return issues

def empty(msg):
    return {
        "fields": {k: "" for k in EXPECTED_KEYS},
        "field_confidence": {k: "low" for k in EXPECTED_KEYS},
        "validation": {},
        "confidence_summary": {"total_extracted":0,"high":0,"medium":0,
                               "low":26,"review_needed":0},
        "documents_detected": [],
        "error": msg
    }

class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key.strip()

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        t0 = time.time()
        hint = hint_name or "not specified"
        doj = date_of_joining or ""

        all_images, all_texts = [], []

        # Sort: JPG/PNG first (clearest), then PDFs
        sorted_files = sorted(files, key=lambda x: (
            0 if Path(x[0]).suffix.lower() in IMAGE_FORMATS else 1
        ))

        for fn, fd in sorted_files:
            try:
                imgs, txt = process_file(fn, fd)
                all_images.extend(imgs)
                if txt:
                    all_texts.append(f"=== {Path(fn).name} ===\n{txt}")
                logger.info(f"{fn}: {len(imgs)} imgs, {len(txt)} text chars")
            except Exception as e:
                logger.error(f"File error {fn}: {e}")

        if not all_images and not all_texts:
            return empty("No readable files found.")

        fields = {k: "" for k in EXPECTED_KEYS}

        # Step 1: Text model on PDF text (fast, accurate for digital PDFs)
        if all_texts:
            combined = "\n\n".join(all_texts)
            raw = call_groq_text(self.api_key, combined, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    fields = merge(fields, parsed)
                    logger.info(f"Text got: {sum(1 for v in fields.values() if v)} fields")

        # Step 2: Vision on all images (handles scanned PDFs)
        if all_images:
            raw = call_groq_vision(self.api_key, all_images, hint, doj)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    before = sum(1 for v in fields.values() if v)
                    fields = merge(fields, parsed)
                    after = sum(1 for v in fields.values() if v)
                    logger.info(f"Vision added +{after-before}, total={after}")

        # Clean, fix OCR errors, validate
        fields = clean_and_fix(fields, doj)
        val = validate(fields)
        ex = sum(1 for v in fields.values() if v)

        if ex == 0:
            return empty("No data extracted. Use clear JPG photos for best results.")

        key_fields = {"employee_name","aadhaar_number","pan_number",
                      "bank_account_number","date_of_birth","ifsc_code","bank_name"}
        conf = {k: ("high" if fields.get(k) and k in key_fields else
                    "medium" if fields.get(k) else "low")
                for k in EXPECTED_KEYS}

        docs = []
        if fields.get("aadhaar_number"): docs.append("Aadhaar Card")
        if fields.get("pan_number"): docs.append("PAN Card")
        if fields.get("bank_account_number"): docs.append("Bank Document")
        if not docs: docs = ["Documents processed"]

        logger.info(f"Done {time.time()-t0:.1f}s: {ex} fields, {len(val)} issues")
        return {
            "fields": fields,
            "field_confidence": conf,
            "validation": val,
            "confidence_summary": {
                "total_extracted": ex,
                "high": sum(1 for c in conf.values() if c=="high"),
                "medium": sum(1 for c in conf.values() if c=="medium"),
                "low": sum(1 for c in conf.values() if c=="low"),
                "review_needed": len(val)
            },
            "documents_detected": docs
        }
