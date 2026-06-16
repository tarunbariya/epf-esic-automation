import csv, io, requests

COLUMNS = [
    "SR.N","PF/ESIC","OLD UAN NO.","OLD ESIC NO.",
    "AADHAR WISE NAME","AADHAR WISE FATHER/HUSBAND NAME",
    "RELATION (F/H)","MALE/FE -MALE","MARRIED/UN -MARRIED",
    "DATE OF BIRTH","DATE OF JOING","AADHAR NO.","PF WAGES",
    "MOBILE NO.","BANK NAME","BANK A/C NO.","IFSC CODE","PAN NO.",
    "PAN CARD PHOTO","EMPLOYEE PRESENT ADDRESS","EMPLOYEE PERMANENT ADDRESS",
    "EMPLOYEE ADDRES WISE DISPENSARY","EMPLOYEE PHOTO",
    "EMPLOYEE NOMINEE NAME","EMPLOYEE RELATION WITH NOMINEE",
    "EMPLOYEE NOMINEE ADDRESS","EMPLOYEE FAMILY NAME",
    "EMPLOYEE FAMILY BIRTH DATE","EMPLOYEE RELATION WITH FAMILY MEMBER",
    "EMPLOYEE FAMILY ADDRESS","EMPLOYEE FAMILY AADHAR CARD PHOTO"
]

def fix_date(d):
    """Normalize any date to DD/MM/YYYY"""
    if not d: return ""
    d = str(d).strip()
    if len(d)==10 and d[2]=="/" and d[5]=="/": return d
    if len(d)==10 and d[4]=="-":
        try:
            p=d.split("-"); return f"{p[2]}/{p[1]}/{p[0]}"
        except: pass
    return d

def get_relation(gender, marital_status):
    """
    Correct relation logic:
    - Unmarried (any gender)  → Father
    - Married + Female        → Husband
    - Married + Male          → Wife
    - Unknown                 → Father (default)
    """
    g = str(gender).lower().strip()
    m = str(marital_status).lower().strip()
    if "unmarried" in m:
        return "Father"
    if "married" in m:
        return "Husband" if "female" in g else "Wife"
    return "Father"

def build_row(sr_no, fields):
    gender  = fields.get("gender","") or ""
    marital = fields.get("marital_status","") or ""
    return [
        str(sr_no),                                                    # SR.N
        fields.get("pf_eligibility","") or "ESIC",                    # PF/ESIC
        fields.get("uan_number","") or "",                             # OLD UAN NO.
        fields.get("esic_number","") or "",                            # OLD ESIC NO.
        fields.get("employee_name","") or "",                          # AADHAR WISE NAME
        fields.get("father_husband_name","") or "",                    # FATHER/HUSBAND
        get_relation(gender, marital),                                 # RELATION
        gender.upper(),                                                 # MALE/FEMALE
        marital.title(),                                               # MARRIED/UNMARRIED
        fix_date(fields.get("date_of_birth","")),                     # DOB
        fix_date(fields.get("date_of_joining","")),                   # DOJ
        fields.get("aadhaar_number","") or "",                        # AADHAR NO
        fields.get("pf_basic_wages","") or "",                        # PF WAGES
        fields.get("mobile_number","") or "",                         # MOBILE
        fields.get("bank_name","") or "",                             # BANK NAME
        fields.get("bank_account_number","") or "",                   # BANK A/C
        fields.get("ifsc_code","") or "",                             # IFSC
        fields.get("pan_number","") or "",                            # PAN
        "",                                                            # PAN CARD PHOTO
        fields.get("present_address","") or "",                       # PRESENT ADDRESS
        fields.get("permanent_address","") or fields.get("present_address","") or "", # PERMANENT
        fields.get("esic_dispensary","") or "",                       # DISPENSARY
        "",                                                            # EMPLOYEE PHOTO
        fields.get("nominee_name","") or "",                          # NOMINEE NAME
        fields.get("nominee_relationship","") or "",                  # NOMINEE RELATION
        fields.get("present_address","") or "",                       # NOMINEE ADDRESS
        fields.get("family_members","") or "",                        # FAMILY NAME
        fix_date(fields.get("nominee_dob","")),                       # FAMILY DOB
        fields.get("nominee_relationship","") or "",                  # FAMILY RELATION
        fields.get("permanent_address","") or "",                     # FAMILY ADDRESS
        "",                                                            # FAMILY AADHAR PHOTO
    ]

def employees_to_csv(employees):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for i, emp in enumerate(employees, 1):
        w.writerow(build_row(i, emp.get("fields", {})))
    return out.getvalue()

class SheetsWriter:
    def __init__(self, script_url, sheet_url=None):
        self.script_url = script_url.strip()

    def write_employees(self, employees):
        rows = [build_row(i+1, emp.get("fields",{})) for i,emp in enumerate(employees)]
        resp = requests.post(
            self.script_url,
            json={"rows": rows},
            timeout=60,
            headers={"Content-Type": "application/json"}
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("status") == "error":
                raise Exception(f"Script error: {result.get('message','Unknown')}")
            return len(employees)
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:300]}")
