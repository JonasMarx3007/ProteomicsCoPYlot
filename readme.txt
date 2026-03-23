# Install
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install

# Run
cd ..
run_app.bat
