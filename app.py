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
    try:
        if Path(CONFIG_FILE).exists():
            return json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
    except: pass
    return {}

def save_config(cfg):
    try:
        Path(CONFIG_FILE).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except: pass

cfg = load_config()

for k, v in {"extracted_employees": [], "approved_employees": []}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    st.caption("All settings saved automatically")

    st.markdown("### 🔑 Groq API Key")
    st.markdown("[Get free key →](https://console.groq.com)")
    groq_key = st.text_input("Groq API key (gsk_...)", type="password",
                              value=cfg.get("groq_key",""), placeholder="gsk_...",
                              key="groq_input")
    if groq_key != cfg.get("groq_key",""):
        cfg["groq_key"] = groq_key
        save_config(cfg)
    st.success("✅ Key saved & loaded automatically" if cfg.get("groq_key") else "")

    st.divider()
    st.markdown("### 📊 Google Sheets")
    script_url = st.text_input("Apps Script Web App URL",
                                value=cfg.get("script_url",""),
                                placeholder="https://script.google.com/macros/s/.../exec",
                                key="script_input")
    if script_url != cfg.get("script_url",""):
        cfg["script_url"] = script_url
        save_config(cfg)
    st.success("✅ URL saved & loaded automatically" if cfg.get("script_url") else "")

    with st.expander("📖 Setup Google Sheet (one time)"):
        st.markdown("""
1. Open your Google Sheet
2. **Extensions → Apps Script**
3. Delete all code, paste:

```javascript
function doPost(e) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    var data = JSON.parse(e.postData.contents);
    var lastRow = sheet.getLastRow();
    var nextRow = Math.max(lastRow + 1, 5);
    data.rows.forEach(function(row) {
      for (var i = 0; i < row.length; i++) {
        sheet.getRange(nextRow, i+1).setValue(row[i]);
      }
      nextRow++;
    });
    return ContentService.createTextOutput(
      JSON.stringify({status:"ok",written:data.rows.length}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService.createTextOutput(
      JSON.stringify({status:"error",message:err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
```

4. Save → Deploy → New deployment
5. Web app, Execute as=Me, Access=Anyone
6. Deploy → Copy URL → paste above
        """)

    st.divider()
    st.metric("Extracted", len(st.session_state.extracted_employees))
    st.metric("Approved", len(st.session_state.approved_employees))
    if st.button("🗑️ Clear all data"):
        st.session_state.extracted_employees = []
        st.session_state.approved_employees = []
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""<div style="background:#1a237e;color:white;padding:18px 28px;
border-radius:10px;margin-bottom:18px">
<h1 style="margin:0;font-size:24px">📋 EPF & ESIC Registration Automation</h1>
<p style="margin:4px 0 0;opacity:0.85;font-size:13px">
Bulk processing · Persistent settings · Groq AI · Google Sheets</p>
</div>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📤 Upload & Extract",
    "📅 Set Joining Dates",
    "🔍 Review & Edit",
    "✅ Approve & Export",
    "📜 Audit Log"
])

