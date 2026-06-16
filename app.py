import streamlit as st
import json, os, time, zipfile, io
from datetime import datetime, date
from pathlib import Path

Path("logs").mkdir(exist_ok=True)
import logging
logging.basicConfig(filename="logs/automation.log", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

st.set_page_config(page_title="EPF & ESIC Automation", page_icon="📋",
                   layout="wide", initial_sidebar_state="expanded")

CONFIG_FILE = "config.json"

def load_config():
    """Load config from file, then override with Streamlit secrets if available."""
    cfg = {}
    # Load from local file
    try:
        if Path(CONFIG_FILE).exists():
            cfg = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
    except: pass
    # Override with Streamlit Cloud secrets if available
    try:
        if "groq_key" in st.secrets:
            cfg["groq_key"] = st.secrets["groq_key"]
        if "script_url" in st.secrets:
            cfg["script_url"] = st.secrets["script_url"]
    except: pass
    return cfg

def save_config(cfg):
    try:
        Path(CONFIG_FILE).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except: pass

cfg = load_config()

for k, v in {"extracted_employees": [], "approved_employees": []}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def detect_employees(zip_bytes):
    """Detect all employee folders from ZIP regardless of wrapper folders."""
    SUPPORTED = {".pdf",".jpg",".jpeg",".png",".webp"}
    folder_files = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for entry in zf.namelist():
            clean = entry.replace("\\", "/")
            parts = [p.strip() for p in clean.split("/") if p.strip()]
            if not parts: continue
            ext = Path(parts[-1]).suffix.lower()
            if ext not in SUPPORTED: continue
            folder_key = "/".join(parts[:-1]) if len(parts) > 1 else "__root__"
            folder_files.setdefault(folder_key, []).append((parts[-1], zf.read(entry)))
    if not folder_files: return {}
    all_folders = [k for k in folder_files if k != "__root__"]
    if not all_folders:
        return {"Documents": folder_files.get("__root__", [])}
    parent_children = {}
    for fk in all_folders:
        parts = fk.split("/")
        for depth in range(len(parts)):
            parent = "/".join(parts[:depth]) if depth > 0 else "__top__"
            parent_children.setdefault(parent, set()).add("/".join(parts[:depth+1]))
    employee_folders = {}
    for parent, children in parent_children.items():
        if len(children) >= 2:
            for child_path in sorted(children):
                emp_name = child_path.split("/")[-1]
                emp_files = []
                for fk, files in folder_files.items():
                    if fk == child_path or fk.startswith(child_path + "/"):
                        emp_files.extend(files)
                if emp_files:
                    employee_folders[emp_name] = emp_files
            break
    if not employee_folders:
        for fk, files in folder_files.items():
            employee_folders.setdefault(fk.split("/")[0], []).extend(files)
    return employee_folders

# ── Sidebar ──
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    
    # Check if secrets are loaded from Streamlit Cloud
    secrets_loaded = bool(cfg.get("groq_key")) or bool(cfg.get("script_url"))
    if secrets_loaded:
        st.success("✅ Settings loaded from cloud secrets")

    st.markdown("### 🔑 Groq API Key")
    st.markdown("[Get free key →](https://console.groq.com)")
    groq_key = st.text_input("Groq API key (gsk_...)", type="password",
                              value=cfg.get("groq_key",""), placeholder="gsk_...",
                              key="groq_input")
    if groq_key != cfg.get("groq_key",""):
        cfg["groq_key"] = groq_key
        save_config(cfg)
    if cfg.get("groq_key"):
        st.success("✅ Key ready")

    st.divider()
    st.markdown("### 📊 Google Sheets")
    script_url = st.text_input("Apps Script Web App URL",
                                value=cfg.get("script_url",""),
                                placeholder="https://script.google.com/macros/s/.../exec",
                                key="script_input")
    if script_url != cfg.get("script_url",""):
        cfg["script_url"] = script_url
        save_config(cfg)
    if cfg.get("script_url"):
        st.success("✅ Sheet URL ready")

    with st.expander("📖 Setup Google Sheet"):
        st.markdown("""
1. Open your Google Sheet
2. Extensions > Apps Script
3. Delete all code, paste:

```javascript
function doPost(e) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    var data = JSON.parse(e.postData.contents);
    var rows = data.rows;
    var lastRow = sheet.getLastRow();
    var nextRow = Math.max(lastRow + 1, 5);
    for (var r = 0; r < rows.length; r++) {
      var row = rows[r];
      for (var c = 0; c < row.length; c++) {
        sheet.getRange(nextRow, c + 1).setValue(row[c] || "");
      }
      nextRow++;
    }
    return ContentService.createTextOutput(
      JSON.stringify({status:"ok",written:rows.length}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService.createTextOutput(
      JSON.stringify({status:"error",message:err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
```

4. Save > Deploy > New deployment
5. Web app, Execute=Me, Access=Anyone
6. Deploy > Copy URL > paste above
        """)

    st.divider()
    st.metric("Extracted", len(st.session_state.extracted_employees))
    st.metric("Approved", len(st.session_state.approved_employees))
    if st.button("🗑️ Clear all data"):
        st.session_state.extracted_employees = []
        st.session_state.approved_employees = []
        st.rerun()

# ── Header ──
st.markdown("""<div style="background:#1a237e;color:white;padding:18px 28px;
border-radius:10px;margin-bottom:18px">
<h1 style="margin:0;font-size:24px">📋 EPF & ESIC Registration Automation</h1>
<p style="margin:4px 0 0;opacity:0.85;font-size:13px">
Bulk ZIP | All 31 columns | Multiple employees | Google Sheets</p>
</div>""", unsafe_allow_html=True)

tab1,tab2,tab3,tab4,tab5 = st.tabs([
    "📤 Upload & Extract","📅 Joining Dates","🔍 Review & Edit","✅ Approve & Export","📜 Log"])

with tab1:
    st.markdown("### Upload Employee Documents")
    saved_key = cfg.get("groq_key","")
    if not saved_key:
        st.warning("⚠️ Enter Groq API key in sidebar first!")

    mode = st.radio("Mode", ["Single employee","Batch ZIP (multiple employees)"], horizontal=True)
    files = st.file_uploader("Drop files here",
        type=["pdf","jpg","jpeg","png","zip"], accept_multiple_files=True)

    if mode == "Single employee":
        emp_hint = st.text_input("Employee name hint", placeholder="e.g. Krupal Patel")
        doj_val = str(st.date_input("Date of Joining"))
    else:
        emp_hint = ""
        doj_val = ""
        st.info("""
**ZIP structure — any ZIP name works:**
```
anyname.zip
└── employees/         (optional wrapper)
    ├── Krupal Patel/  <- Employee 1
    └── Saloni Master/ <- Employee 2
```
        """)

    if files:
        for f in files:
            tp = "ZIP" if "zip" in f.type else "PDF" if "pdf" in f.type else "IMG"
            st.caption(f"[{tp}] {f.name} ({round(f.size/1024,1)} KB)")

    st.divider()
    if st.button("🚀 Extract Data with AI", type="primary",
                  disabled=not files or not saved_key):
        from extractor import DocumentExtractor
        extractor = DocumentExtractor(saved_key)
        prog = st.progress(0)
        status = st.empty()

        if mode == "Single employee":
            groups = {"Employee_1": [(uf.name, uf.read()) for uf in files]}
        else:
            groups = {}
            for uf in files:
                if uf.name.lower().endswith(".zip"):
                    status.text(f"Scanning {uf.name}...")
                    detected = detect_employees(uf.read())
                    st.success(f"Found {len(detected)} employee(s): {', '.join(list(detected.keys()))}")
                    for name, flist in detected.items():
                        groups.setdefault(name, []).extend(flist)
                else:
                    groups.setdefault("Other", []).append((uf.name, uf.read()))

        if not groups:
            st.error("No employees found!"); st.stop()

        existing = {e.get("group_name","") for e in st.session_state.extracted_employees}
        to_process = {k:v for k,v in groups.items() if k not in existing}
        if not to_process:
            st.info("All already extracted!"); st.stop()

        new_emps = []
        total = len(to_process)
        for idx,(grp,gfiles) in enumerate(to_process.items()):
            prog.progress(idx/total)
            status.text(f"AI reading: {grp} ({idx+1}/{total}) — {len(gfiles)} files...")
            hint = emp_hint if mode=="Single employee" else grp
            result = extractor.process_employee_documents(gfiles, hint_name=hint, date_of_joining=doj_val)
            result["group_name"] = grp
            result["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result["joining_date_override"] = doj_val
            new_emps.append(result)
            logging.info(f"Extracted: {grp} | {result['confidence_summary'].get('total_extracted',0)} fields")
            if idx < total-1: time.sleep(1)

        prog.progress(1.0)
        st.session_state.extracted_employees.extend(new_emps)
        status.text(f"Done! {len(new_emps)} employees processed.")
        st.success(f"✅ {len(new_emps)} employee records created!")

        for emp in new_emps:
            f = emp.get("fields",{})
            cs = emp.get("confidence_summary",{})
            name = f.get("employee_name") or emp["group_name"]
            with st.expander(f"👤 {name} — {cs.get('total_extracted',0)} fields", expanded=True):
                filled = {k:v for k,v in f.items() if v}
                if filled: st.json(filled)
                else: st.error(emp.get("error","No data extracted"))

with tab2:
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
                        try: parsed = dt2.strptime(cur[:10],fmt).date(); break
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

with tab3:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown(f"### Review & Edit — {len(st.session_state.extracted_employees)} employees")
        names = [e.get("fields",{}).get("employee_name") or e.get("group_name",f"Emp {i+1}")
                 for i,e in enumerate(st.session_state.extracted_employees)]
        idx = st.selectbox("Select",range(len(names)),format_func=lambda i:names[i])
        emp = st.session_state.extracted_employees[idx]
        fields = emp.get("fields",{})
        conf = emp.get("field_confidence",{})
        SECS = {
            "👤 Personal":[("employee_name","Name"),("father_husband_name","Father/Husband"),
                ("gender","Gender"),("marital_status","Marital"),
                ("date_of_birth","DOB"),("date_of_joining","DOJ"),
                ("aadhaar_number","Aadhaar"),("mobile_number","Mobile"),("pan_number","PAN")],
            "🏦 Bank":[("bank_name","Bank"),("bank_account_number","Account"),
                ("ifsc_code","IFSC"),("branch_name","Branch")],
            "💰 Salary":[("pf_basic_wages","PF Wages"),("gross_salary","Gross"),
                ("pf_eligibility","PF/ESIC"),("uan_number","UAN"),("esic_number","ESIC")],
            "📍 Address":[("present_address","Present"),("permanent_address","Permanent")],
            "👨‍👩‍👧 Nominee":[("nominee_name","Nominee"),("nominee_relationship","Relation"),
                ("nominee_dob","DOB"),("family_members","Family")],
        }
        updated = dict(fields)
        for sec,sfs in SECS.items():
            st.markdown(f"#### {sec}")
            c1,c2 = st.columns(2)
            for i,(fk,fl) in enumerate(sfs):
                with (c1 if i%2==0 else c2):
                    cl = conf.get(fk,"low")
                    badge = {"high":"✅","medium":"🟡"}.get(cl,"⬜")
                    updated[fk] = st.text_input(f"{badge} {fl}",
                        value=str(fields.get(fk,"") or ""),key=f"ed_{idx}_{fk}")
        if st.button("💾 Save"):
            st.session_state.extracted_employees[idx]["fields"] = updated
            st.success("Saved!")

with tab4:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown("### Approve & Export")
        c1,c2,c3 = st.columns(3)
        if c1.button("✅ Approve All"):
            for emp in st.session_state.extracted_employees:
                name = emp.get("fields",{}).get("employee_name") or emp.get("group_name","")
                if not any(a.get("fields",{}).get("employee_name")==name
                           for a in st.session_state.approved_employees):
                    st.session_state.approved_employees.append(emp)
            st.success(f"All {len(st.session_state.extracted_employees)} approved!")
            st.rerun()
        c2.metric("Total",len(st.session_state.extracted_employees))
        c3.metric("Approved",len(st.session_state.approved_employees))
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
        ca,cb = st.columns(2)
        with ca:
            st.markdown("#### 📊 Push to Google Sheet")
            url = cfg.get("script_url","")
            if not url: st.warning("Enter Apps Script URL in sidebar.")
            elif not st.session_state.approved_employees: st.info("Approve employees first.")
            else:
                if st.button(f"📊 Push {len(st.session_state.approved_employees)} records"):
                    from sheets_writer import SheetsWriter
                    try:
                        with st.spinner("Writing to Google Sheet..."):
                            w = SheetsWriter(url)
                            n = w.write_employees(st.session_state.approved_employees)
                        st.success(f"✅ {n} records written with all columns!")
                    except Exception as e: st.error(str(e))
        with cb:
            st.markdown("#### ⬇️ Download CSV")
            if st.session_state.approved_employees:
                from sheets_writer import employees_to_csv
                st.download_button(
                    f"⬇️ Download CSV ({len(st.session_state.approved_employees)} employees)",
                    data=employees_to_csv(st.session_state.approved_employees),
                    file_name=f"epf_esic_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv")

with tab5:
    lf = Path("logs/automation.log")
    if lf.exists() and lf.stat().st_size>0:
        with open(lf,encoding="utf-8",errors="ignore") as f: lines=f.readlines()
        st.code("".join(lines[-100:]))
    else: st.info("Log appears after processing.")
    if st.button("🗑️ Clear"): open(lf,"w").close(); st.success("Cleared.")
