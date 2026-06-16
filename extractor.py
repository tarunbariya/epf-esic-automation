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
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
            images.append(("image/jpeg", pix.tobytes("jpeg")))
        doc.close()
        logging.info(f"PDF converted: {len(images)} pages")
        return images
    except Exception as e:
        logging.warning(f"PyMuPDF failed: {e}")
        return []

def compress(data):
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if max(img.size) > 1200:
            r = 1200/max(img.size)
            img = img.resize((int(img.width*r), int(img.height*r)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue()
    except:
        return data

def to_images(data, fn):
    ext = Path(fn).suffix.lower()
    if ext == ".pdf":
        imgs = pdf_to_images(data)
        if imgs: return imgs
        return []
    mime = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png"}.get(ext)
    if not mime: return []
    return [(mime, compress(data))]

def call_groq(key, prompt, images):
    """Call Groq API with vision."""
    content = [{"type":"text","text":prompt}]
    for mime, data in images[:4]:
        b64 = base64.standard_b64encode(data).decode()
        content.append({"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}})

    for model in ["meta-llama/llama-4-scout-17b-16e-instruct",
                  "meta-llama/llama-4-maverick-17b-128e-instruct"]:
        try:
            h = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
            p = {"model":model,"messages":[{"role":"user","content":content}],
                 "temperature":0.1,"max_tokens":4096}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                            json=p, headers=h, timeout=120)
            logging.info(f"Groq {model}: {r.status_code}")
            if r.status_code == 200:
                text = r.json()["choices"][0]["message"]["content"]
                logging.info(f"Response: {text[:200]}")
                return text
            logging.error(f"Groq error: {r.text[:200]}")
        except Exception as e:
            logging.error(f"Exception: {e}")
    return "ERROR:All Groq models failed"

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
    return {"fields":{k:"" for k in EXPECTED_KEYS},
            "field_confidence":{k:"low" for k in EXPECTED_KEYS},
            "validation":{"_e":{"error":True,"message":r}},
            "confidence_summary":{"total_extracted":0,"high":0,"medium":0,"low":0,"review_needed":1},
            "documents_detected":[],"error":r}

class DocumentExtractor:
    def __init__(self, api_key): self.api_key = api_key.strip()

    def process_employee_documents(self, files, hint_name="", date_of_joining=""):
        images = []
        for fn, fd in files:
            imgs = to_images(fd, fn)
            logging.info(f"{fn}: {len(imgs)} image(s)")
            images.extend(imgs)

        if not images:
            return empty("No readable images found.")

        logging.info(f"Sending {len(images)} images to Groq AI")

        prompt = f"""Extract employee data from these Indian HR documents (Aadhaar, PAN, bank cheque).
Employee: {hint_name}  Date of joining: {date_of_joining}

Return ONLY this JSON (no explanation):
{{
  "employee_name": "name exactly as on Aadhaar",
  "father_husband_name": "father or husband name",
  "gender": "Male or Female",
  "marital_status": "Married or Unmarried",
  "date_of_birth": "DD/MM/YYYY",
  "date_of_joining": "{date_of_joining}",
  "aadhaar_number": "12 digit aadhaar",
  "mobile_number": "10 digit mobile",
  "pan_number": "PAN like ABCDE1234F",
  "present_address": "full address from Aadhaar",
  "permanent_address": "same as present if not specified",
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

        raw = call_groq(self.api_key, prompt, images)

        if not raw or raw.startswith("ERROR"):
            result = empty(f"API error: {raw[:200] if raw else 'No response'}")
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

        return {"fields":fields,"field_confidence":fc,"validation":val,
                "confidence_summary":{"total_extracted":ex,"high":ex,"medium":0,
                "low":len(EXPECTED_KEYS)-ex,"review_needed":len(val)},
                "documents_detected":docs}