# ══ TAB 1: UPLOAD & EXTRACT ══════════════════════════════════════════════════
with tab1:
    st.markdown("### Upload Employee Documents")
    saved_key = cfg.get("groq_key","")
    if not saved_key:
        st.warning("⚠️ Enter your Groq API key in the sidebar first!")

    col1, col2 = st.columns([2,1])
    with col1:
        mode = st.radio("Upload mode",
            ["Single employee (any files)",
             "Batch — ZIP file (one folder per employee)"],
            horizontal=True)

        files = st.file_uploader("Drop files here",
            type=["pdf","jpg","jpeg","png","zip"],
            accept_multiple_files=True)

        if "Batch" in mode:
            st.info("""
**ZIP structure required:**
```
employees.zip
├── Ramesh_Kumar/        ← folder name = employee name
│   ├── aadhaar.pdf
│   ├── pan.jpg
│   └── cheque.pdf
├── Suresh_Patel/
│   ├── aadhaar.jpg
│   └── pan.jpg
```
            """)
        else:
            emp_name = st.text_input("Employee name hint",
                                      placeholder="e.g. Krupal Patel")
            doj_single = st.date_input("Date of Joining", key="doj_single")

        if files:
            st.markdown(f"**{len(files)} file(s) selected:**")
            for f in files:
                tp = "PDF" if "pdf" in f.type else "ZIP" if "zip" in f.type else "IMG"
                st.caption(f"[{tp}] {f.name} — {round(f.size/1024,1)} KB")

    with col2:
        st.markdown("#### Documents needed")
        docs_info = {
            "🪪 Aadhaar Card": "Name, DOB, Address, Aadhaar No.",
            "💳 PAN Card": "PAN Number",
            "🏦 Bank Cheque": "Account No., IFSC",
            "👤 Photo": "Employee photo (optional)",
            "👨‍👩‍👧 Family Aadhaar": "Nominee/family details",
        }
        for d, i in docs_info.items():
            st.markdown(f"**{d}**  \n*{i}*")

    st.divider()
    if st.button("🚀 Extract Data with AI", type="primary",
                  disabled=not files or not saved_key):
        from extractor import DocumentExtractor
        extractor = DocumentExtractor(saved_key)
        prog = st.progress(0)
        status = st.empty()

        # ── Collect files ──────────────────────────────────────────────────
        raw_files = []  # list of (filename, bytes)
        for uf in files:
            if uf.name.lower().endswith(".zip"):
                status.text(f"📦 Unpacking {uf.name}...")
                try:
                    with zipfile.ZipFile(io.BytesIO(uf.read())) as zf:
                        for nm in zf.namelist():
                            nm_clean = nm.replace("\\","/")
                            if not nm_clean.endswith("/") and any(
                                nm_clean.lower().endswith(e)
                                for e in [".pdf",".jpg",".jpeg",".png"]):
                                raw_files.append((nm_clean, zf.read(nm)))
                except Exception as e:
                    st.error(f"Cannot open ZIP: {e}")
            else:
                raw_files.append((uf.name, uf.read()))

        # ── Group by employee ──────────────────────────────────────────────
        if "Batch" in mode:
            groups = {}
            ungrouped = []
            for fname, fdata in raw_files:
                parts = fname.split("/")
                if len(parts) >= 2 and parts[0].strip():
                    folder = parts[0].strip()
                    groups.setdefault(folder, []).append((fname, fdata))
                else:
                    ungrouped.append((fname, fdata))
            if ungrouped:
                groups["Ungrouped_Documents"] = ungrouped
            if not groups:
                st.error("No employee folders found in ZIP!")
                st.stop()
            st.info(f"✅ Found **{len(groups)} employee(s)**: {', '.join(list(groups.keys())[:8])}")
        else:
            groups = {"Employee_1": raw_files}

        # ── Duplicate check ────────────────────────────────────────────────
        existing_groups = {e.get("group_name","") for e in st.session_state.extracted_employees}
        groups_to_process = {k:v for k,v in groups.items() if k not in existing_groups}
        if len(groups_to_process) < len(groups):
            st.warning(f"Skipping {len(groups)-len(groups_to_process)} already-extracted employee(s)")

        if not groups_to_process:
            st.info("All employees already extracted!")
            st.stop()

        # ── Process each employee ──────────────────────────────────────────
        new_emps = []
        total = len(groups_to_process)
        results_area = st.empty()

        for idx, (grp_name, grp_files) in enumerate(groups_to_process.items()):
            prog.progress(idx/total)
            status.text(f"🤖 Processing: {grp_name} ({idx+1}/{total})...")

            doj_val = str(doj_single) if "Single" in mode else ""
            hint_val = emp_name if "Single" in mode else grp_name

            result = extractor.process_employee_documents(
                grp_files, hint_name=hint_val, date_of_joining=doj_val)
            result["group_name"] = grp_name
            result["processed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Store individual joining date (editable in Tab 2)
            result["joining_date_override"] = doj_val
            new_emps.append(result)
            logging.info(f"Extracted: {grp_name} | {result['confidence_summary'].get('total_extracted',0)} fields")

            if idx < total-1:
                time.sleep(1)

        prog.progress(1.0)
        st.session_state.extracted_employees.extend(new_emps)
        status.text(f"✅ Done! {len(new_emps)} employee(s) processed.")

        st.success(f"✅ {len(new_emps)} employee(s) extracted! Go to **Set Joining Dates** tab next.")
        for emp in new_emps:
            f = emp.get("fields",{})
            cs = emp.get("confidence_summary",{})
            name = f.get("employee_name") or emp["group_name"]
            with st.expander(f"👤 {name} — {cs.get('total_extracted',0)} fields found"):
                filled = {k:v for k,v in f.items() if v}
                if filled:
                    st.json(filled)
                else:
                    st.error(f"No data: {emp.get('error','')}")
                    if emp.get("raw_response"):
                        st.code(emp["raw_response"][:300])

# ══ TAB 2: SET JOINING DATES ═════════════════════════════════════════════════
with tab2:
    st.markdown("### Set Individual Joining Dates")
    st.caption("Each employee can have a different joining date. Changes save immediately.")

    if not st.session_state.extracted_employees:
        st.info("No employees yet. Upload in Tab 1 first.")
    else:
        st.markdown("Set the joining date for each employee:")
        updated_any = False
        for i, emp in enumerate(st.session_state.extracted_employees):
            fields = emp.get("fields",{})
            name = fields.get("employee_name") or emp.get("group_name",f"Employee {i+1}")
            current_doj = emp.get("joining_date_override","") or fields.get("date_of_joining","")

            # Parse current date
            parsed_date = date.today()
            if current_doj:
                try:
                    if "/" in current_doj:
                        parts = current_doj.split("/")
                        if len(parts[0])==4:
                            parsed_date = date(int(parts[0]),int(parts[1]),int(parts[2]))
                        else:
                            parsed_date = date(int(parts[2]),int(parts[1]),int(parts[0]))
                    elif "-" in current_doj:
                        parts = current_doj.split("-")
                        parsed_date = date(int(parts[0]),int(parts[1]),int(parts[2]))
                except: pass

            col_name, col_date, col_status = st.columns([3,2,1])
            with col_name:
                st.markdown(f"**{name}**")
                st.caption(emp.get("group_name",""))
            with col_date:
                new_doj = st.date_input(f"DOJ", value=parsed_date, key=f"doj_{i}",
                                         label_visibility="collapsed")
            with col_status:
                doj_str = str(new_doj)
                if doj_str != emp.get("joining_date_override",""):
                    st.session_state.extracted_employees[i]["joining_date_override"] = doj_str
                    # Also update the field
                    from sheets_writer import fix_date
                    st.session_state.extracted_employees[i]["fields"]["date_of_joining"] = fix_date(doj_str)
                    updated_any = True
                st.success("✅")

        if updated_any:
            st.success("Joining dates updated!")

# ══ TAB 3: REVIEW & EDIT ════════════════════════════════════════════════════
with tab3:
    if not st.session_state.extracted_employees:
        st.info("No employees yet.")
    else:
        st.markdown(f"### Review & Edit — {len(st.session_state.extracted_employees)} employee(s)")
        names = [e.get("fields",{}).get("employee_name") or e.get("group_name",f"Emp {i+1}")
                 for i,e in enumerate(st.session_state.extracted_employees)]
        idx = st.selectbox("Select employee", range(len(names)), format_func=lambda i:names[i])
        emp = st.session_state.extracted_employees[idx]
        fields = emp.get("fields",{})
        conf = emp.get("field_confidence",{})
        val = emp.get("validation",{})
        docs = emp.get("documents_detected",[])

        if docs:
            st.markdown("**Detected:** " + " | ".join(f"`{d}`" for d in docs))

        SECTIONS = {
            "👤 Personal": [
                ("employee_name","Employee Name (Aadhaar)"),
                ("father_husband_name","Father / Husband Name"),
                ("gender","Gender"), ("marital_status","Marital Status"),
                ("date_of_birth","Date of Birth (DD/MM/YYYY)"),
                ("date_of_joining","Date of Joining"),
                ("aadhaar_number","Aadhaar Number"),
                ("mobile_number","Mobile Number"),("pan_number","PAN Number"),
            ],
            "💰 Salary & PF": [
                ("pf_basic_wages","PF Basic Wages"),("gross_salary","Gross Salary"),
                ("pf_eligibility","PF/ESIC Eligibility"),
                ("uan_number","UAN Number"),("esic_number","ESIC Number"),
            ],
            "🏦 Bank": [
                ("bank_name","Bank Name"),("bank_account_number","Bank Account No."),
                ("ifsc_code","IFSC Code"),("branch_name","Branch Name"),
            ],
            "📍 Address": [
                ("present_address","Present Address"),
                ("permanent_address","Permanent Address"),
            ],
            "👨‍👩‍👧 Nominee": [
                ("nominee_name","Nominee Name"),
                ("nominee_relationship","Nominee Relationship"),
                ("nominee_dob","Nominee DOB"),("family_members","Family Members"),
            ],
            "🏥 ESIC": [
                ("esic_dispensary","ESIC Dispensary"),
                ("insurance_details","Insurance Details"),
            ],
        }
        updated = dict(fields)
        for sec, sec_fields in SECTIONS.items():
            st.markdown(f"#### {sec}")
            c1,c2 = st.columns(2)
            for i,(fk,fl) in enumerate(sec_fields):
                col = c1 if i%2==0 else c2
                with col:
                    cl = conf.get(fk,"low")
                    ve = val.get(fk,{})
                    badge = {"high":"🟢","medium":"🟡","low":"⚪"}.get(cl,"⚪")
                    if ve.get("error"): badge="🔴"
                    nv = st.text_input(f"{badge} {fl}",
                                       value=str(fields.get(fk,"") or ""),
                                       key=f"e{idx}_{fk}")
                    updated[fk] = nv

        if st.button("💾 Save Changes"):
            st.session_state.extracted_employees[idx]["fields"] = updated
            st.success("✅ Changes saved!")

# ══ TAB 4: APPROVE & EXPORT ══════════════════════════════════════════════════
with tab4:
    if not st.session_state.extracted_employees:
        st.info("No employees to approve yet.")
    else:
        st.markdown(f"### Approve & Export — {len(st.session_state.extracted_employees)} employee(s)")

        c1,c2,c3 = st.columns(3)
        with c1:
            if st.button("✅ Approve All"):
                for emp in st.session_state.extracted_employees:
                    name = emp.get("fields",{}).get("employee_name") or emp.get("group_name","")
                    already = any(a.get("fields",{}).get("employee_name")==name
                                  for a in st.session_state.approved_employees)
                    if not already:
                        st.session_state.approved_employees.append(emp)
                st.success(f"All {len(st.session_state.extracted_employees)} approved!")
                st.rerun()
        with c2:
            st.metric("Pending", len(st.session_state.extracted_employees)-len(st.session_state.approved_employees))
        with c3:
            st.metric("Approved", len(st.session_state.approved_employees))

        st.divider()
        for i,emp in enumerate(st.session_state.extracted_employees):
            f = emp.get("fields",{})
            name = f.get("employee_name") or emp.get("group_name",f"Employee {i+1}")
            approved = any(a.get("fields",{}).get("employee_name")==name
                           for a in st.session_state.approved_employees)
            with st.expander(f"{'✅' if approved else '⏳'} {name}", expanded=False):
                r1,r2,r3,r4 = st.columns(4)
                r1.markdown(f"**DOJ:** {f.get('date_of_joining','-')}")
                r2.markdown(f"**Aadhaar:** {f.get('aadhaar_number','-')}")
                r3.markdown(f"**PAN:** {f.get('pan_number','-')}")
                r4.markdown(f"**Bank:** {f.get('bank_account_number','-')}")
                if not approved:
                    if st.button("✅ Approve", key=f"app{i}"):
                        st.session_state.approved_employees.append(emp)
                        logging.info(f"Approved: {name}"); st.rerun()
                else:
                    st.success("Approved ✅")

        st.divider()
        st.markdown(f"### Export — **{len(st.session_state.approved_employees)} approved** employee(s)")
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### 📊 Push to Google Sheet")
            saved_url = cfg.get("script_url","")
            if not saved_url:
                st.warning("Enter Apps Script URL in sidebar first.")
            elif not st.session_state.approved_employees:
                st.info("Approve employees first.")
            else:
                st.success(f"✅ Connected")
                if st.button(f"📊 Push {len(st.session_state.approved_employees)} record(s) to Google Sheet"):
                    from sheets_writer import SheetsWriter
                    try:
                        with st.spinner("Writing to Google Sheet..."):
                            writer = SheetsWriter(saved_url)
                            n = writer.write_employees(st.session_state.approved_employees)
                        st.success(f"✅ {n} record(s) written to Google Sheet!")
                        logging.info(f"Pushed {n} records to sheet")
                    except Exception as e:
                        st.error(f"Error: {e}")
                        st.info("Check Apps Script URL and make sure access is set to 'Anyone'")

        with col_b:
            st.markdown("#### ⬇️ Download CSV")
            if st.session_state.approved_employees:
                from sheets_writer import employees_to_csv
                csv_data = employees_to_csv(st.session_state.approved_employees)
                st.download_button(
                    f"⬇️ Download CSV ({len(st.session_state.approved_employees)} employees)",
                    data=csv_data,
                    file_name=f"epf_esic_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )
                st.caption("Each employee = one row in CSV")

# ══ TAB 5: AUDIT LOG ═════════════════════════════════════════════════════════
with tab5:
    st.markdown("### Audit Log")
    lf = Path("logs/automation.log")
    if lf.exists() and lf.stat().st_size > 0:
        with open(lf, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        st.code("".join(lines[-150:]))
        st.caption(f"Showing last {min(150,len(lines))} of {len(lines)} entries")
    else:
        st.info("Log appears after processing.")
    if st.button("🗑️ Clear Log"):
        open(lf,"w").close(); st.success("Cleared.")
