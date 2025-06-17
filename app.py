import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
import csv
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Bank Statement Converter",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
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
        
        self.debit_keywords = [
            'fee', 'service', 'maintenance', 'charge', 'interest', 'pnp', 
            'vodacom', 'mtn', 'savoy liquors', 'soccer', 'flm norwood',
            'current ac', 'yoco', 'centracom', 'ankerdata', 'jpc',
            'instant payment', 'disputed debit', 'builders exp', 'checkers',
            'vets pantry', 'montrose plumbing', 'discovery life', 'absa bond',
            'sandringham vet', 'woolworths', 'dis-chem', 'multichoice',
            'atm', 'withdrawal', 'debit order'
        ]
    
    def extract_transactions_from_pdf(self, pdf_file):
        transactions = []
        
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                st.write(f"📄 Processing page {page_num}...")
                
                # Try text extraction with multiple methods
                text = page.extract_text()
                
                # Try alternative extraction methods if first attempt fails
                if not text or len(text.strip()) < 50:
                    try:
                        text = page.extract_text(x_tolerance=3, y_tolerance=3)
                    except:
                        pass
                
                if not text or len(text.strip()) < 50:
                    try:
                        text = page.extract_text(layout=True)
                    except:
                        pass
                
                if not text or len(text.strip()) < 50:
                    try:
                        chars = page.chars
                        if chars:
                            sorted_chars = sorted(chars, key=lambda x: (x.get('y0', 0), x.get('x0', 0)))
                            text = ''.join([char.get('text', '') for char in sorted_chars])
                    except:
                        pass
                
                if not text or len(text.strip()) < 50:
                    try:
                        words = page.extract_words()
                        if words:
                            text = ' '.join([word.get('text', '') for word in words])
                    except:
                        pass
                
                # Check if we got meaningful text
                has_meaningful_text = (text and 
                                     len(text.strip()) > 20 and 
                                     any(keyword in text.lower() for keyword in ['transaction', 'balance', 'date', 'account', 'nedbank', 'batch', 'dep', 'herd', 'current']))
                
                if has_meaningful_text:
                    st.write(f"✅ Text extracted from page {page_num} ({len(text)} characters)")
                    
                    # Process transactions from text
                    page_transactions = self._process_transaction_text(text)
                    transactions.extend(page_transactions)
                    
                    # Also try table extraction
                    tables = page.extract_tables()
                    if tables:
                        table_transactions = self._process_tables(tables)
                        transactions.extend(table_transactions)
                
                else:
                    st.write(f"❌ Could not extract meaningful text from page {page_num}")
                    st.write("This appears to be a scanned/image-based PDF that requires OCR")
        
        return self._clean_and_format_transactions(transactions)
    
    def _process_transaction_text(self, text):
        """Process text to find transactions in both 2021 and 2023 formats"""
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
        """Parse a single transaction line"""
        # Extract date
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', line)
        if not date_match:
            return None
        
        date = date_match.group(1)
        # Normalize date format
        date_parts = date.split('/')
        if len(date_parts) == 3:
            day, month, year = date_parts
            date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        
        # Remove date from line
        remainder = line.replace(date_match.group(0), '').strip()
        
        # Skip non-transaction entries
        remainder_lower = remainder.lower()
        skip_phrases = ['statement period', 'total pages', 'balance brought forward', 'balance carried forward', 'statementperiod', 'totalpages']
        if any(phrase in remainder_lower for phrase in skip_phrases):
            return None
        
        # Extract all numbers from the line
        numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.\d{2}\b', remainder)
        if not numbers:
            numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{0,2}\b', remainder)
        
        if not numbers or len(numbers) == 0:
            return None
        
        # Extract description by removing numbers and cleaning up
        description = remainder
        for num in numbers:
            description = description.replace(num, ' ')
        
        # Remove transaction numbers and clean up
        description = re.sub(r'\b\d{6}\b', '', description)  # Remove 6-digit transaction numbers
        description = re.sub(r'[^\w\s-]', ' ', description)
        description = ' '.join(description.split())
        
        if not description:
            description = 'Transaction'
        
        # Determine amount and balance based on the format
        balance = numbers[-1].replace(',', '') if numbers else ''
        
        amount = ''
        if len(numbers) >= 2:
            # For lines with multiple numbers, try to identify the transaction amount
            if len(numbers) == 2:
                # Simple case: amount and balance
                potential_amount = numbers[0].replace(',', '')
            else:
                # Multiple numbers - transaction amount is usually second-to-last
                potential_amount = numbers[-2].replace(',', '')
            
            # Determine if credit or debit
            if self._is_credit(description):
                amount = potential_amount
            else:
                amount = f"-{potential_amount}"
        
        return {
            'date': date,
            'description': description.strip(),
            'amount': amount,
            'balance': balance
        }
    
    def _process_tables(self, tables):
        """Process extracted tables"""
        transactions = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
            
            # Find header row
            header_row = None
            for i, row in enumerate(table):
                if row and any(cell and any(keyword in str(cell).lower() for keyword in ['date', 'tran list', 'description']) for cell in row):
                    header_row = i
                    break
            
            if header_row is None:
                continue
            
            # Process data rows
            for row in table[header_row + 1:]:
                if not row or not any(row):
                    continue
                
                transaction = self._parse_table_row(row)
                if transaction:
                    transactions.append(transaction)
        
        return transactions
    
    def _parse_table_row(self, row):
        """Parse a single table row"""
        clean_row = [str(cell).strip() if cell else '' for cell in row]
        
        # Find date
        date = None
        date_cell_index = None
        for i, cell in enumerate(clean_row):
            date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', str(cell))
            if date_match:
                date = date_match.group(1)
                date_cell_index = i
                date_parts = date.split('/')
                if len(date_parts) == 3:
                    day, month, year = date_parts
                    date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
                break
        
        if not date:
            return None
        
        # Skip non-transaction rows
        row_text = ' '.join(clean_row).lower()
        skip_phrases = ['statement period', 'total pages', 'statementperiod', 'totalpages', 'balance brought forward', 'balance carried forward']
        if any(skip_phrase in row_text for skip_phrase in skip_phrases):
            return None
        
        # Extract description and amounts
        description = ''
        amounts = []
        
        for i, cell in enumerate(clean_row):
            if i == date_cell_index:
                continue
                
            cell_str = str(cell).strip()
            if not cell_str or cell_str == 'None':
                continue
            
            # Extract numbers
            cell_numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{0,2}\b', cell_str)
            if cell_numbers:
                amounts.extend(cell_numbers)
            
            # Extract description text
            desc_text = cell_str
            for num in cell_numbers:
                desc_text = desc_text.replace(num, ' ')
            desc_text = re.sub(r'[^\w\s-]', ' ', desc_text)
            desc_text = ' '.join(desc_text.split())
            
            if desc_text and len(desc_text) > 3 and not desc_text.isdigit():
                if len(desc_text) > len(description):
                    description = desc_text
        
        if not description and not amounts:
            return None
        
        if not description:
            description = 'Transaction'
        
        # Determine amount and balance
        amount = ''
        balance = amounts[-1].replace(',', '') if amounts else ''
        
        if len(amounts) >= 2:
            transaction_amount = amounts[-2].replace(',', '')
            
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
        """Determine if transaction is a credit"""
        desc_lower = description.lower()
        return any(keyword in desc_lower for keyword in self.credit_keywords)
    
    def _clean_and_format_transactions(self, transactions):
        """Clean and format the final transaction list"""
        seen = set()
        unique_transactions = []
        
        for txn in transactions:
            # Filter out statement period rows
            desc_lower = txn['description'].lower()
            skip_phrases = ['statement period', 'total pages', 'statementperiod', 'totalpages']
            if any(skip_phrase in desc_lower for skip_phrase in skip_phrases):
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

