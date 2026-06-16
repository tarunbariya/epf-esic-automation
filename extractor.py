import json, base64, re, time, logging, requests, io
from pathlib import Path

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

def extract_text_from_pdf(data):
    """Extract text from PDF using PyMuPDF."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        logging.info(f"PDF text extracted: {len(text)} chars")
        return text.strip()
    except Exception as e:
        logging.warning(f"PDF text extract failed: {e}")
        return ""

def pdf_to_images(data):
    """Convert PDF to images."""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            images.append(pix.tobytes("jpeg"))
        doc.close()
        return images
    except:
        pass
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        images = []
        for i in range(getattr(img, "n_frames", 1)):
            try: img.seek(i)
            except EOFError: break
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=70)
            images.append(buf.getvalue())
        return images
    except:
        return []

def compress(data, max_px=800, quality=70):
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if max(img.size) > max_px:
            r = max_px / max(img.size)
            img = img.resize((int(img.width*r), int(img.height*r)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()
    except:
        return data

def call_groq_vision(key, prompt, images):
    """Call Groq with vision - max 1 image at a time."""
    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        for img in images[:2]:  # Try first 2 images
            try:
                b64 = base64.standard_b64encode(img).decode()
                content = [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
                h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                p = {"model": model, "messages": [{"role": "user", "content": content}],
                     "temperature": 0.1, "max_tokens": 2048}
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                  json=p, headers=h, timeout=60)
                logging.info(f"Groq vision {model}: {r.status_code}")
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                if r.status_code == 429:
                    time.sleep(20)
            except Exception as e:
                logging.error(f"Groq vision error: {e}")
            time.sleep(3)
    return None

def call_groq_text(key, text_content, hint, doj):
    """Use Groq text model to extract from PDF text."""
    prompt = f"""Extract employee registration data from this Indian document text.
Employee hint: {hint}
Date of joining: {doj}

Document text:
{text_content[:3000]}

Return ONLY this JSON:
{{
  "employee_name": "name from document",
  "father_husband_name": "father/husband name",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried", 
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number",
  "mobile_number": "10 digit mobile",
  "pan_number": "PAN like ABCDE1234F",
  "present_address": "full address",
  "permanent_address": "full address",
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

    for model in ["llama-3.3-70b-versatile", "llama3-70b-8192"]:
        try:
            h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            p = {"model": model,
                 "messages": [{"role": "user", "content": prompt}],
                 "temperature": 0.1, "max_tokens": 2048}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                             json=p, headers=h, timeout=60)
            logging.info(f"Groq text {model}: {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logging.error(f"Groq text error: {e}")
        time.sleep(2)
    return None

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

def merge_fields(base, update):
    """Merge two field dicts, keeping non-empty values."""
    result = dict(base)
    for k, v in update.items():
        if v and not result.get(k):
            result[k] = v
    return result

def empty(r):
    return {
        "fields": {k:"" for k in EXPECTED_KEYS},
        "field_confidence": {k:"low" for k in EXPECTED_KEYS},
        "validation": {"_e":{"error":True,"message":r}},
        "confidence_summary": {"total_extracted":0,"high":0,"medium":0,"low":0,"review_needed":1},
        "documents_detected": [],
        "error": r
    }

class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key.strip()

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        all_images = []
        all_text = []

        for fn, fd in files:
            ext = Path(fn).suffix.lower()
            logging.info(f"Processing: {fn} ({len(fd)} bytes)")

            if ext == ".pdf":
                # Extract text from PDF
                text = extract_text_from_pdf(fd)
                if text:
                    all_text.append(f"[From {fn}]:\n{text}")
                # Also convert to images
                imgs = pdf_to_images(fd)
                all_images.extend([compress(img) for img in imgs])

            elif ext in {".jpg",".jpeg",".png",".webp",".bmp",".heic"}:
                all_images.append(compress(fd))

        if not all_images and not all_text:
            return empty("No readable documents found.")

        combined_fields = {k:"" for k in EXPECTED_KEYS}
        raw_results = []

        # Step 1: Try vision on images (1 at a time)
        if all_images:
            vision_prompt = f"""Extract employee data from this Indian document image (Aadhaar/PAN/bank cheque).
Employee: {hint_name}  DOJ: {date_of_joining}
Return ONLY JSON with keys: employee_name, father_husband_name, gender, marital_status, date_of_birth, date_of_joining, aadhaar_number, mobile_number, pan_number, present_address, permanent_address, bank_name, bank_account_number, ifsc_code, branch_name, pf_eligibility(=ESIC), uan_number, esic_number, pf_basic_wages, gross_salary, nominee_name, nominee_relationship, nominee_dob, family_members, esic_dispensary, insurance_details
Use empty string for missing fields."""

            vision_result = call_groq_vision(self.api_key, vision_prompt, all_images)
            if vision_result:
                raw_results.append(vision_result)
                parsed = parse_json(vision_result)
                if parsed:
                    combined_fields = merge_fields(combined_fields, parsed)
                    logging.info(f"Vision extracted {sum(1 for v in parsed.values() if v)} fields")

        # Step 2: Use text extraction for PDFs
        if all_text:
            combined_text = "\n\n".join(all_text)
            text_result = call_groq_text(self.api_key, combined_text, hint_name, date_of_joining)
            if text_result:
                raw_results.append(text_result)
                parsed = parse_json(text_result)
                if parsed:
                    combined_fields = merge_fields(combined_fields, parsed)
                    logging.info(f"Text extracted {sum(1 for v in parsed.values() if v)} fields")

        if not any(combined_fields.values()):
            return empty(f"Could not extract data. Check document quality.")

        # Clean up fields
        for k in EXPECTED_KEYS:
            if k not in combined_fields or combined_fields[k] is None:
                combined_fields[k] = ""
            else:
                combined_fields[k] = str(combined_fields[k]).strip()

        if date_of_joining and not combined_fields.get("date_of_joining"):
            combined_fields["date_of_joining"] = date_of_joining

        fc = {k:("high" if combined_fields[k] else "low") for k in EXPECTED_KEYS}
        val = {}
        if not combined_fields.get("employee_name"):
            val["employee_name"] = {"error":True,"message":"Name not found"}
        ex = sum(1 for v in combined_fields.values() if v)

        docs = []
        if combined_fields.get("aadhaar_number"): docs.append("Aadhaar Card")
        if combined_fields.get("pan_number"): docs.append("PAN Card")
        if combined_fields.get("bank_account_number"): docs.append("Bank Document")
        if not docs: docs = ["Documents processed"]

        return {
            "fields": combined_fields,
            "field_confidence": fc,
            "validation": val,
            "confidence_summary": {"total_extracted":ex,"high":ex,"medium":0,
                                   "low":len(EXPECTED_KEYS)-ex,"review_needed":len(val)},
            "documents_detected": docs
        }
