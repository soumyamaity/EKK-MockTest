# MCQ Test Platform

A simple platform for administering MCQ tests to students, with admin upload and auto-grading features.

## Features
- Admin upload of questions and model answers (CSV/Excel)
- Student test-taking portal
- Auto-grading and results view

## Setup
1. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   python app.py
   ```
4. Open your browser:
   - Admin upload: [http://localhost:5000/admin/upload](http://localhost:5000/admin/upload)
   - Student test: [http://localhost:5000/test](http://localhost:5000/test)
   - Admin results: [http://localhost:5000/admin/results](http://localhost:5000/admin/results)

## File Format
Upload questions as CSV/Excel with columns:
| Question | Option A | Option B | Option C | Option D | Correct Option |

## To Do
- Implement models and logic for upload, test, and results
- Add authentication (optional) 