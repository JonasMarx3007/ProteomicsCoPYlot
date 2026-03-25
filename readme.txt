# Windows Install
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install

# Windows Run Analysis
cd ..
run_app.bat

# Windows Run Viewer
run_viewer.bat

# macOS Install
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend
npm install
cd ..
chmod +x run_app_macos.sh run_viewer_macos.sh

# macOS Run Analysis
./run_app_macos.sh

# macOS Run Viewer
./run_viewer_macos.sh

# Linux Install
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend
npm install
cd ..
chmod +x run_app_linux.sh run_viewer_linux.sh

# Linux Run Analysis
./run_app_linux.sh

# Linux Run Viewer
./run_viewer_linux.sh
