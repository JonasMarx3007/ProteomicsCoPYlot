WINDOWS INSTALL
git clone https://github.com/JonasMarx3007/ProteomicsCoPYlot.git
cd ProteomicsCoPYlot
cd backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm install
cd ..

WINDOWS RUN ANALYSIS
run_app.bat

WINDOWS RUN VIEWER
run_viewer.bat

WINDOWS PRODUCTION RUN
cd frontend
npm run build
cd ..
.\backend\.venv\Scripts\python.exe launch.py

WINDOWS BUILD EXE TOOL ONLY (ONEFILE)
.\build_exe_windows.ps1 -Target Tool
output: .\dist\ProteomicsCoPYlot.exe

WINDOWS BUILD EXE VIEWER ONLY (ONEFILE)
.\build_exe_windows.ps1 -Target Viewer
output: .\dist\DataViewer.exe

MACOS INSTALL
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

MACOS RUN ANALYSIS
./run_app_macos.sh

MACOS RUN VIEWER
./run_viewer_macos.sh

MACOS PRODUCTION RUN
cd frontend
npm run build
cd ..
./backend/.venv/bin/python3 launch.py

LINUX INSTALL
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

LINUX RUN ANALYSIS
./run_app_linux.sh

LINUX RUN VIEWER
./run_viewer_linux.sh

LINUX PRODUCTION RUN
cd frontend
npm run build
cd ..
./backend/.venv/bin/python3 launch.py
