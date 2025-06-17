import streamlit as st
import pandas as pd
import re
import io
import csv
from datetime import datetime
import pdfplumber

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

class BankStatementParser:
    def __init__(self):
        self.credit_keywords = [
            'batch dep', 'deposit', 'business', 'herd2', 'herd', 'netsurit', 
            'top vending rebate', 'merch discount', 'reversal',
            'transfer in', 'credit', 'salary', 'refund', 'merch d'
        ]
    
    def parse_text_input(self, text_input):
        """Parse transactions from direct text input"""
        transactions = []
        lines = text_input.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for lines with dates
            if re.search(r'\d{1,2}/\d{1,2}/\d{4}', line):
                transaction = self._parse_transaction_line(line)
                if transaction:
                    transactions.append(transaction)
        
        return self._clean_and_format_transactions(transactions)
    
    def extract_from_pdf(self, pdf_file):
        """Extract transactions from PDF"""
        transactions = []
        
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                st.write(f"📄 Processing page {page_num}...")
                
                # Try multiple text extraction methods
                text = None
                methods_tried = []
                
                # Method 1: Standard extraction
                try:
                    text = page.extract_text()
                    methods_tried.append("Standard")
                    if text and len(text.strip()) > 100:
                        st.write(f"✅ Standard extraction worked: {len(text)} chars")
                    else:
                        text = None
                except Exception as e:
                    methods_tried.append(f"Standard (failed: {str(e)[:50]})")
                
                # Method 2: Layout extraction
                if not text:
                    try:
                        text = page.extract_text(layout=True)
                        methods_tried.append("Layout")
                        if text and len(text.strip()) > 100:
                            st.write(f"✅ Layout extraction worked: {len(text)} chars")
                        else:
                            text = None
                    except Exception as e:
                        methods_tried.append(f"Layout (failed: {str(e)[:50]})")
                
                # Method 3: Character-based extraction
                if not text:
                    try:
                        chars = page.chars
                        if chars:
                            sorted_chars = sorted(chars, key=lambda x: (x.get('y0', 0), x.get('x0', 0)))
                            text = ''.join([char.get('text', '') for char in sorted_chars])
                            methods_tried.append("Characters")
                            if text and len(text.strip()) > 100:
                                st.write(f"✅ Character extraction worked: {len(text)} chars")
                            else:
                                text = None
                    except Exception as e:
                        methods_tried.append(f"Characters (failed: {str(e)[:50]})")
                
                # Method 4: Word-based extraction
                if not text:
                    try:
                        words = page.extract_words()
                        if words:
                            sorted_words = sorted(words, key=lambda x: (x.get('y0', 0), x.get('x0', 0)))
                            text = ' '.join([word.get('text', '') for word in sorted_words])
                            methods_tried.append("Words")
                            if text and len(text.strip()) > 100:
                                st.write(f"✅ Word extraction worked: {len(text)} chars")
                            else:
                                text = None
                    except Exception as e:
                        methods_tried.append(f"Words (failed: {str(e)[:50]})")
                
                st.write(f"Methods tried: {', '.join(methods_tried)}")
                
                if text and len(text.strip()) > 50:
                    # Check for banking keywords
                    banking_keywords = ['transaction', 'balance', 'date', 'account', 'nedbank', 'batch', 'dep', 'herd', 'current', 'tran list']
                    keywords_found = [kw for kw in banking_keywords if kw in text.lower()]
                    
                    if keywords_found:
                        st.write(f"✅ Found banking keywords: {', '.join(keywords_found)}")
                        
                        # Show a sample of the extracted text
                        st.write("📝 Sample extracted text:")
                        st.text(text[:500] + "..." if len(text) > 500 else text)
                        
                        # Process transactions
                        page_transactions = self._process_transaction_text(text)
                        if page_transactions:
                            st.write(f"✅ Found {len(page_transactions)} transactions on page {page_num}")
                            transactions.extend(page_transactions)
                        else:
                            st.write("❌ No transactions found in extracted text")
                    else:
                        st.write(f"❌ No banking keywords found in {len(text)} characters")
                        st.write("📝 Sample of what was extracted:")
                        st.text(text[:300] + "..." if len(text) > 300 else text)
                else:
                    st.write(f"❌ Could not extract meaningful text from page {page_num}")
                    if text:
                        st.write(f"Only extracted {len(text)} characters")
                    else:
                        st.write("No text extracted at all")
        
        return self._clean_and_format_transactions(transactions)
    
    def _process_transaction_text(self, text):
        """Process text to find transactions"""
        transactions = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for lines with dates
            if re.search(r'\d{1,2}/\d{1,2}/\d{4}', line):
                transaction = self._parse_transaction_line(line)
                if transaction:
                    transactions.append(transaction)
        
        return transactions
    
    def _parse_transaction_line(self, line):
        """Parse a single transaction line - proven working logic"""
        # Extract date
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', line)
        if not date_match:
            return None
        
        date = date_match.group(1)
        date_parts = date.split('/')
        if len(date_parts) == 3:
            day, month, year = date_parts
            date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        
        # Remove date from line
        remainder = line.replace(date_match.group(0), '').strip()
        
        # Skip non-transaction entries
        remainder_lower = remainder.lower()
        skip_phrases = ['statement period', 'total pages', 'balance brought forward', 'balance carried forward']
        if any(phrase in remainder_lower for phrase in skip_phrases):
            return None
        
        # Extract numbers
        numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.\d{2}\b', remainder)
        if not numbers:
            numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{0,2}\b', remainder)
        
        # Filter reasonable transaction amounts
        filtered_numbers = []
        for num in numbers:
            num_value = float(num.replace(',', ''))
            if 0.01 <= num_value <= 999999999:
                filtered_numbers.append(num)
        
        if not filtered_numbers:
            return None
        
        # Extract description
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
        balance = filtered_numbers[-1].replace(',', '') if filtered_numbers else ''
        
        amount = ''
        if len(filtered_numbers) >= 2:
            # Find transaction amount (not balance)
            transaction_amount = None
            for num in filtered_numbers[:-1]:
                num_value = float(num.replace(',', ''))
                if num_value >= 1.0:  # Skip small fees
                    transaction_amount = num.replace(',', '')
                    break
            
            if transaction_amount:
                # Determine credit/debit
                if self._is_credit(description):
                    amount = transaction_amount
                else:
                    amount = f"-{transaction_amount}"
        
        return {
            'date': date,
            'description': description.strip(),
            'amount': amount,
            'balance': balance
        }
    
    def _is_credit(self, description):
        desc_lower = description.lower()
        return any(keyword in desc_lower for keyword in self.credit_keywords)
    
    def _clean_and_format_transactions(self, transactions):
        seen = set()
        unique_transactions = []
        
        for txn in transactions:
            # Skip statement period rows
            desc_lower = txn['description'].lower()
            if any(skip in desc_lower for skip in ['statement period', 'total pages']):
                continue
                
            key = f"{txn['date']}_{txn['description'][:20]}_{txn['balance']}"
            if key not in seen and txn['date'] and txn['description']:
                seen.add(key)
                unique_transactions.append(txn)
        
        # Sort by date
        try:
            unique_transactions.sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
        except:
            pass
        
        return unique_transactions