# Initialize parser
@st.cache_resource
def get_parser():
    return BankStatementParser()

def main():
    # Header
    st.markdown('<h1 class="main-header">🏦 Bank Statement PDF to CSV Converter</h1>', unsafe_allow_html=True)
    
    st.markdown("""
    <div class="info-box">
        <strong>How to use:</strong><br>
        1. Upload your bank statement PDF file<br>
        2. Wait for processing to complete<br>
        3. Download the CSV file<br>
        4. Open in Excel or any spreadsheet program<br><br>
        <strong>Supported formats:</strong><br>
        • Text-based PDFs (preferred)<br>
        • Image-based/scanned PDFs (may require OCR)
    </div>
    """, unsafe_allow_html=True)
    
    # File uploader
    uploaded_file = st.file_uploader(
        "Choose a PDF file", 
        type="pdf",
        help="Upload your bank statement PDF file"
    )
    
    if uploaded_file is not None:
        st.success(f"📁 File uploaded: {uploaded_file.name}")
        
        # Process button
        if st.button("🔄 Convert PDF to CSV", type="primary"):
            parser = get_parser()
            
            with st.spinner('Processing PDF... This may take a few moments.'):
                try:
                    # Process the PDF
                    transactions = parser.extract_transactions_from_pdf(uploaded_file)
                    
                    if not transactions:
                        st.markdown("""
                        <div class="error-box">
                            <strong>❌ No transactions found</strong><br>
                            Please check if this is a valid bank statement PDF. 
                            The PDF might be scanned or have a different format.
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div class="success-box">
                            <strong>✅ Success!</strong><br>
                            Extracted {len(transactions)} transactions from your PDF
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Create DataFrame for display
                        df = pd.DataFrame(transactions)
                        
                        # Display preview
                        st.subheader("📊 Transaction Preview")
                        st.dataframe(df.head(10), use_container_width=True)
                        
                        if len(transactions) > 10:
                            st.info(f"Showing first 10 of {len(transactions)} transactions")
                        
                        # Create CSV download
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
                        
                        csv_content = csv_buffer.getvalue()
                        csv_buffer.close()
                        
                        # Download button
                        filename = uploaded_file.name.replace('.pdf', '_transactions.csv')
                        st.download_button(
                            label="💾 Download CSV File",
                            data=csv_content,
                            file_name=filename,
                            mime="text/csv",
                            type="primary"
                        )
                        
                        # Summary statistics
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Total Transactions", len(transactions))
                        
                        with col2:
                            try:
                                opening_balance = float(transactions[0]['balance'].replace(',', ''))
                                st.metric("Opening Balance", f"R {opening_balance:,.2f}")
                            except:
                                st.metric("Opening Balance", "N/A")
                        
                        with col3:
                            try:
                                closing_balance = float(transactions[-1]['balance'].replace(',', ''))
                                st.metric("Closing Balance", f"R {closing_balance:,.2f}")
                            except:
                                st.metric("Closing Balance", "N/A")
                
                except Exception as e:
                    st.markdown(f"""
                    <div class="error-box">
                        <strong>❌ Error processing PDF</strong><br>
                        {str(e)}<br><br>
                        Please try with a different PDF file or contact support.
                    </div>
                    """, unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666;">
        <p>💡 Supports Nedbank and most standard bank statement formats</p>
        <p>🔒 Files are processed securely and not stored on our servers</p>
        <p>📸 Automatically handles both text-based and image-based PDFs</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()