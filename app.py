import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from PIL import Image
import pytesseract

# --- OCR Text Extraction ---
def extract_text_ocr(pdf):
    all_text = []
    for page in pdf.pages:
        im = page.to_image(resolution=300)
        pil_img = im.original
        text = pytesseract.image_to_string(pil_img)
        all_text.append(text)
    return "\n".join(all_text)

# --- Transaction Parser (Flexible) ---
def extract_transactions_from_text(text):
    transactions = []
    transaction = None
    date_regex = r'\d{2}/\d{2}/\d{4}'
    trans_regex = re.compile(
        r'^(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<desc>.+?)\s+'
        r'(?:(?P<fees>-?[\d,]+\.\d{2})\s+)?'
        r'(?:(?P<debit>-?[\d,]+\.\d{2})\s+)?'
        r'(?:(?P<credit>-?[\d,]+\.\d{2})\s+)?'
        r'(?P<balance>-?[\d,]+\.\d{2})$'
    )
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if re.match(f'^{date_regex}', line):  # New transaction
            if transaction:
                transactions.append(transaction)
            m = trans_regex.match(line)
            if m:
                transaction = {
                    'Date': m.group('date'),
                    'Description': m.group('desc').strip(),
                    'Fees': m.group('fees') or '',
                    'Debit': m.group('debit') or '',
                    'Credit': m.group('credit') or '',
                    'Balance': m.group('balance') or ''
                }
            else:
                # Fallback: If doesn't match, just start new and parse more simply
                parts = re.split(r'\s{2,}', line)
                transaction = {
                    'Date': parts[0],
                    'Description': parts[1] if len(parts) > 1 else '',
                    'Fees': '',
                    'Debit': '',
                    'Credit': '',
                    'Balance': parts[-1] if len(parts) > 2 else ''
                }
        else:
            # Likely a continuation of previous description
            if transaction:
                transaction['Description'] += ' ' + line
    if transaction:
        transactions.append(transaction)
    return transactions

# --- Clean Transactions (Only date, description, amount, balance; credit = positive, debit = negative) ---
def clean_transactions(transactions):
    cleaned = []
    for t in transactions:
        # Skip rows missing date, description or balance, or with no debit/credit
        if not t.get('Date') or not t.get('Description') or not t.get('Balance'):
            continue
        debit = t.get('Debit') or ''
        credit = t.get('Credit') or ''
        # Remove thousands separators and spaces
        def clean_amt(val):
            return val.replace(',', '').replace(' ', '') if val else ''
        debit = clean_amt(debit)
        credit = clean_amt(credit)
        balance = clean_amt(t.get('Balance'))
        try:
            if debit and debit != '0.00':
                amount = -abs(float(debit))
            elif credit and credit != '0.00':
                amount = abs(float(credit))
            else:
                # If neither debit nor credit is set, skip row
                continue
            cleaned.append({
                'Date': t['Date'],
                'Description': t['Description'].strip(),
                'Amount': amount,
                'Balance': float(balance) if balance else ''
            })
        except Exception:
            # Skip malformed lines
            continue
    return cleaned

# --- Combined PDF Processor ---
def extract_transactions(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        # Try regular text extraction
        raw_text = []
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                raw_text.append(page_text)
        text = "\n".join(raw_text)
        if not text.strip():
            # No text found, fall back to OCR
            st.info("No selectable text found in PDF. Using OCR (may take longer)...")
            text = extract_text_ocr(pdf)
        return extract_transactions_from_text(text)

# --- Streamlit App ---
st.title("Nedbank Statement Parser (All Formats)")

uploaded_file = st.file_uploader("Upload Nedbank PDF", type=["pdf"])

if uploaded_file:
    with st.spinner("Processing..."):
        pdf_bytes = BytesIO(uploaded_file.read())
        transactions = extract_transactions(pdf_bytes)
        cleaned = clean_transactions(transactions)
        if cleaned:
            df = pd.DataFrame(cleaned)
            st.write(df)
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Download as CSV",
                csv,
                "nedbank_transactions.csv",
                "text/csv",
                key='download-csv'
            )
        else:
            st.error("No transactions found. The statement format may be different or unclear.")

st.markdown("""
---
**Tip:**  
If your statement is a scan/photo, OCR will be used.  
If parsing is inaccurate, try increasing the scan quality or brightness.
""")
