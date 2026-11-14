#!/usr/bin/env python3
"""
compile_docs.py
Standardized Markdown to DOCX and PDF document compiler for job search files.
Compiles one .md resume or cover letter into PDF + DOCX in the SAME folder as the source.
Layout: applications/<market>/<date>_<company>_<role>/{resume.md, cover_letter.md, jd.txt}
plus the generated send files <First>_<Last>_<Role>[_Tag][_Cover_Letter].{pdf,docx}.
"""

import sys
import os
import re
import argparse
import docx
from docx.shared import Inches, Pt, RGBColor, Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

import reportlab
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def parse_markdown(md_text):
    """Simple parser for markdown sections, headers, bullets, and links."""
    lines = md_text.splitlines()
    elements = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('# '):
            elements.append({'type': 'h1', 'text': stripped[2:].strip()})
        elif stripped.startswith('## '):
            elements.append({'type': 'h2', 'text': stripped[3:].strip()})
        elif stripped.startswith('### '):
            elements.append({'type': 'h3', 'text': stripped[4:].strip()})
        elif stripped.startswith('- ') or stripped.startswith('* ') or stripped.startswith('• '):
            elements.append({'type': 'bullet', 'text': stripped[2:].strip()})
        elif stripped.startswith('---'):
            elements.append({'type': 'hr', 'text': ''})
        else:
            elements.append({'type': 'p', 'text': stripped})
            
    return elements

