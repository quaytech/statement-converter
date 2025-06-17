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

# --- Transaction Parser: Start at "Opening balance" only ---
def extract_transactions_from_text(text):
    transactions = []
    in_transactions = False
    date_regex = r'(\d{2}/\d{2}/\d{4})'
    opening_balance_regex = re.compile(r'(\d{2}/\d{2}/\d{4}).*opening balance', re.IGNORECASE)
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        # Look for opening balance
        if not in_transactions:
            m = opening_balance_regex.search(line)
            if m:
                in_transactions = True
                date = m.group(1)
                # Get balance (last number on line)
                amounts = re.findall(r'-?[\d,]+\.\d{2}', line)
                balance = amounts[-1] if amounts else None
                transactions.append({
                    'Date': date,
                    'Description': 'Opening balance',
                    'Debit': '',
                    'Credit': '',
                    'Balance': balance
                })
            continue
        # Collect transactions (date anywhere in line)
        date_match = re.search(date_regex, line)
        if in_transactions and date_match:
            date = date_match.group(1)
            rest = line.split(date, 1)[1].strip()
            # Find all amounts in the line
            amounts = re.findall(r'-?[\d,]+\.\d{2}', rest)
            desc = rest
            balance = None
            amount = None
            if amounts:
                balance = amounts[-1]
                desc = rest.rsplit(balance, 1)[0].strip()
                if len(amounts) > 1:
                    amount = amounts[-2]
            debit, credit = '', ''
            if amount:
                # Heuristic: negative means debit, otherwise credit
                if '-' in amount:
                    debit = amount
                else:
                    credit = amount
            transactions.append({
                'Date': date,
                'Description': desc,
                'Debit': debit,
                'Credit': credit,
                'Balance': balance
            })
        # Optional: Stop if you hit "closing balance" (uncomment if you want to stop parsing at that point)
        # if in_transactions and "closing balance" in line.lower():
        #     break
    return transactions

# --- Clean & Format Transactions (Arrow/Streamlit-safe) ---
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
        # Use None for missing values (not empty string)
        amount = None
        try:
            if debit and debit != '0.00':
                amount = -abs(float(debit))
            elif credit and credit != '0.00':
                amount = abs(float(credit))
        except Exception:
            amount = None
        try:
            balance_val = float(balance) if balance else None
        except Exception:
            balance_val = None
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
st.title("Nedbank Statement Parser (Reliable - Starts at Opening Balance)")

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
