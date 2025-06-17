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

# --- Improved Transaction Parser ---
def extract_transactions_from_text(text):
    transactions = []
    transaction = None
    # Date format: dd/mm/yyyy
    date_regex = r'(\d{2}/\d{2}/\d{4})'
    # Flexible regex for rows: optional code, date, description, optional fees, debit, credit, balance
    trans_regex = re.compile(
        r'^(?:\S+\s+)?'                        # Optional Tran list no (ignore)
        r'(?P<date>\d{2}/\d{2}/\d{4})\s+'      # Date
        r'(?P<desc>.+?)\s*'                    # Description
        r'(?:(?P<fees>-?[\d,]+\.\d{2})\s+)?'   # Optional Fees (ignore)
        r'(?:(?P<debit>-?[\d,]+\.\d{2})\s+)?'  # Optional Debit
        r'(?:(?P<credit>-?[\d,]+\.\d{2})\s+)?' # Optional Credit
        r'(?P<balance>-?[\d,]+\.\d{2})?'       # Optional Balance
        r'$'
    )

    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        # Any line with optional leading code, then a date, is a new transaction
        if re.match(f'^(?:\S+\s+)?{date_regex}', line):
            # Save previous transaction, if any
            if transaction:
                transactions.append(transaction)
            m = trans_regex.match(line)
            if m:
                transaction = {
                    'Date': m.group('date'),
                    'Description': m.group('desc').strip(),
                    'Debit': m.group('debit') or '',
                    'Credit': m.group('credit') or '',
                    'Balance': m.group('balance') or ''
                }
            else:
                # Fallback: try to extract what we can (date, description, balance)
                parts = re.split(r'\s{2,}', line)
                date = ''
                desc = ''
                balance = ''
                if len(parts) >= 2:
                    # Ignore first part if not a date
                    if re.match(date_regex, parts[0]):
                        date = parts[0]
                        desc = parts[1]
                        if len(parts) > 2:
                            balance = parts[-1]
                    elif re.match(date_regex, parts[1]):
                        date = parts[1]
                        desc = parts[2] if len(parts) > 2 else ''
                        balance = parts[-1] if len(parts) > 3 else ''
                transaction = {
                    'Date': date,
                    'Description': desc.strip(),
                    'Debit': '',
                    'Credit': '',
                    'Balance': balance
                }
        else:
            # Multiline description support
            if transaction:
                transaction['Description'] += ' ' + line
    if transaction:
        transactions.append(transaction)
    return transactions

# --- Clean & Format Transactions ---
def clean_transactions(transactions):
    cleaned = []
    for t in transactions:
        if not t.get('Date') or not t.get('Description'):
            continue
        debit = t.get('Debit') or ''
        credit = t.get('Credit') or ''
        def clean_amt(val):
            return val.replace(',', '').replace(' ', '') if val else ''
        debit = clean_amt(debit)
        credit = clean_amt(credit)
        balance = clean_amt(t.get('Balance'))
        # Determine Amount: blank if neither debit nor credit
        amount = ''
        try:
            if debit and debit != '0.00':
                amount = -abs(float(debit))
            elif credit and credit != '0.00':
                amount = abs(float(credit))
        except Exception:
            amount = ''
        try:
            balance_val = float(balance) if balance else ''
        except Exception:
            balance_val = ''
        cleaned.append({
            'Date': t['Date'],
            'Description': t['Description'].strip(),
            'Amount': amount,
            'Balance': balance_val
        })
    return cleaned

# --- Combined PDF Processor ---
def extract_transactions(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        # Try regular text extraction first
        raw_text = []
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                raw_text.append(page_text)
        text = "\n".join(raw_text)
        if not text.strip():
            st.info("No selectable text found in PDF. Using OCR (may take longer)...")
            text = extract_text_ocr(pdf)
        return extract_transactions_from_text(text)

# --- Streamlit App ---
st.title("Nedbank Statement Parser (Flexible, All Formats)")

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