def clean_md_formatting(text):
    """Strip basic markdown bold/italic syntax for plain text or formatting runs."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1 (\2)', text)
    return text

def compile_to_docx(md_path, docx_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
        
    doc = docx.Document()
    
    # Set page size (A4 — Irish/EU standard) and margins
    for section in doc.sections:
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.55)
        section.right_margin = Inches(0.55)
        
    # Styles setup
    style_normal = doc.styles['Normal']
    font = style_normal.font
    font.name = 'Calibri'
    font.size = Pt(10)
    font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    
    elements = parse_markdown(md_content)
    
    for el in elements:
        t = el['type']
        raw = el['text']
        
        if t == 'h1':
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(clean_md_formatting(raw))
            run.bold = True
            run.font.size = Pt(16)
            run.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
        elif t == 'h2':
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(clean_md_formatting(raw).upper())
            run.bold = True
            run.font.size = Pt(10.5)
            run.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
            
            pPr = p._p.get_or_add_pPr()
            pBdr = parse_xml(r'<w:pBdr %s><w:bottom w:val="single" w:sz="8" w:space="2" w:color="003366"/></w:pBdr>' % nsdecls('w'))
            pPr.append(pBdr)
        elif t == 'h3':
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(1)
            run = p.add_run(clean_md_formatting(raw))
            run.bold = True
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0x00, 0x33, 0x66)
        elif t == 'bullet':
            p = doc.add_paragraph(style='List Bullet')
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(1.5)
            p.paragraph_format.line_spacing = 1.1
            p.add_run(clean_md_formatting(raw))
        elif t == 'p':
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.15
            p.add_run(clean_md_formatting(raw))
            
    os.makedirs(os.path.dirname(docx_path), exist_ok=True)
    doc.save(docx_path)
    print(f"[+] {os.path.relpath(docx_path)}")

def md_to_reportlab_html(text):
    """Convert basic markdown tags (**bold**, *italic*, links) to ReportLab XML tags."""
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" color="#003366"><u>\1</u></a>', text)
    return text

def compile_to_pdf(md_path, pdf_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
        
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,  # Irish/EU standard page size (was US Letter)
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    
    h1_style = ParagraphStyle(
        'DocH1', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=15, leading=17,
        textColor=colors.HexColor('#003366'), alignment=1, spaceAfter=4
    )
    h2_style = ParagraphStyle(
        'DocH2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=10.5, leading=13,
        textColor=colors.HexColor('#003366'), spaceBefore=8, spaceAfter=2
    )
    h3_style = ParagraphStyle(
        'DocH3', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9.5, leading=12,
        textColor=colors.HexColor('#003366'), spaceBefore=4, spaceAfter=2
    )
    body_style = ParagraphStyle(
        'DocBody', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9, leading=11.5,
        textColor=colors.HexColor('#222222'), spaceAfter=3
    )
    bullet_style = ParagraphStyle(
        'DocBullet', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.8, leading=11,
        textColor=colors.HexColor('#222222'), leftIndent=12, firstLineIndent=-8, spaceAfter=1.5
    )
    
    story = []
    elements = parse_markdown(md_content)
    
    for el in elements:
        t = el['type']
        raw = el['text']
        html_text = md_to_reportlab_html(raw)
        
        if t == 'h1':
            story.append(Paragraph(html_text, h1_style))
        elif t == 'h2':
            story.append(Paragraph(html_text.upper(), h2_style))
            story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#003366'), spaceAfter=3, spaceBefore=1))
        elif t == 'h3':
            story.append(Paragraph(html_text, h3_style))
        elif t == 'bullet':
            story.append(Paragraph(f"&bull; {html_text}", bullet_style))
        elif t == 'p':
            story.append(Paragraph(html_text, body_style))
        elif t == 'hr':
            story.append(Spacer(1, 4))
            
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    doc.build(story)
    print(f"[+] {os.path.relpath(pdf_path)}")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from candidate import file_prefix, PROFILE  # noqa: E402
PREFIX = file_prefix()

# --- submission filename safety + index ------------------------------------
# The submission filename IS visible to the employer. It must identify the
# CANDIDATE and the SPECIALISATION, never the company being applied to.
# (an early version wrote files like <Name>_Data_Engineer_<Company>.pdf, which told one
# employer where else the candidate was applying.)
# The company -> filename mapping lives in applications/INDEX.csv instead.

# Data/BA vocabulary that is legitimate as a tag even if some company shares the word.
GENERIC_TAG_WORDS = {
    'data', 'analytics', 'analyst', 'reporting', 'governance', 'quality', 'insight',
    'insights', 'migration', 'warehouse', 'engineering', 'engineer', 'master', 'audit',
    'reference', 'platform', 'pipeline', 'modelling', 'modeling', 'integration',
    'automation', 'oracle', 'python', 'snowflake', 'fabric', 'tableau', 'cloud',
    'finance', 'financial', 'banking', 'insurance', 'healthcare', 'retail', 'public',
}


def company_leak_reason(tag_slug, base_name, root_dir):
    """Return a reason string if tag_slug looks like a company name, else None."""
    tag_norm = tag_slug.replace('_', '').lower()
    if len(tag_norm) < 2:
        return None

    # 1. Does the tag echo the company token of the internal filename?
    #    Internal names are resume_<company>_<role>.md
    parts = base_name.lower().replace('resume_', '', 1).split('_')
    for n in (3, 2, 1):
        token = ''.join(parts[:n])
        if token and (token == tag_norm or (len(tag_norm) >= 4 and tag_norm in token)):
            return f"it matches the company token in the internal filename ('{'_'.join(parts[:n])}')"

    # 2. Does the tag match an employer on the permits-issued list?
    #    Match on the employer's DISTINCTIVE leading word(s), ignoring the legal
    #    suffixes (Limited, UC, Ireland, Group...) that every company name carries.
    #    Generic data vocabulary is allowlisted so 'Reporting' or 'Analytics' is
    #    never mistaken for a company.
    csv_path = os.path.join(root_dir, 'data', 'employer_names.csv')
    if len(tag_norm) >= 4 and tag_norm not in GENERIC_TAG_WORDS and os.path.exists(csv_path):
        noise = {'limited', 'ltd', 'uc', 'plc', 'dac', 'ireland', 'irl', 'group',
                 'holdings', 'services', 'international', 'global', 'solutions',
                 'company', 'technologies', 'the', 'and', 'of', 'europe', 'emea'}
        try:
            with open(csv_path, encoding='utf-8', errors='ignore') as fh:
                next(fh, None)
                for line in fh:
                    name = line.split(',')[0].strip()
                    words = [re.sub(r'[^a-z0-9]+', '', w.lower()) for w in name.split()]
                    core = [w for w in words if w and w not in noise]
                    if not core:
                        continue
                    # the full distinctive name, and its leading word
                    if tag_norm == ''.join(core) or tag_norm == core[0]:
                        return f"it matches '{name}' on the employment-permits list"
        except OSError:
            pass
    return None


def update_index(root_dir, folder_rel, filename, role, tag, is_cover):
    """applications/INDEX.csv: the private map from folder (company) to send-filename.
    One row per folder per document type, replaced on every recompile."""
    import csv as _csv
    from datetime import date
    idx = os.path.join(root_dir, 'applications', 'INDEX.csv')
    header = ['folder', 'send_filename', 'role_title', 'tag', 'built']
    rows = []
    if os.path.exists(idx):
        with open(idx, newline='', encoding='utf-8') as fh:
            for r in _csv.reader(fh):
                if not r or r[0] == 'folder':
                    continue
                if r[0] == folder_rel and ('Cover_Letter' in r[1]) == is_cover:
                    if not role and r[1] == filename:   # plain recompile: keep recorded role/tag
                        role, tag = r[2], r[3]
                    continue
                rows.append(r)
    rows.append([folder_rel, filename, role, tag, date.today().isoformat()])
    rows.sort()
    with open(idx, 'w', newline='', encoding='utf-8') as fh:
        w = _csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    print(f"[+] Indexed: {folder_rel} -> {filename}")


def main():
    parser = argparse.ArgumentParser(description="Compile a Markdown resume or cover letter to PDF + DOCX next to the source file")
    parser.add_argument("--md_file", type=str, required=True, help="Path to the Markdown file to compile")
    parser.add_argument("--docx", action="store_true",
                        help="Also generate DOCX for files outside applications/ (always on inside it).")
    parser.add_argument("--submit-role", type=str,
                        help="Role title for the send filename, e.g. 'Data Analyst' -> <First>_<Last>_Data_Analyst.pdf. "
                             "Omit on a recompile to keep the folder's existing send name.")
    parser.add_argument("--submit-tag", type=str, default="",
                        help="Optional neutral specialisation tag (EDW, Governance, Power_BI). Visible to the employer, "
                             "so it must never be a company name - a tag that looks like one is refused.")
    args = parser.parse_args()

    import glob
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    md_path = os.path.abspath(args.md_file)
    if not os.path.exists(md_path):
        sys.exit(f"[!] File not found: {md_path}")

    out_dir = os.path.dirname(md_path)
    base_name = os.path.splitext(os.path.basename(md_path))[0]
    is_cover = 'cover_letter' in base_name.lower() or 'coverletter' in base_name.lower()
    in_app = md_path.startswith(os.path.join(root_dir, 'applications') + os.sep)

    # Inside applications/<market>/<date>_<company>_<role>/ every output is a send file:
    # named for the candidate, never the company, and only one pdf+docx pair per document.
    if in_app:
        folder = os.path.basename(out_dir)
        internal_name = folder.split('_', 1)[1] if folder[:4].isdigit() and '_' in folder else folder
        mine = lambda f: ('_Cover_Letter' in f) == is_cover
        existing = sorted(f for f in glob.glob(os.path.join(out_dir, PREFIX + '*.pdf')) if mine(f))
        if args.submit_role:
            role_slug = re.sub(r'[^A-Za-z0-9]+', '_', args.submit_role).strip('_')
            tag_slug = re.sub(r'[^A-Za-z0-9]+', '_', args.submit_tag).strip('_')
            if tag_slug:
                reject = company_leak_reason(tag_slug, internal_name, root_dir)
                if reject:
                    sys.exit(f"[!] REFUSED submit tag '{args.submit_tag}': {reject}. The send filename is "
                             "visible to the employer; use a neutral skill/domain tag instead.")
            stem = f"{PREFIX}{role_slug}" + (f"_{tag_slug}" if tag_slug else "")
            stem += "_Cover_Letter" if is_cover else ""
        elif existing:
            stem = os.path.splitext(os.path.basename(existing[-1]))[0]   # recompile keeps its name
            role_slug, tag_slug = '', ''
        else:
            stem = PREFIX + ("Cover_Letter" if is_cover else "Resume")
            role_slug, tag_slug = '', ''
        if len(stem + '.docx') >= 55:
            sys.exit(f"[!] REFUSED: send filename '{stem}.docx' is {len(stem) + 5} chars (must be < 55, it is "
                     "visible to the employer). Shorten --submit-role and/or --submit-tag.")
        for old in glob.glob(os.path.join(out_dir, PREFIX + '*')):
            if mine(old) and os.path.splitext(os.path.basename(old))[0] != stem and old.endswith(('.pdf', '.docx')):
                os.remove(old)
    else:
        stem = base_name

    pdf_path = os.path.join(out_dir, f"{stem}.pdf")
    compile_to_pdf(md_path, pdf_path)
    if in_app or args.docx:
        compile_to_docx(md_path, os.path.join(out_dir, f"{stem}.docx"))
    if in_app:
        folder_rel = os.path.relpath(out_dir, os.path.join(root_dir, 'applications'))
        update_index(root_dir, folder_rel, f"{stem}.docx", args.submit_role or '', args.submit_tag or '', is_cover)


if __name__ == '__main__':
    main()
