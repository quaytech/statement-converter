import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO
from PIL import Image
import pytesseract

# Page configuration
st.set_page_config(
    page_title="Bank Statement Converter",
    page_icon="🏦",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        text-align: center;
        color: #2c3e50;
        margin-bottom: 2rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #d1ecf1;
        border: 1px solid #bee5eb;
        color: #0c5460;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# --- OCR Text Extraction (Fixed) ---
def extract_text_ocr(pdf):
    all_text = []
    for page_num, page in enumerate(pdf.pages, 1):
        st.write(f"🔍 OCR processing page {page_num}...")
        try:
            # Convert page to high-resolution image for better OCR
            im = page.to_image(resolution=300)
            pil_img = im.original
            
            # Use optimized OCR settings for bank statements
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,-/: ()'
            text = pytesseract.image_to_string(pil_img, config=custom_config)
            
            if text.strip():
                st.write(f"✅ OCR extracted {len(text)} characters from page {page_num}")
                all_text.append(text)
            else:
                st.write(f"❌ No text extracted from page {page_num}")
                
        except Exception as e:
            st.write(f"❌ OCR error on page {page_num}: {str(e)}")
            
    return "\n".join(all_text)

# --- Improved Transaction Parser (Fixed to handle opening balance) ---
def extract_transactions_from_text(text):
    transactions = []
    
    # Credit keywords for classification
    credit_keywords = [
        'batch dep', 'deposit', 'business', 'herd2', 'herd', 'netsurit', 
        'top vending rebate', 'merch discount', 'reversal', 'opening balance',
        'transfer in', 'credit', 'salary', 'refund', 'merch d'
    ]
    
    def is_credit(description):
        desc_lower = description.lower()
        return any(keyword in desc_lower for keyword in credit_keywords)
    
    # Process line by line to find transactions
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Look for lines with dates (handles both formats)
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', line)
        if not date_match:
            continue
            
        date = date_match.group(1)
        # Normalize date format
        date_parts = date.split('/')
        if len(date_parts) == 3:
            day, month, year = date_parts
            date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        
        # Remove date from line to get remainder
        remainder = line.replace(date_match.group(0), '').strip()
        
        # Skip non-transaction entries
        remainder_lower = remainder.lower()
        skip_phrases = ['statement period', 'total pages', 'balance brought forward', 'balance carried forward']
        if any(phrase in remainder_lower for phrase in skip_phrases):
            continue
        
        # Extract all numbers from the line
        numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.\d{2}\b', remainder)
        if not numbers:
            numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{0,2}\b', remainder)
        
        # Filter reasonable amounts and exclude small fee amounts
        filtered_numbers = []
        for num in numbers:
            try:
                num_value = float(num.replace(',', ''))
                # Include all reasonable amounts, we'll filter fees later based on context
                if 1.0 <= num_value <= 999999999:
                    filtered_numbers.append(num)
            except:
                continue
        
        if not filtered_numbers:
            continue
        
        # Extract description by removing numbers and cleaning
        description = remainder
        for num in numbers:
            description = description.replace(num, ' ')
        
        # Clean description
        description = re.sub(r'\b\d{6,}\b', '', description)  # Remove long codes
        description = re.sub(r'[^\w\s-]', ' ', description)
        description = ' '.join(description.split())
        
        if not description or len(description.strip()) < 2:
            description = 'Transaction'
        
        # Determine amount and balance
        balance = None
        if filtered_numbers:
            try:
                balance = float(filtered_numbers[-1].replace(',', ''))
            except:
                balance = None
        
        # Determine amount and balance based on position in the line
        # In 2023 format: Date | Description | Fees | Debits | Credits | Balance
        # We need to identify which numbers are debits vs credits vs balance
        
        balance = None
        if filtered_numbers:
            try:
                balance = float(filtered_numbers[-1].replace(',', ''))
            except:
                balance = None
        
        amount = None
        
        # For opening balance, there's typically no transaction amount
        if 'opening balance' in description.lower():
            amount = None
        else:
            # Try to identify debits vs credits based on position and context
            # Credits: BATCH DEP, Herd2, deposits - should be positive
            # Debits: PnP, fees, withdrawals - should be negative
            
            if len(filtered_numbers) >= 2:
                # Look for the transaction amount (excluding balance)
                potential_amounts = filtered_numbers[:-1]  # All except last (balance)
                
                # Find the largest amount that's not a fee
                transaction_amount = None
                for num in reversed(potential_amounts):  # Start from the end (closer to balance)
                    try:
                        num_value = float(num.replace(',', ''))
                        # Skip obvious fees but keep real transaction amounts
                        if num_value >= 20.0:  # Anything 20 or above is likely a real transaction
                            transaction_amount = num_value
                            break
                        elif num_value >= 10.0 and len(potential_amounts) <= 2:  # If only small amounts, use them
                            transaction_amount = num_value
                            break
                    except:
                        continue
                
                if transaction_amount:
                    # Determine sign based on transaction type
                    if is_credit(description):
                        amount = transaction_amount  # Credits are positive
                    else:
                        amount = -transaction_amount  # Debits are negative
        
        transactions.append({
            'Date': date,
            'Description': description.strip(),
            'Amount': amount,
            'Balance': balance
        })
    
    return transactions

# --- Clean & Format Transactions ---
def clean_transactions(transactions):
    seen = set()
    cleaned = []
    
    for t in transactions:
        if not t.get('Date') or not t.get('Description'):
            continue
            
        # Create unique key to avoid duplicates
        key = f"{t['Date']}_{t['Description'][:20]}_{t.get('Balance', '')}"
        if key in seen:
            continue
        seen.add(key)
        
        cleaned.append({
            'Date': t['Date'],
            'Description': t['Description'],
            'Amount': t['Amount'],
            'Balance': t['Balance']
        })
    
    # Sort by date
    try:
        from datetime import datetime
        cleaned.sort(key=lambda x: datetime.strptime(x['Date'], '%d/%m/%Y'))
    except:
        pass
    
    return cleaned

# --- Combined PDF Processor (Fixed to process ALL pages) ---
def extract_transactions(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        # First try text extraction on ALL pages
        all_text = []
        pages_with_text = []
        
        st.write(f"📄 Processing {len(pdf.pages)} pages...")
        
        for page_num, page in enumerate(pdf.pages, 1):
            st.write(f"📄 Processing page {page_num}...")
            
            # Try text extraction first
            page_text = page.extract_text()
            if page_text and len(page_text.strip()) > 50:
                # Check if it contains banking keywords
                banking_keywords = ['transaction', 'balance', 'date', 'account', 'nedbank', 'batch', 'dep', 'herd', 'current', 'tran list', 'opening balance']
                if any(keyword in page_text.lower() for keyword in banking_keywords):
                    st.write(f"✅ Text extraction worked on page {page_num}")
                    all_text.append(page_text)
                    pages_with_text.append(page_num)
                else:
                    st.write(f"❌ No banking keywords found on page {page_num}")
            else:
                st.write(f"❌ Little/no text extracted from page {page_num}")
        
        # If we got some text, use it
        if all_text:
            st.write(f"✅ Using text extraction from pages: {pages_with_text}")
            text = "\n".join(all_text)
        else:
            # Fall back to OCR for ALL pages
            st.info("No selectable text found in PDF. Using OCR on all pages...")
            text = extract_text_ocr(pdf)
        
        if not text.strip():
            st.error("Could not extract any text from PDF")
            return []
            
        # Show sample of extracted text for debugging
        st.write("📝 Sample of extracted text:")
        st.text(text[:500] + "..." if len(text) > 500 else text)
        
        return extract_transactions_from_text(text)

# --- Streamlit App ---
def main():
    st.markdown('<h1 class="main-header">🏦 Bank Statement PDF to CSV Converter</h1>', unsafe_allow_html=True)
    
    st.markdown("""
    <div class="info-box">
        <strong>Features:</strong><br>
        • Works with both text-based and image-based PDFs<br>
        • Processes ALL pages including opening balance<br>
        • Uses OCR automatically when needed<br>
        • Handles both 2021 and 2023 Nedbank formats
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader("Upload Nedbank PDF", type=["pdf"])

    if uploaded_file:
        with st.spinner("Processing PDF..."):
            try:
                pdf_bytes = BytesIO(uploaded_file.read())
                transactions = extract_transactions(pdf_bytes)
                cleaned = clean_transactions(transactions)
                
                if cleaned:
                    st.markdown(f"""
                    <div class="success-box">
                        <strong>✅ Success!</strong><br>
                        Extracted {len(cleaned)} transactions from PDF
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Display with editing capability
                    st.subheader("📊 Transaction Preview")
                    st.markdown("**Review transactions before download:**")
                    
                    df = pd.DataFrame(cleaned)
                    
                    # Add selection capability
                    if 'selected_rows' not in st.session_state:
                        st.session_state.selected_rows = [True] * len(df)
                    
                    if len(st.session_state.selected_rows) != len(df):
                        st.session_state.selected_rows = [True] * len(df)
                    
                    # Create a display dataframe with selection checkboxes
                    display_data = []
                    for i, (_, row) in enumerate(df.iterrows()):
                        # Handle NaN values properly
                        amount_str = ""
                        if row['Amount'] is not None and not pd.isna(row['Amount']):
                            amount_str = f"{row['Amount']:.2f}"
                        
                        balance_str = ""
                        if row['Balance'] is not None and not pd.isna(row['Balance']):
                            balance_str = f"{row['Balance']:.2f}"
                        
                        display_data.append({
                            'Select': st.session_state.selected_rows[i],
                            'Date': row['Date'],
                            'Description': row['Description'],
                            'Amount': amount_str,
                            'Balance': balance_str
                        })
                    
                    # Selection controls
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        select_all = st.checkbox("Select All", value=all(st.session_state.selected_rows))
                        if select_all != all(st.session_state.selected_rows):
                            st.session_state.selected_rows = [select_all] * len(df)
                            st.rerun()
                    
                    # Create the editable dataframe
                    edited_df = st.data_editor(
                        pd.DataFrame(display_data),
                        column_config={
                            "Select": st.column_config.CheckboxColumn(
                                "Include",
                                help="Select transactions to include in CSV",
                                default=True,
                            ),
                            "Date": st.column_config.TextColumn(
                                "Date",
                                disabled=True,
                            ),
                            "Description": st.column_config.TextColumn(
                                "Description", 
                                disabled=True,
                            ),
                            "Amount": st.column_config.TextColumn(
                                "Amount",
                                disabled=True,
                            ),
                            "Balance": st.column_config.TextColumn(
                                "Balance",
                                disabled=True,
                            ),
                        },
                        disabled=["Date", "Description", "Amount", "Balance"],
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    # Update session state based on edited dataframe
                    st.session_state.selected_rows = edited_df['Select'].tolist()
                    
                    # Download selected transactions
                    selected_count = sum(st.session_state.selected_rows)
                    st.info(f"Selected {selected_count} of {len(df)} transactions for download")
                    
                    if selected_count > 0:
                        selected_transactions = [txn for i, txn in enumerate(cleaned) if st.session_state.selected_rows[i]]
                        selected_df = pd.DataFrame(selected_transactions)
                        csv = selected_df.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            f"💾 Download CSV ({selected_count} transactions)",
                            csv,
                            "nedbank_transactions.csv",
                            "text/csv",
                            type="primary"
                        )
                    else:
                        st.warning("Please select at least one transaction to download.")
                        
                else:
                    st.markdown("""
                    <div class="error-box">
                        <strong>❌ No transactions found</strong><br>
                        The statement format may be different or the text extraction failed.
                    </div>
                    """, unsafe_allow_html=True)
                    
            except Exception as e:
                st.error(f"Error processing PDF: {str(e)}")

    st.markdown("""
    ---
    <div style="text-align: center; color: #666;">
        <p>💡 <strong>Tip:</strong> For image-based PDFs, OCR will be used automatically</p>
        <p>🔒 Files are processed securely and not stored</p>
        <p>📸 Supports both text-based and scanned PDFs</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()