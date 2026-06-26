"""EPF/ESIC Registration Automation - Premium Corporate Navy v2"""
import streamlit as st
import json, time, zipfile, io, hashlib
from datetime import datetime, date
from pathlib import Path

Path("logs").mkdir(exist_ok=True)
import logging
logging.basicConfig(filename="logs/automation.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("app")

st.set_page_config(page_title="EPF & ESIC Automation", page_icon="📋",
                   layout="wide", initial_sidebar_state="expanded")

# ══ PREMIUM CORPORATE THEME ════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif; }

/* Page background - midnight */
.stApp { background: #0f1117; }
.main .block-container { padding-top: 2rem; max-width: 1280px; }

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
/* Keep header transparent but DON'T hide it - the sidebar toggle lives here */
header[data-testid="stHeader"] { background: transparent; height: 0; }
/* Ensure sidebar collapse/expand control is always visible and styled */
[data-testid="collapsedControl"] {
    visibility: visible !important;
    display: block !important;
    color: #818cf8 !important;
    background: #161a26 !important;
    border-radius: 8px;
    border: 1px solid #2d3350;
}
[data-testid="stSidebarCollapseButton"] { visibility: visible !important; display: block !important; }
[data-testid="stSidebarCollapseButton"] button { color: #818cf8 !important; }
/* Sidebar must always be visible */
section[data-testid="stSidebar"][aria-expanded="false"] { display: flex !important; }

/* ── SIDEBAR - dark panel ── */
section[data-testid="stSidebar"] {
    background: #161a26 !important;
    border-right: 1px solid #232838;
    min-width: 260px !important;
    visibility: visible !important;
}
section[data-testid="stSidebar"] > div { padding-top: 1.5rem; }
section[data-testid="stSidebar"] * { color: #c4cae0 !important; }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] h5 { color: #f1f3f9 !important; font-weight: 600 !important; }
section[data-testid="stSidebar"] .stTextInput input {
    background: #0f1117 !important;
    color: #f1f3f9 !important;
    border: 1px solid #2d3350 !important;
    border-radius: 10px !important;
    padding: 10px 12px !important;
}
section[data-testid="stSidebar"] .stTextInput input::placeholder { color: #6b7194 !important; }
section[data-testid="stSidebar"] .stButton button {
    background: #232838 !important;
    color: #f1f3f9 !important;
    border: 1px solid #2d3350 !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
}
section[data-testid="stSidebar"] .stButton button:hover { background: #2d3350 !important; }
section[data-testid="stSidebar"] hr { border-color: #232838 !important; }
section[data-testid="stSidebar"] [data-testid="stMetricValue"] { color: #ffffff !important; font-weight: 700 !important; }
section[data-testid="stSidebar"] [data-testid="stMetricLabel"] { color: #6b7194 !important; }

/* ── METRIC CARDS ── */
[data-testid="stMetric"] {
    background: #161a26;
    border: 1px solid #232838;
    border-radius: 14px;
    padding: 18px 20px;
    transition: transform 0.2s, border-color 0.2s;
}
[data-testid="stMetric"]:hover { transform: translateY(-2px); border-color: #3d4570; }
[data-testid="stMetricValue"] { color: #818cf8; font-weight: 700; font-size: 26px; }
[data-testid="stMetricLabel"] { color: #6b7194; font-weight: 500; }

/* ── TABS - pill ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 6px;
    background: #161a26;
    border-radius: 14px;
    padding: 8px;
    border: 1px solid #232838;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    padding: 10px 18px;
    color: #9ca3c4;
    font-weight: 500;
    font-size: 14px;
}
.stTabs [data-baseweb="tab"]:hover { background: #1e2333; color: #c4cae0; }
.stTabs [aria-selected="true"] {
    background: #6366f1 !important;
    color: #ffffff !important;
}

/* ── BUTTONS ── */
.stButton button { border-radius: 10px; font-weight: 500; padding: 8px 18px; transition: all 0.2s; }
button[kind="primary"] {
    background: #6366f1 !important;
    border: none !important;
    color: #ffffff !important;
}
button[kind="primary"]:hover { background: #4f46e5 !important; transform: translateY(-1px); }
button[kind="secondary"] {
    background: #161a26 !important;
    border: 1px solid #2d3350 !important;
    color: #818cf8 !important;
}
.main .stButton button { background: #232838; color: #f1f3f9; border: 1px solid #2d3350; }
.main .stButton button:hover { background: #2d3350; }

/* ── EXPANDERS ── */
[data-testid="stExpander"] {
    border: 1px solid #232838 !important;
    border-radius: 12px;
    background: #161a26;
    margin-bottom: 8px;
}
[data-testid="stExpander"] summary { color: #f1f3f9 !important; font-weight: 500; padding: 14px 18px; }
[data-testid="stExpander"] summary:hover { color: #818cf8 !important; }

/* ── FILE UPLOADER ── */
[data-testid="stFileUploader"] {
    background: #161a26;
    border: 2px dashed #3730a3;
    border-radius: 16px;
    padding: 20px;
}
[data-testid="stFileUploader"] * { color: #c4cae0 !important; }
[data-testid="stFileUploader"] button {
    background: #6366f1 !important; color: #fff !important; border: none !important;
}

/* ── INPUTS in main ── */
.main .stTextInput input, .main input, .main textarea {
    background: #161a26 !important;
    color: #f1f3f9 !important;
    border: 1px solid #232838 !important;
    border-radius: 10px !important;
}
.main .stTextInput input::placeholder { color: #6b7194 !important; }

/* Selectbox */
.main [data-baseweb="select"] > div {
    background: #161a26 !important;
    border: 1px solid #232838 !important;
    color: #f1f3f9 !important;
}

/* Radio */
.main .stRadio label { color: #c4cae0 !important; }

/* ── ALERTS ── */
.stSuccess, .stInfo, .stWarning, .stError { border-radius: 12px; }

/* ── HEADINGS & TEXT ── */
h1,h2,h3,h4 { color: #f1f3f9 !important; font-weight: 600; }
.main p, .main label, .main span, .main div { color: #c4cae0; }
.main .stMarkdown { color: #c4cae0; }

/* Date input */
.main [data-baseweb="input"] { background: #161a26 !important; }

/* Code blocks */
.stCode, code { background: #0a0c12 !important; color: #a5b4fc !important; }

/* JSON */
[data-testid="stJson"] { background: #0a0c12 !important; border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

CONFIG_FILE = "config.json"

def load_config():
    cfg = {}
    try:
        if Path(CONFIG_FILE).exists():
            cfg = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
    except: pass
    try:
        if "groq_key" in st.secrets: cfg["groq_key"] = st.secrets["groq_key"]
        if "script_url" in st.secrets: cfg["script_url"] = st.secrets["script_url"]
    except: pass
    return cfg

def save_config(cfg):
    try: Path(CONFIG_FILE).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except: pass

cfg = load_config()

for k, v in {"extracted_employees":[], "approved_employees":[], "processing_log":[]}.items():
    if k not in st.session_state: st.session_state[k] = v

def detect_employees(zip_bytes):
    SUPPORTED = {".pdf",".jpg",".jpeg",".png",".webp",".bmp",".heic",".tiff",".docx",".doc"}
    folder_files = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for entry in zf.namelist():
            clean = entry.replace("\\","/")
            parts = [p.strip() for p in clean.split("/") if p.strip()]
            if not parts: continue
            if Path(parts[-1]).suffix.lower() not in SUPPORTED: continue
            folder_key = "/".join(parts[:-1]) if len(parts)>1 else "__root__"
            folder_files.setdefault(folder_key,[]).append((parts[-1], zf.read(entry)))
    if not folder_files: return {}
    all_folders = [k for k in folder_files if k != "__root__"]
    if not all_folders:
        return {"All_Documents": folder_files.get("__root__",[])}
    parent_children = {}
    for fk in all_folders:
        parts = fk.split("/")
        for depth in range(len(parts)):
            parent = "/".join(parts[:depth]) if depth>0 else "__top__"
            parent_children.setdefault(parent,set()).add("/".join(parts[:depth+1]))
    employee_folders = {}
    for parent, children in parent_children.items():
        if len(children) >= 2:
            for child_path in sorted(children):
                emp_name = child_path.split("/")[-1]
                emp_files = []
                for fk, files in folder_files.items():
                    if fk==child_path or fk.startswith(child_path+"/"):
                        emp_files.extend(files)
                if emp_files: employee_folders[emp_name] = emp_files
            break
    if not employee_folders:
        for fk, files in folder_files.items():
            employee_folders.setdefault(fk.split("/")[0],[]).extend(files)
    return employee_folders

def file_hash(files):
    h = hashlib.md5()
    for fn, fd in files:
        h.update(fn.encode()); h.update(fd[:100])
    return h.hexdigest()

# ══ SIDEBAR - Navigation only ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("""<div style="padding:4px 0 20px; border-bottom:1px solid #232838; margin-bottom:20px;">
    <div style="display:flex; align-items:center; gap:12px;">
    <div style="width:44px; height:44px; border-radius:12px; background:#6366f1; display:flex; align-items:center; justify-content:center; font-size:22px;">📋</div>
    <div>
    <div style="font-size:19px; font-weight:700; color:#ffffff;">EPF · ESIC</div>
    <div style="font-size:12px; color:#6b7194;">HR automation suite</div>
    </div></div>
    </div>""", unsafe_allow_html=True)

    # Status indicators
    key_ok = bool(cfg.get("groq_key"))
    url_ok = bool(cfg.get("script_url"))
    st.markdown(f"""<div style="margin-bottom:20px;">
    <div style="display:flex; align-items:center; gap:8px; padding:8px 0; font-size:13px;">
    <span style="color:{'#5DCAA5' if key_ok else '#EF9F27'};">●</span> AI engine {'connected' if key_ok else 'not set'}</div>
    <div style="display:flex; align-items:center; gap:8px; padding:8px 0; font-size:13px;">
    <span style="color:{'#5DCAA5' if url_ok else '#EF9F27'};">●</span> Google Sheet {'connected' if url_ok else 'not set'}</div>
    </div>""", unsafe_allow_html=True)

    st.divider()
    st.markdown("##### Overview")
    c1,c2 = st.columns(2)
    c1.metric("Extracted", len(st.session_state.extracted_employees))
    c2.metric("Approved", len(st.session_state.approved_employees))

    st.divider()
    if st.button("🗑️ Clear all data", use_container_width=True):
        st.session_state.extracted_employees = []
        st.session_state.approved_employees = []
        st.session_state.processing_log = []
        st.rerun()

    st.markdown("""<div style="position:relative; margin-top:30px; padding-top:16px; border-top:1px solid #232838; font-size:11px; color:#6b7194;">
    Vasundhara · HR Portal v2.0</div>""", unsafe_allow_html=True)

# ══ HEADER ═════════════════════════════════════════════════════════════════
st.markdown("""<div style="background:linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #4f46e5 100%);
color:white; padding:26px 32px; border-radius:18px; margin-bottom:24px;
display:flex; justify-content:space-between; align-items:center;
box-shadow:0 8px 28px rgba(0,0,0,0.4); border:1px solid #3730a3;">
<div>
<h1 style="margin:0; font-size:24px; color:#ffffff; font-weight:700;">Employee Onboarding</h1>
<p style="margin:6px 0 0; opacity:0.85; font-size:13px; color:#c7d2fe;">
EPF & ESIC registration · AI-powered extraction · All 31 columns auto-filled</p>
</div>
<div style="display:flex; align-items:center; gap:14px;">
<div style="text-align:right;">
<div style="font-size:13px; font-weight:600; color:#ffffff;">Tarun Bariya</div>
<div style="font-size:11px; color:#a5b4fc;">HR Manager</div>
</div>
<div style="width:46px; height:46px; border-radius:50%; background:rgba(255,255,255,0.15);
display:flex; align-items:center; justify-content:center; font-weight:700; font-size:16px;">TB</div>
</div>
</div>""", unsafe_allow_html=True)

tabs = st.tabs(["📤 Upload","📅 Joining Dates","🔍 Review","✅ Approve & Export","📊 Validation","📜 Logs","⚙️ Settings"])

# ══ TAB 1: UPLOAD ══════════════════════════════════════════════════════════
with tabs[0]:
    saved_key = cfg.get("groq_key","")
    if not saved_key:
        st.warning("⚠️ Set up your API key in the **Settings** tab first!")
    else:
        mode = st.radio("Mode", ["Single employee","Batch ZIP (multiple employees)"], horizontal=True)
        files = st.file_uploader("Drop files",
            type=["pdf","jpg","jpeg","png","webp","zip","bmp","docx","heic","tiff"],
            accept_multiple_files=True)
        if mode == "Single employee":
            emp_hint = st.text_input("Employee name hint", placeholder="e.g. Krupal Patel")
            doj_val = str(st.date_input("Date of Joining"))
        else:
            emp_hint, doj_val = "", ""
            st.info("ZIP structure: each employee in their own folder. Supports PDF, JPG, PNG, screenshots, photos, DOCX.")
        if files:
            for f in files:
                st.caption(f"{'📦' if 'zip' in f.type else '📄' if 'pdf' in f.type else '🖼️'} {f.name} ({round(f.size/1024,1)} KB)")
        st.divider()
        if st.button("🚀 Extract Data with AI", type="primary", disabled=not files):
            from extractor import DocumentExtractor
            extractor = DocumentExtractor(saved_key)
            prog = st.progress(0); status = st.empty()
            if mode == "Single employee":
                groups = {"Employee_1": [(uf.name, uf.read()) for uf in files]}
            else:
                groups = {}
                for uf in files:
                    if uf.name.lower().endswith(".zip"):
                        status.text(f"📦 Scanning {uf.name}...")
                        detected = detect_employees(uf.read())
                        if detected:
                            st.success(f"Found **{len(detected)} employee(s)**: {', '.join(list(detected.keys()))}")
                            for name, flist in detected.items():
                                groups.setdefault(name,[]).extend(flist)
                        else: st.error("No employee folders found!")
                    else:
                        groups.setdefault("Other",[]).append((uf.name, uf.read()))
            if not groups: st.error("No files!"); st.stop()
            existing_hashes = {e.get("file_hash","") for e in st.session_state.extracted_employees}
            existing_names = {e.get("group_name","") for e in st.session_state.extracted_employees}
            to_process = {}
            for k,v in groups.items():
                h = file_hash(v)
                if k in existing_names: st.warning(f"Skipping {k} — already extracted")
                elif h in existing_hashes: st.warning(f"Skipping {k} — duplicate")
                else: to_process[k] = (v, h)
            if not to_process: st.info("All already extracted!"); st.stop()
            st.info(f"Processing **{len(to_process)}** employee(s)...")
            new_emps = []; total = len(to_process)
            for idx, (grp, (gfiles, ghash)) in enumerate(to_process.items()):
                prog.progress(idx/total)
                status.text(f"🤖 AI reading: {grp} ({idx+1}/{total})...")
                hint = emp_hint if mode=="Single employee" else grp
                try:
                    result = extractor.process_employee_documents(gfiles, hint_name=hint, date_of_joining=doj_val)
                except Exception as e:
                    from extractor import EXPECTED_KEYS
                    result = {"fields":{k:"" for k in EXPECTED_KEYS},
                              "confidence_summary":{"total_extracted":0},"error":str(e),
                              "documents_detected":[],"field_confidence":{},"validation":{}}
                result["group_name"]=grp; result["file_hash"]=ghash
                result["processed_at"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                result["joining_date_override"]=doj_val
                new_emps.append(result)
                ex = result.get("confidence_summary",{}).get("total_extracted",0)
                logger.info(f"Extracted {grp}: {ex} fields")
                st.session_state.processing_log.append(
                    f"{datetime.now().strftime('%H:%M:%S')} — {grp}: {ex} fields")
                if idx < total-1: time.sleep(8)
            prog.progress(1.0)
            st.session_state.extracted_employees.extend(new_emps)
            status.text(f"✅ Done! {len(new_emps)} processed.")
            st.success(f"✅ **{len(new_emps)} employee records created!**")
            for emp in new_emps:
                f = emp.get("fields",{}); cs = emp.get("confidence_summary",{})
                name = f.get("employee_name") or emp["group_name"]
                filled = {k:v for k,v in f.items() if v}
                with st.expander(f"👤 {name} — {cs.get('total_extracted',0)} fields", expanded=True):
                    if filled: st.json(filled)
                    else: st.error(f"No data. {emp.get('error','')}")

# ══ TAB 2: JOINING DATES ══════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### Individual Joining Dates")
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        for i,emp in enumerate(st.session_state.extracted_employees):
            fields = emp.get("fields",{})
            name = fields.get("employee_name") or emp.get("group_name",f"Emp {i+1}")
            cur = emp.get("joining_date_override","") or fields.get("date_of_joining","")
            parsed = date.today()
            if cur:
                try:
                    from datetime import datetime as dt2
                    for fmt in ["%Y-%m-%d","%d/%m/%Y"]:
                        try: parsed=dt2.strptime(cur[:10],fmt).date(); break
                        except: pass
                except: pass
            c1,c2,c3 = st.columns([3,2,1])
            c1.markdown(f"**{name}**")
            with c2:
                nd = st.date_input("",value=parsed,key=f"doj_{i}",label_visibility="collapsed")
            with c3:
                from sheets_writer import fix_date
                ns = str(nd)
                if ns != emp.get("joining_date_override",""):
                    st.session_state.extracted_employees[i]["joining_date_override"] = ns
                    st.session_state.extracted_employees[i]["fields"]["date_of_joining"] = fix_date(ns)
                st.success("✅")

# ══ TAB 3: REVIEW ══════════════════════════════════════════════════════════
with tabs[2]:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown(f"### Review & Edit — {len(st.session_state.extracted_employees)} employees")
        names = [e.get("fields",{}).get("employee_name") or e.get("group_name",f"Emp {i+1}")
                 for i,e in enumerate(st.session_state.extracted_employees)]
        idx = st.selectbox("Select employee",range(len(names)),format_func=lambda i:names[i])
        emp = st.session_state.extracted_employees[idx]
        fields = emp.get("fields",{}); conf = emp.get("field_confidence",{})
        val = emp.get("validation",{}); docs = emp.get("documents_detected",[])
        if docs: st.markdown("**Detected:** " + " · ".join(f"`{d}`" for d in docs))
        if val:
            st.warning(f"⚠️ {len(val)} issue(s): " + "; ".join(f"{k}: {v}" for k,v in val.items()))
        SECS = {
            "👤 Personal":[("employee_name","Name (Aadhaar)"),("father_husband_name","Father/Husband"),
                ("gender","Gender"),("marital_status","Marital Status"),
                ("date_of_birth","Date of Birth"),("date_of_joining","Date of Joining"),
                ("aadhaar_number","Aadhaar Number"),("mobile_number","Mobile"),("pan_number","PAN")],
            "🏦 Bank":[("bank_name","Bank Name"),("bank_account_number","Account Number"),
                ("ifsc_code","IFSC Code"),("branch_name","Branch")],
            "💰 Salary & PF":[("pf_basic_wages","PF Wages"),("gross_salary","Gross"),
                ("pf_eligibility","PF/ESIC"),("uan_number","UAN"),("esic_number","ESIC")],
            "📍 Address":[("present_address","Present Address"),("permanent_address","Permanent Address")],
            "👨‍👩‍👧 Nominee":[("nominee_name","Nominee"),("nominee_relationship","Relationship"),
                ("nominee_dob","Nominee DOB"),("family_members","Family")],
            "🏥 ESIC":[("esic_dispensary","Dispensary"),("insurance_details","Insurance")],
        }
        updated = dict(fields)
        for sec,sfs in SECS.items():
            st.markdown(f"#### {sec}")
            c1,c2 = st.columns(2)
            for i,(fk,fl) in enumerate(sfs):
                with (c1 if i%2==0 else c2):
                    cl = conf.get(fk,"low"); ve = val.get(fk,"")
                    badge = {"high":"🟢","medium":"🟡","low":"⚪"}.get(cl,"⚪")
                    if ve: badge = "🔴"
                    updated[fk] = st.text_input(f"{badge} {fl}",
                        value=str(fields.get(fk,"") or ""), key=f"rv_{idx}_{fk}", help=ve or "")
        if st.button("💾 Save Changes", type="primary"):
            st.session_state.extracted_employees[idx]["fields"] = updated
            st.success("✅ Saved!")

# ══ TAB 4: APPROVE & EXPORT ════════════════════════════════════════════════
with tabs[3]:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown("### Approve & Export")
        ca,cm1,cm2,cm3 = st.columns(4)
        if ca.button("✅ Approve All", type="primary"):
            for emp in st.session_state.extracted_employees:
                name = emp.get("fields",{}).get("employee_name") or emp.get("group_name","")
                if not any(a.get("fields",{}).get("employee_name")==name
                           for a in st.session_state.approved_employees):
                    st.session_state.approved_employees.append(emp)
            st.success("All approved!"); st.rerun()
        cm1.metric("Total",len(st.session_state.extracted_employees))
        cm2.metric("Approved",len(st.session_state.approved_employees))
        cm3.metric("Pending",len(st.session_state.extracted_employees)-len(st.session_state.approved_employees))
        st.divider()
        for i,emp in enumerate(st.session_state.extracted_employees):
            f = emp.get("fields",{})
            name = f.get("employee_name") or emp.get("group_name",f"Emp {i+1}")
            approved = any(a.get("fields",{}).get("employee_name")==name
                           for a in st.session_state.approved_employees)
            with st.expander(f"{'✅' if approved else '⏳'} {name}"):
                c1,c2,c3,c4 = st.columns(4)
                c1.markdown(f"**DOJ:** {f.get('date_of_joining','-')}")
                c2.markdown(f"**Aadhaar:** {f.get('aadhaar_number','-')}")
                c3.markdown(f"**PAN:** {f.get('pan_number','-')}")
                c4.markdown(f"**Bank:** {f.get('bank_account_number','-')}")
                if not approved:
                    if st.button("✅ Approve",key=f"ap_{i}"):
                        st.session_state.approved_employees.append(emp); st.rerun()
                else: st.success("Approved ✅")
        st.divider()
        st.markdown(f"### Export — {len(st.session_state.approved_employees)} approved")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("#### 📊 Push to Google Sheet")
            url = cfg.get("script_url","")
            if not url: st.warning("Set Apps Script URL in Settings.")
            elif not st.session_state.approved_employees: st.info("Approve employees first.")
            else:
                if st.button(f"📊 Push {len(st.session_state.approved_employees)} records", type="primary"):
                    from sheets_writer import SheetsWriter
                    try:
                        with st.spinner("Writing all 31 columns..."):
                            w = SheetsWriter(url)
                            n = w.write_employees(st.session_state.approved_employees)
                        st.success(f"✅ {n} records written!")
                    except Exception as e: st.error(f"Error: {e}")
        with col_b:
            st.markdown("#### ⬇️ Download CSV")
            if st.session_state.approved_employees:
                from sheets_writer import employees_to_csv
                st.download_button(
                    f"⬇️ Download CSV ({len(st.session_state.approved_employees)})",
                    data=employees_to_csv(st.session_state.approved_employees),
                    file_name=f"epf_esic_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv")

# ══ TAB 5: VALIDATION ══════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### Validation Report")
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        for emp in st.session_state.extracted_employees:
            f = emp.get("fields",{})
            name = f.get("employee_name") or emp.get("group_name","Unknown")
            val = emp.get("validation",{}); cs = emp.get("confidence_summary",{})
            with st.expander(f"👤 {name} — {cs.get('total_extracted',0)} fields | {len(val)} issues"):
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Fields", cs.get("total_extracted",0))
                c2.metric("High", cs.get("high",0))
                c3.metric("Medium", cs.get("medium",0))
                c4.metric("Issues", len(val))
                if val:
                    for field, issue in val.items():
                        st.markdown(f"🔴 **{field}**: {issue}")

# ══ TAB 6: LOGS ════════════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### Processing Logs")
    if st.session_state.processing_log:
        st.code("\n".join(st.session_state.processing_log))
    lf = Path("logs/automation.log")
    if lf.exists() and lf.stat().st_size > 0:
        with open(lf,encoding="utf-8",errors="ignore") as f:
            lines = f.readlines()
        st.code("".join(lines[-100:]))
    else: st.info("Log appears after processing.")
    if st.button("🗑️ Clear Logs"):
        open(lf,"w").close(); st.session_state.processing_log = []
        st.success("Cleared.")

# ══ TAB 7: SETTINGS ════════════════════════════════════════════════════════
with tabs[6]:
    st.markdown("### ⚙️ Configuration")
    st.caption("Set up your API key and Google Sheet connection. These are stored securely and not shown on the dashboard.")
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🔑 Groq AI Engine")
        st.caption("Powers document extraction. Get a free key at console.groq.com")
        groq_key = st.text_input("Groq API key", type="password",
                                  value=cfg.get("groq_key",""), placeholder="gsk_...")
        if groq_key != cfg.get("groq_key",""):
            cfg["groq_key"] = groq_key; save_config(cfg)
            st.rerun()
        if cfg.get("groq_key"):
            st.success("✅ AI engine connected")
        else:
            st.warning("⚠️ Not configured")
        st.markdown("[Get free Groq key →](https://console.groq.com)")

    with col2:
        st.markdown("#### 📊 Google Sheet")
        st.caption("Where employee data is written. Paste your Apps Script web app URL.")
        script_url = st.text_input("Apps Script URL",
                                    value=cfg.get("script_url",""),
                                    placeholder="https://script.google.com/macros/s/.../exec")
        if script_url != cfg.get("script_url",""):
            cfg["script_url"] = script_url; save_config(cfg)
            st.rerun()
        if cfg.get("script_url"):
            st.success("✅ Google Sheet connected")
        else:
            st.warning("⚠️ Not configured")

    st.divider()
    with st.expander("📖 How to set up Google Sheet integration"):
        st.markdown("""
1. Open your Google Sheet → **Extensions → Apps Script**
2. Delete all code and paste the cell-by-cell write script
3. **Save → Deploy → New deployment → Web app**
4. Set **Execute as: Me**, **Access: Anyone**
5. Copy the web app URL and paste it above
        """)
        st.code("""function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var rows = JSON.parse(e.postData.contents).rows;
  var nextRow = Math.max(sheet.getLastRow()+1, 5);
  for (var r=0;r<rows.length;r++){
    for (var c=0;c<rows[r].length;c++){
      sheet.getRange(nextRow+r, c+1).setValue(String(rows[r][c]||""));
    }
  }
  return ContentService.createTextOutput(
    JSON.stringify({status:"ok",written:rows.length}))
    .setMimeType(ContentService.MimeType.JSON);
}""", language="javascript")
