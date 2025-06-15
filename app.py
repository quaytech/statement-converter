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

# EXACT copy of the BankStatementParser from your working desktop version
class BankStatementParser:
    def __init__(self):
        self.credit_keywords = [
            'batch dep', 'deposit', 'business', 'herd2', 'netsurit', 
            'top vending rebate', 'merch discount', 'reversal'
        ]
        
        self.debit_keywords = [
            'fee', 'service', 'maintenance', 'charge', 'interest', 'pnp', 
            'vodacom', 'mtn', 'savoy liquors', 'soccer', 'flm norwood',
            'current ac', 'yoco', 'centracom', 'ankerdata', 'jpc',
            'instant payment', 'disputed debit', 'builders exp', 'checkers',
            'vets pantry', 'montrose plumbing', 'discovery life', 'absa bond',
            'sandringham vet', 'woolworths', 'dis-chem', 'multichoice'
        ]
    
    def extract_transactions_from_pdf(self, pdf_path):
        transactions = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                st.write(f"📄 Processing page {page_num}...")
                
                # Extract text with layout preservation
                text = page.extract_text()
                if not text:
                    continue
                
                # Try to extract tables first
                tables = page.extract_tables()
                if tables:
                    transactions.extend(self._process_tables(tables))
                else:
                    # Fallback to text processing
                    transactions.extend(self._process_text(text))
        
        return self._clean_and_format_transactions(transactions)
    
    def _process_tables(self, tables):
        transactions = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
            
            # Look for header row
            header_row = None
            for i, row in enumerate(table):
                if row and any(cell and 'date' in str(cell).lower() for cell in row):
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
        # Clean the row
        clean_row = [str(cell).strip() if cell else '' for cell in row]
        
        # Find date
        date = None
        for cell in clean_row:
            date_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', cell)
            if date_match:
                date = date_match.group(1)
                break
        
        if not date:
            return None
        
        # Find description and amounts
        description = ''
        amounts = []
        
        for cell in clean_row:
            if re.search(r'\b\d{2}/\d{2}/\d{4}\b', cell):
                continue
            
            # Check if cell contains numbers
            if re.search(r'\d{1,3}(?:,\d{3})*\.?\d{0,2}', cell):
                numbers = re.findall(r'\d{1,3}(?:,\d{3})*\.?\d{0,2}', cell)
                amounts.extend(numbers)
                
                desc_part = re.sub(r'\d{1,3}(?:,\d{3})*\.?\d{0,2}', '', cell).strip()
                if desc_part and len(desc_part) > len(description):
                    description = desc_part
            else:
                if len(cell) > len(description):
                    description = cell
        
        if not description:
            return None
        
        # Determine amount and balance
        amount = ''
        balance = ''
        
        if amounts:
            balance = amounts[-1].replace(',', '')
            
            if len(amounts) >= 2:
                transaction_amount = amounts[-2].replace(',', '')
                
                if self._is_credit(description):
                    amount = transaction_amount
                else:
                    amount = f"-{transaction_amount}"
            elif description.lower().strip() != 'opening balance':
                if self._is_credit(description):
                    amount = amounts[0].replace(',', '')
                else:
                    amount = f"-{amounts[0].replace(',', '')}"
        
        return {
            'date': date,
            'description': description.strip(),
            'amount': amount,
            'balance': balance
        }
    
    def _process_text(self, text):
        transactions = []
        lines = text.split('\n')
        
        in_transaction_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if any(keyword in line.lower() for keyword in ['tran list', 'date', 'description', 'balance']):
                in_transaction_section = True
                continue
            
            if 'closing balance' in line.lower():
                break
            
            if not in_transaction_section:
                continue
            
            date_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', line)
            if date_match:
                transaction = self._parse_text_line(line)
                if transaction:
                    transactions.append(transaction)
        
        return transactions
    
    def _parse_text_line(self, line):
        date_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', line)
        if not date_match:
            return None
        
        date = date_match.group(1)
        remainder = line.replace(date, '').strip()
        remainder = re.sub(r'^\d{6}\s*', '', remainder)
        
        numbers = re.findall(r'\d{1,3}(?:,\d{3})*\.?\d{0,2}', remainder)
        
        description = remainder
        for num in numbers:
            description = description.replace(num, ' ')
        description = re.sub(r'\s+', ' ', description).strip()
        
        if not description:
            return None
        
        amount = ''
        balance = ''
        
        if numbers:
            balance = numbers[-1].replace(',', '')
            
            if len(numbers) >= 2 and description.lower() != 'opening balance':
                transaction_amount = numbers[-2].replace(',', '')
                
                if self._is_credit(description):
                    amount = transaction_amount
                else:
                    amount = f"-{transaction_amount}"
        
        return {
            'date': date,
            'description': description,
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
            key = f"{txn['date']}_{txn['description']}_{txn['balance']}"
            if key not in seen:
                seen.add(key)
                unique_transactions.append(txn)
        
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
        4. Open in Excel or any spreadsheet program
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
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()