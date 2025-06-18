import streamlit as st
import pandas as pd
import requests
import base64
import time
import re
from datetime import datetime
import io
import zipfile
from pathlib import Path

class BankStatementProcessor:
    def __init__(self, pdfco_api_key):
        self.pdfco_api_key = pdfco_api_key
        
    def upload_to_pdfco(self, file_content, filename):
        """Upload PDF file to PDF.co and get a URL"""
        file_data = base64.b64encode(file_content).decode('utf-8')
        
        upload_url = "https://api.pdf.co/v1/file/upload/base64"
        headers = {
            'x-api-key': self.nikky.gibson@quay-tech.co.uk_ZyQGnhrmW9DuqJPyj4QI4eoNikmf6mW4MblyTZViW87dPDXY45TN0iNu3dFbL3jb,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'file': file_data,
            'name': filename
        }
        
        response = requests.post(upload_url, headers=headers, json=payload)
        
        if response.status_code == 200:
            return response.json()['url']
        else:
            raise Exception(f"Failed to upload file: {response.status_code} - {response.text}")
    
    def extract_text_from_pdf(self, pdf_url):
        """Extract text from PDF using PDF.co OCR"""
        extract_url = "https://api.pdf.co/v1/pdf/convert/to/text"
        headers = {
            'x-api-key': self.pdfco_api_key,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'url': pdf_url,
            'ocrLanguage': 'eng',
            'async': False
        }
        
        response = requests.post(extract_url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            text_url = result.get('url')
            if text_url:
                text_response = requests.get(text_url)
                if text_response.status_code == 200:
                    return text_response.text
                else:
                    raise Exception(f"Failed to download extracted text: {text_response.status_code}")
            else:
                raise Exception("No text URL returned from PDF.co")
        else:
            raise Exception(f"Failed to extract text: {response.status_code} - {response.text}")
    
    def parse_transaction_line(self, line):
        """Parse a single transaction line"""
        # Extract date - support multiple formats
        date_match = re.search(r'(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})', line)
        if not date_match:
            return None
        
        date = date_match.group(1)
        remainder = line.replace(date, '').strip()
        
        # Skip non-transaction entries
        skip_phrases = [
            'statement period', 'total pages', 'balance brought forward',
            'balance carried forward', 'page', 'account number', 'sort code',
            'opening balance', 'closing balance', 'total credits', 'total debits',
            'statement date', 'account summary', 'previous statement'
        ]
        
        if any(phrase in remainder.lower() for phrase in skip_phrases):
            return None
        
        # Extract monetary amounts
        numbers = re.findall(r'-?\d{1,3}(?:,\d{3})*\.?\d{0,2}', remainder)
        filtered_numbers = [
            float(num.replace(',', '')) for num in numbers 
            if 0.01 <= abs(float(num.replace(',', ''))) <= 999999999
        ]
        
        if not filtered_numbers:
            return None
        
        # Extract description
        description = remainder
        for num in numbers:
            description = description.replace(num, ' ')
        
        # Clean description
        description = re.sub(r'\b\d{6,}\b', '', description)
        description = re.sub(r'[^\w\s\-&]', ' ', description)
        description = re.sub(r'\s+', ' ', description).strip()
        
        if not description or len(description) < 2:
            description = 'Transaction'
        
        # Determine amount and balance
        balance = filtered_numbers[-1]
        amount = None
        
        if len(filtered_numbers) >= 2:
            transaction_amount = filtered_numbers[-2]
            
            # Determine if credit or debit
            credit_keywords = [
                'deposit', 'credit', 'transfer in', 'refund', 'reversal',
                'payment received', 'interest', 'dividend', 'salary', 'wages',
                'batch dep', 'business', 'herd2', 'herd'
            ]
            
            debit_keywords = [
                'withdrawal', 'atm', 'purchase', 'payment', 'fee', 'charge',
                'direct debit', 'standing order', 'card payment', 'transfer out'
            ]
            
            desc_lower = description.lower()
            is_credit = any(keyword in desc_lower for keyword in credit_keywords)
            is_debit = any(keyword in desc_lower for keyword in debit_keywords)
            
            if is_credit:
                amount = abs(transaction_amount)
            elif is_debit:
                amount = -abs(transaction_amount)
            else:
                amount = transaction_amount
        
        return {
            'Date': date,
            'Description': description,
            'Amount': amount,
            'Balance': balance
        }
    
    def parse_transactions(self, text):
        """Parse transactions from extracted text"""
        transactions = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            transaction = self.parse_transaction_line(line)
            if transaction:
                transactions.append(transaction)
        
        # Remove duplicates and sort
        transactions = self.clean_and_sort_transactions(transactions)
        return transactions
    
    def clean_and_sort_transactions(self, transactions):
        """Remove duplicates and sort transactions"""
        # Remove duplicates
        seen = set()
        unique_transactions = []
        
        for txn in transactions:
            key = f"{txn['Date']}_{txn['Description'][:30]}_{txn['Balance']}_{txn['Amount']}"
            if key not in seen:
                seen.add(key)
                unique_transactions.append(txn)
        
        # Sort by date
        unique_transactions.sort(key=lambda x: self.parse_date(x['Date']))
        
        return unique_transactions
    
    def parse_date(self, date_str):
        """Parse date string to datetime object"""
        parts = re.split(r'[\/\-]', date_str)
        
        if len(parts[0]) == 4:
            return datetime(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
    
    def process_pdf(self, file_content, filename):
        """Process a single PDF file"""
        try:
            # Upload to PDF.co
            pdf_url = self.upload_to_pdfco(file_content, filename)
            
            # Extract text
            extracted_text = self.extract_text_from_pdf(pdf_url)
            
            # Parse transactions
            transactions = self.parse_transactions(extracted_text)
            
            if not transactions:
                return None, "No transactions found in the PDF"
            
            # Create DataFrame
            df = pd.DataFrame(transactions)
            
            # Format amounts
            df['Amount'] = df['Amount'].apply(lambda x: f"{x:.2f}" if x is not None else "")
            df['Balance'] = df['Balance'].apply(lambda x: f"{x:.2f}")
            
            return df, None
            
        except Exception as e:
            return None, str(e)

def main():
    st.set_page_config(
        page_title="Bank Statement Processor",
        page_icon="🏦",
        layout="wide"
    )
    
    st.title("🏦 Bank Statement PDF to CSV Converter")
    st.markdown("Upload your bank statement PDFs and convert them to CSV format with automatic transaction parsing.")
    
    # Sidebar for API key
    with st.sidebar:
        st.header("⚙️ Configuration")
        api_key = st.text_input(
            "PDF.co API Key",
            type="password",
            help="Get your free API key from https://pdf.co"
        )
        
        if not api_key:
            st.warning("Please enter your PDF.co API key to continue")
            st.info("💡 PDF.co offers a free tier with 100 API calls per month")
            st.stop()
    
    # Main interface
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("📁 Upload PDF Files")
        uploaded_files = st.file_uploader(
            "Choose PDF bank statements",
            type=['pdf'],
            accept_multiple_files=True,
            help="You can upload multiple PDF files at once"
        )
        
        if uploaded_files:
            st.success(f"📄 {len(uploaded_files)} file(s) uploaded")
            
            # Show file details
            for file in uploaded_files:
                st.text(f"• {file.name} ({file.size:,} bytes)")
    
    with col2:
        st.header("🔄 Processing")
        
        if uploaded_files and st.button("🚀 Process All Files", type="primary"):
            processor = BankStatementProcessor(api_key)
            
            # Progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            results = {}
            successful_files = []
            failed_files = []
            
            for i, uploaded_file in enumerate(uploaded_files):
                status_text.text(f"Processing {uploaded_file.name}...")
                
                # Read file content
                file_content = uploaded_file.read()
                
                # Process the PDF
                df, error = processor.process_pdf(file_content, uploaded_file.name)
                
                if df is not None:
                    results[uploaded_file.name] = df
                    successful_files.append(uploaded_file.name)
                    st.success(f"✅ {uploaded_file.name}: {len(df)} transactions found")
                else:
                    failed_files.append((uploaded_file.name, error))
                    st.error(f"❌ {uploaded_file.name}: {error}")
                
                # Update progress
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            status_text.text("✨ Processing complete!")
            
            # Summary
            st.header("📊 Results Summary")
            col_success, col_failed = st.columns(2)
            
            with col_success:
                st.metric("✅ Successful", len(successful_files))
            
            with col_failed:
                st.metric("❌ Failed", len(failed_files))
    
    # Display results
    if 'results' in locals() and results:
        st.header("📋 Transaction Data")
        
        # Tabs for each file
        if len(results) == 1:
            filename = list(results.keys())[0]
            df = results[filename]
            st.subheader(f"📄 {filename}")
            st.dataframe(df, use_container_width=True)
            
            # Download button for single file
            csv = df.to_csv(index=False)
            csv_filename = filename.replace('.pdf', '_transactions.csv')
            st.download_button(
                label=f"💾 Download {csv_filename}",
                data=csv,
                file_name=csv_filename,
                mime='text/csv'
            )
        
        else:
            # Multiple files - create tabs
            tabs = st.tabs([f"📄 {name}" for name in results.keys()])
            
            for tab, (filename, df) in zip(tabs, results.items()):
                with tab:
                    st.dataframe(df, use_container_width=True)
                    
                    # Individual download
                    csv = df.to_csv(index=False)
                    csv_filename = filename.replace('.pdf', '_transactions.csv')
                    st.download_button(
                        label=f"💾 Download {csv_filename}",
                        data=csv,
                        file_name=csv_filename,
                        mime='text/csv',
                        key=f"download_{filename}"
                    )
            
            # Download all as ZIP
            st.header("📦 Download All")
            if st.button("📥 Download All CSVs as ZIP"):
                zip_buffer = io.BytesIO()
                
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for filename, df in results.items():
                        csv = df.to_csv(index=False)
                        csv_filename = filename.replace('.pdf', '_transactions.csv')
                        zip_file.writestr(csv_filename, csv)
                
                st.download_button(
                    label="💾 Download ZIP File",
                    data=zip_buffer.getvalue(),
                    file_name="bank_statements_csvs.zip",
                    mime="application/zip"
                )
    
    # Footer
    st.markdown("---")
    st.markdown("💡 **Tip**: This tool works with both text-based and image-based PDF bank statements using OCR technology.")

if __name__ == "__main__":
    main()