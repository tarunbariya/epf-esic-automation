"""EPF/ESIC Registration Automation - Production Ready v3"""
import streamlit as st
import json, time, zipfile, io, hashlib
from datetime import datetime, date
from pathlib import Path

Path("logs").mkdir(exist_ok=True)
import logging
logging.basicConfig(
    filename="logs/automation.log", level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("app")

st.set_page_config(page_title="EPF & ESIC Automation", page_icon="📋",
                   layout="wide", initial_sidebar_state="expanded")

# ── Config ───────────────────────────────────────────────────────────────────
def load_config():
    cfg = {}
    try:
        if Path("config.json").exists():
            cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    except: pass
    try:
        if "groq_key" in st.secrets: cfg["groq_key"] = st.secrets["groq_key"]
        if "script_url" in st.secrets: cfg["script_url"] = st.secrets["script_url"]
    except: pass
    return cfg

def save_config(cfg):
    try: Path("config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except: pass

cfg = load_config()

for k, v in {"extracted_employees":[], "approved_employees":[], "processing_log":[]}.items():
    if k not in st.session_state: st.session_state[k] = v

# ── ZIP Detection ─────────────────────────────────────────────────────────────
def detect_employees(zip_bytes):
    """Detect employee folders from any ZIP structure."""
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

    # Find parent with multiple children = employee level
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
                if emp_files:
                    employee_folders[emp_name] = emp_files
            break

    if not employee_folders:
        for fk, files in folder_files.items():
            employee_folders.setdefault(fk.split("/")[0],[]).extend(files)

    logger.info(f"ZIP detected {len(employee_folders)} employees: {list(employee_folders.keys())}")
    return employee_folders

def file_hash(files):
    h = hashlib.md5()
    for fn, fd in files:
        h.update(fn.encode())
        h.update(fd[:100])
    return h.hexdigest()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    st.caption("Settings auto-saved")

    if cfg.get("groq_key") or cfg.get("script_url"):
        st.success("✅ Settings loaded automatically")

    st.markdown("### 🔑 Groq API Key")
    st.markdown("[Get free key →](https://console.groq.com)")
    groq_key = st.text_input("Groq API key", type="password",
                              value=cfg.get("groq_key",""), placeholder="gsk_...")
    if groq_key != cfg.get("groq_key",""):
        cfg["groq_key"] = groq_key; save_config(cfg)
    if cfg.get("groq_key"): st.success("✅ Key ready")

    st.divider()
    st.markdown("### 📊 Google Sheets")
    script_url = st.text_input("Apps Script URL",
                                value=cfg.get("script_url",""),
                                placeholder="https://script.google.com/macros/s/.../exec")
    if script_url != cfg.get("script_url",""):
        cfg["script_url"] = script_url; save_config(cfg)
    if cfg.get("script_url"): st.success("✅ Sheet URL ready")

    with st.expander("📖 Setup Google Sheet"):
        st.code("""function doPost(e) {
  try {
    var sheet = SpreadsheetApp
      .getActiveSpreadsheet()
      .getActiveSheet();
    var data = JSON.parse(e.postData.contents);
    var rows = data.rows;
    var nextRow = Math.max(
      sheet.getLastRow()+1, 5);
    for (var r=0;r<rows.length;r++) {
      for (var c=0;c<rows[r].length;c++) {
        sheet.getRange(nextRow,c+1)
          .setValue(rows[r][c]||"");
      }
      nextRow++;
    }
    return ContentService
      .createTextOutput(
        JSON.stringify({status:"ok",
          written:rows.length}))
      .setMimeType(
        ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService
      .createTextOutput(
        JSON.stringify({status:"error",
          message:err.toString()}))
      .setMimeType(
        ContentService.MimeType.JSON);
  }
}""", language="javascript")
        st.caption("Save → Deploy → New version → Web app → Execute as Me → Access Anyone → Copy URL")

    st.divider()
    c1,c2 = st.columns(2)
    c1.metric("Extracted", len(st.session_state.extracted_employees))
    c2.metric("Approved", len(st.session_state.approved_employees))

    if st.button("🗑️ Clear all data"):
        st.session_state.extracted_employees = []
        st.session_state.approved_employees = []
        st.session_state.processing_log = []
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""<div style="background:#1a237e;color:white;padding:16px 26px;
border-radius:10px;margin-bottom:16px">
<h1 style="margin:0;font-size:22px">📋 EPF & ESIC Registration Automation</h1>
<p style="margin:3px 0 0;opacity:0.85;font-size:12px">
Production Ready v3 | PDF/JPG/PNG/Screenshots | Bulk ZIP | All 31 columns | Validation</p>
</div>""", unsafe_allow_html=True)

tabs = st.tabs(["📤 Upload","📅 Joining Dates","🔍 Review","✅ Approve & Export","📊 Validation","📜 Logs"])

# ══ TAB 1: UPLOAD ════════════════════════════════════════════════════════════
with tabs[0]:
    st.markdown("### Upload Employee Documents")
    saved_key = cfg.get("groq_key","")
    if not saved_key:
        st.warning("⚠️ Enter Groq API key in sidebar first!")
        st.stop()

    mode = st.radio("Mode", ["Single employee","Batch ZIP (multiple employees)"], horizontal=True)
    files = st.file_uploader("Drop files",
        type=["pdf","jpg","jpeg","png","webp","zip","bmp","docx","heic","tiff"],
        accept_multiple_files=True)

    if mode == "Single employee":
        emp_hint = st.text_input("Employee name hint", placeholder="e.g. Krupal Patel")
        doj_val = str(st.date_input("Date of Joining"))
    else:
        emp_hint, doj_val = "", ""
        st.info("""
**ZIP structure (any name):**
```
anyfile.zip
└── employees/          ← optional wrapper
    ├── Krupal Patel/   ← Employee 1
    │   ├── aadhaar.pdf
    │   └── pan.jpg
    └── Saloni Master/  ← Employee 2
        ├── aadhaar.jpg
        └── cheque.pdf
```
Supports: PDF, JPG, PNG, Screenshots, Photos, DOCX
        """)

    if files:
        for f in files:
            st.caption(f"{'📦' if 'zip' in f.type else '📄' if 'pdf' in f.type else '🖼️'} {f.name} ({round(f.size/1024,1)} KB)")

    st.divider()
    if st.button("🚀 Extract Data with AI", type="primary", disabled=not files):
        from extractor import DocumentExtractor
        extractor = DocumentExtractor(saved_key)
        prog = st.progress(0)
        status = st.empty()

        # Build groups
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
                    else:
                        st.error("No employee folders found in ZIP!")
                else:
                    groups.setdefault("Other",[]).append((uf.name, uf.read()))

        if not groups:
            st.error("No files to process!"); st.stop()

        # Skip duplicates by hash
        existing_hashes = {e.get("file_hash","") for e in st.session_state.extracted_employees}
        existing_names = {e.get("group_name","") for e in st.session_state.extracted_employees}
        to_process = {}
        for k,v in groups.items():
            h = file_hash(v)
            if k in existing_names:
                st.warning(f"Skipping {k} — already extracted")
            elif h in existing_hashes:
                st.warning(f"Skipping {k} — duplicate files")
            else:
                to_process[k] = (v, h)

        if not to_process:
            st.info("All employees already extracted!"); st.stop()

        st.info(f"Processing **{len(to_process)}** employee(s)...")
        new_emps = []
        total = len(to_process)

        for idx, (grp, (gfiles, ghash)) in enumerate(to_process.items()):
            prog.progress(idx/total)
            status.text(f"🤖 AI reading: **{grp}** ({idx+1}/{total}) — {len(gfiles)} files...")
            hint = emp_hint if mode=="Single employee" else grp
            try:
                result = extractor.process_employee_documents(
                    gfiles, hint_name=hint, date_of_joining=doj_val)
            except Exception as e:
                result = {"fields":{k:"" for k in["employee_name","father_husband_name","gender",
                    "marital_status","date_of_birth","date_of_joining","aadhaar_number",
                    "mobile_number","pan_number","present_address","permanent_address","bank_name",
                    "bank_account_number","ifsc_code","branch_name","uan_number","esic_number",
                    "pf_basic_wages","gross_salary","pf_eligibility","nominee_name",
                    "nominee_relationship","nominee_dob","family_members","esic_dispensary",
                    "insurance_details"]},
                    "confidence_summary":{"total_extracted":0},"error":str(e),
                    "documents_detected":[],"field_confidence":{},"validation":{}}

            result["group_name"] = grp
            result["file_hash"] = ghash
            result["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result["joining_date_override"] = doj_val
            new_emps.append(result)

            f = result.get("fields",{})
            ex = result.get("confidence_summary",{}).get("total_extracted",0)
            name = f.get("employee_name") or grp
            log_msg = f"Extracted: {grp} | {ex} fields | {result.get('documents_detected',[])} | {len(gfiles)} files"
            logger.info(log_msg)
            st.session_state.processing_log.append(f"{datetime.now().strftime('%H:%M:%S')} — {log_msg}")

            if idx < total-1:
                time.sleep(8)  # Rate limit protection

        prog.progress(1.0)
        st.session_state.extracted_employees.extend(new_emps)
        status.text(f"✅ Done! {len(new_emps)} employees processed.")
        st.success(f"✅ **{len(new_emps)} employee records created!** Go to Review tab to verify data.")

        for emp in new_emps:
            f = emp.get("fields",{})
            cs = emp.get("confidence_summary",{})
            name = f.get("employee_name") or emp["group_name"]
            filled = {k:v for k,v in f.items() if v}
            with st.expander(f"👤 **{name}** — {cs.get('total_extracted',0)} fields extracted", expanded=True):
                if filled:
                    st.json(filled)
                else:
                    st.error(f"No data. Error: {emp.get('error','Unknown')}")

# ══ TAB 2: JOINING DATES ══════════════════════════════════════════════════════
with tabs[1]:
    st.markdown("### Individual Joining Dates")
    if not st.session_state.extracted_employees:
        st.info("No employees yet. Upload in Tab 1.")
    else:
        st.caption("Set a unique joining date for each employee")
        c1,c2,c3 = st.columns([3,2,1])
        c1.markdown("**Employee**"); c2.markdown("**Date of Joining**"); c3.markdown("**Status**")
        st.divider()
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

# ══ TAB 3: REVIEW ════════════════════════════════════════════════════════════
with tabs[2]:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown(f"### Review & Edit — {len(st.session_state.extracted_employees)} employees")
        names = [e.get("fields",{}).get("employee_name") or e.get("group_name",f"Emp {i+1}")
                 for i,e in enumerate(st.session_state.extracted_employees)]
        idx = st.selectbox("Select employee",range(len(names)),format_func=lambda i:names[i])
        emp = st.session_state.extracted_employees[idx]
        fields = emp.get("fields",{})
        conf = emp.get("field_confidence",{})
        val = emp.get("validation",{})
        docs = emp.get("documents_detected",[])

        if docs: st.markdown("**Detected:** " + " · ".join(f"`{d}`" for d in docs))
        if val:
            st.warning(f"⚠️ {len(val)} validation issue(s): " + "; ".join(f"{k}: {v}" for k,v in val.items()))

        SECS = {
            "👤 Personal":[
                ("employee_name","Employee Name (Aadhaar)"),
                ("father_husband_name","Father/Husband Name"),
                ("gender","Gender"),("marital_status","Marital Status"),
                ("date_of_birth","Date of Birth (DD/MM/YYYY)"),
                ("date_of_joining","Date of Joining"),
                ("aadhaar_number","Aadhaar Number"),
                ("mobile_number","Mobile Number"),("pan_number","PAN Number")],
            "🏦 Bank":[
                ("bank_name","Bank Name"),("bank_account_number","Account Number"),
                ("ifsc_code","IFSC Code"),("branch_name","Branch Name")],
            "💰 Salary & PF":[
                ("pf_basic_wages","PF Wages"),("gross_salary","Gross Salary"),
                ("pf_eligibility","PF/ESIC"),("uan_number","UAN"),("esic_number","ESIC")],
            "📍 Address":[
                ("present_address","Present Address"),
                ("permanent_address","Permanent Address")],
            "👨‍👩‍👧 Nominee":[
                ("nominee_name","Nominee Name"),("nominee_relationship","Relationship"),
                ("nominee_dob","Nominee DOB"),("family_members","Family Members")],
            "🏥 ESIC":[
                ("esic_dispensary","ESIC Dispensary"),("insurance_details","Insurance")],
        }
        updated = dict(fields)
        for sec,sfs in SECS.items():
            st.markdown(f"#### {sec}")
            c1,c2 = st.columns(2)
            for i,(fk,fl) in enumerate(sfs):
                with (c1 if i%2==0 else c2):
                    cl = conf.get(fk,"low")
                    ve = val.get(fk,"")
                    badge = {"high":"🟢","medium":"🟡","low":"⚪"}.get(cl,"⚪")
                    if ve: badge = "🔴"
                    updated[fk] = st.text_input(
                        f"{badge} {fl}",
                        value=str(fields.get(fk,"") or ""),
                        key=f"rv_{idx}_{fk}",
                        help=ve or "")
        if st.button("💾 Save Changes"):
            st.session_state.extracted_employees[idx]["fields"] = updated
            logger.info(f"HR edited: {updated.get('employee_name','')} — {idx}")
            st.success("✅ Saved!")

# ══ TAB 4: APPROVE & EXPORT ══════════════════════════════════════════════════
with tabs[3]:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown("### Approve & Export")
        ca,cm1,cm2,cm3 = st.columns(4)
        if ca.button("✅ Approve All"):
            for emp in st.session_state.extracted_employees:
                name = emp.get("fields",{}).get("employee_name") or emp.get("group_name","")
                if not any(a.get("fields",{}).get("employee_name")==name
                           for a in st.session_state.approved_employees):
                    st.session_state.approved_employees.append(emp)
            st.success(f"All {len(st.session_state.extracted_employees)} approved!")
            st.rerun()
        cm1.metric("Total",len(st.session_state.extracted_employees))
        cm2.metric("Approved",len(st.session_state.approved_employees))
        cm3.metric("Pending",len(st.session_state.extracted_employees)-len(st.session_state.approved_employees))

        st.divider()
        for i,emp in enumerate(st.session_state.extracted_employees):
            f = emp.get("fields",{})
            name = f.get("employee_name") or emp.get("group_name",f"Emp {i+1}")
            approved = any(a.get("fields",{}).get("employee_name")==name
                           for a in st.session_state.approved_employees)
            val_issues = emp.get("validation",{})
            with st.expander(f"{'✅' if approved else '⏳'} {name}" +
                             (f" ⚠️{len(val_issues)} issues" if val_issues else "")):
                c1,c2,c3,c4 = st.columns(4)
                c1.markdown(f"**DOJ:** {f.get('date_of_joining','-')}")
                c2.markdown(f"**Aadhaar:** {f.get('aadhaar_number','-')}")
                c3.markdown(f"**PAN:** {f.get('pan_number','-')}")
                c4.markdown(f"**Bank:** {f.get('bank_account_number','-')}")
                if not approved:
                    if st.button("✅ Approve",key=f"ap_{i}"):
                        st.session_state.approved_employees.append(emp)
                        logger.info(f"Approved: {name}")
                        st.rerun()
                else:
                    st.success("Approved ✅")

        st.divider()
        st.markdown(f"### Export — **{len(st.session_state.approved_employees)} approved**")
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### 📊 Push to Google Sheet")
            url = cfg.get("script_url","")
            if not url:
                st.warning("Enter Apps Script URL in sidebar.")
            elif not st.session_state.approved_employees:
                st.info("Approve employees first.")
            else:
                st.caption(f"Will write {len(st.session_state.approved_employees)} rows × 31 columns")
                if st.button(f"📊 Push {len(st.session_state.approved_employees)} records"):
                    from sheets_writer import SheetsWriter, build_row, COLUMNS
                    try:
                        with st.spinner("Writing all 31 columns to Google Sheet..."):
                            w = SheetsWriter(url)
                            n = w.write_employees(st.session_state.approved_employees)
                        st.success(f"✅ {n} records written with all 31 columns!")
                        logger.info(f"Pushed {n} records to Google Sheet")
                        st.session_state.processing_log.append(
                            f"{datetime.now().strftime('%H:%M:%S')} — Pushed {n} records to sheet")
                    except Exception as e:
                        st.error(f"Error: {e}")
                        logger.error(f"Sheet push failed: {e}")

        with col_b:
            st.markdown("#### ⬇️ Download CSV")
            if st.session_state.approved_employees:
                from sheets_writer import employees_to_csv
                csv_data = employees_to_csv(st.session_state.approved_employees)
                st.download_button(
                    f"⬇️ Download CSV ({len(st.session_state.approved_employees)} employees)",
                    data=csv_data,
                    file_name=f"epf_esic_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv")
                st.caption("One row per employee · All 31 columns · Same data as Google Sheet")

# ══ TAB 5: VALIDATION ════════════════════════════════════════════════════════
with tabs[4]:
    st.markdown("### Data Validation Report")
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        for emp in st.session_state.extracted_employees:
            f = emp.get("fields",{})
            name = f.get("employee_name") or emp.get("group_name","Unknown")
            val = emp.get("validation",{})
            conf = emp.get("field_confidence",{})
            cs = emp.get("confidence_summary",{})

            with st.expander(f"👤 {name} — {cs.get('total_extracted',0)} fields | {len(val)} issues"):
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Total Fields", cs.get("total_extracted",0))
                c2.metric("High Confidence", cs.get("high",0))
                c3.metric("Medium", cs.get("medium",0))
                c4.metric("Issues", len(val))

                if val:
                    st.error("**Validation Issues:**")
                    for field, issue in val.items():
                        st.markdown(f"- 🔴 **{field}**: {issue}")

                # Show confidence for each field
                st.markdown("**Field Confidence:**")
                cols = st.columns(3)
                items = [(k, f.get(k,""), conf.get(k,"low")) for k in
                         ["employee_name","aadhaar_number","pan_number","mobile_number",
                          "bank_account_number","ifsc_code","date_of_birth","date_of_joining"]]
                for j,(k,v,c) in enumerate(items):
                    icon = {"high":"🟢","medium":"🟡","low":"⚪","missing":"⬜"}.get(c,"⬜")
                    cols[j%3].markdown(f"{icon} **{k}**  \n`{v or 'MISSING'}`")

# ══ TAB 6: LOGS ══════════════════════════════════════════════════════════════
with tabs[5]:
    st.markdown("### Processing Logs")
    # In-memory log
    if st.session_state.processing_log:
        st.markdown("**Session Log:**")
        st.code("\n".join(st.session_state.processing_log))
    # File log
    lf = Path("logs/automation.log")
    if lf.exists() and lf.stat().st_size > 0:
        st.markdown("**Full Log:**")
        with open(lf,encoding="utf-8",errors="ignore") as f:
            lines = f.readlines()
        st.code("".join(lines[-150:]))
        st.caption(f"Last {min(150,len(lines))} of {len(lines)} entries")
    else:
        st.info("Log appears after processing.")
    if st.button("🗑️ Clear Logs"):
        open(lf,"w").close()
        st.session_state.processing_log = []
        st.success("Cleared.")
