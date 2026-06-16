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

def pdf_to_images(data):
    """Convert PDF pages to JPEG images."""
    # Try PyMuPDF first
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            images.append(pix.tobytes("jpeg"))
        doc.close()
        if images:
            logging.info(f"PyMuPDF: {len(images)} pages")
            return images
    except Exception as e:
        logging.warning(f"PyMuPDF: {e}")

    # Try Pillow
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        images = []
        for i in range(getattr(img, "n_frames", 1)):
            try: img.seek(i)
            except EOFError: break
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=75)
            images.append(buf.getvalue())
        if images:
            logging.info(f"Pillow PDF: {len(images)} pages")
            return images
    except Exception as e:
        logging.warning(f"Pillow PDF: {e}")
    return []

def compress(data, max_px=1000, quality=75):
    """Compress image to reduce size."""
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

def to_images(data, fn):
    """Convert any file to list of compressed JPEG bytes."""
    ext = Path(fn).suffix.lower()
    if ext == ".pdf":
        imgs = pdf_to_images(data)
        return [compress(img) for img in imgs] if imgs else []
    if ext in {".jpg",".jpeg",".png",".webp",".heic",".bmp"}:
        return [compress(data)]
    return []

def call_claude(api_key, prompt, images):
    """Call Claude API (Anthropic) - handles all image types perfectly."""
    content = []
    for img_data in images[:5]:  # Claude supports up to 5 images
        b64 = base64.standard_b64encode(img_data).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
        })
    content.append({"type": "text", "text": prompt})

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}]
    }
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                         json=payload, headers=headers, timeout=120)
        logging.info(f"Claude API: {r.status_code}")
        if r.status_code == 200:
            text = r.json()["content"][0]["text"]
            logging.info(f"Claude response: {text[:200]}")
            return text
        logging.error(f"Claude error: {r.text[:300]}")
        return f"ERROR_CLAUDE_{r.status_code}:{r.text[:200]}"
    except Exception as e:
        logging.error(f"Claude exception: {e}")
        return f"ERROR:{e}"

def call_groq(api_key, prompt, images):
    """Call Groq vision API as fallback."""
    content = [{"type":"text","text":prompt}]
    for img_data in images[:2]:
        b64 = base64.standard_b64encode(img_data).decode()
        content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}})

    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        try:
            h = {"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}
            p = {"model":model,"messages":[{"role":"user","content":content}],
                 "temperature":0.1,"max_tokens":2048}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                            json=p, headers=h, timeout=120)
            logging.info(f"Groq {model}: {r.status_code}")
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(30)
        except Exception as e:
            logging.error(f"Groq error: {e}")
        time.sleep(3)
    return "ERROR:Groq failed"

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

def empty(r):
    return {
        "fields": {k:"" for k in EXPECTED_KEYS},
        "field_confidence": {k:"low" for k in EXPECTED_KEYS},
        "validation": {"_e":{"error":True,"message":r}},
        "confidence_summary": {"total_extracted":0,"high":0,"medium":0,"low":0,"review_needed":1},
        "documents_detected": [],
        "error": r
    }

PROMPT = """You are an expert at reading Indian government documents (Aadhaar card, PAN card, bank cheques/passbooks).

Extract ALL visible information from the document image(s) provided.
Employee name hint: {hint}
Date of joining: {doj}

Return ONLY this JSON (no explanation, no markdown):
{{
  "employee_name": "name exactly as on Aadhaar card",
  "father_husband_name": "father or husband name from Aadhaar",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried",
  "date_of_birth": "DD/MM/YYYY from Aadhaar",
  "date_of_joining": "{doj}",
  "aadhaar_number": "12 digit Aadhaar number",
  "mobile_number": "10 digit mobile number if visible",
  "pan_number": "PAN number like ABCDE1234F",
  "present_address": "complete address from Aadhaar back side",
  "permanent_address": "same as present if not specified separately",
  "bank_name": "bank name from cheque or passbook",
  "bank_account_number": "account number from cheque",
  "ifsc_code": "IFSC code from cheque",
  "branch_name": "branch name from cheque",
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

class DocumentExtractor:
    def __init__(self, api_key):
        self.api_key = api_key.strip()
        # Detect key type
        if api_key.startswith("sk-ant-"):
            self.key_type = "claude"
        elif api_key.startswith("gsk_"):
            self.key_type = "groq"
        else:
            self.key_type = "unknown"
        logging.info(f"API key type: {self.key_type}")

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        # Convert all files to images
        all_images = []
        for fn, fd in files:
            imgs = to_images(fd, fn)
            logging.info(f"{fn}: {len(imgs)} image(s)")
            all_images.extend(imgs)

        if not all_images:
            return empty("No readable images. Upload JPG, PNG or PDF files.")

        prompt = PROMPT.format(hint=hint_name or "not provided", doj=date_of_joining or "")

        # Try Claude first, then Groq as fallback
        if self.key_type == "claude":
            raw = call_claude(self.api_key, prompt, all_images)
            if raw.startswith("ERROR") and "groq" in raw.lower():
                raw = call_groq(self.api_key, prompt, all_images)
        elif self.key_type == "groq":
            raw = call_groq(self.api_key, prompt, all_images)
        else:
            # Try Claude format first
            raw = call_claude(self.api_key, prompt, all_images)
            if raw.startswith("ERROR"):
                raw = call_groq(self.api_key, prompt, all_images)

        if not raw or raw.startswith("ERROR"):
            result = empty(f"API error: {raw[:300] if raw else 'No response'}")
            result["raw_response"] = raw or ""
            return result

        fields = parse_json(raw)
        if not fields:
            result = empty("Could not parse response")
            result["raw_response"] = raw[:500]
            return result

        for k in EXPECTED_KEYS:
            if k not in fields or fields[k] is None: fields[k] = ""
            else: fields[k] = str(fields[k]).strip()

        if date_of_joining and not fields.get("date_of_joining"):
            fields["date_of_joining"] = date_of_joining

        fc = {k:("high" if fields[k] else "low") for k in EXPECTED_KEYS}
        val = {}
        if not fields.get("employee_name"):
            val["employee_name"] = {"error":True,"message":"Name not found"}
        ex = sum(1 for v in fields.values() if v)
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