@st.cache_resource
def get_parser():
    return BankStatementParser()

def create_csv_download(transactions, filename):
    """Create CSV for download"""
    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer)
    csv_writer.writerow(['Date', 'Description', 'Amount', 'Balance'])
    
    for txn in transactions:
        csv_writer.writerow([
            txn['date'],
            txn['description'],
            txn['amount'],
            txn['balance']
        ])
    
    return csv_buffer.getvalue()

def main():
    st.markdown('<h1 class="main-header">🏦 Bank Statement PDF to CSV Converter</h1>', unsafe_allow_html=True)
    
    st.markdown("""
    <div class="info-box">
        <strong>Two ways to use this tool:</strong><br>
        1. <strong>Upload PDF</strong> - For text-based PDFs (works with 2021 format)<br>
        2. <strong>Paste Text</strong> - Copy transaction table from PDF and paste below (works for any format)
    </div>
    """, unsafe_allow_html=True)
    
    # Create tabs for different input methods
    tab1, tab2 = st.tabs(["📁 Upload PDF", "📝 Paste Text"])
    
    parser = get_parser()
    
    with tab1:
        st.subheader("Upload PDF File")
        uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
        
        if uploaded_file is not None:
            st.success(f"📁 File uploaded: {uploaded_file.name}")
            
            if st.button("🔄 Convert PDF to CSV", type="primary", key="pdf_convert"):
                with st.spinner('Processing PDF...'):
                    try:
                        transactions = parser.extract_from_pdf(uploaded_file)
                        
                        if not transactions:
                            st.markdown("""
                            <div class="error-box">
                                <strong>❌ No transactions found in PDF</strong><br>
                                Try the "Paste Text" method instead - copy the transaction table from your PDF viewer and paste it in the other tab.
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                            <div class="success-box">
                                <strong>✅ Success!</strong><br>
                                Extracted {len(transactions)} transactions from PDF
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # Display results
                            df = pd.DataFrame(transactions)
                            st.subheader("📊 Transaction Preview")
                            st.dataframe(df.head(10), use_container_width=True)
                            
                            # Download button
                            csv_content = create_csv_download(transactions, uploaded_file.name)
                            filename = uploaded_file.name.replace('.pdf', '_transactions.csv')
                            st.download_button(
                                label="💾 Download CSV File",
                                data=csv_content,
                                file_name=filename,
                                mime="text/csv",
                                type="primary"
                            )
                    
                    except Exception as e:
                        st.error(f"Error processing PDF: {str(e)}")
    
    with tab2:
        st.subheader("Paste Transaction Text")
        st.markdown("""
        **Instructions:**
        1. Open your PDF in a viewer (Adobe Reader, browser, etc.)
        2. Select and copy the transaction table (from the header row down to closing balance)
        3. Paste the copied text in the box below
        4. Click "Convert Text to CSV"
        """)
        
        text_input = st.text_area(
            "Paste your transaction table here:",
            height=300,
            placeholder="Paste transaction data here...\nExample:\n21/01/2023 Opening balance 2,549.98\n21/01/2023 Herd2 - 1213779758 2,000.00 4,549.98\n..."
        )
        
        if text_input.strip():
            if st.button("🔄 Convert Text to CSV", type="primary", key="text_convert"):
                with st.spinner('Processing text...'):
                    try:
                        transactions = parser.parse_text_input(text_input)
                        
                        if not transactions:
                            st.error("❌ No transactions found in the pasted text. Please check the format.")
                        else:
                            st.markdown(f"""
                            <div class="success-box">
                                <strong>✅ Success!</strong><br>
                                Extracted {len(transactions)} transactions from text
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # Display results
                            df = pd.DataFrame(transactions)
                            st.subheader("📊 Transaction Preview")
                            st.dataframe(df.head(10), use_container_width=True)
                            
                            # Download button
                            csv_content = create_csv_download(transactions, "pasted_text")
                            st.download_button(
                                label="💾 Download CSV File",
                                data=csv_content,
                                file_name="bank_transactions.csv",
                                mime="text/csv",
                                type="primary"
                            )
                    
                    except Exception as e:
                        st.error(f"Error processing text: {str(e)}")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666;">
        <p>💡 Supports Nedbank and most standard bank statement formats</p>
        <p>🔒 Files are processed securely and not stored</p>
        <p>📝 If PDF upload fails, try the "Paste Text" method</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()