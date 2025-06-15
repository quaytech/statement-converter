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
            'batch dep', 'deposit', 'business', 'herd2', 'netsurit', 
            'top vending rebate', 'merch discount', 'reversal',
            'transfer in', 'credit', 'salary', 'refund'
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
                
                text = page.extract_text()
                if not text:
                    continue
                
                # First, specifically look for opening balance
                opening_balance = self._find_opening_balance_in_text(text, page_num)
                if opening_balance:
                    transactions.append(opening_balance)
                
                # Extract tables for regular transactions
                tables = page.extract_tables()
                if tables:
                    page_transactions = self._process_tables(tables)
                    # Filter out opening balance duplicates
                    page_transactions = [t for t in page_transactions if 'opening balance' not in t['description'].lower()]
                    transactions.extend(page_transactions)
                
                # Also try text processing
                text_transactions = self._process_text(text)
                text_transactions = [t for t in text_transactions if 'opening balance' not in t['description'].lower()]
                transactions.extend(text_transactions)
        
        return self._clean_and_format_transactions(transactions)
    
    def _find_opening_balance_in_text(self, text, page_num):
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            if 'opening balance' in line.lower():
                date = None
                balance = None
                
                search_start = max(0, i - 3)
                search_end = min(len(lines), i + 4)
                
                for j in range(search_start, search_end):
                    search_line = lines[j].strip()
                    
                    if not date:
                        date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', search_line)
                        if date_match:
                            date = date_match.group(1)
                            date_parts = date.split('/')
                            if len(date_parts) == 3:
                                day, month, year = date_parts
                                date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
                    
                    numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{2}\b', search_line)
                    for num in numbers:
                        num_value = float(num.replace(',', ''))
                        if num_value > 100:
                            balance = num
                            break
                    
                    if date and balance:
                        break
                
                if date and balance:
                    return {
                        'date': date,
                        'description': 'Opening balance',
                        'amount': '',
                        'balance': balance.replace(',', '')
                    }
        
        return None
    
    def _process_tables(self, tables):
        transactions = []
        
        for table in tables:
            if not table or len(table) < 2:
                continue
            
            header_row = None
            for i, row in enumerate(table):
                if row and any(cell and 'date' in str(cell).lower() for cell in row):
                    header_row = i
                    break
            
            if header_row is None:
                continue
            
            for row in table[header_row + 1:]:
                if not row or not any(row):
                    continue
                
                transaction = self._parse_table_row(row)
                if transaction and 'opening balance' not in transaction['description'].lower():
                    transactions.append(transaction)
        
        return transactions
    
    def _parse_table_row(self, row):
        clean_row = [str(cell).strip() if cell else '' for cell in row]
        
        date = None
        for cell in clean_row:
            date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', cell)
            if date_match:
                date = date_match.group(1)
                date_parts = date.split('/')
                if len(date_parts) == 3:
                    day, month, year = date_parts
                    date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
                break
        
        if not date:
            return None
        
        # Skip non-transaction rows like "Statement period"
        row_text = ' '.join(clean_row).lower()
        if any(skip_phrase in row_text for skip_phrase in ['statement period', 'total pages']):
            return None
        
        description = ''
        amounts = []
        
        for cell in clean_row:
            if re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', cell):
                continue
            
            cell_numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{0,2}\b', cell)
            if cell_numbers:
                amounts.extend(cell_numbers)
                
                desc_part = cell
                for num in cell_numbers:
                    desc_part = desc_part.replace(num, ' ')
                desc_part = re.sub(r'[^\w\s]', ' ', desc_part)
                desc_part = ' '.join(desc_part.split())
                
                if desc_part and len(desc_part) > len(description):
                    description = desc_part
            else:
                clean_text = re.sub(r'[^\w\s-]', ' ', cell)
                clean_text = ' '.join(clean_text.split())
                if len(clean_text) > len(description):
                    description = clean_text
        
        if not description or not amounts:
            return None
        
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
    
    def _process_text(self, text):
        transactions = []
        lines = text.split('\n')
        in_transaction_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if any(keyword in line.lower() for keyword in ['transaction', 'date', 'description', 'balance']):
                in_transaction_section = True
                continue
            
            if 'closing balance' in line.lower():
                continue
            
            if not in_transaction_section:
                continue
            
            if 'opening balance' in line.lower():
                continue
            
            if re.search(r'\b\d{1,2}/\d{1,2}/\d{4}\b', line):
                transaction = self._parse_text_line(line)
                if transaction and 'opening balance' not in transaction['description'].lower():
                    transactions.append(transaction)
        
        return transactions
    
    def _parse_text_line(self, line):
        date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', line)
        if not date_match:
            return None
        
        # Skip non-transaction rows like "Statement period"
        line_lower = line.lower()
        if any(skip_phrase in line_lower for skip_phrase in ['statement period', 'total pages']):
            return None
        
        date = date_match.group(1)
        date_parts = date.split('/')
        if len(date_parts) == 3:
            day, month, year = date_parts
            date = f"{day.zfill(2)}/{month.zfill(2)}/{year}"
        
        remainder = line.replace(date_match.group(0), '').strip()
        remainder = re.sub(r'^\d{6}\s*', '', remainder)
        
        numbers = re.findall(r'\b\d{1,3}(?:,\d{3})*\.?\d{0,2}\b', remainder)
        
        description = remainder
        for num in numbers:
            description = description.replace(num, ' ')
        description = re.sub(r'[^\w\s-]', ' ', description)
        description = ' '.join(description.split())
        
        if not description or not numbers:
            return None
        
        amount = ''
        balance = numbers[-1].replace(',', '') if numbers else ''
        
        if len(numbers) >= 2:
            transaction_amount = numbers[-2].replace(',', '')
            
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
            key = f"{txn['date']}_{txn['description'][:20]}_{txn['balance']}"
            if key not in seen and txn['date'] and txn['description']:
                seen.add(key)
                unique_transactions.append(txn)
        
        try:
            unique_transactions.sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
        except:
            pass
        
        # Check if we have an opening balance
        has_opening_balance = any('opening balance' in txn['description'].lower() for txn in unique_transactions)
        
        # If no opening balance found, try to calculate it
        if not has_opening_balance and unique_transactions:
            first_txn = unique_transactions[0]
            try:
                first_balance = float(first_txn['balance'].replace(',', ''))
                first_amount = float(first_txn['amount'].replace(',', '')) if first_txn['amount'] else 0
                calculated_opening = first_balance - first_amount
                
                if calculated_opening > 0:
                    opening_balance = {
                        'date': first_txn['date'],
                        'description': 'Opening balance',
                        'amount': '',
                        'balance': f"{calculated_opening:.2f}"
                    }
                    unique_transactions.insert(0, opening_balance)
            except:
                pass
        
        # Ensure opening balance is first
        opening_balance = None
        other_transactions = []
        
        for txn in unique_transactions:
            if 'opening balance' in txn['description'].lower():
                if opening_balance is None:
                    opening_balance = txn
            else:
                other_transactions.append(txn)
        
        final_transactions = []
        if opening_balance:
            final_transactions.append(opening_balance)
        final_transactions.extend(other_transactions)
        
        return final_transactions

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
                                closing_balance = float(transactions[-1]['balance'].replace(',', ''))
                                st.metric("Opening Balance", f"R {opening_balance:,.2f}")
                            except:
                                st.metric("Opening Balance", "N/A")
                        
                        with col3:
                            try:
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