## Setup

### Backend
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

### Frontend
cd frontend
npm install

### Env
Copy the example env files and fill them in.

### Run
Backend: uvicorn app.main:app --reload
Frontend: npm run dev