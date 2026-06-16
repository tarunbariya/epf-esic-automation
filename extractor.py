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

def extract_pdf_text(data):
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        logging.info(f"PDF text: {len(text)} chars")
        return text.strip()
    except Exception as e:
        logging.warning(f"PDF text failed: {e}")
        return ""

def pdf_to_images(data):
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        imgs = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            imgs.append(pix.tobytes("jpeg"))
        doc.close()
        return imgs
    except:
        pass
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        imgs = []
        for i in range(getattr(img, "n_frames", 1)):
            try: img.seek(i)
            except EOFError: break
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=70)
            imgs.append(buf.getvalue())
        return imgs
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

def groq_text(key, content, hint, doj):
    """Extract data using Groq TEXT model — no vision, no rate limits."""
    prompt = f"""You are extracting employee registration data from Indian HR documents.
Employee name hint: {hint}
Date of joining: {doj}

Document content:
{content[:4000]}

Extract all visible information. Return ONLY this JSON (no explanation):
{{
  "employee_name": "name exactly as shown",
  "father_husband_name": "father or husband name",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit number",
  "mobile_number": "10 digit mobile",
  "pan_number": "PAN like ABCDE1234F",
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

    for model in ["llama-3.3-70b-versatile", "llama3-70b-8192", "gemma2-9b-it"]:
        try:
            h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            p = {"model": model, "messages": [{"role":"user","content":prompt}],
                 "temperature": 0.1, "max_tokens": 2048}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              json=p, headers=h, timeout=60)
            logging.info(f"Groq text {model}: {r.status_code}")
            if r.status_code == 200:
                text = r.json()["choices"][0]["message"]["content"]
                logging.info(f"Text response: {text[:200]}")
                return text
            if r.status_code == 429:
                time.sleep(10)
        except Exception as e:
            logging.error(f"Groq text {model} error: {e}")
        time.sleep(2)
    return None

def groq_vision(key, prompt, img_data):
    """Extract data from a single image using Groq vision."""
    b64 = base64.standard_b64encode(img_data).decode()
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
    ]
    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        try:
            h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            p = {"model": model, "messages": [{"role":"user","content":content}],
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
        images = []   # compressed JPEG bytes
        texts = []    # extracted text from PDFs

        for fn, fd in files:
            ext = Path(fn).suffix.lower()
            logging.info(f"File: {fn} ({len(fd)} bytes)")

            if ext == ".pdf":
                # Extract text first
                txt = extract_pdf_text(fd)
                if txt:
                    texts.append(f"[{fn}]:\n{txt}")
                # Also get images from PDF
                imgs = pdf_to_images(fd)
                images.extend([compress(i) for i in imgs])

            elif ext in {".jpg",".jpeg",".png",".webp",".bmp",".heic",".tiff"}:
                images.append(compress(fd))

        if not images and not texts:
            return empty("No readable files found.")

        fields = {k:"" for k in EXPECTED_KEYS}

        vision_prompt = f"""Extract employee data from this Indian document image.
Employee: {hint_name}  DOJ: {date_of_joining}
Return ONLY JSON with these keys (empty string if not found):
employee_name, father_husband_name, gender, marital_status, date_of_birth,
date_of_joining, aadhaar_number, mobile_number, pan_number, present_address,
permanent_address, bank_name, bank_account_number, ifsc_code, branch_name,
pf_eligibility(use ESIC), uan_number, esic_number, pf_basic_wages, gross_salary,
nominee_name, nominee_relationship, nominee_dob, family_members,
esic_dispensary, insurance_details"""

        # Process images one at a time with vision
        for i, img in enumerate(images[:3]):
            logging.info(f"Vision processing image {i+1}/{min(len(images),3)}")
            raw = groq_vision(self.api_key, vision_prompt, img)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    fields = merge(fields, parsed)
                    logging.info(f"Vision img {i+1}: {sum(1 for v in parsed.values() if v)} fields")
            time.sleep(3)  # Avoid rate limits between images

        # Process PDF text with text model
        if texts:
            combined = "\n\n".join(texts)
            logging.info(f"Text processing: {len(combined)} chars")
            raw = groq_text(self.api_key, combined, hint_name, date_of_joining)
            if raw:
                parsed = parse_json(raw)
                if parsed:
                    fields = merge(fields, parsed)
                    logging.info(f"Text: {sum(1 for v in parsed.values() if v)} fields")

        # Clean fields
        for k in EXPECTED_KEYS:
            if k not in fields or fields[k] is None: fields[k] = ""
            else: fields[k] = str(fields[k]).strip()

        if date_of_joining and not fields.get("date_of_joining"):
            fields["date_of_joining"] = date_of_joining

        ex = sum(1 for v in fields.values() if v)
        if ex == 0:
            return empty("No data extracted. Check document quality.")

        fc = {k:("high" if fields[k] else "low") for k in EXPECTED_KEYS}
        val = {}
        if not fields.get("employee_name"):
            val["employee_name"] = {"error":True,"message":"Name not found"}

        docs = []
        if fields.get("aadhaar_number"): docs.append("Aadhaar Card")
        if fields.get("pan_number"): docs.append("PAN Card")
        if fields.get("bank_account_number"): docs.append("Bank Document")
        if not docs: docs = ["Documents processed"]

        return {
            "fields": fields, "field_confidence": fc, "validation": val,
            "confidence_summary": {"total_extracted":ex,"high":ex,"medium":0,
                                   "low":len(EXPECTED_KEYS)-ex,"review_needed":len(val)},
            "documents_detected": docs
        }
